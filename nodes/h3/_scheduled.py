"""Running a plan — a `res_multistep` walk that spends its steps unevenly on purpose.

The integrator here is core's `res_multistep` (`comfy/k_diffusion/sampling.py:1394`) with four
things added, and it is deliberately not a new solver: the second-order exponential-multistep
update is unchanged, so a plan that asks for nothing behaves exactly like the stock sampler.

  * **Subdivision.** Steps the plan marked expensive are walked as several smaller ones. This needs
    no special case in the integrator because subdividing a step and putting more sigmas there are
    the same operation — `Plan.expanded()` splices them in and the multistep history flows across a
    substep boundary exactly as it does across a step boundary.
  * **Publishing.** Each step's entry is filed into `transformer_options` before the model runs, so
    Block Cache reads a decision instead of inferring one from a denoise percentage computed on a
    curve the schedule stopped following. See `_cache.py`.
  * **Banded eta and CFG.** Both are per-step, and both are the settings that do something other
    than improve accuracy — eta changes which trajectory is taken, CFG 1.0 makes core drop the
    unconditional pass outright and halve the step.
  * **A free error measurement.** The Euler and second-order predictions of the next latent are
    both already in hand at every step; their difference is a standard embedded estimate of that
    step's local error, and it costs a subtraction on a latent rather than a model evaluation. The
    plan predicts error from step size alone; this is what actually happened, and the end-of-run
    report puts the two side by side.

**What the report is for.** The prediction is `h^(p+1)` with the constant assumed flat across the
schedule. It will not be exactly flat — the model is stiffer near sigma 1 than near sigma 0 — and
the measured column is how far off that assumption is on real content. If the two columns disagree
badly, the allocator is spending in the wrong place and the numbers say where instead of leaving it
to taste.
"""

from __future__ import annotations

import logging

import torch
from comfy.k_diffusion.sampling import default_noise_sampler, get_ancestral_step, to_d
from tqdm.auto import trange

from . import _plan

NAME = "H3 Scheduled Sampler"

#: The key the plan is published under, defined in `_plan.py` so `_cache.py` can read it without
#: importing this module.
KEY = _plan.KEY

#: Stats from the most recent run, for a report node. Published for the same reason `_cache.py`
#: publishes its own: the node that built the sampler ran long before the sampling it describes.
LAST: dict | None = None


def _noise_scale(model) -> float:
    """Core multiplies `s_noise` by the model's own noise scale; H3's packed AV latent has one."""
    try:
        sampling = model.inner_model.model_patcher.get_model_object("model_sampling")
    except (AttributeError, KeyError):
        return 1.0
    return float(getattr(sampling, "noise_scale", 1.0))


def _guider(model):
    """The object holding `cfg`, if this run has one.

    `SamplerCustomAdvanced` can be driven by a guider with no CFG at all (`Guider_Basic`), in which
    case per-step CFG has nothing to act on and is skipped rather than faked.
    """
    inner = getattr(model, "inner_model", None)
    return inner if hasattr(inner, "cfg") else None


class Run:
    """Per-run bookkeeping: what the plan asked for against what it cost and what it measured."""

    def __init__(self, plan: _plan.Plan, verbose: bool):
        self.plan = plan
        self.verbose = verbose
        self.evaluations = 0
        self.uncond_dropped = 0
        #: Measured local error per ORIGINAL step index, summed over its substeps.
        self.measured: dict[int, float] = {}

    def record(self, owner: int, error: float) -> None:
        self.measured[owner] = self.measured.get(owner, 0.0) + error

    def report(self) -> list[str]:
        plan = self.plan
        lines = [
            f"{NAME}: {self.evaluations} evaluations over {plan.base_nfe} steps "
            f"(plan asked {plan.planned_nfe}"
            + (
                f", {self.uncond_dropped} uncond passes dropped by CFG 1.0"
                if self.uncond_dropped
                else ""
            )
            + ")"
        ]
        total = sum(self.measured.values())
        if total <= 0:
            return lines

        body = [s for s in plan.steps if not s.readout and s.index in self.measured]
        ranked = sorted(body, key=lambda s: -self.measured[s.index])[:6]
        if self.verbose:
            lines.append(
                f"{NAME} [verbose]: local error, predicted from step size vs measured on this "
                f"content (top {len(ranked)} of {len(body)})"
            )
            for step in ranked:
                got = self.measured[step.index] / total * 100.0
                lines.append(
                    f"  step {step.index:3d}  sigma {step.sigma_from:6.4f}  "
                    f"predicted {step.share * 100:5.2f}%  measured {got:5.2f}%  "
                    f"({step.substeps} eval{'s' if step.substeps > 1 else ''})"
                )

        # The one number that says whether the allocator aimed at the right steps. Agreement means
        # step size alone predicts error well enough to plan open-loop; a large gap means it does
        # not, and the honest response is to lower the bias and let the measurement lead.
        predicted_top = sum(s.share for s in sorted(body, key=lambda s: -s.share)[:4])
        measured_top = sum(self.measured[s.index] for s in ranked[:4]) / total
        lines.append(
            f"{NAME}: top-4 concentration — predicted {predicted_top * 100:.1f}%, "
            f"measured {measured_top * 100:.1f}%"
        )
        return lines


def sampler_function(
    model,
    x,
    sigmas,
    extra_args=None,
    callback=None,
    disable=None,
    plan_settings: dict | None = None,
    s_noise: float = 1.0,
    verbose: bool = False,
):
    """A `KSAMPLER` body. `plan_settings` is everything the node collected, applied to the real
    schedule at run time rather than to whatever the node was shown when the graph was built."""
    global LAST
    extra_args = {} if extra_args is None else extra_args
    settings = dict(plan_settings or {})

    values = [float(v) for v in sigmas]
    plan = _plan.build(values, settings=settings, **settings)
    run = Run(plan, verbose)

    expanded = plan.expanded()
    owners = plan.owners()
    walk = torch.tensor(expanded, dtype=sigmas.dtype, device=sigmas.device)

    # One line always, the whole table only when asked — the same split the block cache uses, and
    # for the same reason: the summary is worth seeing every run, the table is worth seeing while
    # a setting is being chosen.
    if verbose:
        logging.info("%s: plan for this run\n%s", NAME, plan.describe())
    else:
        logging.info(
            "%s enabled — %s, %d steps, %d evaluations planned, bias %+g",
            NAME,
            plan.solver,
            plan.base_nfe,
            plan.planned_nfe,
            settings.get("bias", 0.0),
        )

    # Read off the plan rather than taken as a second setting: the allocator already weighted every
    # step by `h^(order+1)` for this solver, and a sampler running a different one would be spending
    # a budget computed for someone else.
    euler_mode = plan.solver == "euler"

    seed = extra_args.get("seed", None)
    noise_sampler = default_noise_sampler(x, seed=seed)
    noise_gain = s_noise * _noise_scale(model)
    s_in = x.new_ones([x.shape[0]])
    sigma_fn = lambda t: t.neg().exp()  # noqa: E731
    t_fn = lambda sigma: sigma.log().neg()  # noqa: E731
    phi1_fn = lambda t: torch.expm1(t) / t  # noqa: E731
    phi2_fn = lambda t: (phi1_fn(t) - 1.0) / t  # noqa: E731

    options = extra_args.get("model_options")
    published = options.setdefault("transformer_options", {}) if isinstance(options, dict) else None
    guider = _guider(model)
    original_cfg = getattr(guider, "cfg", None) if guider is not None else None

    old_denoised = None
    old_sigma_down = None
    try:
        for i in trange(len(walk) - 1, disable=disable):
            step = plan.steps[owners[i]]

            # Everything the rest of the graph is allowed to know about this step, filed before the
            # model runs so the block patches see it on this forward and not the next one.
            if published is not None:
                published[KEY] = step
            if guider is not None and step.cfg is not None and original_cfg is not None:
                guider.cfg = step.cfg
                if abs(step.cfg - 1.0) < 1e-6 and abs(original_cfg - 1.0) > 1e-6:
                    run.uncond_dropped += 1
            elif guider is not None and original_cfg is not None:
                guider.cfg = original_cfg

            denoised = model(x, walk[i] * s_in, **extra_args)
            run.evaluations += 1
            sigma_down, sigma_up = get_ancestral_step(walk[i], walk[i + 1], eta=step.eta)
            if callback is not None:
                # Addressed in the caller's step numbers: subdividing must not make a 23-step run
                # report 31 to a progress bar that was told there would be 23.
                callback(
                    {
                        "x": x,
                        "i": step.index,
                        "sigma": walk[i],
                        "sigma_hat": walk[i],
                        "denoised": denoised,
                    }
                )

            d = to_d(x, walk[i], denoised)
            euler = x + d * (sigma_down - walk[i])
            if sigma_down == 0 or old_denoised is None:
                # The readout, and the opening step. Euler to sigma 0 returns `denoised` exactly,
                # and there is no history yet on the first step, so both solvers agree here.
                x = euler
            else:
                t, t_old = t_fn(walk[i]), t_fn(old_sigma_down)
                t_next, t_prev = t_fn(sigma_down), t_fn(walk[i - 1])
                h = t_next - t
                c2 = (t_prev - t_old) / h

                phi1_val, phi2_val = phi1_fn(-h), phi2_fn(-h)
                b1 = torch.nan_to_num(phi1_val - phi2_val / c2, nan=0.0)
                b2 = torch.nan_to_num(phi2_val / c2, nan=0.0)
                second = sigma_fn(h) * x + h * (b1 * denoised + b2 * old_denoised)

                # **The estimate stays free in both modes.** It is the gap between the first- and
                # second-order predictions of the same step, and running Euler does not stop the
                # second-order one being computable — the history is already in hand and the
                # arithmetic is elementwise on a latent. So choosing Euler costs the diagnostic
                # nothing, and in that mode the number is a more direct reading of the error of the
                # step actually taken, because Euler IS the lower-order member of the pair.
                taken = euler if euler_mode else second
                scale = taken.abs().mean().clamp_min(1e-6)
                run.record(step.index, float(((second - euler).abs().mean() / scale).item()))
                x = taken

            if sigma_up > 0:
                x = x + noise_sampler(walk[i], walk[i + 1]) * noise_gain * sigma_up

            old_denoised = denoised
            old_sigma_down = sigma_down
    finally:
        if guider is not None and original_cfg is not None:
            guider.cfg = original_cfg
        if published is not None:
            published.pop(KEY, None)
        for line in run.report():
            logging.info("%s", line)
        LAST = {
            "evaluations": run.evaluations,
            "base_nfe": plan.base_nfe,
            "planned_nfe": plan.planned_nfe,
            "uncond_dropped": run.uncond_dropped,
            "measured": dict(run.measured),
        }
    return x
