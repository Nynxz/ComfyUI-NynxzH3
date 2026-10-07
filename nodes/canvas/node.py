"""H3 Canvas — the size and duration H3 samples at, on the wire so it can be switched off.

Three numbers: width, height, seconds. No modes, no widgets that only apply sometimes.

**It sits on the `h3_inputs` wire rather than putting widgets on H3 Encode**, and that is the
whole reason it is a node. The canvas travels with the assets it frames, so:

  * **Bypassing it falls back cleanly.** Ctrl-B this node and the chain carries no canvas, so
    H3 Encode uses H3's defaults. A widget on the encode cannot be switched off that way.
  * **Two of them can sit in one graph** — a 768p pass and a 2K regenerate pass — and swapping
    which one feeds the encode is a wire, not three retyped numbers.
  * `_payload.merge` keeps **the most downstream canvas**, so this can sit anywhere in the chain:
    before the asset nodes, after them, or between two of them.

**It does no resolution picking.** Aspect ratios, megapixel targets and snapping belong to
`nynxz.Util.Resolution` in ComfyUI-NynxzNodes, which does them visually — wire its width and
height in. What is left here is only what is H3-specific and cannot be got anywhere else: the
`17k+5` frame grid, and how far past H3's trained envelope the result lands.

It deliberately does **not** emit width / height / length as ints. `H3 Extras` already reads the
canvas back off the wire, and returns more — frame_count and the latent lengths too. Two nodes
returning the same numbers is two places for them to disagree.
"""

from __future__ import annotations

from comfy_api.latest import io

from .. import _core
from .._base import CATEGORY, PackNode
from ..inputs import _payload
from ..inputs.types import H3InputData


class H3Canvas(PackNode):
    CATEGORY = f"{CATEGORY}/Conditioning"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3Canvas",
            display_name="H3 Canvas",
            description="The canvas H3 samples at — size and duration — carried on the h3_inputs "
            "wire so it can be bypassed or swapped between passes. Snaps the duration UP onto "
            "H3's legal frame grid (n % 17 == 5), so 5 seconds is 124 frames, and both axes onto "
            "the 32px grid, and reports how far past H3's trained envelope you land. Pick the "
            "resolution itself with a Resolution node and wire width and height in.",
            inputs=[
                H3InputData.Input(
                    "h3_inputs",
                    optional=True,
                    tooltip="Chain from H3 Image / Video / Audio, or leave unwired. Assets pass "
                    "through untouched; only the canvas is set.",
                ),
                io.Int.Input(
                    "width",
                    default=1344,
                    min=32,
                    max=16384,
                    step=32,
                    tooltip="Canvas width, snapped to the 32px grid — the VAE's /16 then the DiT's "
                    "2x2 patch. H3's own envelope is a 768 short edge capped at 768*1344; the "
                    "report says how far past that you are.",
                ),
                io.Int.Input(
                    "height",
                    default=768,
                    min=32,
                    max=16384,
                    step=32,
                    tooltip="Canvas height, on the same 32px grid.",
                ),
                io.Float.Input(
                    "seconds",
                    default=5.0,
                    min=0.2,
                    max=150.0,
                    step=0.1,
                    tooltip="Duration at 24 fps, snapped UP to the legal frame grid — the report "
                    "names what you actually get. H3's trained range is ~5-15s; past that the "
                    "rope runs off the end of what it saw and sung or spoken content degrades "
                    "into gibberish well before a minute.",
                ),
            ],
            outputs=[
                H3InputData.Output(
                    display_name="h3_inputs",
                    tooltip="Into H3 Encode, or on through more asset nodes.",
                ),
                io.String.Output(
                    display_name="report",
                    tooltip="What you actually get: the snapped canvas and frame count, the "
                    "aspect ratio, and how far past H3's base envelope it lands. For the numbers "
                    "as values, put an H3 Extras on the wire.",
                ),
            ],
        )

    @classmethod
    def execute(cls, h3_inputs=None, width=1344, height=768, seconds=5.0):
        const = _core.constants()
        # Ask in seconds, snap in frames. `temporal_shape` rounds UP onto 17k+5, so a duration
        # between grid points gives the next one up rather than the nearest — hence the report
        # naming both. Size goes through `_payload.canvas`, the same coercion every other node in
        # the pack reads back out, so what travels is what gets sampled.
        asked_frames = max(1, round(float(seconds) * const["fps"]))
        frame_count, latent_t, audio_t = _core.temporal_shape(asked_frames)
        canvas = _payload.canvas(
            {"width": int(width), "height": int(height), "length": frame_count}
        )
        out_w, out_h = canvas["width"], canvas["height"]

        cap = int(const["max_pixels"])
        pixels = out_w * out_h
        lines = [
            f"canvas: {out_w}x{out_h}, {frame_count} frames "
            f"({frame_count / const['fps']:.2f}s at {const['fps']:g} fps)"
        ]
        if (out_w, out_h) != (int(width), int(height)):
            lines.append(f"  asked {int(width)}x{int(height)} — snapped onto the 32px grid")
        if frame_count != asked_frames:
            lines.append(f"  asked {asked_frames} frames ({seconds:g}s) — snapped up to the grid")

        lines.append(f"  {pixels / 1e6:.2f} MP — {pixels / cap:.2f}x H3's base cap")
        lines.append(f"  latent: {latent_t} video frames, {audio_t} audio frames")
        if frame_count > 362:
            lines.append(
                "  WARNING: past H3's trained range (~124-362 frames). Lyrics and speech turn to "
                "gibberish here; chain shorter segments instead."
            )

        payload = _payload.merge(h3_inputs, _payload.make(canvas_value=canvas))
        return io.NodeOutput(payload, "\n".join(lines))
