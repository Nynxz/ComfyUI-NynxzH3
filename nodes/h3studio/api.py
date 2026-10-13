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

    @_routes.post("/nynxz/h3studio/films")
    async def h3studio_films(request: web.Request) -> web.Response:
        """The films saved from a project (by its scene ids), newest first."""
        if (denied := request_allowed(request)) is not None:
            return denied
        from . import film

        body = await request.json()
        ids = [str(x) for x in body.get("scenes", []) if isinstance(x, (str, int))][:200]
        return web.json_response({"films": film.films(ids)})

    @_routes.post("/nynxz/h3studio/film/export")
    async def h3studio_export_film(request: web.Request) -> web.Response:
        """Join every scene's current take into the film and save it, now. CPU only (files in, a
        file out), so it runs beside the queue, on a thread of its own."""
        if (denied := request_allowed(request)) is not None:
            return denied
        import asyncio

        from . import film

        body = await request.json()
        workflow = body.get("workflow")
        from comfy.cli_args import args

        keep = isinstance(workflow, dict) and not args.disable_metadata
        metadata = {"workflow": workflow} if keep else None
        try:
            record = await asyncio.to_thread(film.save, normalize(body.get("project")), metadata)
        except Exception as e:  # noqa: BLE001 - reported to the editor
            return web.json_response({"error": str(e)}, status=500)
        return web.json_response(record)

    @_routes.post("/nynxz/h3studio/take/mix")
    async def h3studio_mix_takes(request: web.Request) -> web.Response:
        """Join shots from several of a scene's takes into one clip and make it the scene's clip.
        CPU only (files in, a file out), so it runs beside the queue, on a thread of its own."""
        if (denied := request_allowed(request)) is not None:
            return denied
        import asyncio

        from . import mix

        body = await request.json()
        try:
            take = await asyncio.to_thread(
                mix.make, body.get("project"), str(body.get("scene", "")), body.get("parts") or []
            )
        except mix.MixError as e:
            return web.json_response({"error": str(e)}, status=400)
        except Exception as e:  # noqa: BLE001 - reported to the editor
            return web.json_response({"error": str(e)}, status=500)
        return web.json_response(take)

    @_routes.post("/nynxz/h3studio/sheet")
    async def h3studio_sheet(request: web.Request) -> web.Response:
        """A render's contact sheet (frames evenly through it, in a grid); its media ref. CPU only,
        on a thread of its own."""
        if (denied := request_allowed(request)) is not None:
            return denied
        import asyncio

        from . import sheet

        body = await request.json()
        shots = body.get("shots")
        try:
            made = await asyncio.to_thread(
                sheet.make,
                str(body.get("ref", "")),
                int(body.get("count", 12)),
                int(body.get("columns", sheet.COLUMNS)),
                [int(s) for s in shots] if isinstance(shots, list) else None,
                str(body.get("title", "")),
            )
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        except Exception as e:  # noqa: BLE001 - reported to the editor
            return web.json_response({"error": str(e)}, status=500)
        return web.json_response(made)

    @_routes.post("/nynxz/h3studio/rewriter-prompt")
    async def h3studio_rewriter_prompt(request: web.Request) -> web.Response:
        """The chat prompt the MiniMax-H3 rewriter LoRA was trained on, for the studio's scene
        rewrite (the same text H3 Rewrite Prompt builds)."""
        if (denied := request_allowed(request)) is not None:
            return denied
        from ..rewrite._prompt import MAX_DURATION, MIN_DURATION, build_chat_prompt

        body = await request.json()
        try:
            duration = min(MAX_DURATION, max(MIN_DURATION, round(float(body.get("duration", 10)))))
            text = build_chat_prompt(
                str(body.get("prompt", "")),
                task=str(body.get("task", "t2va")),
                resolution=str(body.get("resolution", "16:9")),
                duration=duration,
            )
        except (TypeError, ValueError) as e:
            return web.json_response({"error": str(e)}, status=400)
        return web.json_response({"text": text, "duration": duration})

    @_routes.post("/nynxz/h3studio/rewriter-clean")
    async def h3studio_rewriter_clean(request: web.Request) -> web.Response:
        """A rewriter answer split into its three fields (as H3 Rewrite Clean)."""
        if (denied := request_allowed(request)) is not None:
            return denied
        from ..rewrite._rewrite import clean_response

        body = await request.json()
        prompt, fields = clean_response(str(body.get("text", "")))
        return web.json_response({"prompt": prompt, "fields": fields})

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
