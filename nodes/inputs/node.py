"""H3 Inputs — several references on one node, instead of a chain of one-asset nodes.

**Autogrow is not the problem with core's node; parallel autogrows are.** *Reference to Video*
carries four of them and pairs the third to the second by parsing the index out of the slot name
(`ref_video_audios.get("ref_video_audio_" + name.rsplit("_", 1)[-1])`), so `ref_video_audio_2` is
the soundtrack of `ref_video_2` with nothing on screen saying so. Add, remove or reorder one group
and the other silently misaligns.

A single autogrow of pictures cannot do that — there is nothing to pair it with. It is also
*clearer* than a chain: `picture_2` names the `<Picture 2>` it will answer to, where chained nodes
leave you counting.

So the split here is by whether a slot can stand alone:

  * **pictures and audio autogrow** — one value each, nothing to keep in step.
  * **first_frame / last_frame are single inputs**, because keyframes are first-and-last by
    definition; there is never a third.
  * **reference video is not here at all — it goes on H3 Video.** A video is four correlated
    settings (frames, fps, soundtrack, detail) and a slot holds one value, so an autogrow can
    only carry it by splitting those across parallel groups. That is the bug above, and it is
    worse than it looks: a silent clip in slot 0 does not merely lose its own pairing, it shifts
    every later one, so the next clip's soundtrack lands on the wrong video with nothing on
    screen saying so. H3 Video binds all four together on one node and chains — the same
    relationship, structurally, with no index arithmetic to get wrong.

Ordinals still count what actually reaches the encode, so a picture wired upstream shifts the tags
here. The `report` output names the tag each slot really got.
"""

from __future__ import annotations

from comfy_api.latest import io

from .._base import PackNode
from . import _payload, _rows
from .types import H3InputData

#: Slots per group. Nine pictures matches core's ceiling; audio is rarer and four is generous.
MAX_PICTURES = 9
MAX_AUDIOS = 4


def _slots(prefix: str, count: int) -> list[str]:
    """Slot names, numbered from **1**.

    `Autogrow.TemplatePrefix` would be the obvious choice and it numbers from zero
    (`names = [f"{prefix}{i}" for i in range(max)]`, `comfy_api/latest/_io.py:1126`), which is what
    core's `ref_image_0` comes from. That is one off from H3's own tags — the first picture is
    `<Picture 1>` — and this node's whole claim is that a slot names the tag it answers to. So the
    names are given explicitly instead, which `TemplateNames` exists for.
    """
    return [f"{prefix}{i}" for i in range(1, count + 1)]


class H3Inputs(PackNode):
    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3Inputs",
            display_name="H3 Inputs",
            description="Several MiniMax H3 references on one node: keyframes, reference pictures "
            "and reference audio, with slots that grow as you fill them. Each slot names the tag "
            "it answers to — picture_2 is <Picture 2>. Reference video goes on H3 Video, which "
            "keeps a clip and its soundtrack together. Chain onto other H3 nodes in either "
            "direction.",
            inputs=[
                io.Image.Input(
                    "first_frame",
                    optional=True,
                    tooltip="Opens the clip. Wiring either keyframe selects H3's fl2va task, "
                    "which cannot be combined with references — H3 Encode's report says what it "
                    "set aside.",
                ),
                io.Image.Input(
                    "last_frame",
                    optional=True,
                    tooltip="Closes the clip. Can be used with or without a first frame.",
                ),
                io.Autogrow.Input(
                    "pictures",
                    optional=True,
                    template=io.Autogrow.TemplateNames(
                        input=io.Image.Input(
                            "picture",
                            tooltip="A reference picture. Its slot number is the <Picture i> tag "
                            "it answers to, unless another H3 node upstream contributes pictures "
                            "first — the report gives the real tags.",
                        ),
                        names=_slots("picture_", MAX_PICTURES),
                        min=0,
                    ),
                ),
                io.Autogrow.Input(
                    "audios",
                    optional=True,
                    template=io.Autogrow.TemplateNames(
                        input=io.Audio.Input(
                            "audio", tooltip="A reference audio track, tagged <Audio j>."
                        ),
                        names=_slots("audio_", MAX_AUDIOS),
                        min=0,
                    ),
                ),
                io.Combo.Input(
                    "size",
                    options=list(_rows.SIZES),
                    default="auto",
                    tooltip="How much detail the reference pictures are fed in at. Reference rows "
                    "are processed on every sampling step, so 'max' costs several times more. "
                    "Applies to the pictures here, not to the keyframes, which are canvas-sized.",
                ),
                H3InputData.Input(
                    "h3_inputs",
                    optional=True,
                    tooltip="Another H3 node upstream. Its assets come first, then this one's.",
                ),
            ],
            outputs=[
                H3InputData.Output(display_name="h3_inputs"),
                io.String.Output(
                    display_name="report",
                    tooltip="The tag each slot ended up with, counting anything wired upstream.",
                ),
            ],
        )

    @classmethod
    def execute(
        cls,
        first_frame=None,
        last_frame=None,
        pictures=None,
        audios=None,
        size="auto",
        h3_inputs=None,
    ) -> io.NodeOutput:
        size = size if size in _rows.SIZES else "auto"
        items: list[dict] = []

        # Keyframes first, and first before last: `_rows.ordinals` counts in list order, so this is
        # what makes a first frame `<Picture 1>` when both are wired.
        for image, role in ((first_frame, "first_frame"), (last_frame, "last_frame")):
            if image is not None:
                items.append(_image_item(image, role, "auto"))

        # `.values()` preserves the slot order ComfyUI filled them in, which is what the ordinals
        # follow. Sorting by name would put picture_10 before picture_2.
        for image in (pictures or {}).values():
            if image is not None:
                items.append(_image_item(image, "reference", size))

        for audio in (audios or {}).values():
            if audio is not None:
                items.append(
                    {
                        "kind": "audio",
                        "role": "reference",
                        "label": "H3 Inputs (audio)",
                        "image": None,
                        "audio": audio,
                        "fps": None,
                        "size": "auto",
                    }
                )

        payload = _payload.merge(h3_inputs, _payload.make(items))
        return io.NodeOutput(payload, _report(payload, items))


def _image_item(image, role: str, size: str) -> dict:
    return {
        "kind": "image",
        "role": role,
        "label": f"H3 Inputs ({role})",
        # One picture per slot: a batch would silently become several <Picture i> blocks, and a
        # keyframe is one frame by definition.
        "image": image[:1],
        "audio": None,
        "fps": None,
        "size": size,
    }


def _report(payload, own: list[dict]) -> str:
    """The tag each of this node's assets ended up with, in the merged chain."""
    if not own:
        return "H3 Inputs: nothing wired"

    merged = _payload.items_of(payload)
    tags = _rows.tags(merged)
    # This node's items are the tail of the merge — upstream assets come first.
    offset = len(merged) - len(own)
    lines = [f"H3 Inputs: {len(own)} asset(s)"]
    if offset:
        lines[0] += f", after {offset} from upstream"
    for index, item in enumerate(own):
        role = item["role"]
        where = "keyframe" if role in _rows.KEYFRAME_ROLES else item["kind"]
        lines.append(
            f"  {tags[offset + index]}  {where}" + (f" ({role})" if role != "reference" else "")
        )
    return "\n".join(lines)
