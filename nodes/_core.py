"""The seam onto ComfyUI's own MiniMax H3 helpers, and the shape rules the whole pack obeys.

Latent geometry is **borrowed, never reimplemented**. `temporal_shape` snaps a frame count onto
the model's `17k+5` grid and derives the audio latent length from it; `adapt_canvas` picks a
768-short-edge canvas under a pixel cap, each axis rounded to 32. Copying that arithmetic here
would work right up until a ComfyUI release adjusted it, and the failure would be a silently
mis-shaped latent rather than an error — so this module reaches for core's copy and keeps the
coupling in one visible place.

Imported lazily, because `comfy_extras.nodes_minimax_h3` only exists on builds that have H3 at
all (ComfyUI 0.30.0, the `CORE-375` merge). Importing it at module scope would turn "this pack
needs a newer ComfyUI" into "this pack fails to load", which tells the user nothing.

**There is a second copy of this arithmetic and it is deliberate.** `web/lib/canvas.js`
reimplements the canvas fit and the frame grid in TypeScript, because the picker has to show the
canvas it will produce *while you drag it*, and a widget cannot call Python. `tests/test_canvas.py`
pins the Python side against core's own functions and prints the table the TS side is written to
match. Two copies with one test is the price of a live picker.
"""

from __future__ import annotations

MODULE = "comfy_extras.nodes_minimax_h3"

_MISSING = (
    "Nynxz H3 needs ComfyUI's own MiniMax H3 support, and this build does not have it "
    f"({MODULE} could not be imported). H3 landed in ComfyUI 0.30.0 — update ComfyUI, or use "
    "the stock MiniMax H3 nodes if they are present under a different name."
)


def core():
    """The core H3 node module, or a ValueError that says which upgrade is missing."""
    try:
        import comfy_extras.nodes_minimax_h3 as module
    except Exception as exc:
        raise ValueError(_MISSING) from exc
    return module


def empty_latent(width: int, height: int, length: int):
    """`({"samples": NestedTensor(video, audio)}, frame_count)` — the AV latent to sample into."""
    return core()._empty_av_latent(width, height, length)


def resize(image, width: int, height: int, crop: str = "disabled"):
    """`[B, H, W, C] -> [B, height, width, 3]` through core's lanczos path."""
    return core()._resize(image, width, height, crop)


def adapt_canvas(width: int, height: int) -> tuple[int, int]:
    """A canvas for an aspect ratio: 768 short edge, capped by area, each axis rounded to 32."""
    return core().adapt_canvas(width, height)


def encode_ref_audio(audio_vae, audio):
    """`(latent [1, 32, 2, T], T)` — resampled to the audio VAE's rate first."""
    return core().MiniMaxH3ReferenceToVideo._encode_ref_audio(audio_vae, audio)


def temporal_shape(length: int) -> tuple[int, int, int]:
    """`(frame_count, latent_t, audio_t)` for a requested length.

    `frame_count` is `length` snapped **up** onto the model's `17k+5` grid, which is why the
    length a graph asks for and the length it gets need not be the same number — and why
    H3 Extras reports both.
    """
    return core().temporal_shape(length)


#: How much resolution a reference video is fed in at, as a per-axis factor.
#:
#: This is a pure cost dial and it is free of alignment consequences, which is not obvious and is
#: the reason it can exist at all. H3's spatial rope is **area-normalized**
#: (`comfy/ldm/minimax/model.py:80`): each axis spans `[(1-ratio)/2, (1+ratio)/2) * 32` where
#: `ratio = dim / sqrt(h*w)` — a function of aspect ratio alone. A half-resolution reference
#: therefore occupies the *identical* coordinate box as the full-resolution one and stays
#: registered to the target row for row. Only the sampling density changes.
REFERENCE_DETAIL = {"full": 1.0, "half": 0.5, "quarter": 0.25}


def scale_canvas(width: int, height: int, factor: float, multiple: int = 32) -> tuple[int, int]:
    """Scale a canvas by `factor`, both axes landing back on the model's grid.

    **Snapping each axis independently is wrong here, and the failure is quiet.** Both axes must be
    multiples of 32 (the VAE's /16 and the DiT's 2x2 patch), and at small sizes that grid is coarse:
    1344 x 0.25 is 336, which snaps to 320 and drags the aspect ratio from 1.750 to 1.667 — a 4.8%
    move. For a *reference* that is not cosmetic. H3 registers a reference to its target through
    rope coordinates spanning `ratio * 32` where `ratio = dim / sqrt(h*w)`, so aspect ratio IS the
    registration, and a reference that drifts is one the model reads as a differently-shaped scene.

    So this searches one grid step either way on both axes and takes the candidate whose aspect is
    closest to the original, breaking ties on area. It costs nine comparisons and typically finds
    something under 1% where naive rounding gives 5%. Preserving the aspect can mean landing a
    little above or below the requested area; that is the right way round to trade, since the area
    is a cost preference and the aspect is a correctness constraint.
    """
    aspect = width / height
    want_area = (width * factor) * (height * factor)
    base_w = max(1, round(width * factor / multiple))
    base_h = max(1, round(height * factor / multiple))
    best = None
    for dw in (-1, 0, 1):
        for dh in (-1, 0, 1):
            w = max(1, base_w + dw) * multiple
            h = max(1, base_h + dh) * multiple
            score = (
                abs(w / h - aspect) / aspect,
                abs(w * h - want_area) / max(1.0, want_area),
            )
            if best is None or score < best[0]:
                best = (score, (w, h))
    return best[1]


def resize_latent(latent, latent_w: int, latent_h: int):
    """Resample a video latent's spatial axes. `common_upscale` handles 5D and restores the shape.

    Downsampling a latent rather than the pixels is an approximation — but a smaller one than the
    VAE round trip it replaces, and it keeps the no-re-encode path that supplying a latent exists
    for. Latents are spatially local and near-linear in pixels, which is what makes resampling one
    across scale meaningful (and, separately, what makes *blending* two of them ghost).
    """
    import comfy.utils

    if (latent.shape[3], latent.shape[4]) == (latent_h, latent_w):
        return latent
    return comfy.utils.common_upscale(latent, latent_w, latent_h, "bicubic", "disabled")


def video_latent_t(frame_count: int) -> int:
    """Latent frames for a pixel frame count already on the `17k+5` grid."""
    return core().video_latent_t(frame_count)


def frames_for_latent_t(latent_t: int) -> int:
    """Inverse of `video_latent_t`: the pixel frame count a video latent came from.

    `video_latent_t` is `((n - 5) // 17) * 5 + 2`, which is exactly invertible on the `17k+5`
    grid — every legal latent length is `5k + 2`. Needed because a *supplied* reference latent
    is authoritative about how long the clip is, and its pixel frames have to be trimmed to
    agree; the presentation Qwen reads would otherwise describe a different span than the
    condition rows the DiT gets.
    """
    if latent_t < 2 or (latent_t - 2) % 5 != 0:
        raise ValueError(
            f"{latent_t} is not a length an H3 video latent can have — they run 2, 7, 12, 17, "
            "... (5k+2), one per 17 pixel frames plus the leading one"
        )
    return ((latent_t - 2) // 5) * 17 + 5


def constants() -> dict:
    """The handful of numbers the pipeline's shape rules are defined by."""
    module = core()
    return {
        "canvas_multiple": module.CANVAS_MULTIPLE,
        "base_short_edge": module.BASE_SHORT_EDGE,
        "max_pixels": module.MAX_PIXELS,
        "ref_image_short_edge": module.REF_IMAGE_SHORT_EDGE,
        "fps": module.FPS,
        "audio_latent_fps": module.AUDIO_LATENT_FPS,
    }
