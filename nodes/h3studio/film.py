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

from . import _carry, _marks, _reuse, _track
from ._media import frame_count, path_of
from ._project import FPS, frames_for

LOG = logging.getLogger(__name__)

FILMS_FILE = "films.json"
FILMS_KEPT = 40
_lock = threading.Lock()


def assemble(proj: dict, music: dict | None = None, volume: float = 0.8, fade: float = 2.0):
    """Every scene's current take (black for its length where there is none), joined with the
    project's film settings into a file in ComfyUI's temp folder — streamed as `save` streams it,
    so the film never sits in memory whole — with `music`, when given, under all of it at
    `volume`, fading out over its last `fade` seconds. Returns the video, read from that file, and
    the scene numbers that had no take."""
    import uuid

    import folder_paths
    from comfy_api.latest import InputImpl

    folder = os.path.join(folder_paths.get_temp_directory(), "h3studio")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"film_{uuid.uuid4().hex[:12]}.mp4")
    score = (music, volume, fade) if music is not None else None
    _, missing = _stream(proj, path, None, score)
    return InputImpl.VideoFromFile(path), missing


def save(proj: dict, metadata: dict | None = None) -> dict:
    """Join every scene's current take into the film and save it under output/h3studio/film,
    streaming: one scene decoded at a time and written straight to the encoder, so a long film
    never sits in memory whole (it did: a few minutes at full size took tens of GB, and the
    system killed ComfyUI). The sound, small, is joined whole as `_carry.join` does."""
    import folder_paths

    folder, name, counter, subfolder, _ = folder_paths.get_save_image_path(
        "h3studio/film/film", folder_paths.get_output_directory()
    )
    file = f"{name}_{counter:05}_.mp4"
    seconds, missing = _stream(proj, os.path.join(folder, file), metadata)
    ref = "/".join(p for p in ("output", subfolder, file) if p)
    record = {
        "ref": ref,
        "time": time.time(),
        "seconds": round(seconds, 3),
        "scenes": [s["id"] for s in proj["scenes"]],
        "missing": missing,
    }
    with _lock:
        rows = [r for r in _read() if r.get("ref") != ref] + [record]
        _write(rows[-FILMS_KEPT:])
    LOG.info("H3 Studio: film saved to %s", ref)
    return record


def _scenes(proj: dict) -> tuple[list[dict], list[int]]:
    """Each scene as the film plays it: its clip's path (None: black for its length), the head it
    regenerated over the scene before, its handle's sound and its own sound."""
    from ._media import has_audio, load_audio

    out, missing = [], []
    for i, scene in enumerate(proj["scenes"]):
        record = _reuse.latest(scene["id"])
        path = path_of(record["ref"]) if record else None
        if not path or not os.path.exists(path):
            missing.append(i + 1)
            out.append(
                {
                    "path": None,
                    "frames": frames_for(scene["seconds"]),
                    "head": None,
                    "tail": None,
                    "audio": None,
                }
            )
            continue
        _, head = _carry.load_sidecar(path)
        out.append(
            {
                "path": path,
                "head": head,
                "tail": _carry.load_tail(path),
                "audio": load_audio(record["ref"]) if has_audio(record["ref"]) else None,
            }
        )
    if missing:
        LOG.warning(
            "H3 Studio film: scene%s %s never rendered, black",
            "s" if len(missing) > 1 else "",
            ", ".join(map(str, missing)),
        )
    return out, missing


def _frames(scene: dict, width: int, height: int):
    """A scene's pictures one at a time, as uint8 [H, W, 3] arrays at the film's size."""
    import av
    import numpy as np

    if scene["path"] is None:
        black = np.zeros((height, width, 3), dtype=np.uint8)
        for _ in range(scene["frames"]):
            yield black
        return
    with av.open(scene["path"]) as container:
        for frame in container.decode(video=0):
            if frame.width != width or frame.height != height:
                frame = frame.reformat(width=width, height=height)
            yield frame.to_ndarray(format="rgb24")


def _stream(
    proj: dict, path: str, metadata: dict | None, score: tuple | None = None
) -> tuple[float, list[int]]:
    """Stream the film to `path`; its length in seconds, and the scenes that had no take. `score`
    (music, volume, fade) is laid under the whole film's sound, as the H3 Studio Film node asks."""
    from fractions import Fraction

    import av
    import comfy.audio
    import numpy as np
    import torch

    scenes, missing = _scenes(proj)
    crossfade = int(proj["film"]["crossfade"])
    width, height = proj["canvas"]["width"], proj["canvas"]["height"]
    for s in scenes:
        if s["path"]:
            with av.open(s["path"]) as c:
                width, height = c.streams.video[0].width, c.streams.video[0].height
            break
    like = next((s["audio"] for s in scenes if s["audio"] is not None), None)
    if like is None and proj["track"] and proj["track"]["sound"] != "scenes":
        like = _track.song(proj["track"]["media"])
    if like is None and score is not None:
        like = score[0]
    rate = int(like["sample_rate"]) if like else 48000
    channels = like["waveform"].shape[1] if like else 2
    # Where each scene falls, for the tag: tags are written with the header, before any picture,
    # so each clip's length is read from its file first.
    marks, start = [], 0
    for scene, s in zip(proj["scenes"], scenes, strict=True):
        n = frame_count(s["path"]) if s["path"] else s["frames"]
        marks.append(_marks.scene(scene, start, n))
        start += n

    # As ComfyUI's own save: MP4 keeps custom tags (the workflow) only when asked to.
    with av.open(path, "w", options={"movflags": "use_metadata_tags+faststart"}) as output:
        for key, value in (metadata or {}).items():
            output.metadata[key] = json.dumps(value)
        output.metadata[_marks.TAG] = json.dumps(_marks.tag("film", marks))
        video = output.add_stream("libx264", rate=Fraction(FPS))
        video.width, video.height, video.pix_fmt = width, height, "yuv420p"
        video.options = {"crf": "18"}
        # Every stream is declared before anything is written; the sound is filled in last.
        layout = {1: "mono", 2: "stereo"}.get(channels, "stereo")
        audio = output.add_stream("aac", rate=rate, layout=layout) if like is not None else None

        def put(rgb) -> None:
            frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(rgb), format="rgb24")
            output.mux(video.encode(frame.reformat(format="yuv420p")))

        # The last few pictures of each scene wait, in case the next one hands over within them.
        held: list = []
        counts, fades = [], []
        for i, s in enumerate(scenes):
            head = s["head"]
            k = 0
            if i and head is not None and crossfade > 0 and held:
                head_frames, _, head_picture = head
                k = min(crossfade, head_frames.shape[0], len(held))
                if head_picture and tuple(head_frames.shape[1:3]) == (height, width):
                    tail = head_frames[-k:].float()
                    ours = torch.from_numpy(np.stack(held[-k:])).float() / 255.0
                    for j in range(_carry.switch_frame(ours, tail), k):
                        held[len(held) - k + j] = (
                            (tail[j] * 255.0).round().clamp(0, 255).to(torch.uint8).numpy()
                        )
            fades.append(k)
            for rgb in held:
                put(rgb)
            held = []
            n = 0
            for rgb in _frames(s, width, height):
                held.append(rgb)
                n += 1
                if len(held) > crossfade:
                    put(held.pop(0))
            counts.append(n)
        for rgb in held:
            put(rgb)
        output.mux(video.encode(None))

        sound = _sound(scenes, counts, fades, rate, channels, comfy.audio, torch)
        sound = _track.film_sound(proj, sound, counts, rate, channels)
        if score is not None:
            music, volume, fade = score
            under = _carry._under(
                {"waveform": sound[None], "sample_rate": rate} if sound is not None else None,
                music,
                sum(counts) / FPS,
                volume,
                fade,
            )
            sound = under["waveform"][0][:channels]
        if audio is not None and sound is not None:
            frame = av.AudioFrame.from_ndarray(
                sound.contiguous().numpy(), format="fltp", layout=layout
            )
            frame.sample_rate, frame.pts = rate, 0
            output.mux(audio.encode(frame))
            output.mux(audio.encode(None))
        output.set_chapters(_marks.scene_chapters(proj["scenes"], counts))
    return sum(counts) / FPS, missing


def _sound(scenes, counts, fades, rate, channels, audio_lib, torch):
    """The film's sound, joined as `_carry.join` joins it: a continued scene's head sound fades in
    over the end of the one before, unless that one left a handle, which runs on over the cut."""
    import math

    if not any(s["audio"] is not None for s in scenes):
        return None
    sound: list = []
    for i, s in enumerate(scenes):
        length = round(counts[i] / FPS * rate)
        if s["audio"] is None:
            wave = torch.zeros((1, channels, length))
        else:
            wave = s["audio"]["waveform"].float()
            if s["audio"]["sample_rate"] != rate:
                wave = audio_lib.resample(wave, s["audio"]["sample_rate"], rate)
            if wave.shape[1] != channels:
                wave = wave.mean(dim=1, keepdim=True).expand(1, channels, wave.shape[-1])
            wave = wave[..., :length]
            if wave.shape[-1] < length:
                wave = torch.nn.functional.pad(wave, (0, length - wave.shape[-1]))
        head, k = s["head"], fades[i]
        handle = scenes[i - 1]["tail"] if i and head is not None and k else None
        if k and sound and handle is None and head[1] is not None:
            head_wave = head[1]["waveform"].float()
            if head[1]["sample_rate"] != rate:
                head_wave = audio_lib.resample(head_wave, head[1]["sample_rate"], rate)
            n = min(round(k / FPS * rate), sound[-1].shape[-1], head_wave.shape[-1])
            if n > 0 and head_wave.shape[1] == channels:
                t = torch.linspace(0, 1, n) * (math.pi / 2)
                faded = sound[-1][..., -n:] * torch.cos(t) + head_wave[..., -n:] * torch.sin(t)
                sound[-1] = torch.cat([sound[-1][..., :-n], faded], dim=-1)
        if handle is not None:
            wave = _carry._over(wave, handle, rate)
        sound.append(wave)
    return torch.cat(sound, dim=-1)[0]


def films(scene_ids: list[str]) -> list[dict]:
    """The films made from this project (sharing any of its scenes), newest first, still on disk."""
    ids = set(scene_ids)
    return [r for r in reversed(_read()) if ids & set(r.get("scenes") or []) and _on_disk(r)]


def _on_disk(record: dict) -> bool:
    """Whether a film's file is still there. `path_of` refuses a missing (or foreign) file with a
    ValueError, so one deleted film is skipped rather than failing the whole list."""
    try:
        return os.path.exists(path_of(record["ref"]))
    except ValueError:
        return False


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
