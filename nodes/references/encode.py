"""H3 Reference to Video — core's ref2va node, but honouring each reference's role."""

from __future__ import annotations

import math

import node_helpers
from comfy_api.latest import io

from ._base import H3Node
from ._blend import blend as blend_spans
from ._blend import coverage_field
from ._board import PIXELS_PER_TOKEN_EDGE, fit_to_budget
from ._board import tokens as vision_tokens
from ._refs import REFERENCE, H3Refs, board_runs, images_of, ordered
from ._spans import TAGS_KEY, cut, interior, read_span, tags_of, vision_runs, write_span


def _core():
    """Core's own sizing and latent helpers, imported rather than copied so they cannot drift.

    They are private names in `comfy_extras`, so a version that moves them is caught here with
    something readable instead of an ImportError at load time.
    """
    try:
        from comfy_extras.nodes_minimax_h3 import (
            CANVAS_MULTIPLE,
            REF_IMAGE_SHORT_EDGE,
            _empty_av_latent,
            _resize,
        )
    except ImportError as error:  # pragma: no cover - depends on the installed ComfyUI
        raise ValueError(
            "This node builds on ComfyUI's MiniMax H3 nodes and could not import their sizing "
            f"helpers ({error}). Update ComfyUI, or use core's MiniMax H3 Reference to Video."
        ) from error
    return CANVAS_MULTIPLE, REF_IMAGE_SHORT_EDGE, _empty_av_latent, _resize


class NynxzH3ReferenceToVideo(H3Node):
    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3.ReferenceToVideo",
            display_name="H3 Reference to Video",
            description="ref2va conditioning for MiniMax H3 that honours each reference's role: "
            "'reference' images get a VAE latent in the DiT, 'semantic' ones condition through "
            "the text encoder alone. Core's node decides that for all of them at once with a "
            "single VAE check. Images only — chain core's node for reference videos and audio.",
            inputs=[
                io.Clip.Input("clip"),
                H3Refs.Input("references"),
                io.String.Input("prompt", multiline=True, dynamic_prompts=True),
                io.Vae.Input(
                    "vae",
                    optional=True,
                    tooltip="Video VAE. Required if any reference has role 'reference'; an "
                    "all-'semantic' chain needs none.",
                ),
                io.Int.Input("width", default=1344, min=32, max=16384, step=32),
                io.Int.Input("height", default=768, min=32, max=16384, step=32),
                io.Int.Input(
                    "length",
                    default=124,
                    min=5,
                    max=3600,
                    step=17,
                    tooltip="Frame count at 24 fps (124 = ~5s; the trained range is ~124-362).",
                ),
                io.Combo.Input(
                    "ref_image_size",
                    options=["match", "max"],
                    default="match",
                    tooltip="'match' scales each reference (down only, keeping aspect) to the "
                    "generation's pixel area; 'max' uses the 2048px short edge for best identity "
                    "fidelity. Reference tokens ride through every sampling step, so 'max' can "
                    "be several times slower.",
                ),
            ],
            outputs=[
                io.Conditioning.Output(display_name="positive"),
                io.Latent.Output(),
                io.String.Output(
                    display_name="picture_map",
                    tooltip="Which <Picture i> each reference became. Latent references are "
                    "emitted first, so the numbering is not chain order — prompt with this.",
                ),
            ],
            is_experimental=True,
        )

    @classmethod
    def execute(
        cls,
        clip,
        references,
        prompt,
        vae=None,
        width=1344,
        height=768,
        length=124,
        ref_image_size="match",
    ):
        canvas, short_edge, empty_av_latent, resize = _core()

        if references is None:
            raise ValueError(
                "H3 Reference to Video received no references. If an H3 Reference node upstream "
                "is MUTED (Ctrl+M) it produces nothing and the chain dies there — use BYPASS "
                "(Ctrl+B) instead, which passes the rest of the chain through."
            )
        entries = [
            {
                "image": image,
                "role": entry["role"],
                "label": entry["label"],
                "vision_size": int(entry.get("vision_size") or 0),
                "board": entry.get("board"),
            }
            for entry in references
            for image in images_of(entry)
        ]
        if not entries:
            raise ValueError("H3 Reference to Video needs at least one reference.")

        wants_latents = [e for e in entries if e["role"] == REFERENCE]
        if wants_latents and vae is None:
            named = ", ".join(e["label"] for e in wants_latents)
            raise ValueError(
                f"These references have role '{REFERENCE}' and so need a VAE to encode their "
                f"latents: {named}. Wire the H3 video VAE in, or set them to 'semantic' to "
                "condition through the text encoder alone."
            )

        latent, _ = empty_av_latent(width, height, length)
        order, numbers = ordered(entries)

        ref_items, ref_blocks, rows = [], [], []
        for index in order:
            entry = entries[index]
            image = entry["image"]
            h, w = image.shape[1], image.shape[2]
            if ref_image_size == "match":
                # aspect-preserving scale (down only) to the generation's pixel area
                scale = min(1.0, math.sqrt((width * height) / (w * h)))
            else:
                scale = min(1.0, short_edge / min(w, h))
            target_w = max(canvas, round(w * scale / canvas) * canvas)
            target_h = max(canvas, round(h * scale / canvas) * canvas)

            # The two channels are sized independently. What the TEXT ENCODER sees is what
            # decides how literally a reference transfers: one token per 32x32 pixels, and
            # nothing downscales it on the way in.
            board = entry["board"]
            if board is not None:
                # Square, so every image on one board produces an IDENTICAL token grid — the
                # precondition for blending them position by position at all.
                edge = int(board["resolution"])
                vision_w = vision_h = edge
                crop = "center" if board["fit"] == "cover" else "disabled"
                vision = resize(image[:1], edge, edge, crop)
            else:
                budget = entry["vision_size"]
                vision_w, vision_h = (
                    fit_to_budget(target_w, target_h, budget) if budget else (target_w, target_h)
                )
                vision = resize(image[:1], vision_w, vision_h, "disabled")
            ref_items.append({"type": "image", "data": vision})

            if entry["role"] == REFERENCE:
                latent_src = (
                    vision
                    if (vision_w, vision_h) == (target_w, target_h)
                    else resize(image[:1], target_w, target_h, "disabled")
                )
                ref_blocks.append(
                    {
                        "kind": "image",
                        "latent_h": target_h // 16,
                        "latent_w": target_w // 16,
                        "latent": vae.encode(latent_src),
                    }
                )

            rows.append(
                {
                    "picture": numbers[index],
                    "label": entry["label"],
                    "role": entry["role"],
                    "tokens": vision_tokens(vision_w, vision_h),
                    "board": board,
                    # kept for a board's alpha coverage; `_resize` drops the 4th channel
                    "alpha": image[:1, ..., 3:4] if image.shape[-1] >= 4 else None,
                }
            )

        tokens = clip.tokenize(prompt, minimax_ref_items=ref_items)
        conditioning = clip.encode_from_tokens_scheduled(tokens)

        boards = board_runs(entries, order)
        if boards:
            conditioning = fuse_boards(conditioning, boards, rows)

        if ref_blocks:
            conditioning = node_helpers.conditioning_set_values(
                conditioning, {"minimax_refs": ref_blocks}
            )
        return io.NodeOutput(conditioning, latent, render_map(rows, boards))


def fuse_boards(conditioning, boards, rows):
    """Blend each board's vision spans into its first bracket and cut the spare brackets out.

    The presentation is `[<Picture 1>: ][vision] … [prompt]`, so a board's brackets being
    ADJACENT makes the tokens to remove one contiguous stretch: from the end of the first
    bracket's vision run to the end of the last one's. That takes the spare `<Picture i>: `
    labels with it, leaving a single picture holding the blend.
    """
    out = []
    for entry in conditioning:
        cond, extra = entry[0], dict(entry[1])
        tags = tags_of(entry)
        if tags is None:
            raise ValueError(
                "H3 Mood Board needs the text encoder's vision-token map "
                f"('{TAGS_KEY}') to find each picture, and this conditioning carries none. "
                "That map comes from the MiniMax H3 CLIP — check the right one is loaded."
            )
        pictures = vision_runs(tags)
        if len(pictures) != len(rows):
            raise ValueError(
                f"H3 Mood Board expected {len(rows)} vision blocks in the conditioning but "
                f"found {len(pictures)}. The encoder's presentation is not what this node "
                "assumes; do not trust the result."
            )

        cuts = []
        for board, positions in boards:
            if len(positions) < 2:
                continue  # a board of one image is just a reference; nothing to blend
            spans = [interior(pictures[p]) for p in positions]
            edge = int(board["resolution"]) // PIXELS_PER_TOKEN_EDGE
            alphas = [rows[p]["alpha"] for p in positions]
            cond = write_span(
                cond,
                spans[0],
                blend_spans(
                    [read_span(cond, span) for span in spans],
                    weights=board["weights"],
                    mode=board["blend"],
                    grid=(edge, edge),
                    block_size=board["block_size"],
                    feather=board["feather"],
                    jitter=board["jitter"],
                    seed=board["seed"],
                    coverage=(
                        coverage_field(alphas, (edge, edge))
                        if board["alpha_mode"] == "exclude"
                        else None
                    ),
                ),
            )
            cuts.append((pictures[positions[0]][1], pictures[positions[-1]][1]))

        cond, tags = cut(cond, tags, cuts)
        extra[TAGS_KEY] = tags
        out.append([cond, extra])
    return out


def render_map(rows, boards):
    """The picture map, with each board shown as the single picture it collapsed into.

    Collapsing leaves GAPS in the numbering — the surviving labels were written by the
    tokenizer's counter before the cut — so this is the authoritative list of what to prompt
    with, not an assumption that pictures run 1..N.
    """
    folded = {}
    for _, positions in boards:
        for position in positions[1:]:
            folded[position] = positions[0]

    lines = []
    for position, row in enumerate(rows):
        if position in folded:
            continue
        board = row["board"]
        if board is None:
            lines.append(
                f"<Picture {row['picture']}> = {row['label']} "
                f"({row['role']}, {row['tokens']} vision tokens)"
            )
            continue
        members = next(p for b, p in boards if b is board)
        names = ", ".join(rows[p]["label"] for p in members)
        lines.append(
            f"<Picture {row['picture']}> = {board['label']} "
            f"({board['blend']} of {len(members)}: {names}; {row['tokens']} vision tokens)"
        )
    return "\n".join(lines)
