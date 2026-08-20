# Sampling notes

The reasoning behind the sampling nodes — why a schedule is shaped the way it is, where the
measurements came from, and which claims are still hypotheses. The README gives each node its
signature and the one fact you need to use it; this is the rest.

## H3 Detail Schedule — why a split schedule reads out deeper

At H3's default shift of 12, a 20-step schedule spends **one** step below sigma 0.5 and ends on a
0.387 → 0 jump. Budgeting structure and refinement separately fixes that without changing the
shift curve — every sigma still lies on it.

Measured in log-SNR, the coordinate a flow model's difficulty is actually uniform in, what the
node buys is the **readout point**: plain shift-12 at 23 steps reads out at λ 0.61; a 15/8 split
reads out at λ 2.15, a nat and a half deeper into high SNR.

`shift` itself is a pure translation in that coordinate and redistributes nothing, which is why
lowering it is not a substitute.

### `detail_spacing`

Free, and off by default. At 0 the refinement phase follows the curve, which makes its first step
**3.7× shorter** than the structure step before it. `res_multistep` builds its second-order term
from exactly that ratio, and across a drop that size the term stops contributing — its share of
the update falls from ~34% to 10.8% for one step, the handoff step.

At 1 every refinement step is the same size and the ratio is 1.4. The split and the final sigma do
not move at any setting.

## H3 Scheduled Sampler — hidden from the menu

> `is_dev_only` — hidden from the node library, search and the right-click Add Node menu.
> **To use it: Settings → "Enable dev mode options (API save, etc.)"** (`Comfy.DevMode`). It comes
> back with a `Dev Only` badge; no restart needed.
>
> The filtering is UI-only — the node is still registered, so a workflow that already contains it
> loads and runs with dev mode off. See `DEV_ONLY` in `tests/test_registry.py`.

`sigmas, solver, extra_evaluations, bias, cache_floor, max_substeps, detail_eta, eta_below_sigma,
cfg_below_sigma, verbose` → `SAMPLER, SIGMAS, report`

`res_multistep` with a per-step budget. On a 15/8 split, **four of twenty-two steps carry 97% of
the schedule's local truncation error and the smallest twelve carry 0.07%** — effort spread evenly
over that is almost all spent where it cannot matter. `extra_evaluations` are handed out by
marginal error reduction instead, and Block Cache is told where it may skip rather than inferring
it from a denoise percentage.

With `extra_evaluations` 0 and everything else off it is **bit-for-bit `res_multistep`** — or
bit-for-bit `euler` with `solver` set to that. Both integrators are core's, unchanged.

`solver` also re-plans the budget rather than only changing the update: local error is
`h^(order+1)`, so first order is less concentrated (top-4 88.2% against 96.9%) and the evaluations
spread wider. Up to +8 the two allocate identically — the same few steps dominate either way — and
they separate at +10, where multistep starts buying down the schedule join and Euler does not,
because it holds no history for a discontinuity to degrade. **Reach for `euler` when Block Cache
is running hard**: a cached step's approximate `denoised` becomes the next step's history term and
is carried forward with weight ~0.6–0.97, where Euler keeps that error local.

Wire the schedule through it (`SIGMAS` in, `SIGMAS` out) so the report is the plan that runs.

`cache_floor` supersedes Block Cache's `start_percent`/`end_percent` when both are present. Those
are percentages resolved against the model's *unsplit* curve, so they stop meaning what they say
once a split schedule is wired in — at `detail_steps` 8 the default window already excludes the
last 5 of 23 steps, and at 16 it excludes the last 10 of 31, always the refinement phase. It is
permission only: the cache's own drift threshold still decides, so it can never skip more than
before.

**`detail_eta` is the only knob here that adds detail.** Everything else buys fidelity to the
trajectory the model was already taking — more converged, which reads as cleaner and sometimes as
flatter. Ancestral noise, banded to the refinement phase, is what changes *which* trajectory you
land on. Off by default.

`cfg_below_sigma` forces CFG to 1.0 below a sigma, which makes ComfyUI drop the unconditional pass
outright and halve those steps. Biggest available saving, most likely to cost prompt adherence.

**Why it is still hidden:** the arithmetic is tested hard, but "local truncation error is what
limits H3 output quality" is a hypothesis. The run log prints predicted-vs-measured local error so
it gets checked rather than assumed. Once that check has happened on a real checkpoint, drop
`is_dev_only` from the node and its entry from `DEV_ONLY`.

## Where the attention numbers came from

**Sliding Window**, window 8 with 2 taps: attention **1.7× at 5s, 3.2× at 10s**, peak memory
unchanged. Text and references stay fully attended; the rotating long-range taps are what keep
distant frames reachable. Needs a Triton-capable GPU and falls back to dense attention otherwise.

**Reference Isolate** saves in proportion to how much of the sequence is references — **25% with a
full-res video reference, 1.3% with none** — and costs no memory. `start_percent` lets references
watch composition get decided before freezing them.

**Depth Skip**: blocks 3–17 measure as the quietest band on the released checkpoints, and
`attention_only` keeps most of the saving because attention is ~83% of block time at these
sequence lengths. Confirm against your own output before relying on the band.

**Block Cache**: 80s → 30s on a 5s clip at aggressive settings, skipping 49 of 50 blocks on steps
that barely change. `threshold` is an accumulated relative-L1 budget, so it means the same at any
resolution or duration; 0.05–0.1 is usually free, past 0.2 motion smears.

## Why H3 Video exists instead of more autogrow slots

A video is four correlated settings — frames, fps, soundtrack, detail — and an autogrow slot holds
one value, so it can only be carried by splitting those across parallel groups. That is what makes
core's `ref_video_audio_N` pair with `ref_video_N` **by slot number**: put a silent clip in an
early slot and every later soundtrack lands on the wrong video, with nothing on screen saying so.
H3 Video binds all four together on one node and chains.
