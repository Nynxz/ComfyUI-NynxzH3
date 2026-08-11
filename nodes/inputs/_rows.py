"""The grid row schema, and the one rule that decides what a row becomes.

A row is what the Vue grid serializes; a *resolved item* is what the wire carries. This module
owns the coercion between them and nothing else, so both ends have one definition to agree with.

**Roles.** `first_frame` and `last_frame` anchor a picture to a position in the generated clip
(the model's fl2va task); `reference` supplies identity or style with no position (ref2va). They
are different mechanisms, not settings of one — see `nodes/encode/_encode.py` for why the model
cannot take both at once. Only an image can be a keyframe, so a video or audio row is forced
back to `reference` here rather than being allowed to hold a role that would be silently
dropped later.

**Ordinals are positional, per type.** A reference's prompt tag is `<Picture 1>` / `<Video 1>` /
`<Audio 1>`, numbered within its own type in list order. `ordinals()` is the authority; the Vue
grid reimplements the same rule to label each card, and `tests/test_rows.py` pins it. Getting
this wrong is invisible in the graph and produces a prompt that refers to the wrong picture.
"""

from __future__ import annotations

ROLES = ("reference", "first_frame", "last_frame")
KEYFRAME_ROLES = ("first_frame", "last_frame")
SIZES = ("auto", "match", "max")

#: Prompt-tag word per kind, in the order the presentation emits types.
TAG = {"image": "Picture", "video": "Video", "audio": "Audio"}
TYPE_ORDER = ("image", "video", "audio")


def ordinals(items: list[dict]) -> list[int]:
    """1-based index within each item's own type, in list order.

    Counts *every* reference item of that type, muted or not? No — it counts what it is given,
    which is why callers pass the enabled rows. A muted row must not consume an ordinal, or
    every tag after it in the prompt would shift by one the moment something was muted.
    """
    seen: dict[str, int] = {}
    out = []
    for item in items:
        kind = item.get("kind", "image")
        seen[kind] = seen.get(kind, 0) + 1
        out.append(seen[kind])
    return out


def tags(items: list[dict]) -> list[str]:
    """The prompt tag each item will answer to, e.g. `<Picture 2>`."""
    return [
        f"<{TAG.get(item.get('kind', 'image'), 'Picture')} {n}>"
        for item, n in zip(items, ordinals(items), strict=True)
    ]


def by_type(items: list[dict]) -> list[dict]:
    """Items regrouped into the presentation's type order, stable within each type.

    The tokenizer walks `minimax_ref_items` in whatever order it is given, but the model was
    trained on images, then videos, then standalone audio — so the grid's ordering is honoured
    *within* a type (which is what sets the ordinals, and what a user is actually arranging)
    while the type grouping stays fixed. Dragging a video above an image therefore changes
    nothing, and the card's tag label is what makes that visible instead of surprising.
    """
    return [item for kind in TYPE_ORDER for item in items if item.get("kind") == kind]
