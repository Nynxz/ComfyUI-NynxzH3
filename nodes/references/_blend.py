"""Collapsing several style images into one reference — extracting what they have in common.

Ported from `ComfyUI-QI21Remix/nodes/_moodboard.py`, where it blends Qwen Image 2.1 vision spans.
The engine is model-agnostic — it takes `[1, tokens, dim]` spans and returns one of the same
shape — so the only H3-specific part is finding the spans, which lives in `_spans.py`.

A mood board is N images that share a *look* but not a *subject*. Wired as N separate references,
each gets its own `<Picture i>` and the model is left to average them itself. Collapsing them into
one picture computes that average explicitly, costs one bracket instead of N, and gives the prompt
a single ordinal to address.

The vision tower encodes each image independently (`preprocess_embed` runs per image), so their
token spans are directly comparable — and a shared resolution gives them an identical token grid,
which is what makes them blendable at all.

    average    weighted mean of the sources at each position. Where the images agree the
               vectors reinforce; where they differ they partly cancel and the residual is
               what survives.
    mosaic     each grid cell taken whole from one source, checkerboard-style. Keeps each
               image's local coherence instead of averaging it away — a collage rather than
               a shared look.

Per-image weights bias both, but they mean different things. In `average` a weight is how much of
the mix a source carries. In `mosaic`, which never mixes, it is how many CELLS the source claims.
They are NORMALISED and so purely relative: raising every one of them changes nothing.

**Magnitude differs from the 2.1 case and is NOT settled here.** On 2.1 only direction reaches the
model — `txt_in` opens with an RMSNorm, so cancellation's effect on a token's length is erased
before the DiT sees it. H3 instead runs `condition_proj` (a Linear WITH bias, so not
scale-homogeneous) and then a token refiner that ends in an RMSNorm. Magnitude is therefore not
erased at the door, but it IS normalised at the refiner's output, so whatever survives does so
indirectly, through the refiner's own attention. That is a structural reading of the graph, not a
measurement — do not assume weights behave here exactly as they do on 2.1.
"""

from __future__ import annotations

import math

import torch
import torch.nn.functional as F

BLEND_MODES = ["average", "mosaic"]
DEFAULT_BLEND = "average"

#: What a board image's alpha means. "exclude" keeps a transparent area out of the blend, so its
#: share goes to whoever is still opaque there — the way to take only the sky and the grade from
#: a photo and leave its building behind. "ignore" blends the whole frame.
ALPHA_MODES = ["exclude", "ignore"]
DEFAULT_ALPHA_MODE = "exclude"


def _normalised(weights, count, device, dtype):
    if not weights or len(weights) != count:
        weights = [1.0] * count
    tensor = torch.tensor([max(0.0, float(w)) for w in weights], device=device, dtype=dtype)
    if float(tensor.sum()) <= 0.0:
        tensor = torch.ones(count, device=device, dtype=dtype)
    return tensor / tensor.sum()


def coverage_field(alphas, grid):
    """Per-source opacity on the token grid, `[sources, tokens]`, or None if nothing is masked.

    Each source's alpha is area-averaged down to one value per token cell, so a cell a cut-out
    only half covers comes out at 0.5 and the mask edge lands softly at grid resolution. A source
    with no alpha covers its whole frame.
    """
    if not any(alpha is not None for alpha in alphas):
        return None
    columns, rows = grid
    out = []
    for alpha in alphas:
        if alpha is None:
            out.append(torch.ones(rows * columns))
            continue
        cell = F.adaptive_avg_pool2d(alpha.movedim(-1, 1).float(), (rows, columns))
        out.append(cell.reshape(rows * columns).clamp(0.0, 1.0))
    return torch.stack(out)


def _mosaic_field(count, columns, rows, block_size, weights, jitter, seed, device):
    """A one-hot `[sources, tokens]` field: which single source owns each cell.

    Strength biases how many CELLS a source claims rather than how loud its tokens are, because
    mosaic never mixes. The rotation table is round-robin, not grouped — grouping would collapse
    the checkerboard into solid blocks — and with equal strengths it reproduces `pattern % count`
    exactly.
    """
    block_size = max(1, int(block_size))
    row_index = torch.arange(rows, device=device).unsqueeze(1) // block_size
    column_index = torch.arange(columns, device=device).unsqueeze(0) // block_size
    pattern = (row_index + column_index).reshape(-1)

    shares = [int(n) for n in (weights * (4 * count)).round().clamp(min=1)]
    table, remaining = [], list(shares)
    while sum(remaining) > 0:
        for source in range(count):
            if remaining[source] > 0:
                table.append(source)
                remaining[source] -= 1
    lookup = torch.tensor(table, device=device)
    pick = lookup[pattern % len(lookup)]

    if jitter > 0.0 and count > 1:
        # Built on the CPU so a seed picks the same cells whatever device the encode ran on.
        generator = torch.Generator().manual_seed(int(seed))
        roll = torch.rand(pick.shape[0], generator=generator).to(device)
        step = (1 + torch.randint(0, count - 1, pick.shape, generator=generator)).to(device)
        pick = torch.where(roll < jitter, (pick + step) % count, pick)

    field = torch.zeros(count, pick.shape[0], device=device)
    field[pick, torch.arange(pick.shape[0], device=device)] = 1.0
    return field


def _feathered(field, columns, rows, sigma):
    """Blur the weight field across the grid, so mosaic cells meet instead of butting together.

    Only the WEIGHTS are smoothed, never the tokens: position p still ends up a mix of the
    sources at p. Averaging tokens across positions is the operation that produces non-states.
    """
    if sigma <= 0.0:
        return field
    radius = max(1, math.ceil(sigma * 2))
    offsets = torch.arange(-radius, radius + 1, dtype=torch.float32, device=field.device)
    kernel = torch.exp(-(offsets**2) / (2.0 * sigma * sigma))
    kernel = kernel / kernel.sum()

    plane = field.reshape(-1, 1, rows, columns)
    plane = F.conv2d(
        F.pad(plane, (radius, radius, 0, 0), mode="replicate"), kernel.view(1, 1, 1, -1)
    )
    plane = F.conv2d(
        F.pad(plane, (0, 0, radius, radius), mode="replicate"), kernel.view(1, 1, -1, 1)
    )
    return plane.reshape(field.shape)


def _covered(field, coverage):
    """Fold alpha in: a transparent source stops contributing and its share goes to the rest.

    Where NOTHING covers a cell, the ungated field is kept rather than leaving the cell dead —
    a hole every source masked out should still hold something.
    """
    if coverage is None:
        return field
    scaled = field * coverage.to(field.device, field.dtype)
    total = scaled.sum(dim=0, keepdim=True)
    return torch.where(total <= 1e-6, field, scaled)


def _field(count, grid, mode, weights, block_size, feather, jitter, seed, coverage):
    """`[sources, tokens]`: who contributes what, per position. Normalised per token."""
    columns, rows = grid
    tokens = columns * rows
    if mode == "mosaic":
        field = _mosaic_field(
            count, columns, rows, block_size, weights, jitter, seed, weights.device
        )
        field = _feathered(field, columns, rows, feather)
    else:
        field = weights[:, None].expand(count, tokens).clone()
    field = _covered(field, coverage)
    return field / field.sum(dim=0, keepdim=True).clamp_min(1e-6)


def blend(
    spans,
    weights=None,
    mode=DEFAULT_BLEND,
    grid=None,
    block_size=1,
    feather=0.0,
    jitter=0.0,
    seed=0,
    coverage=None,
):
    """Combine several `[1, tokens, dim]` vision spans into one of the same shape.

    `grid` is `(columns, rows)`. `coverage` is the alpha field from `coverage_field`, or None.
    """
    if not spans:
        raise ValueError("A mood board needs at least one image.")
    if any(span.shape != spans[0].shape for span in spans[1:]):
        raise ValueError(
            "Mood board images produced different token counts, so they cannot be blended. Give "
            "every image on one board the same resolution — the token grid has to match."
        )
    if len(spans) == 1 and coverage is None:
        return spans[0]
    if mode not in BLEND_MODES:
        raise ValueError(f"Unknown mood board blend mode: {mode}")

    stacked = torch.stack(spans, dim=0)  # [sources, 1, tokens, dim]
    normalised = _normalised(weights, len(spans), stacked.device, stacked.dtype)
    if grid is None:
        grid = (stacked.shape[2], 1)
    if grid[0] * grid[1] != stacked.shape[2]:
        raise ValueError(
            f"Mood board grid {grid[0]}x{grid[1]} does not match {stacked.shape[2]} tokens."
        )

    field = _field(len(spans), grid, mode, normalised, block_size, feather, jitter, seed, coverage)
    fused = (stacked * field[:, None, :, None]).sum(0)  # [1, tokens, dim]

    return fused
