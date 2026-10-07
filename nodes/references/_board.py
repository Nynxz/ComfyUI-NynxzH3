"""Vision-token budget arithmetic — kept free of torch so it can be checked on its own.

The point of a board is the TOKEN BUDGET. Qwen3-VL patches at 16px and merges 2x2, so an image
costs `(w/32) * (h/32)` vision tokens and nothing downscales it on the way in (`max_pixels` is
12.8M, far above anything a reference reaches). One reference at a generation-sized 1344x768 is
1008 tokens of spatially-resolved, DeepStack-augmented encoding — enough to reproduce the image
closely, which is why a latent-free reference can still transfer almost exactly.

A board spends ONE budget on N images. Four images on a 512x512 board are 256 tokens total, 64
each: enough for palette, texture and composition, too few to rebuild a face. That is the whole
mechanism — there is no magic beyond arithmetic on the patch grid.
"""

from __future__ import annotations

import math

#: Qwen3-VL: 16px patches, merged 2x2. One vision token per 32x32 pixels.
PIXELS_PER_TOKEN_EDGE = 32


def tokens(width, height, edge=PIXELS_PER_TOKEN_EDGE):
    """Vision tokens an image of this size costs the text encoder."""
    return (int(width) // edge) * (int(height) // edge)


def fit_to_budget(width, height, size, multiple=PIXELS_PER_TOKEN_EDGE):
    """Scale (width, height) down to about a `size` x `size` area, aspect kept, snapped to grid.

    A cap, never an enlargement: upscaling would buy tokens without buying information.
    """
    scale = min(1.0, math.sqrt((size * size) / (width * height)))
    return (
        max(multiple, round(width * scale / multiple) * multiple),
        max(multiple, round(height * scale / multiple) * multiple),
    )
