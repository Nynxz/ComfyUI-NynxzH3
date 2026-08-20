"""Deciding, before the run starts, what each sampling step is worth.

Three nodes in this pack each answer a piece of "how much work does this step get" and none of them
can see the others. Detail Schedule places the sigmas. `res_multistep` picks the integration order.
Block Cache decides how much of the model runs. They speak in four different coordinate systems —
sigma, log-sigma, denoise-percent and log-SNR — and the disagreements are not cosmetic. This module
is the one place that converts between them and hands out a single per-step budget.

**The coordinate that matters, and the surprise in it.** A flow model's noise level is naturally
measured in log-SNR, `lambda = log((1-sigma)/sigma)`. Substituting H3's curve into it collapses to

    lambda(t) = logit(1 - t) - log(shift)

so `shift` is a **pure translation** — for a uniform-`t` schedule it slides which SNRs get visited
and redistributes nothing. Every uniform-`t` flow schedule has the same step spacing in log-SNR
whatever its shift, and that spacing is a symmetric U: large steps at both ends, small in the
middle, about 4.3x between the extremes at 23 steps. Which means the familiar reading of shift 12 —
"it crams everything into the noisy end" — is a fact about sigma, not about the model's own
difficulty coordinate, and the plain schedule is far better conditioned than it looks.

What Detail Schedule really buys, then, is not "steps below sigma 0.5". It is **where the run reads
out**: the terminal hop to sigma 0 is infinite in log-SNR and is not an integration step at all, it
is `denoised` being returned. Plain shift-12 at 23 steps reads out at lambda 0.61; a 15/8 split
reads out at lambda 2.15, a nat and a half deeper into high SNR, and that is the refinement.

**Where the error actually is.** `res_multistep` integrates in `t = -log(sigma)`, so its local
truncation error goes as `h^(p+1)` for step size `h` in that coordinate. On a 15/8 split those step
sizes run 0.005 to 0.602 — a 110x spread — and the consequence is stark: **four of twenty-two steps
carry 97% of the total local error, and the smallest twelve carry 0.07%.** Effort spread evenly
over such a schedule is almost all spent where it cannot matter.

**One place the split costs something.** `res_multistep`'s second-order term is built from the
ratio of consecutive step sizes, `c2 = -h_prev/h`. Butt-joining a structure phase onto a detail
phase makes that ratio jump 3.7x at the join, and the second-order contribution to the update
collapses from ~34% to 10.8% for exactly one step — the handoff, the step the schedule exists to
set up. It recovers immediately after. `effective_order` below is what notices this, and because a
degraded step is weighted as first-order it rises up the ranking and the allocator tends to fix the
join on its own. `_schedule.py`'s `detail_spacing` is the free fix for the same thing.

**What this module does NOT decide.** Nothing here changes which trajectory the model is on. Step
density, integration order and how much of the stack runs all converge on the *same* answer — the
exact solution of the model's own ODE — and buying more of them buys fidelity to that answer, not
new detail. The only knob that changes *which* answer you get is stochasticity, which is why `eta`
is banded separately and is not part of the error budget at all.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

#: The key a running plan's current `Step` is published under in `transformer_options`. Lives here
#: rather than next to the sampler so `_cache.py` can read it without importing the sampler, which
#: would drag k-diffusion and tqdm into a node that needs neither.
#:
#: Published as an object, not a dict: `merge_nested_dicts` (`patcher_extension.py:151`) recurses
#: into dict values and merges them, so a dict would accumulate the previous step's keys.
KEY = "nynxz_h3_step"

#: The order `res_multistep` achieves on a well-conditioned step. First order is what it falls back
#: to on the opening step (no history yet) and across a step-size discontinuity.
MULTISTEP_ORDER = 2

#: The integrators this can run, and the order each achieves. **The solver changes the plan, not
#: only the update** — local error goes as `h^(order+1)`, so dropping to Euler flattens the ranking
#: the whole budget is allocated from: on a 15/8 split the top four steps hold 96.9% of second-order
#: error but 88.2% of first-order error, and the budget spreads accordingly. Choosing the solver in
#: the sampler and the order in the allocator separately would let them disagree, so there is one
#: setting and this table is the link.
SOLVERS = ("res_multistep", "euler")
SOLVER_ORDER = {"res_multistep": MULTISTEP_ORDER, "euler": 1}

#: How lopsided `h_prev/h` may get before the second-order term stops contributing. Measured, not
#: guessed: across a healthy shift-12 schedule `|c2|` sits in [0.45, 0.92] and the second-order
#: share of the update holds at 26-35%; at a 15/8 join `|c2|` hits 3.70 and the share falls to
#: 10.8%. Anything past 2.0 is on the wrong side of that cliff.
RATIO_LIMIT = 2.0


def log_snr(sigma: float) -> float:
    """Flow log-SNR. Infinite at both ends of the schedule, which is the point of measuring it.

    **Feed this doubles.** `1 - sigma` cancels catastrophically as sigma approaches 1, and a sigma
    that has been through a float32 tensor has only three or four significant digits left by the
    time it gets here — enough to break the symmetry of a schedule that is exactly symmetric. It is
    used for describing schedules rather than for planning them; the allocator works in `-log
    sigma`, which is well conditioned across the whole range.
    """
    if sigma <= 0.0:
        return math.inf
    if sigma >= 1.0:
        return -math.inf
    return math.log((1.0 - sigma) / sigma)


@dataclass
class Step:
    """One step of the schedule, and everything decided about it before the run."""

    index: int
    sigma_from: float
    sigma_to: float
    #: Step size in the integrator's own coordinate, `-log(sigma)`. Infinite on the terminal hop.
    h: float
    #: `-h_prev/h`, the ratio `res_multistep` builds its second-order term from. None on step 0.
    c2: float | None
    #: What the step-size ratio lets this step actually achieve, 1 or 2. 0 marks the readout.
    order: int
    #: Local truncation error proxy, `h^(order+1)`. Zero for the readout.
    weight: float
    #: `weight` as a fraction of the run's total.
    share: float = 0.0
    #: How many evaluations this step is subdivided into. 1 is one evaluation, the default.
    substeps: int = 1
    #: Whether Block Cache is permitted to skip here. Permission, not instruction — the drift
    #: threshold still decides, so the plan can never make the cache more aggressive than it was.
    cache_ok: bool = False
    #: CFG scale to force for this step, or None to leave the guider's own value alone. Exactly
    #: 1.0 makes core drop the unconditional pass entirely (`samplers.py:610`), halving the step.
    cfg: float | None = None
    #: Ancestral noise for this step. Nonzero is the only setting here that changes *which*
    #: trajectory the sample lands on rather than how accurately it is followed.
    eta: float = 0.0

    @property
    def readout(self) -> bool:
        """The final hop to sigma 0 — a return of `denoised`, not an integration step."""
        return self.sigma_to <= 0.0

    def substep_sigmas(self) -> list[float]:
        """This step's sigmas, subdivided, excluding its endpoint.

        Geometric in sigma, which is uniform in the coordinate the integrator actually works in, so
        the subdivision it produces is the one that flattens this step's own error rather than a
        subdivision that merely looks even on a linear axis.
        """
        if self.substeps <= 1 or self.readout:
            return [self.sigma_from]
        ratio = self.sigma_to / self.sigma_from
        return [self.sigma_from * ratio ** (j / self.substeps) for j in range(self.substeps)]


@dataclass
class Plan:
    """Every step's budget, plus the schedule it was computed from."""

    steps: list[Step]
    sigmas: list[float]
    #: Which integrator this was planned for. `_scheduled.py` reads it rather than taking its own
    #: setting, so the update and the error model can never be for different solvers.
    solver: str = "res_multistep"
    #: Settings echoed into the report so a saved log says what produced it.
    settings: dict = field(default_factory=dict)

    @property
    def nominal_order(self) -> int:
        """The order the chosen solver reaches when nothing is degrading it."""
        return SOLVER_ORDER.get(self.solver, MULTISTEP_ORDER)

    @property
    def base_nfe(self) -> int:
        """Evaluations the schedule would cost with no plan at all — one per step."""
        return len(self.steps)

    @property
    def planned_nfe(self) -> int:
        """Evaluations after subdivision, before the cache or CFG take anything back."""
        return sum(s.substeps for s in self.steps)

    def expanded(self) -> list[float]:
        """The full sigma list to integrate, with every subdivision spliced in.

        Substepping and "put more sigmas there" are the same operation, so the sampler does not
        need a special case for it: it runs an ordinary multistep walk down this list, and the
        history flows across substep boundaries exactly as it does across step boundaries.
        """
        out: list[float] = []
        for step in self.steps:
            out.extend(step.substep_sigmas())
        out.append(self.sigmas[-1])
        return out

    def owners(self) -> list[int]:
        """For each expanded step, which original step index it belongs to.

        The progress bar and preview callback are addressed in the caller's step numbers, and
        subdividing must not make a 23-step run report 31 steps.
        """
        out: list[int] = []
        for step in self.steps:
            out.extend([step.index] * len(step.substep_sigmas()))
        return out

    def describe(self) -> str:
        return describe(self)


def _weights(sigmas: list[float], nominal: int) -> list[Step]:
    """Per-step geometry and the raw error proxy, before any budget is handed out."""
    steps: list[Step] = []
    previous_h: float | None = None
    for i in range(len(sigmas) - 1):
        a, b = float(sigmas[i]), float(sigmas[i + 1])
        if b <= 0.0:
            # The readout. Infinite in every log coordinate, and there is no integration error to
            # estimate because no integration happens: Euler to sigma 0 returns `denoised` exactly.
            steps.append(Step(i, a, b, math.inf, None, 0, 0.0))
            previous_h = None
            continue
        h = math.log(a / b)
        c2 = None if previous_h is None else -previous_h / h
        if previous_h is None:
            order = 1  # no history on the opening step; a multistep method runs Euler here
        elif nominal > 1 and c2 is not None and abs(c2) > RATIO_LIMIT:
            order = 1  # step-size discontinuity: the second-order term stops carrying weight
        else:
            # Euler lands here unconditionally: it holds no history, so there is nothing for a
            # step-size discontinuity to degrade and the join costs it nothing.
            order = nominal
        steps.append(Step(i, a, b, h, c2, order, h ** (order + 1)))
        previous_h = h
    return steps


def _tilt(steps: list[Step], bias: float, strength: float) -> list[float]:
    """Bias the error ranking toward one end of the schedule.

    `bias` runs -1 (spend on structure) to +1 (spend on refinement), 0 being untilted — pure
    error-equalising, which is the honest default. The tilt is exponential in normalised position
    so it re-ranks steps rather than merely rescaling them, and it is applied to the *ranking*
    only: it never changes the reported error shares, which stay the measured quantity.
    """
    n = max(1, len(steps) - 1)
    out = []
    for step in steps:
        u = 2.0 * (step.index / n) - 1.0  # -1 at the first step, +1 at the last
        out.append(step.weight * math.exp(bias * strength * u))
    return out


def build(
    sigmas,
    *,
    extra_nfe: int = 0,
    bias: float = 0.0,
    bias_strength: float = 4.0,
    cache_floor: float = 0.0,
    protect_tail: int = 2,
    protect_head: int = 1,
    max_substeps: int = 4,
    detail_eta: float = 0.0,
    eta_below_sigma: float = 0.0,
    cfg_below_sigma: float = 0.0,
    solver: str = "res_multistep",
    settings: dict | None = None,
) -> Plan:
    """Turn a sigma schedule and a budget into a per-step plan.

    `extra_nfe` is the currency the user actually cares about: model evaluations on top of one per
    step, which is time. They are handed out greedily by **marginal error reduction**, which for a
    step of order `p` subdivided `k` ways is `weight * (1/k^p - 1/(k+1)^p)` — a strictly decreasing
    return, so greedy is the right algorithm and not merely a convenient one.

    `cache_floor` is the other half of the same idea, read from the bottom: the steps holding the
    smallest `cache_floor` fraction of total error become eligible for Block Cache. Expressed this
    way it means the same thing at any shift, split or step count, where a denoise-percent window
    silently means something different the moment the schedule stops being uniform.
    """
    values = [float(v) for v in sigmas]
    solver = solver if solver in SOLVERS else "res_multistep"
    steps = _weights(values, SOLVER_ORDER[solver])

    total = sum(s.weight for s in steps)
    if total > 0:
        for step in steps:
            step.share = step.weight / total

    # --- subdivision: spend the budget where the error is -------------------------------------
    ranking = _tilt(steps, bias, bias_strength)
    remaining = max(0, int(extra_nfe))
    while remaining > 0:
        best, best_gain = None, 0.0
        for step in steps:
            if step.readout or step.substeps >= max_substeps or ranking[step.index] <= 0.0:
                continue
            k, p = step.substeps, max(1, step.order)
            gain = ranking[step.index] * (1.0 / k**p - 1.0 / (k + 1) ** p)
            if gain > best_gain:
                best, best_gain = step, gain
        if best is None:
            break
        best.substeps += 1
        remaining -= 1

    # --- cache permission: read the same ranking from the bottom ------------------------------
    # Cumulative error share, smallest first. A step joins while the running total is under the
    # floor, so the floor is a promise about how much error the cache may be responsible for
    # rather than a guess about where in the run it is safe to be.
    if cache_floor > 0.0 and total > 0:
        running = 0.0
        for step in sorted(steps, key=lambda s: s.weight):
            if step.readout or step.substeps > 1:
                continue
            if running + step.share > cache_floor:
                break
            running += step.share
            step.cache_ok = True
        last = len(steps) - 1
        for step in steps:
            # The opening steps decide composition and the closing ones decide detail, and neither
            # is worth reusing however small their integration error is. This is the one place the
            # plan keeps a positional rule, because the thing being protected is not accuracy.
            if step.index < protect_head or step.index > last - protect_tail:
                step.cache_ok = False

    # --- bands: the two settings that are not about accuracy ----------------------------------
    for step in steps:
        if detail_eta > 0.0 and step.sigma_from <= eta_below_sigma and not step.readout:
            step.eta = detail_eta
        if cfg_below_sigma > 0.0 and step.sigma_from <= cfg_below_sigma:
            step.cfg = 1.0

    return Plan(steps=steps, sigmas=values, solver=solver, settings=dict(settings or {}))


def describe(plan: Plan) -> str:
    """The plan as a table, for the log and for the node's report output.

    Worth reading before a run rather than after: the error-share column is the whole argument for
    where the budget went, and the `2nd` column is where a schedule join announces itself.
    """
    steps = plan.steps
    lines = [
        f"{plan.solver}: {plan.base_nfe} steps, {plan.planned_nfe} evaluations planned "
        f"(+{plan.planned_nfe - plan.base_nfe})",
        "  step   sigma          h      c2   ord   err%   sub  cache   cfg    eta",
    ]
    for step in steps:
        h = "     -" if step.readout else f"{step.h:6.3f}"
        c2 = "     -" if step.c2 is None else f"{step.c2:6.2f}"
        order = "  -" if step.readout else f"{step.order:3d}"
        cache = " yes " if step.cache_ok else "  -  "
        cfg = "   - " if step.cfg is None else f"{step.cfg:4.1f} "
        eta = "   - " if step.eta <= 0 else f"{step.eta:4.2f} "
        lines.append(
            f"  {step.index:4d}  {step.sigma_from:6.4f}  {h}  {c2}  {order}  "
            f"{step.share * 100:5.2f}  {step.substeps:4d}  {cache} {cfg} {eta}"
        )

    body = [s for s in steps if not s.readout]
    if body:
        worst = sorted(body, key=lambda s: -s.share)[:4]
        top = sum(s.share for s in worst)
        cached = [s for s in steps if s.cache_ok]
        lines.append(
            f"  top 4 steps hold {top * 100:.1f}% of local error (steps "
            f"{', '.join(str(s.index) for s in sorted(worst, key=lambda s: s.index))})"
        )
        if cached:
            held = sum(s.share for s in cached)
            lines.append(
                f"  cache may skip {len(cached)} steps holding {held * 100:.2f}% of error "
                f"(the drift threshold still decides whether it does)"
            )
        degraded = [s for s in body if s.order < plan.nominal_order and s.index > 0]
        if degraded:
            lines.append(
                f"  step-size discontinuity at {', '.join(str(s.index) for s in degraded)} — "
                f"res_multistep drops to first order there; detail_spacing on H3 Detail Schedule "
                f"removes it for free"
            )
    return "\n".join(lines)
