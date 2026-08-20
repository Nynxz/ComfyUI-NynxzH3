"""H3 Scheduled Sampler — one owner for how much work each step gets.

Wire the schedule in, wire `SAMPLER` and `SIGMAS` out to `SamplerCustomAdvanced`. The schedule is
an input rather than something the sampler meets for the first time at run time so that the report
this node emits is the plan that will actually run, and so the graph has one place where the two
are tied together.

It composes with **H3 Detail Schedule** (which decides where the sigmas are) and with **H3 Block
Cache** (which decides how much of the model runs). The cache does not have to be present; when it
is, this node's `cache_floor` supersedes its `start_percent`/`end_percent` window, which is worth
doing because those are denoise percentages evaluated on the *unsplit* shift curve and stop meaning
what they say the moment a split schedule is wired in. At `detail_steps` 8 the default window
already excludes the last 5 of 23 steps; at 16 it excludes the last 10 of 31 — always the
refinement phase, always the part with the most step-to-step similarity to exploit.

**The knob that is not like the others.** `extra_evaluations`, `bias` and `cache_floor` all buy
fidelity to the trajectory the model was already going to take. `detail_eta` does not: it is the
only setting here that changes *which* trajectory. Spending steps at eta 0 makes a result more
converged, which reads as cleaner and smoother and sometimes as flatter — if what is wanted is more
texture rather than more polish, that is what the eta band is for. See `_plan.py`.
"""

from __future__ import annotations

from comfy.samplers import KSAMPLER
from comfy_api.latest import io

from .._base import CATEGORY, PackNode
from . import _plan, _scheduled

#: Not exposed. The opening step decides composition and the closing ones decide detail; neither is
#: worth reusing however small its integration error is, and there is no setting of them that is
#: interesting enough to earn a widget.
PROTECT_HEAD = 1
PROTECT_TAIL = 2

#: How hard `bias` tilts the ranking — chosen by measuring, because the obvious value does nothing.
#: The error shares on an H3 schedule span two orders of magnitude, so a tilt has to be steep or it
#: never changes the ordering at all: at 2.0 the centre of spend moves from step 18.5 to 19.3 across
#: the full range of the knob, which a user would rightly call broken. At 4.0 (e^8 end to end) it
#: moves 15.0 to 20.3, and on an evened-out schedule 12.7 to 19.3. Steep enough to re-rank, not so
#: steep that it ignores the measurement it is tilting.
BIAS_STRENGTH = 4.0


class H3ScheduledSampler(PackNode):
    CATEGORY = f"{CATEGORY}/Sampling"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3ScheduledSampler",
            display_name="H3 Scheduled Sampler",
            description="res_multistep with a per-step budget: extra evaluations go where the "
            "integration error actually is, and Block Cache is told where it may skip instead of "
            "guessing from a denoise percentage. Four of a split schedule's 22 steps carry 97% of "
            "its local error; this is the node that acts on that. Reports the plan before it runs.",
            # Experimental until it has run on a real checkpoint. The arithmetic is tested hard —
            # an empty plan reproduces core's res_multistep bit for bit — but the premise that
            # local truncation error is what limits H3 output quality is a hypothesis, and the
            # predicted-vs-measured lines in the run log are how it gets checked, not assumed.
            is_experimental=True,
            # Dev-only until that check has actually happened: the server marks the node
            # `dev_only` and the frontend keeps it out of the menu and search unless dev mode is
            # on. It stays importable and stays working in graphs that already reference it —
            # this hides it from users, it does not withdraw it. Drop this line to publish.
            is_dev_only=True,
            inputs=[
                io.Sigmas.Input(
                    "sigmas",
                    tooltip="The schedule to plan over — H3 Detail Schedule, or any scheduler. "
                    "Passed through unchanged on the SIGMAS output; wire that one onward so the "
                    "plan in the report is the plan that runs.",
                ),
                io.Combo.Input(
                    "solver",
                    options=list(_plan.SOLVERS),
                    default="res_multistep",
                    tooltip="The integrator. res_multistep gets second order for one evaluation by "
                    "reusing the previous step's prediction, and is the better default. Choose "
                    "euler when Block Cache is running hard: a cached step's approximate denoised "
                    "becomes the next step's history term and gets carried forward with weight, "
                    "where Euler keeps that error local. This also re-plans the budget — first-"
                    "order error is less concentrated, so the extra evaluations spread wider.",
                ),
                io.Int.Input(
                    "extra_evaluations",
                    default=4,
                    min=0,
                    max=64,
                    tooltip="Model evaluations on top of one per step — this is time, in the only "
                    "currency that is honest about it. They are handed out by marginal error "
                    "reduction, so the first few land on the handful of steps that hold almost "
                    "all of the error. 0 makes this a plain res_multistep.",
                ),
                io.Float.Input(
                    "bias",
                    default=0.0,
                    min=-1.0,
                    max=1.0,
                    step=0.05,
                    tooltip="Which end gets the extra evaluations. 0 is untilted and spends purely "
                    "where the measured error is. Negative favours structure and motion; positive "
                    "favours refinement. Note this buys ACCURACY at either end — for more texture "
                    "rather than more polish, use detail_eta.",
                ),
                io.Float.Input(
                    "cache_floor",
                    default=0.02,
                    min=0.0,
                    max=0.5,
                    step=0.005,
                    tooltip="The share of total local error H3 Block Cache is allowed to be "
                    "responsible for. Steps are made eligible smallest-error-first until this is "
                    "used up. Permission only — the cache's own drift threshold still decides "
                    "whether it skips, so this can never make it more aggressive than it was. "
                    "0 leaves the cache's start_percent/end_percent window alone.",
                ),
                io.Int.Input(
                    "max_substeps",
                    default=4,
                    min=1,
                    max=16,
                    tooltip="Ceiling on how far one step may be subdivided. Stops the whole budget "
                    "landing on a single enormous step when there is one.",
                ),
                io.Float.Input(
                    "detail_eta",
                    default=0.0,
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    tooltip="Ancestral noise, applied ONLY below eta_below_sigma. The one setting "
                    "here that adds detail rather than resolving it — everything else converges "
                    "harder onto the same trajectory. Banded because eta across H3's long "
                    "structure phase destabilises motion.",
                ),
                io.Float.Input(
                    "eta_below_sigma",
                    default=0.5,
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    tooltip="Where the eta band starts. 0.5 is H3 Detail Schedule's default split, "
                    "so out of the box the noise lands exactly on the refinement phase.",
                ),
                io.Float.Input(
                    "cfg_below_sigma",
                    default=0.0,
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    tooltip="Force CFG to 1.0 below this sigma, which makes ComfyUI drop the "
                    "unconditional pass entirely and halve those steps. The biggest single saving "
                    "available, and the one most likely to cost prompt adherence — 0 is off.",
                ),
                io.Boolean.Input(
                    "verbose",
                    default=False,
                    tooltip="Log the full per-step table before the run, and predicted-vs-measured "
                    "local error after it. The summary lines are logged either way.",
                ),
            ],
            outputs=[
                io.Sampler.Output(),
                io.Sigmas.Output(
                    tooltip="The schedule, unchanged. Wire this to SamplerCustomAdvanced so the "
                    "sampler and the report cannot disagree about what is being run."
                ),
                io.String.Output(
                    display_name="report",
                    tooltip="The plan, step by step: step size, the multistep conditioning ratio, "
                    "the share of total error each step holds, and where the budget went.",
                ),
            ],
        )

    @classmethod
    def execute(
        cls,
        sigmas,
        solver="res_multistep",
        extra_evaluations=4,
        bias=0.0,
        cache_floor=0.02,
        max_substeps=4,
        detail_eta=0.0,
        eta_below_sigma=0.5,
        cfg_below_sigma=0.0,
        verbose=False,
    ) -> io.NodeOutput:
        settings = {
            "solver": str(solver),
            "extra_nfe": int(extra_evaluations),
            "bias": float(bias),
            "bias_strength": BIAS_STRENGTH,
            "cache_floor": float(cache_floor),
            "protect_head": PROTECT_HEAD,
            "protect_tail": PROTECT_TAIL,
            "max_substeps": int(max_substeps),
            "detail_eta": float(detail_eta),
            "eta_below_sigma": float(eta_below_sigma),
            "cfg_below_sigma": float(cfg_below_sigma),
        }
        # Built here as well as at run time. Here it is the report, which has to be exact or it is
        # worse than nothing; there it is the plan, rebuilt against whatever sigmas actually
        # arrive so that a rewired graph still samples correctly rather than silently on stale
        # numbers. Same function, same settings, so the two agree whenever the wiring does.
        plan = _plan.build([float(v) for v in sigmas], settings=settings, **settings)

        sampler = KSAMPLER(
            _scheduled.sampler_function,
            extra_options={"plan_settings": settings, "verbose": bool(verbose)},
        )
        return io.NodeOutput(sampler, sigmas, plan.describe())
