"""MiniMax H3 Depth Skip — drop the blocks the contribution report says are idle, and look.

Wire it between the model and the sampler, name the blocks, render, compare. Nothing here decides
whether a block is skippable; `H3BlockContribution` supplies the evidence and this makes
acting on it a single A/B. Default is empty, which is an exact no-op.

See `_depthskip.py` for what the measurement and the adaLN weights each say about blocks 3-17, and
for why "1.3% of residual movement" is not the same claim as "1.3% output error".
"""

from __future__ import annotations

import logging

import comfy.patcher_extension
from comfy_api.latest import io

from .._base import CATEGORY, PackNode
from . import _depthskip, _h3
from ._patch import block_patch

#: The band both the measured deltas and the static adaLN proxy agree is quiet. Offered as the
#: default *text* rather than the default *value* — it is a starting point for an A/B, and a node
#: that silently removed fifteen blocks the moment it was added would be a trap.
SUGGESTED = "3-17"


class H3DepthSkip(PackNode):
    CATEGORY = f"{CATEGORY}/Sampling"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3DepthSkip",
            display_name="H3 Depth Skip",
            description="Skips named transformer blocks, or just their attention half. Use "
            "MiniMax H3 Block Contribution first to find out which blocks are idle on your "
            "model — on the released checkpoints that is roughly 3-17, worth about 1.4x. Empty "
            "is an exact no-op.",
            inputs=[
                io.Model.Input("model", tooltip="A MiniMax H3 model."),
                io.String.Input(
                    "blocks",
                    default="",
                    tooltip=f"Block indices to skip: '{SUGGESTED}', '3-17, 22', '10'. Ranges are "
                    "inclusive. Empty changes nothing. Read them off MiniMax H3 Block "
                    "Contribution rather than guessing — the quiet band is a property of the "
                    "checkpoint, and it is identical across the fl2va and ref2va releases.",
                ),
                io.Float.Input(
                    "start_percent",
                    default=0.0,
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    tooltip="Where in the schedule the skip switches ON, as a fraction of "
                    "sampling. 0 is the first step.",
                ),
                io.Float.Input(
                    "end_percent",
                    default=1.0,
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    tooltip="Where it switches OFF. 1 runs to the last step; the default pair "
                    "(0, 1) is always-on, which is the behaviour this node had before. Ending "
                    "early is the useful setting: skip the quiet band while structure is being "
                    "decided, then run the full stack for refinement, where the blocks you "
                    "dropped may matter more than their average contribution suggests.",
                ),
                io.Combo.Input(
                    "mode",
                    options=["whole_block", "attention_only"],
                    default="attention_only",
                    tooltip="attention_only keeps the MLP, which is the conservative choice and "
                    "costs about a fifth of the saving — attention is ~83% of block time at these "
                    "sequence lengths. It is also the better-evidenced one: the MLP's gate varies "
                    "8x across depth against attention's 68x, so the MLP is much less obviously "
                    "idle in any band. whole_block drops everything and is the thing to reach for "
                    "once an A/B says the band really is inert.",
                ),
            ],
            outputs=[
                io.Model.Output(),
                io.String.Output(
                    display_name="report",
                    tooltip="Which blocks were skipped, what fraction of the forward that removes, "
                    "and what the number does and does not mean.",
                ),
            ],
        )

    @classmethod
    def execute(
        cls, model, blocks="", mode="attention_only", start_percent=0.0, end_percent=1.0
    ) -> io.NodeOutput:
        # `mode` stays THIRD. ComfyUI binds inputs by name so schema order is free, but callers
        # that pass positionally — every test in this pack — would silently bind "attention_only"
        # to start_percent if the new parameters were inserted ahead of it.
        if not _h3.is_h3(model):
            wired = type(_h3.diffusion_model(model)).__name__
            raise ValueError(
                "MiniMax H3 Depth Skip only understands MiniMax H3 — the wired model's DiT is "
                f"{wired!r}. It indexes H3's block stack and its attention submodule by name."
            )

        m = model.clone()
        dit = _h3.diffusion_model(m)
        dims = _h3.dims(dit)
        layers = dims["layers"]
        chosen = _depthskip.parse_blocks(blocks, layers)

        if not chosen:
            return io.NodeOutput(m, f"no blocks named — exact no-op ({layers} blocks intact)")

        # A full-range window is passed as None: the common case then costs no per-call
        # comparison and — the part that matters — never touches `model_sampling`, so this node
        # keeps working on a model that has none.
        window = None
        if not (start_percent <= 0.0 and end_percent >= 1.0):
            sampling = m.get_model_object("model_sampling")
            window = (
                float(sampling.percent_to_sigma(start_percent)),
                float(sampling.percent_to_sigma(end_percent)),
            )

        if mode == "attention_only":
            # Module-level, so the Block Cache still decides whether a block runs at all and the
            # Row Chunk still governs how its MLP is materialized. Three hooks, no ordering.
            _depthskip.install_attention_skip(m, dit, chosen, dims["hidden"], window)
            # The stand-in needs to know where the video rows start, and `attn.forward` cannot
            # see the packed layout. Publish it from a forward wrapper, as the window does.
            state: dict = {}
            wrappers = (
                m.model_options.setdefault("transformer_options", {})
                .setdefault("wrappers", {})
                .setdefault(comfy.patcher_extension.WrappersMP.DIFFUSION_MODEL, {})
                .setdefault(None, [])
            )
            wrappers.append(_depthskip.geometry_wrapper(state))
        else:
            for index in chosen:
                m.set_model_patch_replace(
                    block_patch(m.model_options, index, _depthskip.skip_block),
                    "dit",
                    "double_block",
                    index,
                )

        # attention's share of block time is sequence-dependent; report the band the regenerate
        # passes actually run at rather than a single number pretending to be universal.
        lines = [
            f"skipping {len(chosen)} of {layers} blocks ({mode}): "
            + (
                f"{chosen[0]}-{chosen[-1]}"
                if chosen == list(range(chosen[0], chosen[-1] + 1))
                else ", ".join(map(str, chosen))
            ),
        ]
        for label, share in (("~50k rows", 0.83), ("~130k rows", 0.92)):
            saved = _depthskip.savings(chosen, layers, share, mode)
            lines.append(
                f"  at {label:<11} removes {saved * 100:>4.1f}% of the forward"
                f"   {1 / (1 - saved):.2f}x"
            )
        lines += [
            "",
            "  Block Contribution measures ||after-before||/||before|| PER BLOCK, each conditional",
            "  on the whole stack running. Removing several compounds: the first one's absence",
            "  changes what the next one reads. Render and compare — the number above is a cost,",
            "  not a quality prediction.",
        ]
        if mode == "whole_block":
            lines.append(
                "  whole_block leaves the chain: Block Cache and the profiler never see "
                "these blocks, which is correct but means their stats exclude them."
            )
        logging.info("MiniMax H3 Depth Skip: %s", lines[0])
        return io.NodeOutput(m, "\n".join(lines))
