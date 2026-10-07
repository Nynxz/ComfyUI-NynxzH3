"""The reference list H3 Reference builds and H3 Reference to Video consumes."""

from __future__ import annotations

from comfy_api.latest import io

#: What a reference contributes.
#:   reference — both channels: its VAE latent in `minimax_refs`, plus its vision tokens.
#:   semantic  — vision tokens only. No latent, so it costs nothing in the DiT sequence.
REFERENCE = "reference"
SEMANTIC = "semantic"
ROLES = [REFERENCE, SEMANTIC]

#: Resolved references, H3 Reference -> H3 Reference to Video. A list of
#: {image, role, label}.
H3Refs = io.Custom("NYNXZ_H3_REFS")


def images_of(entry) -> list:
    """The image(s) one entry contributes."""
    images = entry.get("images")
    return list(images) if images else [entry["image"]]


def board_of(entry):
    """The board dict an entry belongs to, or None for a plain reference."""
    return entry.get("board")


def board_count(entries):
    """How many distinct boards are already in a chain."""
    seen = []
    for entry in entries:
        board = board_of(entry)
        if board is not None and not any(board is s for s in seen):
            seen.append(board)
    return len(seen)


def board_runs(entries, order):
    """`[(board, [positions in `order`])]` for each board, in emission order.

    The mood board's surgery cuts one contiguous stretch of the sequence per board, so a board's
    pictures MUST be adjacent. They always are: one node appends its images in a run and
    `ordered` partitions stably. This returns the runs so the caller can verify rather than
    assume — a silent non-contiguous board would cut the wrong tokens.
    """
    runs = []
    for position, index in enumerate(order):
        board = board_of(entries[index])
        if board is None:
            continue
        if runs and runs[-1][0] is board and runs[-1][1][-1] == position - 1:
            runs[-1][1].append(position)
        else:
            runs.append((board, [position]))
    return runs


def ordered(entries):
    """Emission order with the latent-bearing references first, and each one's `<Picture N>`.

    Nothing tells H3 which `<Picture i>` a latent belongs to except ORDER — the tokenizer labels
    from a counter and the DiT reads `refs[k]` as the k-th picture. Emitting every `reference`
    ahead of every `semantic` is what keeps that correspondence exact once some references have
    no latent: `ref_blocks[k]` is then always `<Picture k+1>`.

    One image per entry; the caller flattens first. Returns
    `(indices_in_emission_order, picture_number_by_original_index)`.
    """
    order = [i for i, e in enumerate(entries) if e["role"] == REFERENCE]
    order += [i for i, e in enumerate(entries) if e["role"] != REFERENCE]

    numbers = [0] * len(entries)
    for picture, index in enumerate(order, start=1):
        numbers[index] = picture
    return order, numbers
