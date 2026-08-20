"""Splitting the sigma schedule so H3 has a refinement phase at all.

**The measurement this exists for.** H3's `shift_video` defaults to 12.0, which compresses the
schedule hard toward the noisy end. At 20 steps that leaves **one** step below sigma 0.5 and none
below 0.2, and the last hop is 0.387 straight to 0 — so every piece of fine detail is decided in a
single jump, with no later step to reconcile neighbouring frames against each other. Only 7.7% of
the schedule's range sits below sigma 0.5 at shift 12; at shift 5 it is 16.7%.

**Why not just lower the shift.** Because shift is not only a step allocation, it is the shape of
the trajectory the model was trained under — high shift exists because high-dimensional data needs
a long structure phase. Lowering it buys refinement by taking steps away from structure, and the
failure mode is global motion going unstable.

**What this does instead.** It keeps the shift-12 curve *exactly* and changes only how densely the
curve is sampled, in two independently-budgeted regions:

    sigma(t) = shift*t / (1 + (shift-1)*t)          the curve, untouched
    t(sigma) = sigma / (shift + sigma*(1 - shift))  its inverse, used to find the split

Structure steps are spread over `t` from 1 down to `t(split)`; detail steps over `t(split)` down
to 0. Every sigma produced still lies exactly on the shift-12 curve — no point exists that plain
shift-12 sampling could not also produce. Only the density changes. That is the difference between
this and lowering the shift, and it is the whole idea.
"""

from __future__ import annotations

import math

import torch


def sigma_of(t: float, shift: float) -> float:
    """The flow schedule's sigma at curve position `t`. t=1 is pure noise, t=0 is clean."""
    return (shift * t) / (1.0 + (shift - 1.0) * t)


def t_of(sigma: float, shift: float) -> float:
    """Inverse of `sigma_of` — where on the curve a given sigma sits."""
    return sigma / (shift + sigma * (1.0 - shift))


def split_sigmas(
    structure_steps: int, detail_steps: int, split: float, shift: float, detail_spacing: float = 0.0
):
    """Sigmas for a two-phase walk down one shift curve, ending at 0.

    Returns `structure_steps + detail_steps + 1` values, strictly decreasing. The +1 is the
    terminal 0 every sampler expects; a schedule of N steps is N+1 sigmas.

    `detail_spacing` fixes the join, and costs nothing. Spreading the detail phase linearly in `t`
    the way the structure phase is spread makes its first step much shorter than the structure step
    that preceded it — 0.075 against 0.275 in `-log(sigma)` at 15/8, a 3.7x drop. `res_multistep`
    builds its second-order term from exactly that ratio, and across a drop that size the term
    stops contributing: its share of the update falls from ~34% to 10.8% for one step, which is the
    handoff step, the one this node exists to set up. At 1.0 the detail phase is instead spread
    evenly in `-log(sigma)`, so every refinement step is the same size and the ratio at the join is
    1.4 rather than 3.7. **The phase's endpoints do not move** — the split it starts at and the
    final sigma it reads out from are identical at every setting, so nothing this node is judged on
    changes. 0.0 is the original spacing, exactly.
    """
    shift = max(1e-3, float(shift))
    split = min(max(float(split), 1e-4), 0.9999)
    # At least one structure step, always. With none the walk would begin at the split, which is
    # a partial denoise wearing a full schedule's name — samplers expect a schedule to start at
    # sigma max, and silently starting at 0.5 would look like the model ignoring the prompt.
    structure_steps = max(1, int(structure_steps))
    detail_steps = max(0, int(detail_steps))
    detail_spacing = min(max(float(detail_spacing), 0.0), 1.0)

    t_split = t_of(split, shift)
    values: list[float] = []

    # Structure: t from 1 down to t_split. The split point itself belongs to the detail phase,
    # so it is not emitted twice.
    for i in range(structure_steps):
        t = 1.0 - (1.0 - t_split) * (i / structure_steps)
        values.append(sigma_of(t, shift))

    # Detail: t_split down to 0, inclusive of the split and exclusive of the terminal zero.
    on_curve = [sigma_of(t_split * (1.0 - i / detail_steps), shift) for i in range(detail_steps)]
    if detail_spacing > 0.0 and detail_steps >= 2:
        # The same span walked at a constant step size in the integrator's own coordinate. Blended
        # in log-sigma because that is the axis both variants are straight in, and because a convex
        # combination there is guaranteed monotonic — the two agree at both ends, so any blend
        # keeps the endpoints and only redistributes what is between them.
        first, last = on_curve[0], on_curve[-1]
        ratio = last / first
        even = [first * ratio ** (i / (detail_steps - 1)) for i in range(detail_steps)]
        on_curve = [
            math.exp((1.0 - detail_spacing) * math.log(a) + detail_spacing * math.log(b))
            for a, b in zip(on_curve, even, strict=True)
        ]
    values.extend(on_curve)

    values.append(0.0)
    return torch.FloatTensor(values)


def uniform_sigmas(steps: int, shift: float):
    """The plain single-phase schedule, for comparison and for the report."""
    shift = max(1e-3, float(shift))
    values = [sigma_of(1.0 - i / steps, shift) for i in range(steps)]
    values.append(0.0)
    return torch.FloatTensor(values)


def describe(sigmas, split: float) -> str:
    """How the budget actually landed — the numbers worth seeing before rendering."""
    body = sigmas[:-1] if len(sigmas) > 1 else sigmas
    # `<=`, not `<`: a step is the hop from sigmas[i] to sigmas[i+1], and the detail phase's
    # first sigma sits exactly ON the split. That step refines; counting it as structure would
    # under-report the budget by one at every setting.
    below = int((body <= split).sum())
    tail = [round(float(v), 3) for v in sigmas[-5:]]
    final = float(sigmas[-2]) if len(sigmas) > 1 else 0.0
    return (
        f"{len(body)} steps, {below} below sigma {split:g}\n"
        f"  final hop: {final:.3f} -> 0\n"
        f"  tail: {tail}"
    )
