"""Editing a still with H3: the prompt, written the way H3's own reference guide lays it out.

H3 is a video model, but its shortest clip — 5 frames, the first step of the `17k+5` grid —
decodes to a clean still at the end, which makes it an image editor that understands references.
What it lacks for that job is a prompt: H3 was trained on six-section reference prompts
(`subject_definitions` … `non_diegetic_music`), not on "make this a watercolour". This module
writes those sections from three things a person actually has — the picture, what should change,
and the references that say how.

**References are named, not numbered.** A picture is `@style` or `@ren` in the instruction, and
becomes the `<Subject N>` / `<Picture N>` H3 knows it by only here, so reordering the slots never
silently re-points a sentence at the wrong picture.

**What a reference is *for* is its retention marker**, the field H3's guide uses for exactly this:

    look   fully_preserved     a person, prop or place that appears as shown
    style  attribute_transfer  its rendering moves onto the edited picture; none of its content
    loose  weak_reference      only a broad likeness

**Two ways in**, because they trade differently and only trying tells which suits a picture:

    reference    the source is <Subject 1> (ref2va). References are full subjects. The source is
                 re-drawn, so it can move a long way — the strongest restyle.
    first_frame  the source is the opening keyframe (fl2va). It is pinned exactly at frame 0 and
                 the edit happens across the clip; references reach the text encoder only.
"""

from __future__ import annotations

import re

ROLES = ("look", "style", "loose")
KEEPS = ("closely", "changes", "loosely")
MODES = ("reference", "first_frame")
SOURCE = "source"

#: Shortest clip on H3's frame grid — the still is its decoded last frame.
FRAMES = 5

_LINE = re.compile(
    r"^\s*[-*]?\s*@([\w-]+)\s*(?:\(\s*(look|style|loose)\s*\))?\s*(?::\s*(.*?))?\s*$", re.I
)
_MENTION = re.compile(r"@([\w-]+)")

_KEEP = {
    "closely": (
        "fully_preserved",
        "its composition, subjects, poses and framing stay exactly as they are; only what the "
        "edit asks for changes",
    ),
    "changes": (
        "partially_preserved",
        "its composition, subjects and poses stay; the edit changes what it asks for",
    ),
    "loosely": (
        "weak_reference",
        "only its broad composition and subject are kept",
    ),
}


def parse_references(text: str) -> tuple[list[dict], list[str]]:
    """`@name (role): description` lines, in order — line *n* describes picture slot *n*.

    Returns the references and warnings for lines that could not be read. Blank lines and `//`
    comments are skipped and do not take a slot.
    """
    refs: list[dict] = []
    warnings: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        m = _LINE.match(line)
        if not m:
            warnings.append(f"Couldn't read the reference line {line!r} (write @name (role): …).")
            continue
        name = m.group(1).lower()
        if name == SOURCE:
            warnings.append(
                "@source is the picture being edited; give that reference another name."
            )
            continue
        refs.append(
            {
                "name": name,
                "role": (m.group(2) or "look").lower(),
                "note": (m.group(3) or "").strip().rstrip("."),
            }
        )
    return refs, warnings


def name_pictures(described: list[dict], count: int) -> tuple[list[dict], list[str]]:
    """One reference per wired picture: its description line, or a plain `@ref<n>` look."""
    warnings: list[str] = []
    refs = []
    for i in range(count):
        if i < len(described):
            refs.append(dict(described[i]))
        else:
            refs.append({"name": f"ref{i + 1}", "role": "look", "note": ""})
    for extra in described[count:]:
        warnings.append(f"@{extra['name']} is described but no picture is wired for it.")
    seen: set[str] = set()
    for r in refs:
        if r["name"] in seen:
            warnings.append(f"@{r['name']} names two pictures; the first one is used.")
        seen.add(r["name"])
    return refs, warnings


def _sentence(text: str) -> str:
    text = (text or "").strip()
    if text and text[-1] not in ".!?\"'":
        text += "."
    return text


def compile_prompt(
    instruction: str,
    refs: list[dict],
    mode: str = "reference",
    keep: str = "changes",
    style: str = "",
    source_note: str = "",
) -> tuple[str, list[str]]:
    """The H3 prompt for one edit, and warnings worth showing.

    `refs` are the named references in picture-slot order (see `name_pictures`). In `reference`
    mode the source is `<Picture 1>` / `<Subject 1>` and the references follow; in `first_frame`
    mode the source is the keyframe `<Picture 1>` and the references are `<Picture 2>` onward.
    """
    mode = mode if mode in MODES else "reference"
    keep = keep if keep in KEEPS else "changes"
    warnings: list[str] = []
    if mode == "reference":
        tags = {SOURCE: "<Subject 1>"}
        for i, r in enumerate(refs, start=2):
            tags.setdefault(r["name"], f"<Subject {i}>")
    else:
        tags = {SOURCE: "<Picture 1>"}
        for i, r in enumerate(refs, start=2):
            tags.setdefault(r["name"], f"<Picture {i}>")

    def swap(m: re.Match) -> str:
        tag = tags.get(m.group(1).lower())
        if tag is None:
            warnings.append(f"@{m.group(1)} isn't a reference here.")
            return m.group(0)
        return tag

    edit = _sentence(_MENTION.sub(swap, (instruction or "").strip()))
    if not edit:
        warnings.append("Nothing to change: write what the edit should do.")
    unused = [r["name"] for r in refs if f"@{r['name']}" not in (instruction or "").lower()]
    styles = [r for r in refs if r["role"] == "style"]
    look = _sentence(style)
    hold = "The camera holds a perfectly static shot and nothing in the frame moves."

    if mode == "first_frame":
        mentioned = ", ".join(tags[r["name"]] for r in refs if r["name"] not in unused)
        if unused:
            warnings.append(
                "Not mentioned in the instruction, so H3 is never told what they're for: "
                + ", ".join(f"@{n}" for n in unused)
                + "."
            )
        body = " ".join(
            s
            for s in (
                look,
                "The picture begins exactly as <Picture 1>.",
                f"Across the shot it changes: {edit}" if edit else "",
                f"The references {mentioned} guide the change." if mentioned else "",
                "By the final frame the picture has settled into the edited image. " + hold,
            )
            if s
        )
        prompt = (
            f"integrated_multimodal_description: [Shot 1] {body}\n\n"
            "overall_soundscape: N/A\n\n"
            "non_diegetic_music: N/A"
        )
        return prompt, warnings

    marker, kept = _KEEP[keep]
    note = f", {source_note.strip().rstrip('.')}" if source_note.strip() else ""
    definitions = [
        f"<Subject 1> is the picture being edited, shown in <Picture 1>{note}: its composition, "
        "subjects, poses and layout."
    ]
    retention = [f"<Subject 1> (appears in [Shot 1]): {marker} - {kept}."]
    for i, r in enumerate(refs, start=2):
        if tags.get(r["name"]) != f"<Subject {i}>":
            continue  # a duplicate name: the first picture with it answers
        what = f", {r['note']}" if r["note"] else ""
        if r["role"] == "style":
            definitions.append(
                f"<Subject {i}> is the visual style of <Picture {i}>{what}: its rendering, "
                "linework, colour palette and lighting, not its content."
            )
            retention.append(
                f"<Subject {i}> (appears in [Shot 1]): attribute_transfer - the style of "
                f"<Picture {i}> is transferred onto <Subject 1>; none of its content is copied."
            )
        elif r["role"] == "loose":
            definitions.append(f"<Subject {i}> is the loose reference in <Picture {i}>{what}.")
            retention.append(
                f"<Subject {i}> (appears in [Shot 1]): weak_reference - only a broad likeness "
                f"to <Picture {i}> is kept."
            )
        else:
            definitions.append(f"<Subject {i}> is the subject shown in <Picture {i}>{what}.")
            retention.append(
                f"<Subject {i}> (appears in [Shot 1]): fully_preserved - it keeps the appearance "
                f"shown in <Picture {i}>."
            )
    in_style = " and ".join(f"<Subject {refs.index(r) + 2}>" for r in styles)
    summary = (
        "[reference generation] The target video is a single still frame of <Subject 1>, edited"
    )
    summary += f" and redrawn in the style of {in_style}." if styles else "."
    if unused:
        warnings.append(
            "Not mentioned in the instruction: "
            + ", ".join(f"@{n}" for n in unused)
            + " — H3 still sees them, through the definitions."
        )
    lead = look or "The target video is a single still image."
    shot = (
        f"[Shot 1] <Subject 1>, edited: {edit} {hold}" if edit else f"[Shot 1] <Subject 1>. {hold}"
    )
    prompt = (
        f"subject_definitions:\n{chr(10).join(definitions)}\n\n"
        f"summary:\n{summary}\n\n"
        f"retention_analysis:\n{chr(10).join(retention)}\n\n"
        f"detailed_description:\n{lead}\n{shot}\n\n"
        "overall_soundscape:\nN/A\n\n"
        "non_diegetic_music:\nN/A"
    )
    return prompt, warnings
