"""The grey box command line, for agents and people: check a scene, look at it, render its shots.

    python nodes/greybox/cli.py check  SCENE.json
    python nodes/greybox/cli.py sheet  SCENE.json [--out sheet.png] [--per-shot 4] [--width 320]
    python nodes/greybox/cli.py plan   SCENE.json [--out plan.png] [--at 2.5]
    python nodes/greybox/cli.py frame  SCENE.json --shot 1A --at 2.4 [--out 1A.png] [--width 960]
    python nodes/greybox/cli.py gltf   SCENE.json [--at 2.5] [--out scene.glb]
    python nodes/greybox/cli.py video  SCENE.json --shot 1A [--out 1A.mp4] [--width 832 --height 480] [--depth]
                                       (--shot all: the whole scene as it cuts)

Outputs go beside the scene, in `renders/`, unless `--out` says otherwise. Needs torch, numpy and
Pillow (ComfyUI's Python has them), and ffmpeg for videos. Runs on the CPU unless `--device cuda`.
The format is docs/GREYBOX.md.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

if __package__:
    from .core import gltf as ggltf
    from .core import scene as gscene
    from .core import sheet as gsheet
else:  # run as a script: python nodes/greybox/cli.py …
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from core import gltf as ggltf  # type: ignore[no-redef]
    from core import scene as gscene  # type: ignore[no-redef]
    from core import sheet as gsheet  # type: ignore[no-redef]


def _out(scene_path: Path, given: str | None, name: str) -> Path:
    if given:
        return Path(given)
    return scene_path.parent / "renders" / name


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="greybox", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "sheet", "plan", "frame", "gltf", "video"):
        p = sub.add_parser(name)
        p.add_argument("scene")
        p.add_argument("--out")
        p.add_argument("--device", default="cpu")
        if name == "sheet":
            p.add_argument("--per-shot", type=int, default=4)
            p.add_argument("--width", type=int, default=320)
        if name == "gltf":
            p.add_argument("--at", type=float, default=0.0)
        if name == "plan":
            p.add_argument("--at", type=float, default=0.0)
            p.add_argument("--size", type=int, default=640)
        if name == "frame":
            p.add_argument("--shot", required=True)
            p.add_argument(
                "--at", type=float, help="seconds in the scene (default: the shot's middle)"
            )
            p.add_argument("--width", type=int, default=960)
            p.add_argument("--height", type=int, default=540)
        if name == "video":
            p.add_argument("--shot", required=True)
            p.add_argument("--width", type=int, default=832)
            p.add_argument("--height", type=int, default=480)
            p.add_argument("--fps", type=float)
            p.add_argument("--depth", action="store_true")
    a = ap.parse_args(argv)
    path = Path(a.scene)
    try:
        scene = gscene.load(path)
    except gscene.SceneError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    started = time.time()
    if a.cmd == "check":
        print(
            f"{scene.name}: set {scene.set.name} ({len(scene.set.shapes)} shapes), {scene.length:.2f}s at {scene.fps:g} fps"
        )
        print(f"  marks: {', '.join(scene.set.marks) or '—'}")
        print(f"  set cameras: {', '.join(scene.set.cameras) or '—'}")
        for actor in scene.actors:
            m = actor.member
            print(f"  {actor.id}: {len(actor.keys)} keys, {m.height:.2f} m tall")
        for s in scene.shots:
            print(f"  shot {s.name}: {s.start:.2f}-{s.end:.2f}s, {len(s.camera)} camera keys")
        return 0
    if a.cmd == "sheet":
        out = _out(path, a.out, f"{path.stem}.sheet.png")
        out.parent.mkdir(parents=True, exist_ok=True)
        gsheet.contact_sheet(scene, a.per_shot, a.width, a.device).save(out)
    elif a.cmd == "plan":
        out = _out(path, a.out, f"{path.stem}.plan.png")
        out.parent.mkdir(parents=True, exist_ok=True)
        gsheet.plan(scene, a.size, a.device, a.at).save(out)
    elif a.cmd == "gltf":
        out = _out(path, a.out, f"{path.stem}@{a.at:.2f}.glb")
        ggltf.export(scene, out, a.at)
    elif a.cmd == "frame":
        shot = scene.shot(a.shot)
        if shot is None:
            print(
                f"error: no shot {a.shot!r}; shots: {', '.join(s.name for s in scene.shots)}",
                file=sys.stderr,
            )
            return 2
        t = a.at if a.at is not None else (shot.start + shot.end) / 2
        out = _out(path, a.out, f"{path.stem}.{shot.name}@{t:.2f}.png")
        out.parent.mkdir(parents=True, exist_ok=True)
        gsheet.still(scene, shot, t, a.width, a.height, a.device).save(out)
    elif a.shot == "all":
        if not scene.shots:
            print("error: the scene has no shots", file=sys.stderr)
            return 2
        fps = a.fps or scene.fps
        frames = gsheet.scene_frames(scene, a.width, a.height, a.device, fps, depth=a.depth)
        last = max(scene.shots, key=lambda s: s.start)
        frames = gsheet.pad_to(
            frames,
            gsheet.h3_frames(frames.shape[0]),
            lambda k: gsheet.shot_frames(
                scene, last, a.width, a.height, a.device, fps, a.depth, start=last.end, count=k
            ),
        )
        out = _out(path, a.out, f"{path.stem}.cut{'.depth' if a.depth else ''}.mp4")
        gsheet.save_video(frames, out, fps)
    else:
        shot = scene.shot(a.shot)
        if shot is None:
            print(
                f"error: no shot {a.shot!r}; shots: {', '.join(s.name for s in scene.shots)}",
                file=sys.stderr,
            )
            return 2
        fps = a.fps or scene.fps
        frames = gsheet.shot_frames(scene, shot, a.width, a.height, a.device, fps, depth=a.depth)
        frames = gsheet.pad_to(
            frames,
            gsheet.h3_frames(frames.shape[0]),
            lambda k: gsheet.shot_frames(
                scene, shot, a.width, a.height, a.device, fps, a.depth, start=shot.end, count=k
            ),
        )
        out = _out(path, a.out, f"{path.stem}.{shot.name}{'.depth' if a.depth else ''}.mp4")
        gsheet.save_video(frames, out, fps)
    print(f"{out}  ({time.time() - started:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
