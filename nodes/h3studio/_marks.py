"""Where a saved video's scenes and shots fall, carried in the file itself so another editor (ZenCut)
can cut it where the studio did: a `h3studio` tag (JSON, times in seconds in the file's own timeline)
on every film, mix and take, and MP4 chapters on the ones written here — a film's per scene, a mix's
per shot. A take is saved by core's video saver, which writes tags but not chapters. Pure: no media.
"""

from __future__ import annotations

from fractions import Fraction

from ._project import FPS

TAG = "h3studio"
VERSION = 1
TITLE_CHARS = 60


def scene(scene: dict, start: int, frames: int) -> dict:
    """A scene's entry in the tag, `frames` long from frame `start` of the file. A shot that starts
    past its end (the take is shorter than the scene now is) isn't in it."""
    begin = start / FPS
    return {
        "id": scene["id"],
        "title": scene["title"],
        "start": round(begin, 4),
        "end": round((start + frames) / FPS, 4),
        "shots": [
            {"id": s["id"], "start": round(begin + s["at"], 4), "text": s["text"]}
            for j, s in enumerate(scene["shots"])
            if not j or round(s["at"] * FPS) < frames
        ],
    }


def tag(kind: str, scenes: list[dict]) -> dict:
    """The tag's value: `kind` is "film", "mix" or "take"; `scenes` are `scene` entries."""
    return {"v": VERSION, "fps": FPS, "kind": kind, "scenes": scenes}


def scene_chapters(scenes: list[dict], counts: list[int]) -> list[dict]:
    """A film's chapters, one per scene, `counts` its frames in the film."""
    out, start = [], 0
    for i, (s, n) in enumerate(zip(scenes, counts, strict=True)):
        out.append(_chapter(i, start, start + n, s["title"].strip() or f"Scene {i + 1}"))
        start += n
    return out


def shot_chapters(scene: dict, frames: int) -> list[dict]:
    """A mix's chapters, one per shot of its scene, the last running to its `frames`."""
    shots = [(s, round(s["at"] * FPS)) for s in scene["shots"]]
    shots = [(s, a) for j, (s, a) in enumerate(shots) if not j or a < frames]
    return [
        _chapter(
            j,
            a,
            shots[j + 1][1] if j + 1 < len(shots) else frames,
            _title(s["text"]) or f"Shot {j + 1}",
        )
        for j, (s, a) in enumerate(shots)
    ]


def _chapter(i: int, start: int, end: int, title: str) -> dict:
    return {
        "id": i + 1,
        "start": start,
        "end": end,
        "time_base": Fraction(1, FPS),
        "metadata": {"title": title},
    }


def _title(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= TITLE_CHARS else text[: TITLE_CHARS - 1].rstrip() + "…"
