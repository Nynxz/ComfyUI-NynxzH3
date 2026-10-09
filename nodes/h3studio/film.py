"""The finished film: every scene's current take joined into one video and saved, so a render ends
with the film itself rather than a graph of join and save nodes after the loop.

A full render saves it as its last scene lands (H3 Studio Clip); the studio's Renders sidebar saves
it again on demand, e.g. after a scene is re-rendered on its own or another take is made current.
Everything here runs on the CPU (files in, a file out), so the route may call it off the queue.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time

from . import _carry, _reuse
from ._media import path_of
from ._project import frames_for

LOG = logging.getLogger(__name__)

FILMS_FILE = "films.json"
FILMS_KEPT = 40
_lock = threading.Lock()


def assemble(proj: dict, music: dict | None = None, volume: float = 0.8, fade: float = 2.0):
    """Every scene's current take (black for its length where there is none), joined with the
    project's film settings. Returns the video and the scene numbers that had no take."""
    from comfy_api.latest import InputImpl

    from .studio import _blank_video

    film = proj["film"]
    width, height = proj["canvas"]["width"], proj["canvas"]["height"]
    videos, missing = [], []
    for i, scene in enumerate(proj["scenes"]):
        record = _reuse.latest(scene["id"])
        if record and os.path.exists(path_of(record["ref"])):
            video = InputImpl.VideoFromFile(path_of(record["ref"]))
            video.h3_scene = i
            video.h3_latent, video.h3_head = _carry.load_sidecar(path_of(record["ref"]))
            video.h3_tail = _carry.load_tail(path_of(record["ref"]))
        else:
            missing.append(i + 1)
            video = _blank_video(
                {
                    "scene": i,
                    "frames": frames_for(scene["seconds"]),
                    "width": width,
                    "height": height,
                }
            )
        videos.append(video)
    if missing:
        LOG.warning(
            "H3 Studio film: scene%s %s never rendered, black",
            "s" if len(missing) > 1 else "",
            ", ".join(map(str, missing)),
        )
    joined = _carry.join(videos, film["crossfade"], music, volume, fade)
    return joined, missing


def save(proj: dict, metadata: dict | None = None) -> dict:
    """Assemble the film and save it under output/h3studio/film; the record the studio lists."""
    import folder_paths

    video, missing = assemble(proj)
    folder, name, counter, subfolder, _ = folder_paths.get_save_image_path(
        "h3studio/film/film", folder_paths.get_output_directory()
    )
    file = f"{name}_{counter:05}_.mp4"
    video.save_to(os.path.join(folder, file), metadata=metadata)
    ref = "/".join(p for p in ("output", subfolder, file) if p)
    record = {
        "ref": ref,
        "time": time.time(),
        "seconds": round(float(video.get_duration()), 3),
        "scenes": [s["id"] for s in proj["scenes"]],
        "missing": missing,
    }
    with _lock:
        rows = [r for r in _read() if r.get("ref") != ref] + [record]
        _write(rows[-FILMS_KEPT:])
    LOG.info("H3 Studio: film saved to %s", ref)
    return record


def films(scene_ids: list[str]) -> list[dict]:
    """The films made from this project (sharing any of its scenes), newest first, still on disk."""
    ids = set(scene_ids)
    return [
        r
        for r in reversed(_read())
        if ids & set(r.get("scenes") or []) and os.path.exists(path_of(r["ref"]))
    ]


def _path() -> str:
    return os.path.join(os.path.dirname(_reuse._index_path()), FILMS_FILE)


def _read() -> list[dict]:
    try:
        with open(_path(), encoding="utf-8") as f:
            rows = json.load(f)
        return (
            [r for r in rows if isinstance(r, dict) and r.get("ref")]
            if isinstance(rows, list)
            else []
        )
    except (OSError, ValueError):
        return []


def _write(rows: list[dict]) -> None:
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".part", "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1)
    os.replace(path + ".part", path)
