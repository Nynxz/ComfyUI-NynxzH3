"""HTTP routes for the H3 Studio editor: compile a scene for the live prompt preview, each scene's
render status (up to date, out of date, never rendered), and the guide its shot writer gives the
text model (writer_guide.md, read fresh so it can be tuned live).

The node and the preview share `compile_scene`, so what the editor shows is exactly what H3 gets.
"""

from __future__ import annotations

from pathlib import Path

from aiohttp import web

from .._zenkit.server import request_allowed
from ._media import has_audio
from ._project import compile_scene, normalize

try:
    from server import PromptServer

    _routes = PromptServer.instance.routes
except Exception:  # noqa: BLE001 - no server (import-time checks, tests)
    _routes = None

WRITER_GUIDE = Path(__file__).with_name("writer_guide.md")


if _routes is not None:

    @_routes.post("/nynxz/h3studio/compile")
    async def h3studio_compile(request: web.Request) -> web.Response:
        if (denied := request_allowed(request)) is not None:
            return denied
        body = await request.json()
        project = normalize(body.get("project"))
        try:
            scene = int(body.get("scene", project["active"]))
        except (TypeError, ValueError):
            scene = project["active"]
        return web.json_response(compile_scene(project, scene, has_audio).as_dict())

    @_routes.post("/nynxz/h3studio/status")
    async def h3studio_status(request: web.Request) -> web.Response:
        """Each scene's latest clip and whether it's up to date with the scene as it stands."""
        if (denied := request_allowed(request)) is not None:
            return denied
        from .studio import scene_status

        body = await request.json()
        return web.json_response({"scenes": scene_status(body.get("project"))})

    @_routes.post("/nynxz/h3studio/takes")
    async def h3studio_takes(request: web.Request) -> web.Response:
        """Every take still on disk of each scene asked about (by id), newest first."""
        if (denied := request_allowed(request)) is not None:
            return denied
        from . import _reuse

        body = await request.json()
        ids = [str(x) for x in body.get("scenes", []) if isinstance(x, (str, int))][:200]
        takes = _reuse.takes(ids)
        if body.get("project") is not None:
            from .studio import takes_fit

            takes = {**takes, **takes_fit(body["project"], takes)}
        return web.json_response({"takes": takes})

    @_routes.post("/nynxz/h3studio/take/use")
    async def h3studio_use_take(request: web.Request) -> web.Response:
        """Make one of a scene's takes its current clip again."""
        if (denied := request_allowed(request)) is not None:
            return denied
        from . import _reuse

        body = await request.json()
        ok = _reuse.use_take(str(body.get("scene", "")), str(body.get("ref", "")))
        return web.json_response({"ok": ok}, status=200 if ok else 404)

    @_routes.get("/nynxz/h3studio/writer-guide")
    async def h3studio_writer_guide(_request: web.Request) -> web.Response:
        return web.Response(text=WRITER_GUIDE.read_text(encoding="utf-8"))

    @_routes.get("/nynxz/h3studio/capabilities")
    async def h3studio_capabilities(_request: web.Request) -> web.Response:
        """What this ComfyUI can do for the editor: with dynamic VRAM running, LoRA step shapes
        (hooks) need a second copy of the model, so on Auto they are applied as their average."""
        import comfy.memory_management

        dynamic = bool(getattr(comfy.memory_management, "aimdo_enabled", False))
        return web.json_response({"dynamic_vram": dynamic})
