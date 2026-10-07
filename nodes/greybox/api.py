"""HTTP routes for the Grey Box Studio editor. A grey box project is a Codex show's `greybox/`
folder in the user's ComfyUI user directory:

    nynxz-codex/<show>/greybox/
      cast.json
      sets/<name>.json
      scenes/<name>.json

The editor lists projects, opens a scene (with its set and cast), saves each file as it changes,
notices files changed by someone else (an agent), and asks for exact renders — a still or a shot's
video — of what it has, saved or not.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import re
import shutil
from pathlib import Path

from aiohttp import web

from .._zenkit.server import request_allowed
from .core import scene as gscene
from .core import sheet as gsheet

try:
    from server import PromptServer

    _routes = PromptServer.instance.routes
except Exception:  # noqa: BLE001 - no server (import-time checks, tests)
    _routes = None

HERE = Path(__file__).parent
EXAMPLE = HERE / "examples" / "midnight-spoon"
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
KINDS = {"scene": "scenes", "set": "sets"}


class Bad(Exception):
    """A request that can't be done; its message goes back to the editor."""


def codex_root(request: web.Request | None) -> Path:
    """The user's `nynxz-codex` folder (the default user's without a request)."""
    if request is not None and _routes is not None:
        path = PromptServer.instance.user_manager.get_request_user_filepath(request, "nynxz-codex")
        if path is None:
            raise Bad("No user folder for this request.")
        return Path(path)
    import folder_paths

    return Path(folder_paths.get_user_directory()) / "default" / "nynxz-codex"


def project_dir(root: Path, project: str) -> Path:
    if not isinstance(project, str) or not NAME.match(project):
        raise Bad(f"Not a project name: {project!r}.")
    return root / project / "greybox"


def file_of(pdir: Path, kind: str, name: str) -> Path:
    if kind == "cast":
        return pdir / "cast.json"
    if kind not in KINDS or not isinstance(name, str) or not NAME.match(name):
        raise Bad(f"Not a {kind} name: {name!r}.")
    return pdir / KINDS[kind] / f"{name}.json"


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def listing(pdir: Path) -> dict:
    return {
        "scenes": sorted(p.stem for p in (pdir / "scenes").glob("*.json")),
        "sets": sorted(p.stem for p in (pdir / "sets").glob("*.json")),
        "hasCast": (pdir / "cast.json").exists(),
    }


def stamps(pdir: Path) -> dict[str, int]:
    files = [pdir / "cast.json", *(pdir / "scenes").glob("*.json"), *(pdir / "sets").glob("*.json")]
    return {str(f.relative_to(pdir)): f.stat().st_mtime_ns for f in files if f.exists()}


def scene_from(body: dict, pdir: Path) -> gscene.Scene:
    """The scene to render: the editor's own copy (saved or not) when it sends one, else the file."""
    raw = body.get("scene")
    if isinstance(raw, dict):
        set_raw = body.get("set")
        the_set = (
            gscene.set_from(set_raw, str(raw.get("set", "set")))
            if isinstance(set_raw, dict)
            else None
        )
        if the_set is None and isinstance(raw.get("set"), str):
            found = file_of(pdir, "set", raw["set"])
            the_set = gscene.load_set(found) if found.exists() else None
        cast_raw = body.get("cast")
        cast = (
            gscene.cast_from(cast_raw)
            if isinstance(cast_raw, dict)
            else gscene.load_cast(pdir / "cast.json")
        )
        return gscene.build(raw, the_set, cast, str(body.get("name", "scene")))
    return gscene.load(file_of(pdir, "scene", str(body.get("name", ""))))


def _guard(handler):
    async def wrapped(request: web.Request) -> web.Response:
        if (denied := request_allowed(request)) is not None:
            return denied
        try:
            return await handler(request)
        except (Bad, gscene.SceneError) as e:
            return web.json_response({"error": str(e)}, status=400)

    return wrapped


if _routes is not None:

    @_routes.get("/nynxz/greybox/projects")
    @_guard
    async def gb_projects(request: web.Request) -> web.Response:
        """Every Codex show, with its grey box scenes and sets (if it has any yet)."""
        root = codex_root(request)
        out = []
        for show in sorted(p for p in root.glob("*") if p.is_dir()):
            if not ((show / "show.json").exists() or (show / "codex.json").exists()):
                continue
            head = _read(show / "show.json") or _read(show / "codex.json") or {}
            out.append(
                {
                    "id": show.name,
                    "name": head.get("name") or show.name,
                    **listing(show / "greybox"),
                }
            )
        return web.json_response({"projects": out})

    @_routes.post("/nynxz/greybox/open")
    @_guard
    async def gb_open(request: web.Request) -> web.Response:
        """A scene, its set and the cast, as their files hold them (null when missing)."""
        body = await request.json()
        pdir = project_dir(codex_root(request), body.get("project"))
        scene = _read(file_of(pdir, "scene", body.get("scene", ""))) if body.get("scene") else None
        set_name = body.get("set") or (scene or {}).get("set")
        the_set = (
            _read(file_of(pdir, "set", set_name))
            if isinstance(set_name, str) and set_name
            else None
        )
        return web.json_response(
            {
                "scene": scene,
                "set": the_set,
                "setName": set_name if isinstance(set_name, str) else None,
                "cast": _read(pdir / "cast.json") or {},
                **listing(pdir),
                "stamps": stamps(pdir),
            }
        )

    @_routes.post("/nynxz/greybox/save")
    @_guard
    async def gb_save(request: web.Request) -> web.Response:
        """Write one file: a scene, a set, or the cast."""
        body = await request.json()
        pdir = project_dir(codex_root(request), body.get("project"))
        path = file_of(pdir, str(body.get("kind")), body.get("name", ""))
        data = body.get("data")
        if not isinstance(data, dict):
            raise Bad("Nothing to save.")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.part")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)
        return web.json_response({"ok": True, "stamps": stamps(pdir)})

    @_routes.post("/nynxz/greybox/delete")
    @_guard
    async def gb_delete(request: web.Request) -> web.Response:
        body = await request.json()
        pdir = project_dir(codex_root(request), body.get("project"))
        kind = str(body.get("kind"))
        name = body.get("name", "")
        path = file_of(pdir, kind, name)
        if kind == "set":
            users = [
                p.stem
                for p in sorted((pdir / "scenes").glob("*.json"))
                if (_read(p) or {}).get("set") == name
            ]
            if users:
                raise Bad(f"Scenes still use the set {name}: {', '.join(users)}.")
        if path.exists():
            path.unlink()
        return web.json_response({"ok": True, **listing(pdir), "stamps": stamps(pdir)})

    @_routes.post("/nynxz/greybox/stamps")
    @_guard
    async def gb_stamps(request: web.Request) -> web.Response:
        body = await request.json()
        pdir = project_dir(codex_root(request), body.get("project"))
        return web.json_response({"stamps": stamps(pdir), **listing(pdir)})

    @_routes.post("/nynxz/greybox/example")
    @_guard
    async def gb_example(request: web.Request) -> web.Response:
        """Copy the Midnight Spoon example into a project. Files already there are kept, unless
        `replace` — then the example's own scenes and set are overwritten with the current ones.
        The cast is never overwritten: members it lacks are added."""
        body = await request.json()
        pdir = project_dir(codex_root(request), body.get("project"))
        replace = bool(body.get("replace"))
        for src in EXAMPLE.rglob("*.json"):
            dst = pdir / src.relative_to(EXAMPLE)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.name == "cast.json" and dst.exists():
                cast = _read(dst) or {}
                missing = {k: v for k, v in (_read(src) or {}).items() if k not in cast}
                if missing:
                    dst.write_text(
                        json.dumps({**cast, **missing}, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8",
                    )
            elif replace or not dst.exists():
                shutil.copyfile(src, dst)
        return web.json_response({"ok": True, **listing(pdir), "stamps": stamps(pdir)})

    @_routes.post("/nynxz/greybox/still")
    @_guard
    async def gb_still(request: web.Request) -> web.Response:
        """An exact render of one moment of a shot, as a PNG (base64)."""
        body = await request.json()
        pdir = project_dir(codex_root(request), body.get("project"))
        scene = scene_from(body, pdir)
        shot = scene.shot(str(body.get("shot", ""))) or scene.shots[0]
        t = float(body.get("t", shot.start))
        w = max(64, min(int(body.get("width", 960)), 2048))
        h = max(64, min(int(body.get("height", 540)), 2048))

        def run() -> str:
            import comfy.model_management as mm

            img = gsheet.still(scene, shot, t, w, h, mm.get_torch_device())
            buf = io.BytesIO()
            img.save(buf, "PNG")
            return base64.b64encode(buf.getvalue()).decode()

        png = await asyncio.get_running_loop().run_in_executor(None, run)
        if body.get("save"):
            import folder_paths

            folder, name, counter, subfolder, _ = folder_paths.get_save_image_path(
                f"greybox/{body.get('name') or 'scene'}-{shot.name}-still",
                folder_paths.get_temp_directory(),
            )
            file = f"{name}_{counter:05}_.png"
            (Path(folder) / file).write_bytes(base64.b64decode(png))
            return web.json_response({"ref": "/".join(p for p in ("temp", subfolder, file) if p)})
        return web.json_response({"png": png})

    @_routes.post("/nynxz/greybox/sheet")
    @_guard
    async def gb_sheet(request: web.Request) -> web.Response:
        """The scene's contact sheet — every shot's frames and the plan — saved under temp/greybox;
        its media ref (for agents, who look at it)."""
        body = await request.json()
        pdir = project_dir(codex_root(request), body.get("project"))
        scene = scene_from(body, pdir)
        per = max(1, min(int(body.get("perShot", 4)), 8))

        def run() -> str:
            import comfy.model_management as mm
            import folder_paths

            img = gsheet.contact_sheet(scene, per, 320, mm.get_torch_device())
            folder, name, counter, subfolder, _ = folder_paths.get_save_image_path(
                f"greybox/{body.get('name') or 'scene'}-sheet", folder_paths.get_temp_directory()
            )
            file = f"{name}_{counter:05}_.png"
            img.save(Path(folder) / file)
            return "/".join(p for p in ("temp", subfolder, file) if p)

        ref = await asyncio.get_running_loop().run_in_executor(None, run)
        return web.json_response({"ref": ref})

    @_routes.post("/nynxz/greybox/render")
    @_guard
    async def gb_render(request: web.Request) -> web.Response:
        """A shot's grey video (or its depth), saved to output/greybox; its media ref. `shot: "*"`
        renders the whole scene as it cuts, every shot in order."""
        body = await request.json()
        pdir = project_dir(codex_root(request), body.get("project"))
        scene = scene_from(body, pdir)
        whole = body.get("shot") == "*"
        shot = None if whole else scene.shot(str(body.get("shot", "")))
        if whole and not scene.shots:
            raise Bad("The scene has no shots.")
        if not whole and shot is None:
            raise Bad(f"No shot {body.get('shot')!r}.")
        w = max(64, min(int(body.get("width", 832)), 2048)) // 16 * 16
        h = max(64, min(int(body.get("height", 480)), 2048)) // 16 * 16
        depth = bool(body.get("depth"))

        def run() -> str:
            import comfy.model_management as mm
            import folder_paths

            device = mm.get_torch_device()
            frames = (
                gsheet.scene_frames(scene, w, h, device, depth=depth)
                if shot is None
                else gsheet.shot_frames(scene, shot, w, h, device, depth=depth)
            )
            # To H3's frame grid, so a blocking reference covers the whole H3 scene: the last
            # shot runs on a little past its end.
            last = shot or max(scene.shots, key=lambda s: s.start)
            frames = gsheet.pad_to(
                frames,
                gsheet.h3_frames(frames.shape[0]),
                lambda k: gsheet.shot_frames(
                    scene, last, w, h, device, depth=depth, start=last.end, count=k
                ),
            )
            part = "cut" if shot is None else shot.name
            folder, name, counter, subfolder, _ = folder_paths.get_save_image_path(
                f"greybox/{body.get('name') or scene.name}-{part}{'-depth' if depth else ''}",
                folder_paths.get_output_directory(),
            )
            file = f"{name}_{counter:05}_.mp4"
            gsheet.save_video(frames, Path(folder) / file, scene.fps)
            return "/".join(p for p in ("output", subfolder, file) if p)

        ref = await asyncio.get_running_loop().run_in_executor(None, run)
        return web.json_response({"ref": ref})
