"""H3 Encode — one node for all three MiniMax H3 conditioning tasks.

Wire **H3 Inputs** in and the task follows from what is in the list:

    nothing                      t2va    prompt only
    a first and/or last frame    fl2va   keyframes anchored in the clip
    references                   ref2va  <Picture i> / <Video k> / <Audio j>

which is the whole point of the pair: `MiniMax H3 Image to Video` and `MiniMax H3 Reference to
Video` are two nodes because they build two different presentations, so switching between the
two workflows means rewiring the graph. Here it means changing a row's role.

The canvas — width, height, length, reference sizing — arrives on the same wire, because it
belongs next to the assets it frames rather than on the node that consumes them. `H3 Extras`
breaks it back out for graphs that want the numbers. This node keeps only what is genuinely its
own: the models, the prompt, and how to read the list.

`mode` overrides the guess. It exists mostly for one case: a list holding both a keyframe and
references, which the model cannot take at once (`_encode.py` documents the two places in
ComfyUI that enforce that). On `auto` the keyframes win, reference *images* still reach
Qwen3-VL as `<Picture i>` blocks — fl2va presents keyframes the same way, so that costs nothing
— and anything genuinely incompatible is set aside and named in `report`.

`audio_vae` sits beside `vae` and is optional: it is only needed when a reference carries audio,
and asking for it unconditionally would put a loader in every text-to-video graph that never
uses one.
"""

from __future__ import annotations

import logging

import node_helpers
from comfy_api.latest import io

from .. import _core
from .._base import PackNode
from ..inputs import _payload
from ..inputs.types import H3InputData
from . import _encode


class H3Encode(PackNode):
    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3Encode",
            display_name="H3 Encode",
            description="MiniMax H3 conditioning and its AV latent, from a prompt plus an "
            "optional H3 Inputs list. Covers all three of H3's conditioning tasks — t2va "
            "(prompt only), fl2va (first/last keyframes) and ref2va (references) — replacing "
            "both MiniMax H3 Image to Video and MiniMax H3 Reference to Video: the task follows "
            "from the roles in the list, so switching between keyframes and references is a row "
            "setting rather than a rewire.",
            inputs=[
                io.Clip.Input("clip", tooltip="H3's Qwen3-VL-32B text encoder."),
                io.Vae.Input("vae", tooltip="H3's video VAE."),
                io.Vae.Input(
                    "audio_vae",
                    optional=True,
                    tooltip="H3's audio VAE. Only needed when a reference carries audio — a "
                    "dropped video's soundtrack, or an audio row.",
                ),
                io.String.Input(
                    "prompt",
                    multiline=True,
                    dynamic_prompts=True,
                    tooltip="Refer to references by the tag the H3 Image / Video / Audio node "
                    "reports for them — <Picture 1>, <Video 1>, <Audio 1>. They are numbered in "
                    "wire order, counting each kind separately.",
                ),
                io.Combo.Input(
                    "mode",
                    options=list(_encode.MODES),
                    default="auto",
                    tooltip="Which of H3's three tasks to run. t2va is prompt only; fl2va anchors "
                    "a first and/or last frame in the clip; ref2va uses references with no fixed "
                    "position. auto picks fl2va if anything is wired as a first or last frame, "
                    "ref2va if anything else is wired, t2va otherwise. Force one when both kinds "
                    "are wired — the model cannot take both at once. Forcing fl2va with nothing "
                    "marked uses the first two pictures as the first and last frame.",
                ),
                io.Combo.Input(
                    "keyframe_instruction",
                    options=["auto", "off"],
                    default="auto",
                    tooltip="H3 expects a keyframe prompt to OPEN with a line saying where each "
                    "picture lands in the clip — see VIDEO_PROMPT_WRITING_GUIDE_base_en section "
                    "2.1. auto writes it for you, using the snapped duration (ask for 130 frames "
                    "and the correct mark is 5.88s, not 5.42s). Skipped if your prompt already "
                    "has one. Turn off for a multi-shot prompt, which needs its own shot index.",
                ),
                H3InputData.Input(
                    "h3_inputs",
                    optional=True,
                    tooltip="From H3 Canvas and/or a chain of H3 Image / Video / Audio nodes — "
                    "the assets and the canvas they are framed for. Unwired, this is plain "
                    "text-to-video at H3's default 1344x768, 124 frames.",
                ),
            ],
            outputs=[
                io.Conditioning.Output(display_name="positive"),
                io.Latent.Output(),
                io.String.Output(
                    display_name="report",
                    tooltip="Which task ran, the canvas it ran at, and anything set aside and why.",
                ),
            ],
        )

    @classmethod
    def execute(
        cls,
        clip,
        vae,
        prompt,
        mode="auto",
        keyframe_instruction="auto",
        audio_vae=None,
        h3_inputs=None,
    ):
        # The canvas arrives on the wire, from H3 Canvas — or is H3's default when nothing
        # upstream set one, which is what makes bypassing H3 Canvas fall back cleanly rather than
        # erroring. `canvas_of` is the single place that decision is made.
        canvas = _payload.canvas_of(h3_inputs)
        width, height, length = canvas["width"], canvas["height"], canvas["length"]
        latent, frame_count = _core.empty_latent(width, height, length)
        plan = _encode.plan(_payload.items_of(h3_inputs), mode)

        snapped = "" if frame_count == length else f" (asked {length})"
        lines = [
            _encode.summary(plan),
            f"  canvas: {width}x{height}, {frame_count} frames{snapped}",
        ]
        for label, role in plan.get("promoted", []):
            lines.append(f"  {label} used as the {role.replace('_', ' ')}")
        for label, reason in plan["dropped"]:
            lines.append(f"  set aside: {label} — {reason}")
            logging.warning("H3 Encode: %s — %s", label, reason)

        if plan["task"] == "fl2va":
            images, keyframes = _encode.build_keyframes(plan, vae, width, height, frame_count)
            text = prompt
            if keyframe_instruction == "auto":
                instruction = _encode.alignment_instruction(plan, frame_count)
                text = _encode.with_instruction(prompt, instruction)
                if text is not prompt and instruction:
                    lines.append(f"  opened with: {instruction[:72]}…")
            cond = clip.encode_from_tokens_scheduled(clip.tokenize(text, images=images))
            if keyframes:
                cond = node_helpers.conditioning_set_values(
                    cond, {"minimax_keyframes": keyframes, "minimax_frame_count": frame_count}
                )
        elif plan["task"] == "ref2va":
            ref_items, ref_blocks = _encode.build_references(
                plan, vae, audio_vae, width, height, frame_count, canvas["ref_image_size"]
            )
            cond = clip.encode_from_tokens_scheduled(
                clip.tokenize(prompt, minimax_ref_items=ref_items)
            )
            if ref_blocks:
                cond = node_helpers.conditioning_set_values(cond, {"minimax_refs": ref_blocks})
            lines.append("  tags: " + (", ".join(_tags(plan["refs"])) or "none"))
            reused = [r for r in plan["refs"] if r.get("latent") is not None]
            if reused:
                # Worth stating: the difference between this and the decode/re-encode path is
                # invisible in the output socket and is exactly what a regenerate is buying.
                lines.append(
                    f"  reused {len(reused)} supplied latent(s), no VAE re-encode: "
                    + ", ".join(f"{r['label']} {tuple(r['latent'].shape[2:])}" for r in reused)
                )
        else:
            cond = clip.encode_from_tokens_scheduled(clip.tokenize(prompt))

        report = "\n".join(lines)
        logging.info("H3 Encode: %s", lines[0])
        return io.NodeOutput(cond, latent, report)


def _tags(refs: list[dict]) -> list[str]:
    """`<Picture 1> file.png` per reference, so the report names what the prompt should say."""
    from ..inputs import _rows

    return [f"{tag} {item['label']}" for tag, item in zip(_rows.tags(refs), refs, strict=True)]
