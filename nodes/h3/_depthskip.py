"""Dropping blocks, or just their attention half, from H3's stack.

**The evidence this exists to act on**, from `H3BlockContribution` on a real run plus the
adaLN weights read statically:

  * Measured — the twelve quietest blocks move the residual stream **1.3% of all movement**, and
    they are 12 of the 15 members of the contiguous band **3-17** (only 7, 11 and 13 fall just
    outside the bottom twelve).
  * Static — `gate_msa * |1 + scale_msa|` for the video modality puts blocks 3-22 at **0.13x** the
    per-block mean against **2.01x** for blocks 27-49.

Those two disagree about their biases and agree about the answer, which is what makes the band
worth acting on. `_contribution` measures `||after - before|| / ||before||`, normalised by each
block's own input norm — and that norm *grows* with depth, so the metric systematically flatters
early blocks. Blocks 3-17 came out quiet on a measurement tilted in their favour. Meanwhile the
static proxy has the opposite tilt: `norm1` is RMSNorm, so `|1 + scale|` is free of the residual's
magnitude, but the gate factor is not. Neither alone would be worth a node. Together they are.

**What this cannot tell you, and why the node exists rather than a recommendation.** Every measured
delta is conditional on the whole stack running. Remove fifteen blocks and the errors compound —
block 3's absence changes what block 4 reads, and nothing in the measurement predicts where that
lands. The only way to know is to run it and look at the output, so this is built to make that
one A/B cheap rather than to assert an answer.

**Two modes, and the cheaper one is not the safer one.** `whole_block` drops the block entirely;
`attention_only` keeps the MLP. The MLP is worth keeping in this band on its own evidence — its
gate spread across depth is 8x against attention's 68x, and blocks 0-2 are actively MLP-*heavy*
while attention-light — but at these sequence lengths attention is ~83% of block time, so keeping
it costs only about a fifth of the saving.

**How each mode is installed, and why they differ.** `whole_block` joins the `block_patch` chain
and simply does not call `run`, exactly as the Block Cache skips a step. `attention_only` instead
patches `attn.forward` to return zeros — a *module*-level patch, so it composes with the Block
Cache and the Row Chunk instead of displacing them, and it costs nothing: the zero is a
zero-strided `expand`, so `_mod_gate`'s `addcmul_` reads one element rather than a full
`[S, hidden]` buffer that would have to be allocated and streamed every block of every step.
"""

from __future__ import annotations

import logging

import torch


def parse_blocks(spec: str, layers: int) -> list[int]:
    """`"3-17, 22, 25-27"` -> a sorted list of block indices, validated against the stack depth.

    Ranges are inclusive at both ends, because the tables this is read off — the contribution
    report, the gate dump — name blocks by index, and "3-17" should mean the fifteen blocks a
    reader counts, not fourteen.
    """
    out: set[int] = set()
    for piece in str(spec or "").replace(";", ",").split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            if "-" in piece.lstrip("-"):
                lo, hi = piece.split("-", 1) if not piece.startswith("-") else (piece, piece)
                a, b = int(lo), int(hi)
                if a > b:
                    a, b = b, a
                out.update(range(a, b + 1))
            else:
                out.add(int(piece))
        except ValueError:
            raise ValueError(
                f"MiniMax H3 Depth Skip: {piece!r} is not a block index or range. Use forms like "
                "'3-17', '3-17, 22' or '10'."
            ) from None
    bad = sorted(i for i in out if not 0 <= i < layers)
    if bad:
        raise ValueError(
            f"MiniMax H3 Depth Skip: block(s) {bad} are outside this model's 0..{layers - 1}."
        )
    return sorted(out)


def skip_block(args, _run):
    """A `block_patch` wrapper that does not run the block. The residual passes through."""
    return {"img": args["img"]}


#: Where the forward wrapper leaves this forward's video-row offset for the stand-in to read.
GEOMETRY_KEY = "nynxz_h3_depthskip"


def video_start(layout) -> int | None:
    """First row of the target video segment, or None if the layout is not one we understand.

    The packed order is `[text | references | target audio | target video]`, so this is also the
    row count of everything that must keep its attention.
    """
    segments = getattr(layout, "segments", None)
    if not segments:
        return None
    for start, _stop, kind in segments:
        if kind == "video":
            return int(start)
    return None


def geometry_wrapper(state: dict):
    """Publish `video_start` into transformer_options, which is all `attn.forward` can see.

    `Attention.forward` receives only `(x, rope_freqs, transformer_options)` — the packed layout
    lives in `minimax_payload`, one level up. Same trick the Sliding Window uses for its frame
    geometry, and for the same reason.
    """

    def wrapper(executor, x, timestep, context, transformer_options, **kwargs):
        start = video_start((kwargs.get("minimax_payload") or {}).get("layout"))
        if start is not None:
            transformer_options[GEOMETRY_KEY] = start
        elif not state.get("warned"):
            state["warned"] = True
            logging.warning(
                "MiniMax H3 Depth Skip: no packed layout in this forward's payload, so the video "
                "rows cannot be located — running full attention in the named blocks rather than "
                "guessing where to cut."
            )
        return executor(x, timestep, context, transformer_options, **kwargs)

    return wrapper


class VideoAttentionSkip:
    """Stands in for `Attention.forward`, dropping attention for the VIDEO queries only.

    **Dropping it for the whole sequence destroys the audio — measured 2026-08-05**, on blocks
    3-17. Both analyses that licensed the skip were blind to audio, in the same direction:

      * the static adaLN proxy was read for modality 0, **video**; audio has its own gates;
      * `H3BlockContribution` strides uniformly over the sequence, where audio is **828 of
        ~50,500 rows — 1.6%** — so the mean delta it reports is a video measurement.

    The static profile does not merely miss it, it points the wrong way: audio's attention weight
    in blocks 3-17 is 0.9% of its own total against video's 3.8%. "The residual barely moves" was
    true and irrelevant. Audio carries a whole soundtrack in 1.6% of the rows and is perceptually
    unforgiving where video spreads the same relative error over 43,000 rows and a smooth VAE
    decode — and attention is audio's *only* route to what is on screen, so fifteen consecutive
    blocks without it leaves nothing feeding it the picture.

    **Slicing `x` would not fix it, which is the trap here.** `Attention.forward` derives q, k and
    v from the same tensor, so calling it with `x[:video_start]` gives the audio queries only
    *prefix* keys — cutting them off from the video, which is precisely the failure. The queries
    must be sliced while k and v stay full, so this reimplements the forward
    (`comfy/ldm/minimax/model.py:146-182`) with a rectangular attention: `[video_start, S]` instead
    of `[S, S]`.

    RoPE runs at full length before the slice, deliberately. The fused RMSNorm+rope kernel takes q
    and k together and cannot be given mismatched lengths, and it is O(S) elementwise against an
    O(S^2) attention — computing rope for queries that are then discarded costs nothing worth
    saving and keeps this bit-identical to core's path for the rows that survive.
    """

    def __init__(self, hidden: int):
        self.hidden = int(hidden)
        self.original = None
        self._zero = None

    def _zeros(self, x, rows: int):
        if self._zero is None or self._zero.dtype != x.dtype or self._zero.device != x.device:
            self._zero = torch.zeros(1, 1, dtype=x.dtype, device=x.device)
        return self._zero.expand(rows, self.hidden)

    #: Sigma window this skip is active in. `None` means always, which is what the node passes
    #: when the window covers the whole schedule — so the common case costs no comparison.
    sigma_start: float | None = None
    sigma_end: float | None = None

    def in_window(self, transformer_options) -> bool:
        """Whether the current step is inside the skip window.

        `transformer_options["sigmas"]` carries the RAW sigma — `samplers.py` files the value
        `calc_cond_batch` was handed, before `model_sampling.timestep()` scales it by 1000 — so it
        is directly comparable with `percent_to_sigma`, exactly as the Block Cache relies on.
        Same convention too: sigma descends, so the window is `[end, start]` with end the smaller.
        """
        if self.sigma_start is None:
            return True
        sigmas = (transformer_options or {}).get("sigmas")
        if sigmas is None:
            # No sigma published (a bare forward, or a caller that does not file it). Skipping on
            # an unknown timestep would apply the band everywhere, which is the opposite of what a
            # window is for — so fall through to real attention.
            return False
        sigma = float(sigmas.flatten()[0].item())
        return self.sigma_end <= sigma <= self.sigma_start

    def __call__(self, x, rope_freqs=None, transformer_options=None):
        import comfy.model_management
        import comfy.quant_ops
        from comfy.ldm.modules.attention import optimized_attention

        # Normalized here rather than defaulted in the signature: a `{}` default is shared across
        # every call, and this stands in for a forward that gets handed the real dict.
        transformer_options = {} if transformer_options is None else transformer_options

        s = x.shape[0]
        start = transformer_options.get(GEOMETRY_KEY)
        if not self.in_window(transformer_options):
            # Outside the window this block is ordinary again — the point of scheduling it.
            return self.original(x, rope_freqs=rope_freqs, transformer_options=transformer_options)
        if not isinstance(start, int) or not 0 < start < s or rope_freqs is None:
            # No geometry, or a shape this split was not written for. Run the real attention:
            # cutting the wrong rows is worse than cutting none, and it would be silent.
            return self.original(x, rope_freqs=rope_freqs, transformer_options=transformer_options)

        attn = self.attn
        heads, head_dim = attn.heads, attn.head_dim
        inner = heads * head_dim
        q, k, v = attn.qkv_proj(x).split(inner, dim=-1)
        q = q.view(1, s, heads, head_dim)
        k = k.view(1, s, heads, head_dim)
        v = v.view(s, heads, head_dim)

        qw = comfy.model_management.cast_to(attn.q_norm.weight, device=x.device)
        kw = comfy.model_management.cast_to(attn.k_norm.weight, device=x.device)
        rot = rope_freqs.shape[-3] * 2
        if comfy.model_management.in_training:
            q, k = comfy.quant_ops.ck.rms_rope_split_half(
                q, k, rope_freqs, qw, kw, epsilon=attn.q_norm.eps, rot_dim=rot
            )
        else:
            comfy.quant_ops.ck.rms_rope_split_half_(
                q, k, rope_freqs, qw, kw, epsilon=attn.q_norm.eps, rot_dim=rot
            )

        # queries: prefix only.  keys/values: everything, so audio still reads the video.
        q = q[0][:start].transpose(0, 1).unsqueeze(0)
        k = k[0].transpose(0, 1).unsqueeze(0)
        v = v.transpose(0, 1).unsqueeze(0)
        out = optimized_attention(
            q, k, v, heads, mask=None, skip_reshape=True, transformer_options=transformer_options
        )
        head = attn.out_proj(out.squeeze(0))
        return torch.cat((head, self._zeros(x, s - start)), dim=0)


def install_attention_skip(
    patcher, dit, blocks: list[int], hidden: int, window: tuple[float, float] | None = None
) -> int:
    """Patch `attn.forward` for each named block. Returns how many were patched.

    `window` is `(sigma_start, sigma_end)` with start the LARGER — sigma descends. `None` means
    the skip is active for the whole schedule, which is the original behaviour.
    """
    for index in blocks:
        stand_in = VideoAttentionSkip(hidden)
        if window is not None:
            stand_in.sigma_start, stand_in.sigma_end = window
        # Bound per block: fifteen blocks each need their OWN attention module, and a shared
        # reference would silently give them all the last block's weights.
        stand_in.attn = dit.blocks[index].attn
        stand_in.original = dit.blocks[index].attn.forward
        patcher.add_object_patch(f"diffusion_model.blocks.{index}.attn.forward", stand_in)
    return len(blocks)


def savings(
    blocks: list[int], layers: int, attention_share: float, mode: str, video_fraction: float = 0.86
) -> float:
    """Fraction of the forward removed. Blocks are ~99.5% of it (measured in the profiler).

    `attention_only` no longer removes a whole block's attention: the qkv projection and the
    fused RMSNorm+rope still run at full length (k and v are needed for every row), and only the
    attention matmul and the output projection shrink to the prefix. So a skipped block still
    costs roughly `(1 - video_fraction)` of its attention plus all of its qkv, against nothing at
    all under the old whole-sequence zero — the price of not destroying the audio.
    """
    if not blocks or layers <= 0:
        return 0.0
    if mode == "attention_only":
        # qkv is ~30% of the linear work per token and is not avoidable; out_proj (~10%) shrinks
        # with the queries, as does the attention matmul itself.
        linear = 1.0 - attention_share
        remaining = attention_share * (1.0 - video_fraction) + linear * (
            0.30 + 0.10 * (1.0 - video_fraction) + 0.60
        )
        per_block = 1.0 - remaining
    else:
        per_block = 1.0
    return len(blocks) / layers * per_block * 0.995
