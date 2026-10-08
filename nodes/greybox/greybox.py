"""Grey Box Shot: one shot of a grey box scene, rendered — the grey video H3 can take as a
reference (saved to output/greybox, so H3 Studio can add it), its depth, a character's mask, and
the scene's contact sheet with the plan.

The scene is a JSON file (docs/GREYBOX.md): a path that's absolute, under ComfyUI's user
directory, or one of the pack's examples (`examples/midnight-spoon/scenes/mika-arrives.json`).
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import torch
from comfy_api.latest import io, ui

from .._base import NynxzNode
from .core import scene as gscene
from .core import sheet as gsheet
from .io_types import GreyBoxStudioType

HERE = Path(__file__).parent


def _resolve(path: str) -> Path:
    import folder_paths

    p = Path(path.strip().strip('"'))
    if p.is_absolute():
        return p
    for base in (
        Path(folder_paths.get_user_directory()),
        Path(folder_paths.get_user_directory()) / "default",
        HERE,
    ):
        if (base / p).exists():
            return base / p
    raise gscene.SceneError(
        f"No scene at {path!r}: give an absolute path, one under ComfyUI's user folder, or one of the "
        "pack's examples (examples/midnight-spoon/scenes/mika-arrives.json)."
    )


class NynxzGreyBoxShot(NynxzNode):
    CATEGORY = f"{NynxzNode.CATEGORY}/H3/Grey box"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="GreyBox.Shot",
            display_name="Grey Box Shot",
            description="Render one shot of a grey box scene (simple 3D blocking: a set, characters "
            "moving between marks, a camera) as grey video — a layout and motion reference for H3. "
            "Also gives its depth, a character's mask and the scene's contact sheet.",
            search_aliases=["greybox", "blocking", "previs", "layout video"],
            inputs=[
                io.String.Input(
                    "scene",
                    default="examples/midnight-spoon/scenes/mika-arrives.json",
                    tooltip="The scene file: absolute, under ComfyUI's user folder, or a pack example.",
                ),
                io.String.Input("shot", default="1A", tooltip="The shot's name in the scene."),
                io.Int.Input("width", default=832, min=64, max=2048, step=16),
                io.Int.Input("height", default=480, min=64, max=2048, step=16),
                io.String.Input(
                    "mask_actor",
                    default="",
                    optional=True,
                    tooltip='A character ("@ren") to output a mask of. Empty: an empty mask.',
                ),
                io.Boolean.Input(
                    "save",
                    default=True,
                    tooltip="Save the grey video to output/greybox (to add as an H3 Studio reference).",
                ),
            ],
            outputs=[
                io.Image.Output(display_name="frames"),
                io.Image.Output(display_name="depth"),
                io.Mask.Output(display_name="mask"),
                io.Image.Output(display_name="sheet", tooltip="Every shot's frames and the plan."),
                io.String.Output(
                    display_name="video_ref", tooltip="The saved video, as a media ref."
                ),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, scene, shot, width, height, mask_actor="", save=True):
        # The scene's files change without the node's inputs changing.
        try:
            path = _resolve(scene)
            files = [
                path,
                *path.parent.parent.glob("sets/*.json"),
                *path.parent.parent.glob("cast.json"),
            ]
            return ";".join(f"{f}:{os.stat(f).st_mtime_ns}" for f in files if f.exists())
        except gscene.SceneError:
            return float("nan")

    @classmethod
    def execute(cls, scene, shot, width, height, mask_actor="", save=True):
        path = _resolve(scene)
        return render_shot(gscene.load(path), shot, width, height, mask_actor, save, path.stem)


def render_shot(
    sc: gscene.Scene, shot: str, width: int, height: int, mask_actor: str, save: bool, stem: str
):
    """A shot's frames, depth, one character's mask and the scene's sheet; the video saved."""
    import comfy.model_management as mm
    import folder_paths

    the_shot = sc.shot(shot)
    if the_shot is None:
        raise gscene.SceneError(
            f"No shot {shot!r} in {stem}; shots: {', '.join(s.name for s in sc.shots)}."
        )
    device = mm.get_torch_device()
    frames = gsheet.shot_frames(sc, the_shot, width, height, device)
    depth = gsheet.shot_frames(sc, the_shot, width, height, device, depth=True)
    mask = (
        gsheet.actor_mask(sc, the_shot, gscene._mention(mask_actor.strip()), width, height, device)
        if mask_actor.strip()
        else torch.zeros(frames.shape[0], height, width)
    )
    sheet_img = gsheet.contact_sheet(sc, 4, 320, device)
    sheet = torch.from_numpy(np.asarray(sheet_img, dtype=np.float32) / 255.0).unsqueeze(0)
    ref = ""
    preview = None
    if save:
        folder, name, counter, subfolder, _ = folder_paths.get_save_image_path(
            f"greybox/{stem}-{the_shot.name}", folder_paths.get_output_directory()
        )
        file = f"{name}_{counter:05}_.mp4"
        gsheet.save_video(frames, Path(folder) / file, sc.fps)
        ref = "/".join(p for p in ("output", subfolder, file) if p)
        preview = ui.PreviewVideo([ui.SavedResult(file, subfolder, io.FolderType.output)])
    return io.NodeOutput(frames, depth, mask, sheet, ref, ui=preview)


class NynxzGreyBoxStudio(NynxzNode):
    CATEGORY = f"{NynxzNode.CATEGORY}/H3/Grey box"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="GreyBox.Studio",
            display_name="Grey Box Studio",
            description="Build and block grey box scenes in an editor (a set of plain shapes, "
            "characters moving between marks, a camera per shot) and render them from its Render "
            "menu as grey, depth or edge videos for H3 Studio. The scenes are files in a Codex "
            "show's greybox/ folder, so agents can work on them too. For a render inside a "
            "workflow, use Grey Box Shot.",
            search_aliases=["greybox", "blocking", "previs", "layout", "3d"],
            inputs=[GreyBoxStudioType.Input("studio")],
            outputs=[],
        )

    @classmethod
    def execute(cls, studio):
        # An editor: nothing to run. Renders come from its Render menu (or Grey Box Shot).
        return io.NodeOutput()


class NynxzGreyBoxRender(NynxzNode):
    """The Grey Box Studio's Render menu, as a job on ComfyUI's queue (see `api.gb_render`): GPU
    work has to run on the queue's thread, not beside a sampler. Not for workflows."""

    CATEGORY = f"{NynxzNode.CATEGORY}/H3/Grey box"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="GreyBox.Render",
            display_name="Grey Box Render (internal)",
            description="A render from Grey Box Studio's Render menu, queued. Not for workflows: "
            "use Grey Box Shot.",
            inputs=[io.String.Input("job", multiline=True)],
            outputs=[],
            is_output_node=True,
            is_dev_only=True,
            not_idempotent=True,
        )

    @classmethod
    def execute(cls, job):
        import json

        import folder_paths

        from .api import render_video

        body = json.loads(job)
        pdir = Path(str(body.get("pdir", ""))).resolve()
        users = Path(folder_paths.get_user_directory()).resolve()
        # Only a project inside ComfyUI's user folder (where every Codex show lives).
        if users not in pdir.parents or pdir.name != "greybox":
            raise ValueError("Grey Box Render: not a Grey Box project folder.")
        ref = render_video(body, pdir)
        return io.NodeOutput(ui={"ref": [ref]})
