"""Windowed attention over H3's video rows, with a jittered long-range pass behind it.

H3 attends densely over one packed sequence, so cost grows with `S²` while duration grows with
`S`. The profiler settled where that lands: a 5s run is **compute-bound with attention at 63% of
block time**, and video is ~90% of the rows — so video-attending-to-video is ~82% of all attention
and essentially all of the duration scaling. Halving it is the only lever that changes the shape of
the curve rather than its constant.

**Why a window is the right cut, and why it is not the whole story.** Video rows are laid out
frame-major (`_video_grid` fills `[vt, frame_rows, 3]` then reshapes, `model.py:113-117`), so a
band around the diagonal is exactly "each latent frame sees the frames near it in time, at full
spatial resolution". That is the structure video actually has. What a plain band destroys is the
long-range half: frame 36 stops knowing anything about frame 0, and over 50 layers nothing puts it
back. So the band carries a **follow pass** — a few taps per query frame reaching outside the
window, placed at a low-discrepancy offset that rotates per layer. Fifty layers of rotating taps
cover the whole clip many times over, while any single layer pays for only a few extra frames.
This is BigBird's local+random decomposition with the randomness made deterministic, and it is
deterministic on purpose: the same graph must sample the same way twice, and — load-bearing — the
CFG conditional and unconditional passes must use the **same** mask, or CFG differences the two
approximations and amplifies exactly the error the window introduced. The rotation is keyed to the
call index within a forward, which both passes restart at.

**Identity anchoring is already free and needs no knob.** References, keyframes and the text live
in a contiguous prefix ahead of the target rows (`PackedLayout.__init__`), the window never touches
non-video rows, and so every video row keeps full dense attention to every reference row at every
layer. The thing a sliding window would normally break is the thing H3's packing puts outside the
window's reach.

**Measured on an RTX 5090, bf16, 56x128 heads, 425 rows/frame, window 8, 2 follow taps:**

    5s   (37 frames, S=17,375)   dense  48.4 ms -> flex  28.4 ms   1.70x   54.8% of blocks kept
    10s  (74 frames, S=33,100)   dense 175.0 ms -> flex  55.5 ms   3.15x   31.2%
    20s  (148 frames, S=64,550)  dense 670.6 ms -> flex 108.4 ms   6.19x   16.7%

Attention time goes from quadratic to very nearly linear in duration, and the achieved speedup
tracks the kept fraction almost exactly — the kernel really does skip the masked blocks rather than
computing and discarding them. Peak memory is unchanged (1.78 GB either way at 10s); the mask
itself is under 1 MB.

**Three implementation facts, each of which cost a measurement:**

  * **`torch.compile` is not optional.** Eager `flex_attention` materializes the full `[1, heads,
    S, S]` score matrix — it asked for **63 GiB** at 5s and OOMed. Only the compiled path is fused.
  * **So the recompile limit is a live hazard.** Dynamo's default `recompile_limit` is 8 and is
    keyed on the *code object*, which every `torch.compile(flex_attention)` wrapper shares — one
    wrapper per shape does not help, and was tried. On the 9th distinct sequence length dynamo
    gives up, silently falls back to eager, and the next call asks for 33 GiB. Raising the limit
    (below) fixes it; the guard around the call is the backstop for whatever else can go wrong.
  * **Non-contiguous q/k/v are fine.** The model hands over `[S, heads, dim].transpose(0,1)
    .unsqueeze(0)` (`model.py:178-181`), which is not contiguous. flex reads it at identical speed
    and bit-identical output, so calling `.contiguous()` would be 2.3 ms of pure waste per call.

**What this does not compose with.** The kernel is Triton, so it replaces whatever backend ComfyUI
picked rather than layering on it — SageAttention and this node do not stack, and at 5s they are
worth roughly the same. From 10s up this is several times the better trade. It likewise bypasses
any other `optimized_attention_override` on the same run, which is reported rather than merged:
silently blending two sigma-gated policies is how you get a node that appears to do nothing.

**Reference isolation is therefore built in rather than left to the Reference Isolate node**, which
that override rule would otherwise render dead on every windowed run. It matters most exactly where
the window matters least: on a regenerate pass the conditioning prefix is ~34% of the sequence and
is fully attended by everything including itself, so the frame window — which only ever touches
video-attending-to-video — is working on the other two thirds. Isolating the prefix takes a 5s 2K
regenerate from 77% of blocks kept to 54%, a bigger single step than any window setting.

**It needs three query classes, and collapsing them to two desynchronises the audio.** The packed
order is `[text | references | target audio | target video]`, so "not video" is not the same as
"conditioning" — the target audio sits between them, is being denoised, and has to keep reading the
target video. `geometry` reports `cond_end` alongside `video_start` for exactly this reason.
"""

from __future__ import annotations

import logging

import torch

#: flex_attention's mask granularity. Masks are built at this resolution, so a kept block is fully
#: dense inside — no partial blocks, which is both the fastest kernel path and the reason the
#: window is a conservative *superset* of the frames asked for rather than an exact match.
BLOCK = 128

#: Where the forward wrapper leaves this forward's video geometry for the attention override.
GEOMETRY_KEY = "nynxz_h3_window"

#: Low-discrepancy rotation. Successive layers land maximally far apart in offset space, so the
#: follow taps sweep the clip rather than clustering — the reason this beats a random offset.
GOLDEN = 0.6180339887498949

#: Above this kept fraction the mask is not worth the kernel switch: the dense backend keeps its
#: own tuning, and on short clips it is also the faster one.
DENSE_FLOOR = 0.9

#: How many geometries' worth of masks a patched model keeps. Masks are device tensors held for the
#: model's lifetime, so an uncapped cache would quietly accumulate a plan per resolution tried.
MAX_PLANS = 3

#: Stats from the most recent windowed run, read by the H3 Report node. Published rather than
#: returned because the node that installs the window runs long before the sampling it changes.
LAST: dict | None = None

_COMPILED = None
_DISABLED = False


def publish(stats: dict) -> None:
    global LAST
    LAST = stats


def _compiled():
    """The compiled flex_attention, raising dynamo's limits first.

    Both limits are raised because the fallback they guard is catastrophic here rather than merely
    slow — see the module docstring. They are process-global and deliberately only ever raised,
    never lowered: another pack's compiled function hitting its own limit is a performance problem,
    while this one hitting it is a 33 GiB allocation.
    """
    global _COMPILED
    if _COMPILED is None:
        from torch.nn.attention.flex_attention import flex_attention

        config = torch._dynamo.config
        for name, floor in (
            ("recompile_limit", 64),
            ("cache_size_limit", 64),
            ("accumulated_recompile_limit", 512),
        ):
            if hasattr(config, name):
                setattr(config, name, max(int(getattr(config, name)), floor))
        _COMPILED = torch.compile(flex_attention, dynamic=False)
    return _COMPILED


def geometry(layout) -> dict | None:
    """Where the video rows are and how they divide into frames, or None if they don't.

    Read from the layout rather than recomputed: `signature` is the tuple the forward itself
    validates the layout against (`model.py:520`), so `latent_h`/`latent_w` here are the padded
    dimensions the DiT actually packed, not the ones the latent arrived with.
    """
    segments = getattr(layout, "segments", None)
    signature = getattr(layout, "signature", None)
    if not segments or not signature or len(signature) != 5:
        return None
    _text_len, latent_t, latent_h, latent_w, _audio_t = signature
    frame_rows = (latent_h // 2) * (latent_w // 2)
    if latent_t < 1 or frame_rows < 1:
        return None
    video = next(((a, b) for a, b, kind in segments if kind == "video"), None)
    if video is None or (video[1] - video[0]) != latent_t * frame_rows:
        return None  # a layout shape this mask arithmetic was not written for
    # Where the CONDITIONING ends, which is not where the video begins: the packed order is
    # [text | references | target audio | target video], so `video_start` has the target audio
    # inside it. That distinction is the whole reason reference isolation needs three query
    # classes rather than two — see `build_mask`.
    cond_end = next((a for a, _b, kind in segments if kind in ("audio", "video")), int(video[0]))
    return {
        "video_start": int(video[0]),
        "cond_end": int(cond_end),
        "frame_rows": int(frame_rows),
        "n_frames": int(latent_t),
        "seq_len": int(layout.seq_len),
    }


def _follow_offsets(window: int, n_frames: int, taps: int, jitter: float, layer: int) -> list[int]:
    """Frame distances the follow pass reaches, beyond the window, for one layer.

    The distances are spread evenly across everything the window excludes and then rotated by a
    golden-ratio phase, so layer `i` and layer `i+1` tap different frames and fifty layers tap
    nearly all of them. `jitter` scales the rotation only: at 0 every layer uses the same fixed
    strided taps, which is the honest A/B for whether the rotation is doing anything.
    """
    distant = n_frames - (2 * window + 1)
    if distant <= 0 or taps <= 0:
        return []
    taps = min(taps, distant)
    span = distant / taps
    phase = (jitter * ((layer + 1) * GOLDEN)) % 1.0
    return [window + 1 + int((t + phase) * span) % distant for t in range(taps)]


def build_mask(
    geo: dict, window: int, taps: int, jitter: float, layer: int, device, isolate: bool = False
):
    """A `[nQ, nK]` block-granular keep matrix as a BlockMask, plus the fraction it keeps.

    Every included block is filed as a **full** block: the kernel then runs it with no per-element
    masking at all. That is what makes the measured speedup track the kept fraction. The price is
    that a block straddling a boundary is resolved generously in both directions — a query block is
    only windowed when *all* of its rows are video, and a key block is kept unconditionally when
    *any* of its rows are not. Both errors add attention rather than remove it, which is the side
    to err on.
    """
    from torch.nn.attention.flex_attention import BlockMask

    seq_len, v0 = geo["seq_len"], geo["video_start"]
    rows, n_frames = geo["frame_rows"], geo["n_frames"]

    n_blocks = (seq_len + BLOCK - 1) // BLOCK
    index = torch.arange(n_blocks, device=device)
    first_row = index * BLOCK
    last_row = torch.clamp((index + 1) * BLOCK - 1, max=seq_len - 1)

    # Frame span of each block. Prefix rows floor-divide negative and clamp to 0, which is why
    # every use below is gated on the video flags rather than on the frame numbers alone.
    frame_lo = torch.clamp(torch.div(first_row - v0, rows, rounding_mode="floor"), min=0)
    frame_hi = torch.clamp(torch.div(last_row - v0, rows, rounding_mode="floor"), min=0)
    q_windowed = first_row >= v0  # all rows video -> subject to the window
    k_outside = first_row < v0  # any row not video -> always visible

    # Local band: the query block's frame span, widened by the window, meeting the key block's.
    near = (frame_lo[None, :] <= frame_hi[:, None] + window) & (
        frame_hi[None, :] >= frame_lo[:, None] - window
    )
    keep = (~q_windowed[:, None]) | k_outside[None, :] | near

    if isolate:
        # Reference isolation, expressed in the mask instead of as a competing attention override
        # — which is the only way to have it at all while the window is active, since both would
        # otherwise claim `optimized_attention_override` and the last one installed would win.
        #
        # THREE query classes, and collapsing them to two desynchronises the audio. The packed
        # order is [text | references | target AUDIO | target video], so "not video" is not the
        # same as "conditioning": the target audio sits between them, is being denoised, and must
        # keep reading the target video or the soundtrack stops matching the picture.
        #
        #   conditioning  -> conditioning only. Nothing reads a prefix row's output (`final_layer`
        #                    slices only the target segments) and its timestep never moves, so its
        #                    one reason to drift across steps is reading the noisy target. Cut
        #                    that and the prefix becomes a pure function of [text | references].
        #   target audio  -> everything, unchanged. 414 rows; there is nothing to save here.
        #   target video  -> unchanged: prefix keys plus the local band.
        cond_end = int(geo.get("cond_end", v0))
        q_cond = last_row < cond_end  # query block lies wholly inside the conditioning
        k_cond = first_row < cond_end  # key block touches the conditioning
        # Straddling blocks fall through to "keep", matching the generous-in-both-directions rule
        # the local band already follows: every boundary error here adds attention, never removes it.
        keep = torch.where(
            q_cond[:, None],
            k_cond[None, :],
            torch.where(q_windowed[:, None], keep, torch.ones_like(keep)),
        )

    for offset in _follow_offsets(window, n_frames, taps, jitter, layer):
        target = (frame_lo + offset) % n_frames
        hit = (frame_lo[None, :] <= target[:, None]) & (frame_hi[None, :] >= target[:, None])
        keep |= hit & q_windowed[:, None] & (~k_outside)[None, :]

    counts = keep.sum(-1).to(torch.int32)
    # Kept block ids first, in order; the kernel reads only the first `counts[i]` of each row.
    order = torch.argsort((~keep).to(torch.int8), dim=-1, stable=True).to(torch.int32)
    empty_n = torch.zeros_like(counts)
    empty_i = torch.zeros((n_blocks, 1), dtype=torch.int32, device=device)
    mask = BlockMask.from_kv_blocks(
        empty_n[None, None],
        empty_i[None, None],
        counts[None, None],
        order[None, None],
        BLOCK_SIZE=BLOCK,
        seq_lengths=(seq_len, seq_len),
    )
    # Counted in int64 rather than averaged in float32: a float mean over the ~19k blocks of a
    # 20s clip returns 0.99999994 for an all-keep mask on CUDA (exactly 1.0 on CPU), and the
    # no-op check downstream deserves an exact answer rather than a device-dependent one.
    kept = int(counts.to(torch.int64).sum().item()) / float(n_blocks * n_blocks)
    return mask, kept


class WindowPlan:
    """The per-layer masks for one geometry, built once and reused for every step and CFG pass.

    Masks depend only on `(geometry, parameters, layer)` — never on sigma, the latent, or the
    conditioning — so the whole set is built on first use and then read. That matters at length:
    the build is ~0.7 ms per layer at 5s but ~8 ms at 20s, which would be 400 ms *per step* if it
    were redone per forward, against the ~560 ms the window saves.
    """

    def __init__(
        self, geo: dict, window: int, taps: int, jitter: float, layers: int, isolate: bool = False
    ):
        self.geo = geo
        self.window = int(window)
        self.taps = int(taps)
        self.jitter = float(jitter)
        self.isolate = bool(isolate)
        self.layers = max(1, int(layers))
        self.masks: dict[int, object] = {}
        self.kept: dict[int, float] = {}
        self.dense = geo["n_frames"] <= 2 * self.window + 1 and not self.isolate
        self.announced = False
        if self.dense:
            # Announced from the constructor, because in this case no mask is ever built and the
            # run would otherwise be silent about the one thing worth saying: it is doing nothing.
            self.announce()

    def mask_for(self, call: int, device):
        layer = call % self.layers
        mask = self.masks.get(layer)
        if mask is None:
            mask, kept = build_mask(
                self.geo, self.window, self.taps, self.jitter, layer, device, self.isolate
            )
            self.masks[layer] = mask
            self.kept[layer] = kept
            if kept >= DENSE_FLOOR:
                # Cheaper to run dense than to switch kernels for this little sparsity.
                self.dense = True
                self.announced = False  # the earlier line said "windowed"; correct it
            self.announce()
        return None if self.dense else mask

    def announce(self) -> None:
        """One console line per geometry, saying what this run will actually do.

        The stats also reach the H3 Report, but the report needs a graph wired for it and runs
        after everything — while the question people ask ("is it even on?") is asked during the
        first step. So the numbers that answer it go to the console the moment they exist: the
        clip's real frame count, the window against it, and the fraction of attention kept.

        The no-op case is the one this exists for. A window wider than the clip is by far the most
        common reason for seeing no speedup, and it is invisible from outside without this line.
        """
        if self.announced:
            return
        self.announced = True
        geo = self.geo
        shape = (
            f"{geo['n_frames']} latent frames x {geo['frame_rows']:,} rows, "
            f"{geo['seq_len']:,} packed rows"
        )
        if self.dense:
            logging.info(
                "MiniMax H3 Sliding Window: NOT windowing — %s, and a window of +/-%d frames "
                "already covers %s of the attention. Running dense. Shorten the window (or "
                "lengthen the clip): the saving only appears once the clip is a few times the "
                "window.",
                shape,
                self.window,
                f"{self.mean_kept():.0%}" if self.kept else "all",
            )
            return
        kept = self.mean_kept() or 1.0
        logging.info(
            "MiniMax H3 Sliding Window: %s. Window +/-%d frames + %d follow taps (jitter %.2f) "
            "keeps %.1f%% of attention — about %.2fx on the attention in every block, for %d "
            "layers.",
            shape,
            self.window,
            self.taps,
            self.jitter,
            100.0 * kept,
            1.0 / kept,
            self.layers,
        )

    def mean_kept(self) -> float | None:
        values = list(self.kept.values())
        return sum(values) / len(values) if values else None


def _usable(args, kwargs, geo) -> bool:
    """Whether this particular attention call is the one the window is written for.

    The token refiner attends over the text alone and reaches the same override (`model.py:249-252`
    via `RefinerBlock`), so query length is what tells the two apart. The rest are shapes and
    options this mask has no meaning for: an additive mask would have to be composed with the block
    mask, and GQA would need the key heads expanded first — both are passthroughs rather than
    silent approximations.
    """
    if len(args) < 4 or not isinstance(args[0], torch.Tensor):
        return False
    if not kwargs.get("skip_reshape") or kwargs.get("mask") is not None:
        return False
    if kwargs.get("enable_gqa") or args[0].ndim != 4:
        return False
    return args[0].shape[2] == geo["seq_len"] and args[1].shape[2] == geo["seq_len"]


def attention_override(previous, plan_for, sigma_start: float, sigma_end: float, state: dict):
    """Route H3's self-attention through flex_attention with this call's windowed block mask."""

    def override(func, *args, **kwargs):
        global _DISABLED
        options = kwargs.get("transformer_options") or {}
        geo = options.get(GEOMETRY_KEY)

        def passthrough():
            if previous is not None:
                return previous(func, *args, **kwargs)
            return func(*args, **kwargs)

        if _DISABLED or geo is None or not _usable(args, kwargs, geo):
            return passthrough()
        sigma = options.get("sigmas")
        if sigma is not None:
            value = float(sigma.flatten()[0].item())
            if not (sigma_end <= value <= sigma_start):
                state["dense_calls"] = state.get("dense_calls", 0) + 1
                return passthrough()

        q, k, v = args[0], args[1], args[2]
        plan = plan_for(geo, q.device)
        # Counted per forward, not per layer index: the forward wrapper resets it, so the
        # conditional and unconditional passes walk the same rotation and get the same masks.
        call = state.get("call", 0)
        state["call"] = call + 1
        mask = plan.mask_for(call, q.device)
        if mask is None:
            state["dense_calls"] = state.get("dense_calls", 0) + 1
            return passthrough()

        try:
            out = _compiled()(q, k, v, block_mask=mask, scale=kwargs.get("scale"))
        except Exception:
            # Anything at all — a dynamo fallback, an unsupported head dim, a Triton failure —
            # means dense for the rest of the run. Half a run windowed and half not would be a
            # visible seam, and the eager path this could fall into allocates tens of GiB.
            _DISABLED = True
            state["failed"] = True
            logging.exception(
                "MiniMax H3 Sliding Window: flex_attention failed, falling back to dense "
                "attention for the rest of this process."
            )
            return passthrough()

        state["windowed_calls"] = state.get("windowed_calls", 0) + 1
        state["kept"] = plan.mean_kept()
        state["isolate"] = "nynxz_h3_prefix" in options
        publish(stats(state, plan))
        if kwargs.get("skip_output_reshape"):
            return out
        return out.transpose(1, 2).reshape(out.shape[0], -1, out.shape[1] * out.shape[3])

    return override


def stats(state: dict, plan: WindowPlan) -> dict:
    kept = plan.mean_kept()
    return {
        "window": plan.window,
        "taps": plan.taps,
        "jitter": plan.jitter,
        "layers": plan.layers,
        "n_frames": plan.geo["n_frames"],
        "frame_rows": plan.geo["frame_rows"],
        "video_start": plan.geo["video_start"],
        "seq_len": plan.geo["seq_len"],
        "kept": kept,
        "windowed_calls": state.get("windowed_calls", 0),
        "dense_calls": state.get("dense_calls", 0),
        "failed": bool(state.get("failed")),
        "isolate": bool(state.get("isolate")),
    }
