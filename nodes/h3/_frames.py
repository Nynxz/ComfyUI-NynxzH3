"""Which latent tokens a pixel frame is made of, and decoding only those.

The H3 video VAE does not decode a clip in one shot. `decode_temporal` walks the latent in
`tokens_chunk_size` (5) token steps, hands each step plus `token_overlap` (2) lookahead tokens to
the ViT decoder, throws `frame_pre_padding` (3) frames off the front of every decoded part, and
cross-fades consecutive chunks over `frame_overlap` (5) frames. A 124-frame clip is 7 chunk
decodes of 7 tokens each, not one decode of 37.

The consequence this module exists for: **an output frame depends on at most two of those chunks,
and a chunk reads at most 7 latent tokens.** So "give me frame 37" costs one chunk decode instead
of seven, and "give me frame 3" costs two (it lands in a cross-fade). That is the difference
between decoding a whole video and decoding the one frame you wanted — which is what using a video
model as an edit model needs.

It is also *exact*, not an approximation, and the distinction matters. Slicing one latent frame out
and decoding it alone gives a different picture: the ViT decoder attends across the whole window it
is given and its rope coordinates restart at zero, so a lone token decodes as if it were the start
of a clip. `frame_plan` instead walks the same loop `decode_temporal` walks and records where every
output frame came from, so the frames handed back are bit-for-bit the ones a full decode would have
written, cross-fade included.

Every constant is read off the VAE instance rather than hardcoded — a checkpoint with a different
`clip_length` or `time_down` re-derives its own plan. `tests/test_frames.py` pins the plan against
the model's own `_decode_temporal_frame_plan` and the decode against a real `decode_temporal`, so
if core's chunking ever moves, a test says so rather than a silently wrong frame.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import torch

#: The VAE class this module understands, matched by name so importing it is never required.
VAE_CLASS = "MiniMaxH3VideoVAE"


@dataclass(frozen=True)
class Config:
    """The chunking constants, read off a loaded VAE."""

    ratio_t: int
    clip_length: int
    token_drop: int
    chunk_size: int
    token_overlap: int
    pre_padding: int
    frame_overlap: int

    @property
    def chunk_dec(self) -> int:
        """Frames one decoded chunk contributes before the trailing overlap part."""
        return self.chunk_size * self.ratio_t

    @property
    def splits(self) -> int:
        """Parts a decoded chunk is cut into: 2 when tokens are dropped, else 1."""
        return int(self.token_drop > 0) + 1


def config(fsm) -> Config:
    return Config(
        ratio_t=int(fsm.vae_ratio_t),
        clip_length=int(fsm.clip_length),
        token_drop=int(fsm.token_drop),
        chunk_size=int(fsm.tokens_chunk_size),
        token_overlap=int(fsm.token_overlap),
        pre_padding=int(fsm.frame_pre_padding),
        frame_overlap=int(fsm.frame_overlap),
    )


def is_h3_vae(vae) -> bool:
    return type(getattr(vae, "first_stage_model", None)).__name__ == VAE_CLASS


@dataclass
class Part:
    """A contiguous run of output frames, and where `decode_temporal` copied it from."""

    chunk: int
    """Index of the token chunk whose decode produced these frames."""
    split: int
    """0 for the chunk's main part, 1 for its trailing overlap part."""
    src_start: int
    """Frame index of the first of them inside that chunk's decoded tensor."""
    count: int
    out_start: int = 0
    blend_from: Part | None = None
    """The previous chunk's overlap part, when this one cross-fades in over it."""
    blend_extent: int = 0


@dataclass
class Plan:
    """Where every frame of a decoded clip comes from."""

    cfg: Config
    output_frames: int
    pad_tokens: int
    """Tokens `decode_temporal` appends (by repeating the last one) before it starts."""
    padded_len: int
    windows: list[tuple[int, int]]
    """Token window `[start, stop)` each chunk decodes."""
    parts: list[Part] = field(default_factory=list)
    single: bool = False
    """The `z.shape[2] == 1` path, which bypasses chunking entirely."""

    @property
    def chunks(self) -> int:
        return len(self.windows)


def _pad_frames(cfg: Config, z_len: int, pad_tokens: int) -> int:
    """Mirror of `MiniMaxH3VideoVAE._decode_temporal_pad_frames`."""
    if pad_tokens <= 0:
        return 0
    intra_tail = cfg.clip_length % cfg.ratio_t
    if intra_tail == 0:
        return pad_tokens * cfg.ratio_t

    before = z_len - pad_tokens
    return sum(
        intra_tail if (before + k) % cfg.chunk_size == 0 else cfg.ratio_t for k in range(pad_tokens)
    )


def _total_frames(cfg: Config, z_len: int, num_chunks: int, pad_tokens: int) -> int:
    """Mirror of `MiniMaxH3VideoVAE._decode_temporal_frame_plan`."""
    total = 0
    final_overlap = 0
    for i in range(num_chunks):
        t_start = i * cfg.chunk_size
        t_end = t_start + cfg.chunk_size + cfg.token_overlap
        clip_tokens = max(0, min(t_end, z_len) - min(t_start, z_len))
        clip_frames = clip_tokens * cfg.ratio_t

        for j in range(cfg.splits):
            f_start = j * cfg.chunk_dec
            f_end = min(f_start + cfg.chunk_dec, clip_frames)
            frames = max(0, f_end - f_start - cfg.pre_padding)
            if j == 0:
                total += frames
            else:
                final_overlap = frames

    return total + final_overlap - _pad_frames(cfg, z_len, pad_tokens)


def frame_plan(fsm, z_len: int) -> Plan:
    """Where each of a `z_len`-token latent's output frames comes from.

    A transcription of `decode_temporal` with the tensors taken out: same chunk loop, same split
    into a main part and a trailing overlap part, same cross-fade, and the same truncation against
    the pre-computed output length (core allocates `dec` once and stops copying when it is full,
    which silently drops the tail of short clips — `latent_t == 2` decodes 22 frames and keeps 5).
    """
    cfg = config(fsm)

    if z_len <= 1:
        # decode() short-circuits a single token through _adaptive_decode and keeps only the last
        # of the ratio_t frames it produces — the same frame the encoder's single-image path made.
        part = Part(chunk=0, split=0, src_start=cfg.ratio_t - 1, count=1, out_start=0)
        return Plan(
            cfg=cfg,
            output_frames=1,
            pad_tokens=0,
            padded_len=max(1, z_len),
            windows=[(0, max(1, z_len))],
            parts=[part],
            single=True,
        )

    pseudo = z_len + cfg.token_drop
    pad_tokens = 0
    remainder = pseudo % cfg.chunk_size
    if remainder != 0:
        pad_tokens = cfg.chunk_size - remainder
        pseudo += pad_tokens

    num_chunks = pseudo // cfg.chunk_size - int(cfg.token_drop > 0)
    if num_chunks < 1:
        pad_tokens += cfg.chunk_size
        num_chunks += 1

    padded_len = z_len + pad_tokens
    output_frames = _total_frames(cfg, padded_len, num_chunks, pad_tokens)

    windows = []
    parts: list[Part] = []
    write_pos = 0
    pending: Part | None = None

    def write(part: Part) -> None:
        """Mirror of `write_part`: clamp against the allocated length, keep what fits."""
        nonlocal write_pos
        if part.count <= 0:
            return
        copied = min(part.count, max(0, output_frames - write_pos))
        if copied <= 0:
            return
        part.out_start = write_pos
        part.count = copied
        parts.append(part)
        write_pos += copied

    for i in range(num_chunks):
        t_start = i * cfg.chunk_size
        t_end = min(t_start + cfg.chunk_size + cfg.token_overlap, padded_len)
        windows.append((min(t_start, padded_len), t_end))
        clip_frames = max(0, t_end - min(t_start, padded_len)) * cfg.ratio_t

        for j in range(cfg.splits):
            f_start = j * cfg.chunk_dec
            f_end = min(f_start + cfg.chunk_dec, clip_frames)
            part = Part(
                chunk=i,
                split=j,
                src_start=f_start + cfg.pre_padding,
                count=max(0, f_end - f_start - cfg.pre_padding),
            )
            if j == 0:
                if pending is not None:
                    # blend() cross-fades over min(len(a), len(b), frame_overlap) frames, measured
                    # before write() truncates anything — the overlap part is never truncated.
                    part.blend_extent = min(pending.count, part.count, cfg.frame_overlap)
                    part.blend_from = pending if part.blend_extent > 0 else None
                    pending = None
                write(part)
            else:
                pending = part

        if i == num_chunks - 1 and pending is not None:
            write(pending)
            pending = None

    return Plan(
        cfg=cfg,
        output_frames=output_frames,
        pad_tokens=pad_tokens,
        padded_len=padded_len,
        windows=windows,
        parts=parts,
    )


def sources(plan: Plan, index: int) -> list[tuple[int, int, float]]:
    """`(chunk, frame index within that chunk's decode, weight)` for one output frame.

    One entry normally, two inside a cross-fade. Negative indices count from the end.
    """
    if index < 0:
        index += plan.output_frames
    if not 0 <= index < plan.output_frames:
        raise IndexError(
            f"frame {index} is outside this latent's {plan.output_frames} decoded frames"
        )

    for part in plan.parts:
        offset = index - part.out_start
        if not 0 <= offset < part.count:
            continue
        if part.blend_from is not None and offset < part.blend_extent:
            prev = part.blend_from
            weight = offset / part.blend_extent
            # blend() reads a's LAST blend_extent frames against b's first.
            return [
                (
                    prev.chunk,
                    prev.src_start + prev.count - part.blend_extent + offset,
                    1.0 - weight,
                ),
                (part.chunk, part.src_start + offset, weight),
            ]
        return [(part.chunk, part.src_start + offset, 1.0)]

    raise IndexError(f"frame {index} maps to no decoded part (plan covers {plan.output_frames})")


def window_tokens(plan: Plan, indices) -> int:
    """The largest token window any of `indices` needs decoded — for a memory estimate."""
    needed = {chunk for index in indices for chunk, _, _ in sources(plan, index)}
    return max((plan.windows[c][1] - plan.windows[c][0] for c in needed), default=0)


def decode_frames(fsm, z: torch.Tensor, indices) -> torch.Tensor:
    """Decode exactly `indices` (output frame numbers) out of a normalized video latent.

    `z` is `[B, 24, T_lat, H, W]` on the VAE's device and dtype; the result is
    `[B, 3, len(indices), H*16, W*16]` in **[0, 1]** — the same range and layout
    `MiniMaxH3VideoVAE.decode` returns, before ComfyUI's `process_output`.

    **The range is [0, 1] and not the usual [-1, 1], and that is not an oversight.** Most VAEs
    hand back [-1, 1] and let `VAE.process_output` map it (`comfy/sd.py:501` — `add_(1).div_(2)`).
    H3's does not: it finalizes straight to [0, 1] while streaming chunks out, so core sets
    `process_output = lambda image: image` for this VAE alone (`comfy/sd.py:959`). Returning the
    conventional [-1, 1] here therefore reaches `decode_images` with nothing to undo it and lands
    in an IMAGE as roughly `2x - 1` of the right picture — everything under mid-grey clipping to
    black. `tests/test_frames.py` asserts equality against a full `vae.decode`, which is what
    catches it; that test is the reason this line is one call shorter than it looks like it should
    be.

    Chunks are decoded once each however many frames come out of them, and only the requested
    frames are retained, so asking for a filmstrip of 6 frames spread over a clip costs 6 chunk
    decodes rather than 6 full decodes.
    """
    plan = frame_plan(fsm, z.shape[2])
    resolved = [sources(plan, int(i)) for i in indices]
    if not resolved:
        raise ValueError("decode_frames needs at least one frame index")

    wanted: dict[int, set[int]] = {}
    for entry in resolved:
        for chunk, frame, _ in entry:
            wanted.setdefault(chunk, set()).add(frame)

    if plan.pad_tokens > 0:
        z = torch.cat([z, z[:, :, -1:].repeat(1, 1, plan.pad_tokens, 1, 1)], dim=2)

    latents_mean = fsm.latents_mean.view(1, -1, 1, 1, 1).to(z)
    latents_std = fsm.latents_std.view(1, -1, 1, 1, 1).to(z)

    gathered: dict[tuple[int, int], torch.Tensor] = {}
    for chunk in sorted(wanted):
        start, stop = plan.windows[chunk]
        clip_z = z[:, :, start:stop] * latents_std + latents_mean
        clip_dec = fsm._adaptive_decode(clip_z)
        for frame in sorted(wanted[chunk]):
            gathered[(chunk, frame)] = clip_dec[:, :, frame : frame + 1].clone()
        del clip_dec, clip_z

    frames = []
    for entry in resolved:
        acc = None
        for chunk, frame, weight in entry:
            piece = gathered[(chunk, frame)] * weight
            acc = piece if acc is None else acc.add_(piece)
        frames.append(acc)

    # `_finalize_pixels`, inlined: the VAE's own last step, and where it stops.
    dec = torch.cat(frames, dim=2).float()
    dec.mul_(fsm.pixel_std.to(dec)).add_(fsm.pixel_mean.to(dec)).clamp_(0.0, 1.0)
    return dec
