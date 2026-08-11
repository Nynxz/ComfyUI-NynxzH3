"""MiniMax H3 Sliding Window — make attention linear in duration instead of quadratic.

Wire it between the model and the sampler. Each latent frame attends densely to the frames within
`window` of it in time, plus a few `follow_taps` reaching further out at an offset that rotates
every layer, plus — always, at full density — every text and reference row. Attention stops being
the reason a 20s clip costs far more than four 5s ones.

    5s   1.70x on attention      10s  3.15x      20s  6.19x

measured on the attention call itself; the run-level number is smaller in proportion to attention's
share of block time, which the Profile node reports (63% on a 5s run at 800x544).

**This is the complement of step caching, not a competitor.** A step cache skips whole steps, which
costs nothing when it fires and everything when it fires too often; the window makes every step
cheaper by a factor that *grows with duration*. Run both: on long clips the cache holds its usual
handful of steps while the window flattens the curve underneath it. H3 Block Cache lives in
ComfyUI-NynxzH3, next to the Frame Hold it interacts with.

**What it costs.** Frames further apart than the window only reach each other through the follow
taps, so this trades exact long-range attention for sampled long-range attention. Motion that
depends on a specific distant frame — a fast pan returning to where it started, a hard cut back —
is what degrades first, and it degrades as smear or drift rather than as an artifact. Raise
`window` before anything else; `follow_taps` is the cheaper fix when the failure is global
consistency rather than local motion. Identity is not usually the thing that breaks: references
live outside the window and every frame sees all of them at every layer.

`window` large enough to cover the clip is an exact no-op and falls straight through to the normal
attention path, so this is safe to leave wired in for short runs.
"""

from __future__ import annotations

import logging

import comfy.patcher_extension
from comfy_api.latest import io

from .._base import CATEGORY, PackNode
from . import _h3, _window


def _forward_wrapper(state: dict):
    """Publish this forward's video geometry, and restart the per-forward call counter."""

    def wrapper(executor, x, timestep, context, transformer_options, **kwargs):
        payload = kwargs.get("minimax_payload") or {}
        geo = _window.geometry(payload.get("layout"))
        if geo is not None:
            transformer_options[_window.GEOMETRY_KEY] = geo
        elif not state.get("warned_layout"):
            # The other silent failure, and the only one the plan can never report because no plan
            # is ever built: `extra_conds` prebuilds the PackedLayout only when the conditioning
            # carries both latent shapes (`comfy/model_base.py:2105`), and without it there is no
            # frame geometry to window by.
            state["warned_layout"] = True
            logging.warning(
                "MiniMax H3 Sliding Window: no packed layout in this forward's payload, so there "
                "is no frame geometry to window by — running dense. This is what a conditioning "
                "that did not come from H3's own encode looks like."
            )
        # Reset per forward, so the CFG conditional and unconditional passes walk the same
        # rotation and are approximated identically. See `_window`'s docstring on why that is
        # not cosmetic: CFG differences the two passes.
        state["call"] = 0
        return executor(x, timestep, context, transformer_options, **kwargs)

    return wrapper


class H3SlidingWindow(PackNode):
    CATEGORY = f"{CATEGORY}/Sampling"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3SlidingWindow",
            display_name="H3 Sliding Window",
            description="Restricts each latent frame's attention to a sliding window of nearby "
            "frames plus a rotating set of long-range taps, leaving text and reference rows fully "
            "attended. Turns attention's quadratic duration scaling into near-linear: measured "
            "1.7x at 5s, 3.2x at 10s, 6.2x at 20s. Needs a Triton-capable GPU; falls back to "
            "dense attention if flex_attention is unavailable.",
            is_experimental=True,
            inputs=[
                io.Model.Input("model", tooltip="A MiniMax H3 model. Passed through, patched."),
                io.Int.Input(
                    "window",
                    default=8,
                    min=1,
                    max=512,
                    tooltip="Latent frames each side that stay densely attended. The main dial: "
                    "cost falls roughly as the window shrinks, and local motion is what breaks "
                    "first when it is too small. A window that covers the whole clip is an exact "
                    "no-op. 8 is ~2s of context each way at H3's frame rate.",
                ),
                io.Int.Input(
                    "follow_taps",
                    default=2,
                    min=0,
                    max=16,
                    tooltip="Extra frames outside the window each frame attends to, placed across "
                    "everything the window excludes and rotated every layer — so 50 layers cover "
                    "the whole clip while any one layer pays for 2. Raise if the clip loses "
                    "global consistency (drift, colour or identity wandering over time). 0 is a "
                    "pure local window.",
                ),
                io.Float.Input(
                    "jitter",
                    default=1.0,
                    min=0.0,
                    max=1.0,
                    step=0.05,
                    tooltip="How far the follow taps rotate between layers. 1.0 sweeps the clip "
                    "with a golden-ratio offset so no two layers tap the same frames; 0.0 pins "
                    "every layer to the same fixed taps, which is the A/B for whether the "
                    "rotation is earning its keep. No effect when follow_taps is 0.",
                ),
                io.Boolean.Input(
                    "isolate_references",
                    default=True,
                    tooltip="Stop the text and reference rows attending to the video being "
                    "denoised. Nothing reads their output and their timestep never moves, so "
                    "reading the noisy target is the only reason they drift at all — cutting it "
                    "makes them a pure function of the prompt and the references. On a regenerate "
                    "pass the prefix is around a third of the sequence and this is worth more "
                    "than any window setting: 77% of blocks kept becomes 54%. Does what the "
                    "separate Reference Isolate node does, which cannot run alongside this one. "
                    "Target audio is untouched and keeps reading the video, or the soundtrack "
                    "stops matching the picture.",
                ),
                io.Float.Input(
                    "start_percent",
                    default=0.0,
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    tooltip="Denoise fraction the window switches on at. Above 0 the early steps "
                    "run dense — those are the ones that decide global composition and motion, so "
                    "raise this first if the clip loses its overall shape rather than its detail.",
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
    def execute(
        cls,
        model,
        window=8,
        follow_taps=2,
        jitter=1.0,
        isolate_references=True,
        start_percent=0.0,
        end_percent=1.0,
    ) -> io.NodeOutput:
        if not _h3.is_h3(model):
            wired = type(_h3.diffusion_model(model)).__name__
            raise ValueError(
                "MiniMax H3 Sliding Window only understands MiniMax H3 — the wired model's DiT is "
                f"{wired!r}. It windows the video rows of H3's packed sequence using the frame "
                "geometry in its PackedLayout, which is not a general property."
            )

        m = model.clone()
        sampling = m.get_model_object("model_sampling")
        layers = _h3.dims(_h3.diffusion_model(model))["layers"]
        state: dict = {}
        plans: dict = {}

        def plan_for(geo: dict, device):
            """One plan per geometry, so the masks survive across steps and both CFG passes.

            Capped, because the masks live on the compute device for as long as this patched model
            does: one plan is 50 layers x a `[nQ, nQ]` int32 index table, which is ~1 MB per layer
            at 20s. Three resolutions' worth is a comfortable ceiling; ten would be 500 MB of a
            card that has ~2.5 GB free once H3's weights are resident.
            """
            # cond_end defaulted, not required: a geometry from somewhere other than `geometry()`
            # still keys correctly, and falling back to video_start means "no conditioning to
            # isolate" — which is what build_mask does with the same default.
            key = (
                geo["seq_len"],
                geo["video_start"],
                geo.get("cond_end", geo["video_start"]),
                geo["frame_rows"],
                geo["n_frames"],
            )
            plan = plans.get(key)
            if plan is None:
                plan = _window.WindowPlan(
                    geo, window, follow_taps, jitter, layers, isolate_references
                )
                while len(plans) >= _window.MAX_PLANS:
                    plans.pop(next(iter(plans)))  # insertion-ordered: drop the least recently new
                plans[key] = plan
            return plan

        options = m.model_options["transformer_options"] = m.model_options.get(
            "transformer_options", {}
        ).copy()
        options["optimized_attention_override"] = _window.attention_override(
            options.get("optimized_attention_override"),
            plan_for,
            float(sampling.percent_to_sigma(start_percent)),
            float(sampling.percent_to_sigma(end_percent)),
            state,
        )

        wrappers = options["wrappers"] = {
            kind: dict(keyed) for kind, keyed in options.get("wrappers", {}).items()
        }
        bucket = wrappers.setdefault(comfy.patcher_extension.WrappersMP.DIFFUSION_MODEL, {})
        key = "nynxz_h3_window"
        bucket[key] = [*bucket.get(key, []), _forward_wrapper(state)]
        return io.NodeOutput(m)
