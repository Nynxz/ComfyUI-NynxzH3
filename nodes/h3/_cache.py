"""Step-level block caching — reusing the transformer stack's own output across sampling steps.

The observation every cache of this family rests on: between adjacent sampling steps a diffusion
transformer's *output* changes far less than its input does, because most of the stack is
re-deriving the same structure from a slightly less noisy latent. So the delta the stack produces
can be reused for a step or two, and the arithmetic skipped.

The decision has to be made cheaply, or the measurement costs what it saves. This uses the
first-block signal: run block 0 (1/50th of the stack), look at how much its *residual* moved since
the last computed step, and skip the other 49 when that movement is small. The residual rather
than the raw hidden state, because H3's hidden states are dominated by a large common component
that makes step-to-step relative change look tiny whatever is happening.

Two facts about H3's blocks shape the implementation, both verified rather than assumed:

  * **A block returns the same tensor object it was handed**, mutated in place — `_mod_gate` does
    `x[a:b].addcmul_(...)` and returns `x` (`comfy/ldm/minimax/model.py:209-213`). So "skip this
    block" is exactly `return args unchanged`, and anything the cache wants to remember about a
    block's input has to be cloned before the block runs.
  * **The stack is one contiguous residual path.** Nothing between block 0 and block 49 reads
    anything but `img`, so the whole tail is a single additive delta.

Memory: on a computed step the cache holds block 0's output plus the tail delta, two tensors the
size of the hidden state. On a skipped step it holds only the tail. At 17k rows x 5376 that is
~180 MB each; at 73k rows it is ~790 MB, which is worth knowing before turning it on for a long
clip on a card with no headroom. Both are dropped when sampling finishes rather than left resident
until the next run, which is what `end_run` is for.

**Reporting.** Every sampling run ends with one line saying how many passes were skipped and what
the block stack cost against what it would have cost uncached; `verbose` adds a line per pass
naming the decision and the reason for it. The saving is *measured*, not assumed. EasyCache's
`total / (total - skipped)` counterfactual treats a skipped step as free, which is true for it and
false here: a skipped pass still runs block 0 and the tail add, so an assumed number would flatter
this node by about 2%. Measuring also catches the cases where the arithmetic is not the wall.
"""

from __future__ import annotations

import logging
import time

import torch

#: Prefix on every line this node logs.
NAME = "H3 Block Cache"

#: How many rows the change signal is measured over. A relative L1 over a strided sample is a
#: perfectly good estimator of the same quantity over every row, and it keeps the remembered
#: signal at tens of MB instead of hundreds at long durations.
SIGNAL_ROWS = 4096

#: Stats from the most recent cache, read by the H3 Report node. Published rather than returned
#: because the node that installs the cache runs long before the sampling it measures.
LAST: dict | None = None


def publish(stats: dict) -> None:
    global LAST
    LAST = stats


def _sample_index(rows: int, device) -> torch.Tensor | None:
    """Evenly strided row indices, or None when the sequence is short enough to use whole."""
    if rows <= SIGNAL_ROWS:
        return None
    return torch.arange(0, rows, rows // SIGNAL_ROWS, device=device)[:SIGNAL_ROWS]


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _duration(ms: float) -> str:
    return f"{ms / 1000:.2f}s" if ms >= 1000 else f"{ms:.0f}ms"


def _slot_label(key: tuple) -> str:
    if key == (0,):
        return "cond"
    if key == (1,):
        return "uncond"
    return "conds " + ",".join(map(str, key))


class StackTimer:
    """What the block stack actually cost per pass, without a synchronize on every one.

    Wall-clock around the stack is close to meaningless on CUDA. Kernel launches return
    immediately, so a skipped pass would time as near-free while the device is still working
    through the pass before it, and the reported saving would be whatever the launch queue happened
    to be doing. CUDA events go into the same stream and are stamped by the device, so a single
    synchronize once sampling is over turns them into real durations at no per-step cost. On CPU
    `perf_counter` is already exact and there is nothing to defer.

    Durations are milliseconds throughout, because that is what `Event.elapsed_time` returns.
    """

    def __init__(self):
        self.open = None
        self.pending: list[tuple[bool, object, object]] = []
        self.computed: list[float] = []
        self.skipped: list[float] = []

    def start(self, device) -> None:
        """Open a pass. An already-open one is dropped rather than mismatched: with CFG the two
        conditioning slots run one after the other, so a second `start` before a `stop` means the
        last pass never reached the final block (something removed it from the chain) and its
        duration is not ours to report."""
        if device.type == "cuda":
            event = torch.cuda.Event(enable_timing=True)
            event.record()
            self.open = event
        else:
            self.open = time.perf_counter()

    def stop(self, skipped: bool) -> None:
        started = self.open
        self.open = None
        if started is None:
            return
        if isinstance(started, float):
            self._record(skipped, (time.perf_counter() - started) * 1000.0)
            return
        end = torch.cuda.Event(enable_timing=True)
        end.record()
        self.pending.append((skipped, started, end))

    def _record(self, skipped: bool, ms: float) -> None:
        (self.skipped if skipped else self.computed).append(ms)

    def resolve(self) -> None:
        """Drain queued events into numbers. The one synchronize this class costs, after sampling."""
        if not self.pending:
            return
        torch.cuda.synchronize()
        for skipped, start, end in self.pending:
            self._record(skipped, start.elapsed_time(end))
        self.pending = []

    def reset(self) -> None:
        self.open = None
        self.pending = []
        self.computed = []
        self.skipped = []

    def projection(self) -> tuple[float, float] | None:
        """(actual ms, ms the same passes would have cost uncached), or None if nothing was timed.

        The counterfactual is the *median* computed pass, not the mean. H3's passes are all the
        same shape and cost, with one exception — the first one of a run carries kernel autotuning
        and whatever weight movement the loader deferred, and can be several times the rest. A mean
        would fold that into the baseline and quietly inflate the saving; a median ignores it.

        Two things the number does not claim. It covers the **block stack only**, so end-to-end
        wall time moves by less than this ratio once encoding and VAE decode are counted. And a
        computed pass here still pays the cache's own overhead — the strided residual sample, the
        block-0 clone, the tail subtract — so the baseline is very slightly high, by the ratio of
        three elementwise ops to fifty transformer blocks.
        """
        if not self.computed:
            return None
        actual = sum(self.computed) + sum(self.skipped)
        return actual, _median(self.computed) * (len(self.computed) + len(self.skipped))


class BlockCache:
    """Per-run, per-conditioning-slot cache state.

    Slots are keyed on `cond_or_uncond`: a CFG run interleaves two forwards whose hidden states
    have nothing to do with each other, and sharing one cache between them would compare the
    conditional's residual against the unconditional's and skip on noise.
    """

    def __init__(
        self,
        threshold: float,
        max_consecutive: int,
        sigma_start: float,
        sigma_end: float,
        verbose: bool = False,
        percents: tuple[float, float] = (0.0, 1.0),
    ):
        self.threshold = float(threshold)
        self.max_consecutive = int(max_consecutive)
        self.sigma_start = float(sigma_start)
        self.sigma_end = float(sigma_end)
        self.verbose = bool(verbose)
        #: The denoise fractions the sigma window came from, kept only so the enabled banner can
        #: quote the numbers that were actually typed into the node.
        self.percents = percents
        self.slots: dict[tuple, dict] = {}
        self.computed = 0
        self.skipped = 0
        self.total_steps: int | None = None
        self.timer = StackTimer()
        self._warned_rows = False
        #: Every per-step drift measured, so the report can show the distribution the threshold is
        #: being compared against. Choosing a threshold blind is guesswork; choosing it against
        #: the numbers the model actually produced is not.
        self.drifts: list[float] = []

    def stats(self) -> dict:
        drifts = self.drifts
        projection = self.timer.projection()
        return {
            "computed": self.computed,
            "skipped": self.skipped,
            "threshold": self.threshold,
            "max_consecutive": self.max_consecutive,
            "window": (self.sigma_start, self.sigma_end),
            "drift_count": len(drifts),
            "drift_min": min(drifts) if drifts else None,
            "drift_mean": (sum(drifts) / len(drifts)) if drifts else None,
            "drift_max": max(drifts) if drifts else None,
            # None until end_run resolves the timer: mid-run these would need a device sync per
            # step to mean anything, which is the cost this deliberately does not pay.
            "stack_ms": projection[0] if projection else None,
            "stack_ms_uncached": projection[1] if projection else None,
        }

    def slot(self, options: dict) -> dict:
        key = tuple(options.get("cond_or_uncond") or (0,))
        state = self.slots.get(key)
        if state is None:
            state = {
                "label": _slot_label(key),
                "residual": None,
                "tail": None,
                "out0": None,
                "run": 0.0,
                "accum": 0.0,
                "streak": 0,
                "skip": False,
            }
            self.slots[key] = state
        return state

    @staticmethod
    def _sigma(options: dict) -> float | None:
        sigmas = options.get("sigmas")
        if sigmas is None:
            return None
        return float(sigmas.flatten()[0].item())

    def _new_run(self, state: dict, sigma: float | None) -> bool:
        """Whether sampling restarted since this slot last saw a step.

        `transformer_options["sigmas"]` carries the **raw** sigma — `samplers.py:325` files the
        value `calc_cond_batch` was handed, before `model_sampling.timestep()` scales it by 1000
        for the model — so it is directly comparable with `percent_to_sigma`.

        Sigma descends within a run, so a value *above* the last one means a new run: a fresh
        queue, or a second sampler in the same graph. Without this a cached tail from the previous
        generation would be added to the first step of the next one.

        Strictly greater, not `>=`: a second-order sampler can evaluate twice at one sigma, and
        treating that as a restart would throw away a live cache every step. A new run colliding
        with the previous run's last sigma would need its *first* (largest) sigma to equal the
        old run's *last* (smallest), which does not happen.
        """
        if sigma is None:
            return False
        previous = state.get("run")
        state["run"] = sigma
        return previous is not None and sigma > previous

    def _trace(self, state: dict, verdict: str, reason: str) -> None:
        """One verbose line per pass. `computed`/`skipped` are still the counts *before* this
        pass, so their sum plus one is the number of the pass being decided."""
        if not self.verbose:
            return
        logging.info(
            "%s [verbose]: pass %d (%s) %s — %s",
            NAME,
            self.computed + self.skipped + 1,
            state["label"],
            verdict,
            reason,
        )

    def _compute(self, state: dict, reason: str) -> bool:
        """Decline to skip, for `reason`.

        Every path that returns False goes through here so that the accumulator reset cannot be
        forgotten by a branch added later, and that is load-bearing rather than tidiness. The
        accumulator measures drift *since the last computed step*, so leaving it standing after a
        recompute would carry the drift that triggered the recompute into the next budget — it
        would immediately re-trigger, and the cache would skip once and then never again for the
        rest of the run. That reads from outside as "the node does nothing", which is exactly how
        this was found.
        """
        state["accum"] = 0.0
        self._trace(state, "computing", reason)
        return False

    def decide(self, state: dict, residual: torch.Tensor, options: dict) -> bool:
        """Whether to skip the rest of the stack this step, updating the slot's signal."""
        previous = state["residual"]
        state["residual"] = residual

        sigma = self._sigma(options)
        if previous is None or state["tail"] is None:
            return self._compute(state, "nothing cached yet")
        if sigma is not None and not (self.sigma_end <= sigma <= self.sigma_start):
            return self._compute(
                state,
                f"sigma {sigma:.4f} is outside the caching window "
                f"[{self.sigma_end:.4f}, {self.sigma_start:.4f}]",
            )
        if state["streak"] >= self.max_consecutive:
            return self._compute(state, f"max_consecutive {self.max_consecutive} reached")
        if previous.shape != residual.shape:  # sequence changed under us; the tail is meaningless
            state["tail"] = None
            return self._compute(
                state, f"sequence changed, {tuple(previous.shape)} -> {tuple(residual.shape)}"
            )

        scale = previous.abs().mean().clamp_min(1e-6)
        drift = float(((residual - previous).abs().mean() / scale).item())
        self.drifts.append(drift)
        state["accum"] += drift
        budget = f"drift {drift:.4f}, accumulated {state['accum']:.4f}"
        if state["accum"] < self.threshold:
            self._trace(state, "skipping", f"{budget} < threshold {self.threshold:.4f}")
            return True
        return self._compute(state, f"{budget} >= threshold {self.threshold:.4f}")

    def begin(self, args: dict, run) -> dict:
        """Block 0: always computed, and where the skip decision is made."""
        options = args.get("transformer_options") or {}
        state = self.slot(options)
        if self._new_run(state, self._sigma(options)):
            state.update(residual=None, tail=None, out0=None, accum=0.0, streak=0)

        image = args["img"]
        self.timer.start(image.device)
        index = _sample_index(image.shape[0], image.device)
        before = (image if index is None else image[index]).clone()

        out = run(args)
        img = out["img"]
        if img.shape[0] != image.shape[0]:
            # Something inside this chain changed the row count between block 0's input and its
            # output — H3 Frame Hold does exactly that, and only when it is installed *inside*
            # this patch instead of outside it. The residual would be a subtraction between two
            # different sequences, so stand down for the run rather than raise on the shapes.
            # `out0` and `tail` must go with it: `end` would otherwise difference this pass's
            # output against a clone of a differently-shaped one.
            state.update(skip=False, out0=None, tail=None)
            self.computed += 1
            if not self._warned_rows:
                self._warned_rows = True
                logging.warning(
                    "%s: the block chain changed the sequence length under it (%d -> %d rows), "
                    "so caching is off for this run. Add H3 Frame Hold to the graph AFTER this "
                    "node so it wraps outside.",
                    NAME,
                    image.shape[0],
                    img.shape[0],
                )
            return out
        after = img if index is None else img[index]
        residual = (after - before).float()

        state["skip"] = self.decide(state, residual, options)
        if state["skip"]:
            state["streak"] += 1
            self.skipped += 1
            state["out0"] = None
        else:
            state["streak"] = 0
            self.computed += 1
            # Cloned because the remaining blocks mutate this tensor in place; without the copy
            # the tail delta below would come out as exactly zero.
            state["out0"] = img.clone()
        publish(self.stats())
        return out

    def middle(self, args: dict, run) -> dict:
        state = self.slot(args.get("transformer_options") or {})
        if state["skip"]:
            return {"img": args["img"]}
        return run(args)

    def end(self, args: dict, run) -> dict:
        """Last block: apply the cached tail, or compute and record a fresh one."""
        state = self.slot(args.get("transformer_options") or {})
        if state["skip"]:
            tail = state["tail"]
            image = args["img"]
            if tail is not None and tail.shape == image.shape:
                image.add_(tail.to(image.dtype))
            self.timer.stop(skipped=True)
            return {"img": image}

        out = run(args)
        base = state.pop("out0", None)
        if base is not None:
            state["tail"] = out["img"] - base
        self.timer.stop(skipped=False)
        return out

    # --- run lifecycle -------------------------------------------------------------------------
    # Installed as an OUTER_SAMPLE wrapper (see `sample_wrapper`), which is the only place that
    # knows where one sampling run ends and the next begins. Block patches cannot tell: they see a
    # stream of forwards and have to infer restarts from the sigma rising, which `_new_run` does
    # and which is a heuristic. These two are not.

    def begin_run(self, total_steps: int | None) -> None:
        self.total_steps = total_steps
        self.slots = {}
        self.computed = 0
        self.skipped = 0
        self.drifts = []
        self.timer.reset()
        logging.info(
            "%s enabled — threshold: %g, max_consecutive: %d, start_percent: %g, end_percent: %g",
            NAME,
            self.threshold,
            self.max_consecutive,
            *self.percents,
        )

    def end_run(self) -> None:
        """Report the run, then drop the cached tensors.

        Releasing here matters as much as the reporting does. The cache lives in closures held by
        the patched model, which ComfyUI keeps as this node's cached output — so without this the
        tail and block-0 clone stay resident between runs, and at long durations that is ~790 MB of
        VRAM held by a node that is not doing anything.
        """
        self.timer.resolve()
        for line in self.report():
            logging.info("%s", line)
        self.slots = {}
        self.timer.reset()

    def report(self) -> list[str]:
        """The lines `end_run` logs. Split out so it can be asserted on without a log capture."""
        passes = self.computed + self.skipped
        if passes == 0:
            return []

        head = f"{NAME}: skipped {self.skipped} of {passes} stack passes"
        if self.total_steps and passes % self.total_steps == 0:
            head += f" ({self.total_steps} steps x {passes // self.total_steps} cond)"

        projection = self.timer.projection()
        if projection is not None:
            actual, uncached = projection
            head += (
                f"; block stack {_duration(actual)} against {_duration(uncached)} uncached"
                f" — {uncached / actual:.2f}x, {_duration(uncached - actual)} saved"
            )
        lines = [head]

        if self.skipped == 0 and self.drifts:
            lines.append(
                f"{NAME}: nothing was skipped — per-pass drift ran "
                f"{min(self.drifts):.4f}/{max(self.drifts):.4f} min/max against a threshold of "
                f"{self.threshold:g}. Raise it, or widen the start/end window."
            )
        if not self.verbose:
            return lines

        if self.drifts:
            lines.append(
                f"{NAME} [verbose]: drift over {len(self.drifts)} measurements — min "
                f"{min(self.drifts):.4f}, mean {sum(self.drifts) / len(self.drifts):.4f}, max "
                f"{max(self.drifts):.4f} (threshold {self.threshold:g}, accumulated across passes)"
            )
        computed, skipped = self.timer.computed, self.timer.skipped
        if computed and skipped:
            typical = _median(computed)
            lines.append(
                f"{NAME} [verbose]: median computed pass {_duration(typical)}, median skipped "
                f"pass {_duration(_median(skipped))} — {_median(skipped) / typical * 100:.1f}% of "
                "one, which is block 0 plus the tail add and is why a skip is not free"
            )
        return lines


def sample_wrapper(cache: BlockCache):
    """OUTER_SAMPLE wrapper bracketing one sampling run, for reporting and for releasing memory."""

    def wrapper(executor, *args, **kwargs):
        # `outer_sample(noise, latent_image, sampler, sigmas, ...)` — sigmas has one more entry
        # than there are steps.
        sigmas = args[3] if len(args) > 3 else kwargs.get("sigmas")
        cache.begin_run(len(sigmas) - 1 if sigmas is not None else None)
        try:
            return executor(*args, **kwargs)
        finally:
            cache.end_run()

    return wrapper
