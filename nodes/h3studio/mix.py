"""A scene made of shots from several of its takes, so a good shot from one render and a good shot
from another make one clip without stitching in post.

Takes of the scene's length share their timing, so a shot is the same
frames in each and the takes cut together at shot boundaries. The mix is saved as a take of its
own and made the scene's clip: the monitor, H3 Studio Film and the next scene take it like any
other clip. Its base is the take its last part comes from — the seed it brings back, the
fingerprint it's current under, and the end the next scene continues from — and its head (what
H3 Studio Join fades in) comes from its first part's take. Files in, a file out, on the CPU.
"""

from __future__ import annotations

import logging
import os

from . import _carry, _marks, _reuse
from ._media import frame_count, has_audio, load_audio, path_of
from ._project import FPS, frames_for, normalize

LOG = logging.getLogger(__name__)

#: Seconds of fade either side of each cut in the sound, so a join doesn't click.
EDGE = 0.004


class MixError(ValueError):
    pass


def _parse_parts(parts) -> list[dict]:
    """`parts` as the editor sent them, each `{ref, start}`; a MixError (the editor's mistake, not
    the server's) for anything else."""
    if not isinstance(parts, list):
        raise MixError("The mix's parts should be a list of {ref, start}.")
    out = []
    for p in parts:
        try:
            out.append({"ref": str(p["ref"]), "start": int(p["start"])})
        except (KeyError, TypeError, ValueError):
            raise MixError(f"A mix part should be {{ref, start}}, not {p!r}.") from None
    return out


def make(project: dict, scene_id: str, parts: list[dict], metadata: dict | None = None) -> dict:
    """Join `parts` (`[{ref, start}]`, `start` the frame each takes over at, the first 0) into a
    clip of scene `scene_id` and make it the scene's clip. Returns the new take."""
    from .studio import takes_fit

    proj = normalize(project)
    index = next((i for i, s in enumerate(proj["scenes"]) if s["id"] == scene_id), None)
    if index is None:
        raise MixError("That scene isn't in the project.")
    rows = _reuse.takes([scene_id]).get(scene_id, [])
    fit = {t["ref"]: t for t in takes_fit(project, {scene_id: rows}).get(scene_id, rows)}
    parts = sorted(_parse_parts(parts), key=lambda p: p["start"])
    if not parts or parts[0]["start"] != 0:
        raise MixError("A mix starts with a part at frame 0.")
    for p in parts:
        take = fit.get(p["ref"])
        if take is None:
            raise MixError(f"{p['ref']} isn't one of this scene's takes.")
    # Neighbouring parts from the same take are one part.
    merged = [parts[0]]
    for p in parts[1:]:
        if p["ref"] != merged[-1]["ref"]:
            merged.append(p)
    parts = merged
    if len(parts) == 1:
        raise MixError("Every shot comes from the same take: use that take instead.")

    # Takes of any version cut together, as long as they run the scene's length: the shots are cut
    # where the scene has them now. A mix with an earlier version in it is out of date, as that take
    # would be on its own.
    total = frames_for(proj["scenes"][index]["seconds"])
    for p in parts:
        if (n := frame_count(path_of(p["ref"]))) != total:
            raise MixError(
                f"{os.path.basename(p['ref'])} is {n / FPS:.2f} s and the scene is now "
                f"{total / FPS:.2f} s: only takes of the scene's length can be mixed."
            )
    for i, p in enumerate(parts):
        p["end"] = parts[i + 1]["start"] if i + 1 < len(parts) else total
        if not 0 <= p["start"] < p["end"] <= total:
            raise MixError(f"A part from frame {p['start']} doesn't fit the {total} frames.")

    import folder_paths

    folder, name, counter, subfolder, _ = folder_paths.get_save_image_path(
        f"h3studio/scene{index + 1:02}_mix", folder_paths.get_output_directory()
    )
    file = f"{name}_{counter:05}_.mp4"
    path = os.path.join(folder, file)
    ref = "/".join(x for x in ("output", subfolder, file) if x)
    scene = proj["scenes"][index]
    metadata = {**(metadata or {}), _marks.TAG: _marks.tag("mix", [_marks.scene(scene, 0, total)])}
    _write(path, parts, metadata, _marks.shot_chapters(scene, total))
    _carry_sidecar(path, first=path_of(parts[0]["ref"]), last=path_of(parts[-1]["ref"]))

    base = fit[parts[-1]["ref"]]
    info = {
        "key": base.get("key"),
        "scene_key": base.get("scene_key"),
        "seed": base.get("seed"),
        "seconds": round(total / FPS, 3),
        "prompt": base.get("prompt", ""),
        "mix": [{"ref": p["ref"], "start": p["start"]} for p in parts],
    }
    _reuse.add_take(scene_id, ref, info)
    _reuse.remember_scene(scene_id, ref, base.get("key"), base.get("scene_key"))
    LOG.info(
        "H3 Studio: scene %d mixed from %d takes (%s)",
        index + 1,
        len({p["ref"] for p in parts}),
        ", ".join(f"frame {p['start']}: {os.path.basename(p['ref'])}" for p in parts),
    )
    return {"ref": ref, **info}


def _write(path: str, parts: list[dict], metadata: dict, chapters: list[dict]) -> None:
    """Stream each part's frames from its take into one clip, join their sound, and mark its
    shots as chapters."""
    import json
    from fractions import Fraction

    import av
    import numpy as np
    import torch

    with av.open(path_of(parts[0]["ref"])) as c:
        width, height = c.streams.video[0].width, c.streams.video[0].height
    sounds = [load_audio(p["ref"]) if has_audio(p["ref"]) else None for p in parts]
    like = next((s for s in sounds if s is not None), None)
    rate = int(like["sample_rate"]) if like else 48000
    channels = like["waveform"].shape[1] if like else 2

    with av.open(path, "w", options={"movflags": "use_metadata_tags+faststart"}) as output:
        for key, value in metadata.items():
            output.metadata[key] = json.dumps(value)
        video = output.add_stream("libx264", rate=Fraction(FPS))
        video.width, video.height, video.pix_fmt = width, height, "yuv420p"
        video.options = {"crf": "18"}
        layout = {1: "mono", 2: "stereo"}.get(channels, "stereo")
        audio = output.add_stream("aac", rate=rate, layout=layout) if like is not None else None

        for p in parts:
            with av.open(path_of(p["ref"])) as c:
                for n, frame in enumerate(c.decode(video=0)):
                    if n >= p["end"]:
                        break
                    if n < p["start"]:
                        continue
                    if frame.width != width or frame.height != height:
                        frame = frame.reformat(width=width, height=height)
                    rgb = np.ascontiguousarray(frame.to_ndarray(format="rgb24"))
                    out = av.VideoFrame.from_ndarray(rgb, format="rgb24").reformat(format="yuv420p")
                    output.mux(video.encode(out))
        output.mux(video.encode(None))

        if audio is not None:
            pieces = []
            ramp = max(1, round(EDGE * rate))
            for i, (p, s) in enumerate(zip(parts, sounds, strict=True)):
                a, b = round(p["start"] / FPS * rate), round(p["end"] / FPS * rate)
                if s is None:
                    piece = torch.zeros((channels, b - a))
                else:
                    wave = s["waveform"][0].float()
                    if s["sample_rate"] != rate:
                        import comfy.audio

                        wave = comfy.audio.resample(wave[None], s["sample_rate"], rate)[0]
                    if wave.shape[0] != channels:
                        wave = wave.mean(dim=0, keepdim=True).expand(channels, -1)
                    piece = wave[:, a:b]
                    if piece.shape[-1] < b - a:
                        piece = torch.nn.functional.pad(piece, (0, b - a - piece.shape[-1]))
                piece = piece.clone()
                n = min(ramp, piece.shape[-1] // 2)
                if n and i > 0:
                    piece[:, :n] *= torch.linspace(0, 1, n)
                if n and i < len(parts) - 1:
                    piece[:, -n:] *= torch.linspace(1, 0, n)
                pieces.append(piece)
            sound = torch.cat(pieces, dim=-1)
            frame = av.AudioFrame.from_ndarray(
                sound.contiguous().numpy(), format="fltp", layout=layout
            )
            frame.sample_rate, frame.pts = rate, 0
            output.mux(audio.encode(frame))
            output.mux(audio.encode(None))
        output.set_chapters(chapters)


def _carry_sidecar(path: str, first: str, last: str) -> None:
    """The mix's sidecar: the head from its first part's take, and from its last part's take the
    latent and the sound past its end — what the next scene continues from and fades over."""
    latent, _ = _carry.load_sidecar(last)
    _, head = _carry.load_sidecar(first)
    _carry.save_sidecar(path, latent, head, _carry.load_tail(last))
