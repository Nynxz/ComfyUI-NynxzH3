"""The grey box command line, for agents and people: check a scene, look at it, render its shots.

    python nodes/greybox/cli.py check  SCENE.json
    python nodes/greybox/cli.py sheet  SCENE.json [--out sheet.png] [--per-shot 4] [--width 320]
    python nodes/greybox/cli.py plan   SCENE.json [--out plan.png] [--at 2.5]
    python nodes/greybox/cli.py frame  SCENE.json --shot 1A --at 2.4 [--out 1A.png] [--width 960]
    python nodes/greybox/cli.py gltf   SCENE.json [--at 2.5] [--out scene.glb]
    python nodes/greybox/cli.py video  SCENE.json --shot 1A [--out 1A.mp4] [--width 832 --height 480] [--depth]
                                       (--shot all: the whole scene as it cuts)
    python nodes/greybox/cli.py import SCENE.gb.txt [--out scenes/NAME.json]   (a script -> scene JSON)
    python nodes/greybox/cli.py export SCENE.json                              (scene JSON -> a script)

Every command that takes SCENE.json takes a Grey Box scene script (SCENE.gb.txt) too: its set,
props and cast are found in the show folder around it (sets/, props/, cast.json). The script
format is docs/GREYBOX-SCRIPT.md.

Outputs go beside the scene, in `renders/`, unless `--out` says otherwise. Needs torch, numpy and
Pillow (ComfyUI's Python has them), and PyAV for videos. Runs on the CPU unless `--device cuda`.
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
    from .core import script as gscript
    from .core import sheet as gsheet
else:  # run as a script: python nodes/greybox/cli.py …
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from core import gltf as ggltf  # type: ignore[no-redef]
    from core import scene as gscene  # type: ignore[no-redef]
    from core import script as gscript  # type: ignore[no-redef]
    from core import sheet as gsheet  # type: ignore[no-redef]

import json


def _show(path: Path) -> Path:
    """The show folder a scene or script belongs to: the first one up with a sets/ folder."""
    for d in (path.parent, *path.parents):
        if (d / "sets").is_dir():
            return d
    return path.parent


def _read_script(path: Path) -> dict:
    """A scene script read into scene JSON against its show's set, props and cast. Errors say
    which line, and stop here."""
    show = _show(path)
    text = path.read_text(encoding="utf-8")
    set_name = gscript._sections(text)[0].get("set", "")
    set_path = show / "sets" / f"{set_name}.json"
    if not set_name or not set_path.exists():
        raise gscene.SceneError(f"set {set_name!r} isn't in {show / 'sets'}")
    cast_path = show / "cast.json"
    raw, errors = gscript.import_scene(
        text,
        json.loads(set_path.read_text(encoding="utf-8")),
        gscene.load_props(show / "props"),
        json.loads(cast_path.read_text(encoding="utf-8")) if cast_path.exists() else None,
    )
    if errors:
        raise gscene.SceneError("the script has errors:\n  " + "\n  ".join(errors))
    return raw


def _load(path: Path):
    if path.suffix == ".json":
        return gscene.load(path)
    raw = _read_script(path)
    show = _show(path)
    props = gscene.load_props(show / "props")
    the_set = gscene.load_set(show / "sets" / f"{raw['set']}.json", props)
    return gscene.build(
        raw, the_set, gscene.load_cast(show / "cast.json"), raw.get("name", path.stem)
    )


def _out(scene_path: Path, given: str | None, name: str) -> Path:
    if given:
        return Path(given)
    return scene_path.parent / "renders" / name


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="greybox", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "sheet", "plan", "frame", "gltf", "video", "import", "export"):
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
        if a.cmd == "export":
            raw = json.loads(path.read_text(encoding="utf-8"))
            text = gscript.export_scene(raw)
            if a.out:
                Path(a.out).write_text(text, encoding="utf-8")
            else:
                print(text, end="")
            return 0
        if a.cmd == "import":
            raw = _read_script(path)
            out = (
                Path(a.out) if a.out else _show(path) / "scenes" / f"{path.name.split('.')[0]}.json"
            )
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
            print(f"wrote {out}")
            return 0
        scene = _load(path)
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
        out = _out(path, a.out, f"{path.name.split('.')[0]}.sheet.png")
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
