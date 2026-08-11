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

import torch


def sigma_of(t: float, shift: float) -> float:
    """The flow schedule's sigma at curve position `t`. t=1 is pure noise, t=0 is clean."""
    return (shift * t) / (1.0 + (shift - 1.0) * t)


def t_of(sigma: float, shift: float) -> float:
    """Inverse of `sigma_of` — where on the curve a given sigma sits."""
    return sigma / (shift + sigma * (1.0 - shift))


def split_sigmas(structure_steps: int, detail_steps: int, split: float, shift: float):
    """Sigmas for a two-phase walk down one shift curve, ending at 0.

    Returns `structure_steps + detail_steps + 1` values, strictly decreasing. The +1 is the
    terminal 0 every sampler expects; a schedule of N steps is N+1 sigmas.
    """
    shift = max(1e-3, float(shift))
    split = min(max(float(split), 1e-4), 0.9999)
    # At least one structure step, always. With none the walk would begin at the split, which is
    # a partial denoise wearing a full schedule's name — samplers expect a schedule to start at
    # sigma max, and silently starting at 0.5 would look like the model ignoring the prompt.
    structure_steps = max(1, int(structure_steps))
    detail_steps = max(0, int(detail_steps))

    t_split = t_of(split, shift)
    values: list[float] = []

    # Structure: t from 1 down to t_split. The split point itself belongs to the detail phase,
    # so it is not emitted twice.
    for i in range(structure_steps):
        t = 1.0 - (1.0 - t_split) * (i / structure_steps)
        values.append(sigma_of(t, shift))

    # Detail: t_split down to 0, inclusive of the split and exclusive of the terminal zero.
    for i in range(detail_steps):
        t = t_split * (1.0 - i / detail_steps)
        values.append(sigma_of(t, shift))

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
