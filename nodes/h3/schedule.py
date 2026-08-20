"""H3 Detail Schedule — give the refinement phase a step budget of its own.

Wire the SIGMAS output into `SamplerCustomAdvanced` in place of a scheduler node.

At H3's default `shift_video` of 12, a 20-step schedule spends one step below sigma 0.5 and lands
with a 0.387 -> 0 jump: all fine detail is decided in a single hop with nothing after it. This
splits the budget in two — steps for structure, steps for refinement — **without changing the
shift curve**, so the trajectory stays the one the model was trained under. See `_schedule.py`.
"""

from __future__ import annotations

from comfy_api.latest import io

from .._base import CATEGORY, PackNode
from . import _schedule


class H3DetailSchedule(PackNode):
    CATEGORY = f"{CATEGORY}/Sampling"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3DetailSchedule",
            display_name="H3 Detail Schedule",
            description="Sigmas for MiniMax H3, with the refinement phase budgeted separately "
            "from the structure phase. H3's default shift of 12 leaves only one step below sigma "
            "0.5, so fine detail is decided in a single jump; this gives that region its own "
            "steps while keeping the shift curve unchanged. Wire into SamplerCustomAdvanced.",
            inputs=[
                io.Int.Input(
                    "structure_steps",
                    default=15,
                    min=1,
                    max=1000,
                    tooltip="Steps above the split — where global shape and motion are decided. "
                    "H3 wants a long structure phase; this is what the default shift buys.",
                ),
                io.Int.Input(
                    "detail_steps",
                    default=8,
                    min=0,
                    max=1000,
                    tooltip="Steps below the split — refinement. Plain shift-12 gives you ONE of "
                    "these at 20 steps, which is the whole reason this node exists.",
                ),
                io.Float.Input(
                    "split",
                    default=0.5,
                    min=0.01,
                    max=0.99,
                    step=0.01,
                    tooltip="The sigma where structure ends and refinement begins. Lower spends "
                    "more of the budget on structure; 0.5 is where H3's own curve has spent 92% "
                    "of its range.",
                ),
                io.Float.Input(
                    "shift",
                    default=12.0,
                    min=0.01,
                    max=100.0,
                    step=0.01,
                    tooltip="The flow shift, matching MiniMax H3 Sigma Shift. The CURVE is "
                    "untouched by this node — every sigma it emits lies exactly on this curve, "
                    "only sampled more densely at the bottom. Change it here and on the model.",
                ),
                io.Float.Input(
                    "detail_spacing",
                    default=0.0,
                    min=0.0,
                    max=1.0,
                    step=0.05,
                    tooltip="Evens out the refinement steps. At 0 the detail phase follows the "
                    "curve, which makes its first step 3.7x shorter than the structure step before "
                    "it — and res_multistep's second-order term, built from exactly that ratio, "
                    "stops contributing for one step at the handoff. At 1 every refinement step is "
                    "the same size in the sampler's own coordinate. The split and the final sigma "
                    "do not move at any setting. Free; costs no steps.",
                ),
            ],
            outputs=[
                io.Sigmas.Output(),
                io.String.Output(
                    display_name="report",
                    tooltip="Where the steps landed, and the size of the final hop — the number "
                    "that says whether detail gets resolved or invented.",
                ),
            ],
        )

    @classmethod
    def execute(
        cls, structure_steps=15, detail_steps=8, split=0.5, shift=12.0, detail_spacing=0.0
    ) -> io.NodeOutput:
        sigmas = _schedule.split_sigmas(structure_steps, detail_steps, split, shift, detail_spacing)
        plain = _schedule.uniform_sigmas(max(1, structure_steps + detail_steps), shift)
        report = (
            f"split schedule (shift {shift:g}, split {split:g})\n"
            f"  {_schedule.describe(sigmas, split)}\n"
            f"plain shift {shift:g} at the same step count, for comparison\n"
            f"  {_schedule.describe(plain, split)}"
        )
        return io.NodeOutput(sigmas, report)
