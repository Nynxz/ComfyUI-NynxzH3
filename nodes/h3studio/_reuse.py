"""Reusing a scene's saved render when nothing that shapes it has changed.

ComfyUI's own cache can't do this for a film: every scene's H3 Studio node carries the whole
project, so editing scene 2 changes scene 1's inputs too, and its sampler runs again. Instead, a
scene gets a fingerprint of everything that decides its pixels, and H3 Studio Clip keeps an index of
the clips it saved under those fingerprints. On a match, Clip hands back the saved clip without
asking for the decoded frames, and ComfyUI never runs that scene's sampler.

A fingerprint has two halves:

- **the scene** (`scene_key`, made by H3 Studio): its compiled request — prompt, task, size, LoRAs,
  references and keyframes, with each media file's size and time — and, for a continuation, the
  fingerprint of the clip it continues from;
- **the render chain** (`chain_key`, made by Clip): every node upstream of the decoded frames, by
  class and widget values — the model, the sampler, the seed, the steps — walked by structure, so
  the same chain in another loop pass gives the same key. The studio and the loop's own nodes are
  left to the scene half.

Each scene also keeps its **latest** clip (`scenes.json`, by scene id): the last one rendered or
reused for it, with its fingerprint. A scene rendered on its own continues from the previous
scene's latest clip, a scene left out of a partial render plays its latest clip, and the editor
compares the latest scene half against the scene as it stands now to mark it up to date or not.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from typing import Any

from ._media import path_of

LOG = logging.getLogger(__name__)

#: Nodes whose part in a render the scene half already covers, so the chain walk stops at them.
COVERED = {"nynxz.H3.Studio", "LoopIteration", "StartLoop"}
INDEX_FILE = "renders.json"
SCENES_FILE = "scenes.json"
#: Every clip each scene has rendered, newest last — the Renders sidebar's history.
TAKES_FILE = "takes.json"
#: Takes kept per scene (the oldest go first; their files stay in output/h3studio).
TAKES_KEPT = 60
_lock = threading.Lock()


def digest(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def media_stat(ref: str) -> list:
    try:
        stat = os.stat(path_of(ref))
    except (OSError, ValueError):
        return [ref, None]
    return [ref, stat.st_size, stat.st_mtime_ns]


def scene_key(plan: dict, index: int, carried: str | None) -> str:
    """The scene half: `plan` is the compiled scene, `carried` the fingerprint of what it continues."""
    request = {k: v for k, v in plan.items() if k != "warnings"}
    request["settings"] = {k: v for k, v in plan.get("settings", {}).items() if k != "verbose"}
    media = sorted(
        {m["media"] for m in [*plan.get("refs", []), *plan.get("keyframes", [])] if m.get("media")}
    )
    return digest(
        {
            "scene": index,
            "request": request,
            "media": [media_stat(m) for m in media],
            "carried": carried,
        }
    )


def frames_key(frames, audio: dict | None) -> str:
    """A fingerprint of carried-over frames that came from outside the studio (no clip key)."""
    digest = hashlib.sha256(frames.detach().cpu().numpy().tobytes())
    if audio is not None:
        digest.update(audio["waveform"].detach().cpu().numpy().tobytes())
    return digest.hexdigest()


def chain_key(dynprompt, node_id: str, inputs: tuple[str, ...]) -> str:
    """The render half: the structure and widget values upstream of `node_id`'s `inputs`."""
    memo: dict[str, str] = {}

    def node_key(nid: str) -> str:
        if nid in memo:
            return memo[nid]
        memo[nid] = "cycle"
        node = dynprompt.get_node(nid) if dynprompt.has_node(nid) else None
        if node is None:
            memo[nid] = "missing"
            return memo[nid]
        kind = node["class_type"]
        if kind in COVERED:
            memo[nid] = kind
            return kind
        memo[nid] = digest(
            [kind, [[name, value_key(v)] for name, v in sorted(node["inputs"].items())]]
        )
        return memo[nid]

    def value_key(value: Any) -> Any:
        if _is_link(value):
            return [node_key(str(value[0])), value[1]]
        return value

    node = dynprompt.get_node(node_id)
    return digest([value_key(node["inputs"][name]) for name in inputs if name in node["inputs"]])


def _is_link(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], (str, int))
        and isinstance(value[1], int)
    )


def _index_path() -> str:
    import folder_paths

    return os.path.join(folder_paths.get_output_directory(), "h3studio", INDEX_FILE)


def _read_index() -> dict[str, str]:
    try:
        with open(_index_path(), encoding="utf-8") as f:
            index = json.load(f)
        return index if isinstance(index, dict) else {}
    except (OSError, ValueError):
        return {}


def lookup(key: str) -> str | None:
    """The saved clip (a media ref) rendered under this fingerprint, if it's still there."""
    ref = _read_index().get(key)
    if not ref:
        return None
    try:
        path_of(ref)
    except ValueError:
        return None
    return ref


def remember(key: str, ref: str) -> None:
    with _lock:
        index = _read_index()
        index[key] = ref
        path = _index_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".part", "w", encoding="utf-8") as f:
            json.dump(index, f, indent=1)
        os.replace(path + ".part", path)


def _scenes_path() -> str:
    return os.path.join(os.path.dirname(_index_path()), SCENES_FILE)


def _read_scenes() -> dict[str, dict]:
    try:
        with open(_scenes_path(), encoding="utf-8") as f:
            scenes = json.load(f)
        return scenes if isinstance(scenes, dict) else {}
    except (OSError, ValueError):
        return {}


def remember_scene(scene_id: str | None, ref: str, key: str | None, scene: str | None) -> None:
    """`ref` is now `scene_id`'s latest clip, made under fingerprint `key` (scene half `scene`)."""
    if not scene_id:
        return
    import time

    with _lock:
        scenes = _read_scenes()
        scenes[scene_id] = {"ref": ref, "key": key, "scene_key": scene, "time": time.time()}
        path = _scenes_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".part", "w", encoding="utf-8") as f:
            json.dump(scenes, f, indent=1)
        os.replace(path + ".part", path)


def _takes_path() -> str:
    return os.path.join(os.path.dirname(_index_path()), TAKES_FILE)


def _read_takes() -> dict[str, list[dict]]:
    try:
        with open(_takes_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def add_take(scene_id: str | None, ref: str, info: dict) -> None:
    """A newly rendered clip of `scene_id`, with what's worth showing about it (`info`)."""
    if not scene_id:
        return
    import time

    with _lock:
        takes = _read_takes()
        rows = [t for t in takes.get(scene_id, []) if isinstance(t, dict) and t.get("ref") != ref]
        rows.append({"ref": ref, "time": time.time(), **info})
        takes[scene_id] = rows[-TAKES_KEPT:]
        path = _takes_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".part", "w", encoding="utf-8") as f:
            json.dump(takes, f, indent=1)
        os.replace(path + ".part", path)


def takes(scene_ids: list[str]) -> dict[str, list[dict]]:
    """Each scene's takes still on disk, newest first."""
    all_takes = _read_takes()
    out: dict[str, list[dict]] = {}
    for sid in scene_ids:
        rows = []
        for t in reversed(all_takes.get(sid, [])):
            try:
                path_of(t["ref"])
            except (KeyError, ValueError):
                continue
            rows.append(t)
        # Rendered before takes were kept: its latest clip is its one take so far.
        if not rows and (record := latest(sid)):
            rows.append(
                {"ref": record["ref"], "time": record.get("time", 0), "key": record.get("key")}
            )
        out[sid] = rows
    return out


def use_take(scene_id: str, ref: str) -> bool:
    """Make one of `scene_id`'s takes its latest clip again. False when it isn't one of them."""
    take = next((t for t in _read_takes().get(scene_id, []) if t.get("ref") == ref), None)
    if take is None:
        # A clip from before takes were kept is only ever offered as the scene's latest: it
        # already is.
        record = latest(scene_id)
        return bool(record and record.get("ref") == ref)
    remember_scene(scene_id, ref, take.get("key"), take.get("scene_key"))
    return True


def latest(scene_id: str | None) -> dict | None:
    """The scene's latest clip — `{ref, key, scene_key, time}` — if it's still on disk."""
    record = _read_scenes().get(scene_id or "")
    if not isinstance(record, dict) or not record.get("ref"):
        return None
    try:
        path_of(record["ref"])
    except ValueError:
        return None
    return record
