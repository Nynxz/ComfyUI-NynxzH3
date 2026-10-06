"""H3 Edit — a still picture, an instruction, and named references, as an H3 request.

    source + instruction + pictures ─► H3 Edit ─┬─► prompt    ─► H3 Encode ─► sampler
                                                └─► h3_inputs ─┘                 │
                                                       H3 Decode Frames (last) ◄─┘

It writes the prompt (see `_edit.py`) and the assets — the source, the references and a 5-frame
canvas sized to the source — so H3 Encode and the sampler stay the ones you already use.
"""

from __future__ import annotations

import torch
from comfy.nested_tensor import NestedTensor
from comfy_api.latest import io

from .. import _core
from .._base import CATEGORY, PackNode
from ..inputs import _payload, _rows
from ..inputs.types import H3InputData
from . import _edit

MAX_PICTURES = 8


class H3Edit(PackNode):
    CATEGORY = f"{CATEGORY}/Prompt"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3Edit",
            display_name="H3 Edit",
            description="Edit or restyle a still picture with MiniMax H3. Write what changes, "
            "mentioning the source as @source and each reference by its @name; the node writes "
            "the H3 prompt and the assets for H3 Encode, on a 5-frame canvas. Decode the last "
            "frame with H3 Decode Frames.",
            search_aliases=["h3 image edit", "style transfer", "restyle", "h3 still"],
            is_experimental=True,
            inputs=[
                io.Image.Input("source", tooltip="The picture being edited. @source in the text."),
                io.String.Input(
                    "instruction",
                    multiline=True,
                    default="Redraw @source in the style of @style, keeping its composition.",
                    tooltip="What the edit does, in plain words. @source is the picture being "
                    "edited; @name is a reference from the list below.",
                ),
                io.String.Input(
                    "references",
                    multiline=True,
                    default="@style (style): ",
                    tooltip="One line per wired picture, in slot order: @name (look | style | "
                    "loose): what it is. look = appears as shown; style = its rendering is "
                    "transferred, none of its content; loose = a broad likeness only.",
                ),
                io.Autogrow.Input(
                    "pictures",
                    optional=True,
                    template=io.Autogrow.TemplateNames(
                        input=io.Image.Input(
                            "picture",
                            tooltip="A reference picture, described by the matching line in "
                            "references.",
                        ),
                        names=[f"picture_{i}" for i in range(1, MAX_PICTURES + 1)],
                        min=0,
                    ),
                ),
                io.String.Input(
                    "style",
                    multiline=True,
                    default="",
                    tooltip="The look of the result, said before the shot (optional), e.g. "
                    "'2D cel animation, painted backgrounds, warm amber light'.",
                ),
                io.Combo.Input(
                    "keep",
                    options=list(_edit.KEEPS),
                    default="changes",
                    tooltip="How much of the source to keep (reference mode): closely = only "
                    "what the instruction names changes; changes = composition and poses stay; "
                    "loosely = a broad likeness.",
                ),
                io.Combo.Input(
                    "mode",
                    options=list(_edit.MODES),
                    default="reference",
                    tooltip="reference: the source is a subject H3 redraws (strongest restyle; "
                    "references are full subjects). first_frame: the source is pinned as the "
                    "opening keyframe and changes across the clip (closest to the source; "
                    "references only reach the text encoder). Leave H3 Encode on mode auto.",
                ),
                io.Combo.Input(
                    "size",
                    options=list(_rows.SIZES),
                    default="auto",
                    tooltip="Detail the pictures are fed in at: max costs more and keeps more.",
                ),
                io.Vae.Input(
                    "vae",
                    optional=True,
                    tooltip="H3's video VAE. Wire it to get a latent that starts from the source, "
                    "so the sampler edits your picture instead of inventing a new one.",
                ),
            ],
            outputs=[
                io.String.Output(display_name="prompt", tooltip="Into H3 Encode's prompt."),
                H3InputData.Output(display_name="h3_inputs", tooltip="Into H3 Encode's h3_inputs."),
                io.String.Output(
                    display_name="report",
                    tooltip="Which tag each @name became, and anything worth fixing.",
                ),
                io.Latent.Output(
                    display_name="latent",
                    tooltip="The source held for 5 frames (with the vae wired; empty otherwise). "
                    "Sample it in place of H3 Encode's LATENT with denoise below 1 — lower keeps "
                    "more of the source, around 0.6-0.85 for a restyle.",
                ),
            ],
        )

    @classmethod
    def execute(
        cls,
        source,
        instruction="",
        references="",
        pictures=None,
        style="",
        keep="changes",
        mode="reference",
        size="auto",
        vae=None,
    ) -> io.NodeOutput:
        size = size if size in _rows.SIZES else "auto"
        images = [p for p in (pictures or {}).values() if p is not None]
        described, warnings = _edit.parse_references(references)
        refs, more = _edit.name_pictures(described, len(images))
        warnings += more
        prompt, more = _edit.compile_prompt(instruction, refs, mode=mode, keep=keep, style=style)
        warnings += more

        role = "first_frame" if mode == "first_frame" else "reference"
        items = [_item(source, role, "auto" if role == "first_frame" else size, "@source")]
        items += [
            _item(img, "reference", size, f"@{r['name']}")
            for img, r in zip(images, refs, strict=True)
        ]
        height, width = int(source.shape[1]), int(source.shape[2])
        w, h = _core.adapt_canvas(width, height)
        payload = _payload.make(items, {"width": w, "height": h, "length": _edit.FRAMES})
        latent = _source_latent(source, vae, w, h)
        if vae is None:
            warnings.append(
                "No vae wired: the latent is empty, so the sampler starts from noise and only "
                "the references say what the source looked like."
            )
        return io.NodeOutput(prompt, payload, _report(items, refs, mode, w, h, warnings), latent)


def _source_latent(source, vae, width: int, height: int) -> dict:
    """H3's AV latent for the canvas, with the source in every video frame when a VAE is given.

    The audio half stays silent. The video half is the source resized to the canvas and held for
    the clip, encoded the way core encodes guide frames — so a partial denoise starts from the
    picture rather than from noise.
    """
    empty, _ = _core.empty_latent(width, height, _edit.FRAMES)
    if vae is None:
        return empty
    video, audio = empty["samples"].tensors
    frames = _core.resize(source[:1], width, height, "center").repeat(_edit.FRAMES, 1, 1, 1)
    encoded = vae.encode(frames).to(video.dtype)
    t = video.shape[2]
    if encoded.shape[2] < t:  # hold the last latent frame if the VAE returned fewer
        encoded = torch.cat(
            [encoded, encoded[:, :, -1:].repeat(1, 1, t - encoded.shape[2], 1, 1)], 2
        )
    encoded = encoded[:, :, :t].to(video.device)
    return {"samples": NestedTensor((encoded, audio))}


def _item(image, role: str, size: str, label: str) -> dict:
    return {
        "kind": "image",
        "role": role,
        "label": label,
        "image": image[:1],
        "audio": None,
        "fps": None,
        "size": size,
    }


def _report(items, refs, mode, w, h, warnings) -> str:
    tag = "<Subject {}>" if mode == "reference" else "<Picture {}>"
    lines = [f"H3 Edit · {mode} · {w}x{h}, {_edit.FRAMES} frames (decode the last)"]
    lines.append(f"  @source  {tag.format(1)}")
    for i, r in enumerate(refs, start=2):
        lines.append(f"  @{r['name']}  {tag.format(i)}  ({r['role']})")
    lines += [f"  ! {msg}" for msg in warnings]
    return "\n".join(lines)
