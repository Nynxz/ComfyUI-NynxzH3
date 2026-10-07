"""H3 Mood Board — several images collapsed into ONE <Picture>, blended in token space."""

from __future__ import annotations

from comfy_api.latest import io

from ._base import H3Node
from ._blend import ALPHA_MODES, BLEND_MODES, DEFAULT_ALPHA_MODE, DEFAULT_BLEND
from ._refs import SEMANTIC, H3Refs, board_count


def weights_from(text, count):
    """Parse "1, 0.5, 2" into per-image weights. Blank, short or unparseable means equal."""
    parts = [p for p in text.replace(",", " ").split() if p]
    if not parts:
        return None
    try:
        values = [max(0.0, float(p)) for p in parts]
    except ValueError as error:
        raise ValueError(
            f"H3 Mood Board could not read weights {text!r}: expected numbers separated by "
            "commas or spaces, one per image."
        ) from error
    if len(values) != count:
        raise ValueError(
            f"H3 Mood Board got {len(values)} weights for {count} images. Give one per image, "
            "or leave it blank for an equal blend."
        )
    return values


class NynxzH3MoodBoard(H3Node):
    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3.MoodBoard",
            display_name="H3 Mood Board",
            description="Several images that share a LOOK but not a subject, collapsed into one "
            "<Picture>. Each is encoded by the vision tower separately, then their token spans "
            "are blended position by position and the spare brackets are cut out — so the model "
            "receives what the images have in common rather than N competing references. "
            "'average' reinforces where they agree and cancels where they differ; 'mosaic' takes "
            "each grid cell whole from one source. Chains like an H3 Reference.",
            inputs=[
                io.Autogrow.Input(
                    "images",
                    template=io.Autogrow.TemplateNames(
                        io.Image.Input("image"),
                        names=[f"image_{i}" for i in range(1, 10)],
                        min=1,
                    ),
                    tooltip="Images on the board. They are blended, not laid side by side.",
                ),
                io.Combo.Input(
                    "blend",
                    options=BLEND_MODES,
                    default=DEFAULT_BLEND,
                    tooltip="'average' — a weighted mean at every position, so agreement "
                    "reinforces and disagreement partly cancels; the residual is the shared "
                    "look. 'mosaic' — each cell taken whole from one source, keeping local "
                    "coherence instead of averaging it away.",
                ),
                io.Int.Input(
                    "resolution",
                    default=384,
                    min=64,
                    max=1024,
                    step=32,
                    tooltip="Every board image is fitted to this square so their token grids "
                    "match — which is what makes them blendable at all. It is also the board's "
                    "whole cost: one vision token per 32x32 pixels, so 384 is 144 tokens and 512 "
                    "is 256. Lower reads as mood, higher starts reproducing detail.",
                ),
                io.String.Input(
                    "weights",
                    default="",
                    tooltip="Optional per-image bias, e.g. '1, 0.5, 2' — one per image. Blank is "
                    "an equal blend. NORMALISED, so raising all of them changes nothing. Under "
                    "'average' a weight is how much of the mix a source carries; under 'mosaic', "
                    "which never mixes, it is how many CELLS it claims.",
                ),
                io.Combo.Input(
                    "fit",
                    options=["cover", "stretch"],
                    default="cover",
                    tooltip="How each image reaches the square grid: 'cover' centre-crops and "
                    "keeps proportions, 'stretch' squashes the whole frame in.",
                ),
                io.Int.Input(
                    "block_size",
                    default=1,
                    min=1,
                    max=16,
                    optional=True,
                    tooltip="mosaic only: the checkerboard cell in grid units. 1 alternates every "
                    "token; larger keeps bigger contiguous patches of one source.",
                ),
                io.Float.Input(
                    "feather",
                    default=0.0,
                    min=0.0,
                    max=8.0,
                    step=0.1,
                    optional=True,
                    tooltip="mosaic only: blur the ownership field across the grid so cells meet "
                    "instead of butting together. Only weights are smoothed, never the tokens.",
                ),
                io.Float.Input(
                    "jitter",
                    default=0.0,
                    min=0.0,
                    max=1.0,
                    step=0.05,
                    optional=True,
                    tooltip="mosaic only: the chance a cell goes to a different source than the "
                    "pattern says, breaking up the regular checkerboard.",
                ),
                io.Int.Input(
                    "seed",
                    default=0,
                    min=0,
                    max=0xFFFFFFFF,
                    optional=True,
                    tooltip="Seeds the jitter, so a board is reproducible.",
                ),
                io.Combo.Input(
                    "alpha_mode",
                    options=ALPHA_MODES,
                    default=DEFAULT_ALPHA_MODE,
                    optional=True,
                    tooltip="'exclude' keeps a transparent area out of the blend, so its share "
                    "goes to whoever is still opaque there — take the sky and the grade from a "
                    "photo and leave its building behind. 'ignore' blends the whole frame.",
                ),
                io.String.Input(
                    "label",
                    default="",
                    optional=True,
                    tooltip="A name for the board, used in errors and in the picture map.",
                ),
                H3Refs.Input(
                    "references",
                    optional=True,
                    tooltip="Chain another H3 Reference or Mood Board in here.",
                ),
            ],
            outputs=[H3Refs.Output(display_name="references")],
            is_experimental=True,
        )

    @classmethod
    def execute(
        cls,
        images: io.Autogrow.Type = None,
        blend=DEFAULT_BLEND,
        resolution=384,
        weights="",
        fit="cover",
        block_size=1,
        feather=0.0,
        jitter=0.0,
        seed=0,
        alpha_mode=DEFAULT_ALPHA_MODE,
        label="",
        references=None,
    ):
        images = images or {}
        collected = [
            images[name]
            for name in sorted(images, key=lambda n: int(n.rsplit("_", 1)[-1]))
            if images[name] is not None
        ]
        if not collected:
            raise ValueError("H3 Mood Board needs at least one image.")

        chained = list(references or [])
        # The board dict is shared by every entry this node appends, so its identity IS the
        # group — no counter to keep in step, and two boards can never collide.
        name = label.strip() or f"board {board_count(chained) + 1}"
        board = {
            "blend": blend,
            "resolution": int(resolution),
            "fit": fit,
            "weights": weights_from(weights, len(collected)),
            "block_size": int(block_size),
            "feather": float(feather),
            "jitter": float(jitter),
            "seed": int(seed),
            "alpha_mode": alpha_mode,
            "label": name,
        }
        for index, image in enumerate(collected):
            chained.append(
                {
                    "image": image,
                    "role": SEMANTIC,  # a board is a look, never a latent
                    "label": f"{name}[{index + 1}]",
                    "vision_size": 0,  # the board's own resolution governs
                    "board": board,
                }
            )
        return io.NodeOutput(chained)
