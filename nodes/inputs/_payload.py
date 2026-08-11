"""What travels on the `h3_inputs` wire: the assets, and the canvas they are being made for.

    {"version": 1,
     "items":  [ {kind, role, label, image, audio, fps, size}, ... ],
     "canvas": {width, height, length, ref_image_size} | None}

**Why the canvas rides the same wire as the assets.** Width, height and length used to be
widgets on the encode node, which put them a long way from the pictures they frame — you set a
reference to `max` in one node and the resolution it is being matched against in another. They
belong with the assets, so H3 Inputs owns them and Encode reads them. That also lets **H3
Extras** break them out as plain INTs without a second source of truth.

**Merging is a chain, and the rule is one line:** items concatenate upstream-first, and the
canvas is *the most downstream one that exists*. Only H3 Inputs produces a canvas; the H3 Image
/ Video / Audio nodes pass whatever reaches them straight through. So a chain works in either
direction — a cast node full of references feeding a canvas node, or the other way round — and
the node nearest the encode wins, which is the one you were last looking at.
"""

from __future__ import annotations

VERSION = 1

#: Reference-image sizing. `match` scales to the generation's pixel area, `max` to the
#: reference pipeline's 2048px short edge. A row may override this per asset.
REF_SIZES = ("match", "max")

DEFAULT_CANVAS = {
    # 1344x768 is H3's own default and sits exactly on the 768*1344 pixel cap.
    "width": 1344,
    "height": 768,
    # 124 frames at 24 fps is ~5s, and is on the 17k+5 grid already.
    "length": 124,
    "ref_image_size": "match",
    "source": "custom",
    "snap": 32,
}


def rows_of(setup) -> list:
    """The asset rows out of the node's setup value.

    Tolerates a bare list, which is what the widget held before the canvas moved onto the same
    value — a workflow saved then should still open with its references.
    """
    if isinstance(setup, dict):
        rows = setup.get("rows")
        return list(rows) if isinstance(rows, list) else []
    return list(setup or [])


def canvas_in(setup) -> dict:
    """The canvas out of the node's setup value, defaulted."""
    return canvas(setup.get("canvas") if isinstance(setup, dict) else None)


def canvas(value) -> dict:
    """Coerce a canvas dict, repairing anything missing or out of range.

    Repaired rather than rejected: this arrives from a widget, and a workflow saved by an older
    build should open with a usable canvas instead of an error.
    """
    raw = value if isinstance(value, dict) else {}

    def number(key: str, low: int, high: int) -> int:
        try:
            return max(low, min(high, int(raw.get(key, DEFAULT_CANVAS[key]))))
        except (TypeError, ValueError):
            return int(DEFAULT_CANVAS[key])

    size = raw.get("ref_image_size")
    return {
        # Multiples of 32 are the model's requirement, not a preference — `adapt_canvas` rounds
        # to CANVAS_MULTIPLE and the VAE's /16 plus the DiT's 2x2 patch needs the result even.
        "width": max(32, number("width", 32, 16384) // 32 * 32),
        "height": max(32, number("height", 32, 16384) // 32 * 32),
        "length": number("length", 5, 3600),
        "ref_image_size": size if size in REF_SIZES else DEFAULT_CANVAS["ref_image_size"],
        # Which asset the size was taken from. Pure UI state — nothing here reads it — but it
        # round-trips so the node still says what it is matching after a reload.
        "source": str(raw.get("source") or "custom"),
        # Snap step the picker used. UI state like `source`; the width/height above have already
        # been snapped by the time they reach here.
        "snap": 64 if str(raw.get("snap")) == "64" else 32,
    }


def make(items: list[dict] | None = None, canvas_value=None) -> dict:
    """A payload for one node's own contribution."""
    return {
        "version": VERSION,
        "items": list(items or []),
        "canvas": canvas(canvas_value) if canvas_value is not None else None,
    }


def merge(upstream, own: dict) -> dict:
    """Chain `own` onto whatever arrived, keeping the most downstream canvas."""
    before = items_of(upstream)
    return {
        "version": VERSION,
        "items": before + list(own.get("items") or []),
        "canvas": own.get("canvas") or canvas_of(upstream, default=None),
    }


def items_of(payload) -> list[dict]:
    """The asset list, tolerating the bare-list payload an earlier build wrote."""
    if isinstance(payload, dict):
        return list(payload.get("items") or [])
    return list(payload or [])


def canvas_of(payload, default=DEFAULT_CANVAS) -> dict | None:
    """The canvas, or `default` when nothing upstream set one."""
    if isinstance(payload, dict) and isinstance(payload.get("canvas"), dict):
        return payload["canvas"]
    return dict(default) if default is not None else None
