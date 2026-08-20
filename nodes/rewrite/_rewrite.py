"""Reference-frame ordering, and reading the rewriter's answer back.

Two jobs the nodes are thin over.

**Ordering.** The rendered prompt carries one `<|image_pad|>` per reference frame, and ComfyUI
binds each pad to the next image in the batch handed to Generate Text — by position, with no
names involved. So the batch has to be built in the same order the pads appear (first frame,
then last frame) or fl2va silently describes the wrong end of the clip. `frames_for` is that
ordering, and it is the only place it is written down.

**Batching forces a resize.** An IMAGE socket is one tensor, so two reference frames of
different sizes cannot travel together at all. Rather than refuse the graph, `match_size` scales
the second onto the first and says so — these are references the rewriter *looks at*, not frames
it reproduces, so the resample costs nothing that matters.

**Cleanup is deliberately forgiving.** `clean_response` finds the three fields and returns
everything from the alignment line onward; when it finds nothing it recognises, it hands the
text back untouched rather than returning an empty string, because a graph that shows you a
strange prompt is debuggable and one that shows you nothing is not.
"""

from __future__ import annotations

import logging
import re

import comfy.utils
import torch

from ._prompt import expected_image_count, normalize_task

#: The rewriter's output fields, in the order it emits them.
FIELDS = ("integrated_multimodal_description", "overall_soundscape", "non_diegetic_music")

_FIELD_RE = re.compile(r"^\s*(" + "|".join(FIELDS) + r")\s*:\s*", re.MULTILINE)
_ALIGNMENT_RE = re.compile(r"^\s*(For the target video,|How the reference pictures align)", re.MULTILINE)


def single_frame(image, label: str):
    """One frame out of a slot; a reference slot is a single picture, not a batch."""
    if image is None:
        return None
    if image.shape[0] > 1:
        logging.warning("H3 Rewrite Prompt: %s got %d images, using the first.", label, image.shape[0])
    return image[:1]


def match_size(reference, image):
    """Scale `image` onto `reference`'s canvas so both can share one IMAGE batch."""
    if image.shape[1:] == reference.shape[1:]:
        return image
    height, width = reference.shape[1], reference.shape[2]
    logging.warning(
        "H3 Rewrite Prompt: resizing last_frame %dx%d -> %dx%d so both frames can be batched.",
        image.shape[2],
        image.shape[1],
        width,
        height,
    )
    resized = comfy.utils.common_upscale(image.movedim(-1, 1), width, height, "lanczos", "center")
    return resized.movedim(1, -1).clamp(0.0, 1.0)


def frames_for(task: str, first_frame, last_frame):
    """The reference batch in placeholder order, or None for a text-only task.

    Raises if the task needs a frame that is not wired, and warns about one that is wired but
    unused — switching modes on a built graph should say what it is ignoring, not go quiet.
    """
    task = normalize_task(task)
    slots = []
    if task in ("i2av", "fl2av"):
        slots.append(("first_frame", first_frame))
    if task in ("l2av", "fl2av"):
        slots.append(("last_frame", last_frame))

    missing = [name for name, image in slots if image is None]
    if missing:
        raise ValueError(f"H3 Rewrite Prompt: {task} needs {', '.join(missing)}.")

    unused = []
    if task == "t2av" and (first_frame is not None or last_frame is not None):
        unused.append("both frames")
    elif task == "i2av" and last_frame is not None:
        unused.append("last_frame")
    elif task == "l2av" and first_frame is not None:
        unused.append("first_frame")
    if unused:
        logging.warning("H3 Rewrite Prompt: %s ignores %s.", task, " and ".join(unused))

    if not slots:
        return None
    tensors = [image for _, image in slots]
    tensors[1:] = [match_size(tensors[0], t) for t in tensors[1:]]
    batch = torch.cat(tensors, dim=0)
    assert batch.shape[0] == expected_image_count(task)
    return batch


def clean_response(text: str) -> tuple[str, dict[str, str]]:
    """`(prompt, fields)` — the production prompt, and the three fields split out."""
    text = (text or "").strip()
    text = re.split(r"<\|im_end\|>", text)[0]
    text = re.sub(r"^\s*<\|im_start\|>\s*assistant\s*\n?", "", text)
    text = re.sub(r"^```[a-zA-Z]*\s*\n|\n?```\s*$", "", text.strip())

    matches = list(_FIELD_RE.finditer(text))
    if not matches:
        return text, dict.fromkeys(FIELDS, "")

    start = matches[0].start()
    alignment = [m for m in _ALIGNMENT_RE.finditer(text) if m.start() < start]
    if alignment:
        start = alignment[0].start()

    fields = dict.fromkeys(FIELDS, "")
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        fields[match.group(1)] = text[match.end() : end].strip()
    return text[start:].strip(), fields
