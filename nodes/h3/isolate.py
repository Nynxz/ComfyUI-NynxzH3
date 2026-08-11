"""MiniMax H3 Reference Isolate — stop the references attending to the image being made.

References in H3 are a contiguous prefix of the packed sequence whose timestep never moves and
whose output nothing reads. They change across steps for one reason only: attention lets them
read the noisy target. Cutting that edge turns the prefix into a constant, and turns one `S x S`
attention into `P x P` plus `(S-P) x S`.

Attention saved is `P·(S-P)` out of `S²` — so it pays in proportion to how much of your sequence
is references. On a 5s clip with one keyframe the prefix is ~7% of the rows and this is a rounding
error. On a 2048² edit with a full-size reference the prefix is a third of the sequence and this
is roughly a quarter of all attention, for no memory and no staleness in the generated content.

**Why this is not the "reference KV cache" in full.** The obvious next step is to also stop
*computing* the prefix — cache its keys and values per layer and skip those rows entirely, which
would save the linear work too. The arithmetic on that is discouraging and worth writing down:
50 layers x P rows x 7168 x 2 tensors x 2 bytes is **1.43 MB per prefix row**. A 768px fused
reference (876 prefix rows) wants 1.26 GB to save ~10%; a 2048px reference (4400 rows) wants
6.3 GB. The case where caching pays most is exactly the case where it does not fit. The split
below is the half that is free.

The deviation is real: the references stop seeing the image form. `start_percent` is the dial for
it — let them watch composition get decided, then freeze. Composition is settled early, so a small
value usually costs nothing visible.
"""

from __future__ import annotations

import comfy.patcher_extension
from comfy_api.latest import io

from .._base import CATEGORY, PackNode
from . import _h3, _isolate


def _forward_wrapper(state: dict):
    """Publish the prefix split point for the attention override, per forward."""

    def wrapper(executor, x, timestep, context, transformer_options, **kwargs):
        payload = kwargs.get("minimax_payload") or {}
        layout = payload.get("layout")
        prefix = _isolate.prefix_length(layout)
        if prefix:
            transformer_options[_isolate.PREFIX_KEY] = prefix
            transformer_options[_isolate.SEQLEN_KEY] = int(layout.seq_len)
            state["prefix"] = prefix
            state["seqlen"] = int(layout.seq_len)
            state["references"] = _isolate.has_references(layout)
        return executor(x, timestep, context, transformer_options, **kwargs)

    return wrapper


class H3ReferenceIsolate(PackNode):
    CATEGORY = f"{CATEGORY}/Sampling"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3ReferenceIsolate",
            display_name="H3 Reference Isolate",
            description="Stops the text and reference prefix attending to the denoising target, "
            "turning one square attention into two rectangular ones. Saves attention in "
            "proportion to how much of the packed sequence is references — worth most on "
            "high-resolution multi-reference edits, negligible on a plain clip. Costs no memory.",
            is_experimental=True,
            inputs=[
                io.Model.Input("model", tooltip="A MiniMax H3 model. Passed through, patched."),
                io.Float.Input(
                    "start_percent",
                    default=0.0,
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    tooltip="Denoise fraction the isolation switches on at. Above 0, the "
                    "references watch the early steps — where composition is decided — before "
                    "being frozen. Raise this first if identity or layout drifts.",
                ),
                io.Float.Input(
                    "end_percent",
                    default=1.0,
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    tooltip="Denoise fraction it switches off at. 1.0 keeps it on to the end.",
                ),
            ],
            outputs=[io.Model.Output()],
        )

    @classmethod
    def execute(cls, model, start_percent=0.0, end_percent=1.0) -> io.NodeOutput:
        if not _h3.is_h3(model):
            wired = type(_h3.diffusion_model(model)).__name__
            raise ValueError(
                "MiniMax H3 Reference Isolate only understands MiniMax H3 — the wired model's "
                f"DiT is {wired!r}. It relies on H3's packed layout putting conditioning in a "
                "contiguous prefix ahead of the denoised rows, which is not a general property."
            )

        m = model.clone()
        sampling = m.get_model_object("model_sampling")
        state: dict = {}

        options = m.model_options["transformer_options"] = m.model_options.get(
            "transformer_options", {}
        ).copy()
        options["optimized_attention_override"] = _isolate.attention_override(
            options.get("optimized_attention_override"),
            float(sampling.percent_to_sigma(start_percent)),
            float(sampling.percent_to_sigma(end_percent)),
        )

        wrappers = options["wrappers"] = {
            kind: dict(keyed) for kind, keyed in options.get("wrappers", {}).items()
        }
        bucket = wrappers.setdefault(comfy.patcher_extension.WrappersMP.DIFFUSION_MODEL, {})
        key = "nynxz_h3_isolate"
        bucket[key] = [*bucket.get(key, []), _forward_wrapper(state)]
        return io.NodeOutput(m)
