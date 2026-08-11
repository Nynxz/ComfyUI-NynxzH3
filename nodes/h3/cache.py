"""MiniMax H3 Block Cache — skip the transformer stack on steps that barely change it.

Wire it between the model and the sampler. On a step where block 0's residual has moved less than
`threshold` since the last computed step, blocks 1..49 don't run and the previously measured tail
delta is added instead. A skipped step costs 1/50th of a normal one.

This is the right lever for H3 specifically, and the profiler is why. A 5s run at 800x544 came
back fully resident and **compute-bound at 306 TFLOP/s** with blocks holding 99.5% of the forward.
Nothing is waiting on memory, so the only thing that buys time is issuing less arithmetic — and
skipping whole steps issues none, which beats making attention cheaper on every one of them.

`threshold` is the whole tuning surface and it is not calibrated per model: it is a plain
accumulated relative-L1 budget, so the number means the same thing at any resolution or duration.
0 disables skipping entirely and is an exact no-op. Around 0.05-0.1 is usually free; past ~0.2
motion starts to smear, because the steps this skips are exactly the ones carrying small
continuous change.

Composes with the profiler in either order — both install block patches through `_patch.py`,
which chains rather than overwrites — so profiling a cached run to see what it bought works.

Every run ends with a line in the ComfyUI log saying what it skipped and what that was worth in
measured time; `verbose` adds one line per pass with the decision and the reason behind it, which
is how a threshold gets chosen against real numbers instead of guessed at.
"""

from __future__ import annotations

import logging

import comfy.patcher_extension
from comfy_api.latest import io

from .._base import CATEGORY, PackNode
from . import _h3
from ._cache import NAME, BlockCache, sample_wrapper
from ._patch import block_patch


class H3BlockCache(PackNode):
    CATEGORY = f"{CATEGORY}/Sampling"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3BlockCache",
            display_name="H3 Block Cache",
            description="Reuses the transformer stack's own output on sampling steps where it "
            "barely changes, skipping 49 of 50 blocks on those steps. The biggest available win "
            "on H3, which profiles as compute-bound. Reports what it skipped and what that saved "
            "to the log after each run. threshold 0 is an exact no-op.",
            inputs=[
                io.Model.Input("model", tooltip="A MiniMax H3 model. Passed through, patched."),
                io.Float.Input(
                    "threshold",
                    default=0.08,
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    tooltip="How much block 0's residual may drift, accumulated since the last "
                    "computed step, before the stack must run again. 0 disables the cache "
                    "entirely (exact no-op). 0.05-0.1 is usually free; past 0.2 motion smears.",
                ),
                io.Int.Input(
                    "max_consecutive",
                    default=3,
                    min=1,
                    max=20,
                    tooltip="Never skip more than this many steps in a row, whatever the "
                    "threshold says. The accumulator can drift for a long stretch of a slow "
                    "denoise; this is the floor under how often the model gets a real say.",
                ),
                io.Float.Input(
                    "start_percent",
                    default=0.15,
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    tooltip="Denoise fraction caching switches on at. Not 0 by default on "
                    "purpose: the first steps decide composition and motion, and they are the "
                    "ones you least want reused.",
                ),
                io.Float.Input(
                    "end_percent",
                    default=0.95,
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    tooltip="Denoise fraction it switches off at. Leaving the last steps "
                    "uncached keeps fine detail from being inherited from a stale delta.",
                ),
                io.Boolean.Input(
                    "verbose",
                    default=False,
                    tooltip="Log a line per stack pass saying whether it was skipped and why, "
                    "plus the drift distribution the threshold is being compared against. The "
                    "one-line summary at the end of each run is printed either way.",
                ),
            ],
            outputs=[io.Model.Output()],
        )

    @classmethod
    def execute(
        cls,
        model,
        threshold=0.08,
        max_consecutive=3,
        start_percent=0.15,
        end_percent=0.95,
        verbose=False,
    ) -> io.NodeOutput:
        if not _h3.is_h3(model):
            wired = type(_h3.diffusion_model(model)).__name__
            raise ValueError(
                "MiniMax H3 Block Cache only understands MiniMax H3 — the wired model's DiT is "
                f"{wired!r}. It caches across a single contiguous residual path over one packed "
                "sequence, which is H3's block structure and not a general one."
            )

        m = model.clone()
        if threshold <= 0.0:
            # An exact no-op deserves to be exactly nothing: patching 50 blocks to add zero would
            # still cost the closures, the sampled residual and the tail allocation every step.
            if verbose:
                logging.info("%s: threshold 0 — disabled, the model passes through as it is", NAME)
            return io.NodeOutput(m)

        sampling = m.get_model_object("model_sampling")
        cache = BlockCache(
            threshold=threshold,
            max_consecutive=max_consecutive,
            sigma_start=float(sampling.percent_to_sigma(start_percent)),
            sigma_end=float(sampling.percent_to_sigma(end_percent)),
            verbose=verbose,
            percents=(start_percent, end_percent),
        )
        # Brackets the sampling run: without it there is no moment that is "the end", and neither
        # the summary nor the release of the cached tensors has anywhere to happen.
        m.add_wrapper_with_key(
            comfy.patcher_extension.WrappersMP.OUTER_SAMPLE,
            "nynxz_h3_block_cache",
            sample_wrapper(cache),
        )

        layers = _h3.dims(_h3.diffusion_model(model))["layers"]
        for index in range(layers):
            if index == 0:
                wrap = cache.begin
            elif index == layers - 1:
                wrap = cache.end
            else:
                wrap = cache.middle
            m.set_model_patch_replace(
                block_patch(m.model_options, index, wrap), "dit", "double_block", index
            )
        return io.NodeOutput(m)
