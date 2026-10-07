"""Finding and rewriting a `<Picture i>` vision span inside an encoded H3 conditioning.

This is the H3 half of the mood board; `_blend.py` is the model-agnostic half. On Qwen Image 2.1
the equivalent surgery needs the tokenizer's `image_slots`, because that encoder DELETES vision
tokens. H3 keeps them, and hands over a map: `minimax_token_tags` marks every vision position 0
and every text position 1, widened by one on each side so a run covers its flanking
`<|vision_start|>` / `<|vision_end|>` too.

    [<Picture 1>: ][vs][img1][ve][<Picture 2>: ][vs][img2][ve] … [prompt]
     1 1 1 1 1 1 1  0   0..0  0   1 1 1 1 1 1 1  0   0..0  0     1 1 1 1

So a run of zeros IS a picture, in order, and its interior is exactly the vision tower's output
for that image. No slot arithmetic, no reimplementing the tokenizer.

**The tags tensor is not decoration — it must stay the same length as the conditioning.** The DiT
walks it per text row to pick each row's adaLN modulation (`tags[i]` over the text segment in
`comfy/ldm/minimax/model.py`), so a cut that shortens one without the other silently misaligns
every modulation after the cut. `cut` is the only thing here that changes length, and it trims
both together.
"""

from __future__ import annotations

import torch

#: `token_tags_from_embeds_info`: vision positions carry the video modality, text carries 1.
VISION_TAG = 0

#: Where the tag tensor rides in a conditioning entry's dict.
TAGS_KEY = "minimax_token_tags"


def tags_of(entry):
    """The `[seq]` tag tensor from one `[cond, dict]` conditioning entry, or None."""
    tags = entry[1].get(TAGS_KEY) if len(entry) > 1 and isinstance(entry[1], dict) else None
    return None if tags is None else tags.view(-1)


def vision_runs(tags):
    """`[(start, end)]`, end-exclusive, one per `<Picture i>` in presentation order.

    Each run includes its flanking vision_start/vision_end; `interior` strips them.
    """
    values = tags.view(-1).tolist()
    runs, start = [], None
    for index, value in enumerate(values):
        if value == VISION_TAG and start is None:
            start = index
        elif value != VISION_TAG and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(values)))
    return runs


def interior(run):
    """The image's own tokens, without the `<|vision_start|>` / `<|vision_end|>` markers."""
    start, end = run
    return (start + 1, end - 1)


def read_span(cond, span):
    """`[1, tokens, dim]` — the tokens of one span."""
    start, end = span
    return cond[:, start:end, :]


def write_span(cond, span, tokens):
    """A copy of `cond` with `span` replaced. Lengths must match; use `cut` to change length."""
    start, end = span
    if tokens.shape[1] != end - start:
        raise ValueError(
            f"write_span was given {tokens.shape[1]} tokens for a span of {end - start}."
        )
    out = cond.clone()
    out[:, start:end, :] = tokens.to(out.device, out.dtype)
    return out


def cut(cond, tags, ranges):
    """Drop `ranges` (end-exclusive, in sequence coordinates) from BOTH cond and tags.

    Keeping the two in lockstep is the whole point — see the module note.
    """
    if not ranges:
        return cond, tags
    length = cond.shape[1]
    keep = torch.ones(length, dtype=torch.bool)
    for start, end in ranges:
        keep[max(0, int(start)) : min(length, int(end))] = False
    index = keep.nonzero().view(-1)
    return cond[:, index.to(cond.device), :], tags.view(-1)[index.to(tags.device)]
