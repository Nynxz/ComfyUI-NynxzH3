"""Choosing H3's task from a list of assets, and building the presentation it wants.

H3 has three conditioning tasks and they are not settings of one another:

    t2va   prompt only
    fl2va  prompt + a first and/or last keyframe, anchored to a position in the clip
    ref2va prompt + references (images / videos / audio) with no position

**They cannot be combined, and that is a property of ComfyUI's H3 support rather than a choice
made here.** Two places enforce it. The tokenizer branches — `if minimax_ref_items: ... else:
for img in images` (`comfy/text_encoders/minimax.py:153-179`) — so passing references discards
the keyframe images outright. And `extra_conds` builds `cond_video_latents` from the keyframes
and then *overwrites* it from the references (`comfy/model_base.py:2164-2099`), while
`PackedLayout` still allocates `cond` rows for the keyframes — so a conditioning carrying both
produces a layout whose condition rows outnumber the latents that fill them, and the forward
fails on a shape mismatch deep inside the DiT. Anything this module did to "support both" would
be a crash with extra steps.

So `plan()` picks one, and says what it set aside.

**The one thing that does carry over.** fl2va presents its keyframes as `<Picture 1>: <vision
block>` — the *same* presentation ref2va gives a reference image. So in keyframe mode extra
reference images can still be appended to the tokenizer's `images` list: they get their own
`<Picture i>` tags and reach Qwen3-VL, they simply contribute no DiT latent rows and therefore
no identity pressure through the packed sequence. Reference video and audio have no such
equivalent — their presentation only exists on the ref2va branch — so those are dropped and
reported.
"""

from __future__ import annotations

import math

from .. import _core
from ..inputs import _rows

#: What `mode` may be. `auto` reads the roles that were wired; the rest force one task.
#:
#: Named for the tasks themselves rather than for what you wire at them — `fl2va`, not
#: "keyframes". Those are the names MiniMax's own prompt guides use, the names the model's
#: documentation uses, and therefore the names anyone reading about H3 already has. A second
#: vocabulary that has to be translated back is a cost with no benefit.
MODES = ("auto", "t2va", "fl2va", "ref2va")


def _keyframe_items(items):
    return [i for i in items if i["kind"] == "image" and i["role"] in _rows.KEYFRAME_ROLES]


def plan(items: list[dict], mode: str = "auto") -> dict:
    """Split resolved assets into the one task H3 can actually run.

    Returns `{task, mode, keyframes, semantic, refs, dropped}` where `dropped` is a list of
    `(label, reason)` the caller reports — silently discarding something a user dragged onto a
    node is how a graph comes to look broken for no visible reason.
    """
    items = list(items or [])
    dropped: list[tuple[str, str]] = []

    if mode not in MODES:
        mode = "auto"
    requested = mode
    if mode == "auto":
        if _keyframe_items(items):
            mode = "fl2va"
        elif items:
            mode = "ref2va"
        else:
            mode = "t2va"

    # A reference carrying its own latent is a regenerate pass: somebody wired a finished
    # sampler output back in specifically so it would be re-read in context. Auto picking
    # keyframes then sets it aside, and the run still completes — as fl2va, anchored at both
    # ends and inventing everything between. That reads as "the model is bad at 2K" rather than
    # as a wiring mistake, so auto is not allowed to make this particular guess quietly.
    # An explicitly chosen mode still may: there the user said which task they wanted.
    if requested == "auto" and mode != "ref2va":
        stranded = [i for i in items if i.get("latent") is not None]
        if stranded:
            labels = ", ".join(repr(i["label"]) for i in stranded)
            raise ValueError(
                f"H3 Encode: {labels} supplies a latent, which only the reference task can use, "
                f"but auto chose {mode!r} because "
                + (
                    "a row is set to first_frame or last_frame"
                    if mode == "fl2va"
                    else "there is nothing else to work from"
                )
                + ". Keyframes and references cannot be packed together, so the latent would be "
                "set aside and the run would anchor both ends and generate the middle from "
                "scratch. Set mode to 'ref2va', or clear the keyframe roles."
            )

    if mode == "t2va":
        for item in items:
            dropped.append((item["label"], "mode is t2va: every input is ignored"))
        return {
            "task": "t2va",
            "mode": mode,
            "keyframes": [],
            "semantic": [],
            "refs": [],
            "dropped": dropped,
        }

    if mode == "ref2va":
        # Keyframe roles have no meaning here; the picture is still a perfectly good reference,
        # so it stays as one rather than vanishing.
        refs = []
        for item in items:
            if item["role"] in _rows.KEYFRAME_ROLES:
                dropped.append(
                    (
                        item["label"],
                        f"{item['role']} has no meaning in ref2va — used as a plain reference",
                    )
                )
            refs.append(item)
        return {
            "task": "ref2va",
            "mode": mode,
            "keyframes": [],
            "semantic": [],
            "refs": _rows.by_type(refs),
            "dropped": dropped,
        }

    # keyframes (fl2va)
    promoted: list[tuple[str, str]] = []
    if requested == "fl2va" and not _keyframe_items(items):
        # Forcing the keyframe task with nothing marked as a keyframe would otherwise run fl2va
        # with nothing anchored — identical output to t2va, under a name that says otherwise, and
        # the only hint is the words "no keyframe" in the summary.
        #
        # The first two pictures are the right ones to promote because that is what H3 is being
        # told they are: the FL2VA prompt form names the anchors `Picture 1 (from Shot 1)` and
        # `Picture 2 (from Shot N)` (base guide 2.1). Promoting them makes the prompt and the
        # packing agree.
        #
        # Only when NOTHING is marked. An explicit first_frame/last_frame always wins, so this
        # cannot override a deliberate choice — and it cannot fire under `auto`, which only picks
        # this branch when a role already exists.
        pictures = [i for i in items if i["kind"] == "image"]
        assign = dict(
            zip((id(p) for p in pictures[:2]), ("first_frame", "last_frame"), strict=False)
        )
        if assign:
            # Rebuilt rather than mutated: `items` belongs to the payload on the wire, and other
            # nodes downstream read it.
            items = [dict(i, role=assign.get(id(i), i["role"])) for i in items]
            promoted = [
                (p["label"], role)
                for p, role in zip(pictures, ("first_frame", "last_frame"), strict=False)
            ]

    keyframes: list[dict] = []
    taken: set[str] = set()
    for item in _keyframe_items(items):
        if item["role"] in taken:
            dropped.append((item["label"], f"a {item['role']} was already set"))
            continue
        taken.add(item["role"])
        keyframes.append(item)
    # first before last, so the ordinals match how the model was shown them
    keyframes.sort(key=lambda i: 0 if i["role"] == "first_frame" else 1)

    semantic: list[dict] = []
    for item in items:
        if any(item is k for k in keyframes) or item["role"] in _rows.KEYFRAME_ROLES:
            continue
        if item["kind"] == "image":
            semantic.append(item)
        else:
            dropped.append(
                (
                    item["label"],
                    f"reference {item['kind']} cannot be presented alongside keyframes — "
                    "switch mode to ref2va, or mute the keyframe rows",
                )
            )
    return {
        "task": "fl2va",
        "mode": mode,
        "keyframes": keyframes,
        "semantic": semantic,
        "refs": [],
        "dropped": dropped,
        "promoted": promoted,
    }


def _ref_image_size(item, default: str, width: int, height: int) -> tuple[int, int]:
    """Target pixel size for one reference image, honouring the row's own override.

    `match` scales down to the generation's pixel area; `max` uses the reference pipeline's
    2048px short edge. Neither ever upscales. The choice is per row because it is a cost
    decision as much as a quality one — reference rows ride every sampling step, so a `max`
    reference is paid for on every step of every run, and usually only one source in a grid
    deserves that.
    """
    const = _core.constants()
    multiple = const["canvas_multiple"]
    image = item["image"]
    h, w = int(image.shape[1]), int(image.shape[2])
    size = item.get("size", "auto")
    if size == "auto":
        size = default
    if size == "match":
        scale = min(1.0, math.sqrt((width * height) / (w * h)))
    else:
        scale = min(1.0, const["ref_image_short_edge"] / min(w, h))
    return (
        max(multiple, round(w * scale / multiple) * multiple),
        max(multiple, round(h * scale / multiple) * multiple),
    )


def build_keyframes(plan_out: dict, vae, width: int, height: int, frame_count: int):
    """`(images_for_qwen, minimax_keyframes)` for the fl2va presentation.

    The two crops differ and it is not an oversight — it is what the core node does. The first
    frame is a *geometry anchor* and is stretched to the canvas so the generation inherits its
    framing exactly; the last frame is a *follower* and is cover-cropped so it does not fight
    the composition the first one established.
    """
    images = []
    keyframes = []
    for item in plan_out["keyframes"]:
        first = item["role"] == "first_frame"
        picture = _core.resize(item["image"][:1], width, height, "disabled" if first else "center")
        images.append(picture)
        keyframes.append(
            {
                "resolved_frame_index": 0 if first else frame_count - 1,
                "latent": vae.encode(picture),
            }
        )
    for item in plan_out["semantic"]:
        # Presented, not conditioned: a <Picture i> block for Qwen with no DiT latent rows.
        tw, th = _ref_image_size(item, "match", width, height)
        images.append(_core.resize(item["image"][:1], tw, th, "disabled"))
    return images, keyframes


def build_references(
    plan_out: dict,
    vae,
    audio_vae,
    width: int,
    height: int,
    frame_count: int,
    ref_image_size: str = "match",
):
    """`(ref_items, ref_blocks)` for the ref2va presentation — Qwen's side and the DiT's side.

    The two lists are parallel and ordered together: `ref_items` is what the tokenizer walks to
    emit `<Picture i>` / `<Video k>` / `<Audio j>` labels, `ref_blocks` is what the DiT packs as
    condition rows. A soundtrack contributes an `<Audio j>` label *before* its `<Video k>`,
    which is the order the model was trained on and the reason the two lists are built in one
    pass rather than assembled separately.
    """
    const = _core.constants()
    multiple, fps = const["canvas_multiple"], const["fps"]
    ref_items: list[dict] = []
    ref_blocks: list[dict] = []

    for item in plan_out["refs"]:
        kind = item["kind"]

        if kind == "image":
            tw, th = _ref_image_size(item, ref_image_size, width, height)
            resized = _core.resize(item["image"][:1], tw, th, "disabled")
            ref_items.append({"type": "image", "data": resized})
            ref_blocks.append(
                {
                    "kind": "image",
                    "latent_h": th // 16,
                    "latent_w": tw // 16,
                    "latent": vae.encode(resized),
                }
            )
            continue

        if kind == "audio":
            if audio_vae is None:
                raise ValueError(
                    f"H3 Encode: {item['label']!r} is an audio reference, which needs an "
                    "audio_vae. Wire H3's audio VAE in, or mute the audio rows."
                )
            latent, audio_t = _core.encode_ref_audio(audio_vae, item["audio"])
            ref_items.append({"type": "audio"})
            ref_blocks.append({"kind": "audio", "ref_audio_t": audio_t, "audio_latent": latent})
            continue

        # video: canvas it, trim to the clip, then land on the model's 17k+5 frame grid
        frames = item["image"]
        supplied = item.get("latent")

        detail = _core.REFERENCE_DETAIL.get(item.get("detail", "full"), 1.0)

        if supplied is not None:
            # A supplied latent is AUTHORITATIVE for both the grid and the span. Re-deriving
            # either from the decoded pixels would be the one way this path can go quietly wrong:
            # `adapt_canvas` could land on a different latent grid than the tensor actually has,
            # and the DiT would then be told its condition rows are a shape they are not.
            ch, cw = int(supplied.shape[3]) * 16, int(supplied.shape[4]) * 16
            want = _core.frames_for_latent_t(int(supplied.shape[2]))
            if frames.shape[0] < want:
                raise ValueError(
                    f"H3 Encode: {item['label']!r} supplies a latent covering {want} frames but "
                    f"only {frames.shape[0]} pixel frames. Qwen3-VL reads the pixels, so the two "
                    "have to describe the same clip — decode the whole latent, or drop the "
                    "latent input and let the frames be encoded."
                )
            if detail < 1.0:
                cw, ch = _core.scale_canvas(cw, ch, detail, multiple)
                supplied = _core.resize_latent(supplied, cw // 16, ch // 16)
            frames = _core.resize(frames[:want], cw, ch, "disabled")
            n = want
        else:
            vh, vw = int(frames.shape[1]), int(frames.shape[2])
            cw, ch = _core.adapt_canvas(vw, vh)
            if vw * vh < cw * ch:  # never upscale a reference
                cw = max(multiple, round(vw / multiple) * multiple)
                ch = max(multiple, round(vh / multiple) * multiple)
            if detail < 1.0:
                cw, ch = _core.scale_canvas(cw, ch, detail, multiple)
            frames = _core.resize(frames, cw, ch, "disabled")
            if frames.shape[0] > frame_count:
                frames = frames[:frame_count]
            n = frames.shape[0]
            if n < 5:
                raise ValueError(
                    f"H3 Encode: reference video {item['label']!r} is {n} frame(s) after trimming "
                    "to the generation length, and H3 needs at least 5 (~0.2s at 24 fps). Use a "
                    "longer clip, or a longer generation."
                )
            while n % 17 != 5:
                n -= 1
            frames = frames[:n]

        audio_latent, audio_t = None, 0
        if item.get("audio") is not None:
            if audio_vae is None:
                raise ValueError(
                    f"H3 Encode: {item['label']!r} has a soundtrack, which needs an audio_vae. "
                    "Wire H3's audio VAE in, or turn the row's audio off."
                )
            audio_latent, audio_t = _core.encode_ref_audio(audio_vae, item["audio"])
            ref_items.append({"type": "audio"})  # the <Audio j> label lands before <Video k>

        # H3's latent format has scale_factor 1.0 and no process_in override, so a sampler's
        # LATENT, `vae.encode`'s output and the DiT's condition rows are all one space. A
        # supplied latent therefore drops in with no conversion — and skips a full decode plus
        # re-encode, which for a regenerate is 124 frames through the VAE twice for nothing.
        latent = supplied if supplied is not None else vae.encode(frames)
        sample_index = list(range(0, frames.shape[0], fps // 2))  # Qwen sees it at 2 fps
        ref_items.append(
            {
                "type": "video",
                "data": frames[sample_index],
                "timestamps": [i / 2.0 for i in range(len(sample_index))],
            }
        )
        ref_blocks.append(
            {
                "kind": "video_audio" if audio_t else "video",
                "latent_t": latent.shape[2],
                "latent_h": ch // 16,
                "latent_w": cw // 16,
                "ref_audio_t": audio_t,
                "latent": latent,
                "audio_latent": audio_latent,
            }
        )
    return ref_items, ref_blocks


def summary(plan_out: dict) -> str:
    """A one-line account of what the encode did, for the console and the node's readout."""
    task = plan_out["task"]
    if task == "t2va":
        return "t2va — prompt only, no inputs used."
    if task == "fl2va":
        roles = ", ".join(item["role"].replace("_", " ") for item in plan_out["keyframes"])
        extra = len(plan_out["semantic"])
        semantic = f", {extra} semantic-only reference image(s)" if extra else ""
        return f"fl2va — {roles or 'no keyframe'}{semantic}."
    counts: dict[str, int] = {}
    for item in plan_out["refs"]:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    parts = ", ".join(f"{n} {kind}" for kind, n in counts.items()) or "nothing"
    return f"ref2va — {parts}."


#: The instruction H3 expects as the FIRST line of a keyframe prompt, one form per task shape.
#:
#: Straight out of `VIDEO_PROMPT_WRITING_GUIDE_base_en.md` §2.1, reproduced verbatim — including
#: the fact that the two-keyframe form writes `Picture 1 (from Shot 1)` bare while the one-frame
#: forms write `<Picture 1> (from [Shot 1])`. That looks like an inconsistency in the guide and
#: is deliberately NOT normalised here: these strings describe the shape of prompt the model was
#: trained on, so matching them exactly is the whole point.
_FIRST_ONLY = (
    "For the target video, at 0.00 seconds into the target video, <Picture 1> "
    "(from [Shot 1]) is fully referenced."
)
_FIRST_AND_LAST = (
    "How the reference pictures align with the target video — Picture 1 (from Shot {n}) aligns "
    "with the 0.00-second mark of the target video; Picture 2 (from Shot {n}) aligns with the "
    "{secs:.2f}-second mark of the target video."
)
_LAST_ONLY = (
    "How the reference pictures align with the target video — <Picture 1> (from [Shot {n}]) "
    "aligns with the {secs:.2f}-second mark of the target video."
)

#: A prompt that already carries an alignment line, so the node must not add a second one.
_ALREADY = ("aligns with the", "is fully referenced")


def alignment_instruction(
    plan_out: dict, frame_count: int, fps: int = 24, shot: int = 1
) -> str | None:
    """The keyframe alignment line for this plan, or None when the task has no keyframes.

    The reason this is worth generating rather than typing: the second-mark is the *snapped*
    duration to two decimals, so it depends on `frame_count` after the `17k+5` rounding. Ask for
    130 frames and the correct line says 5.88, not 5.42 — and nothing else on screen would tell
    you that.

    `shot` defaults to 1 because the guide says FL2VA "generally favors a single shot so the
    model can interpolate continuously". A multi-shot keyframe prompt should write its own line
    and set the node's `keyframe_instruction` to `off`.
    """
    roles = [item["role"] for item in plan_out.get("keyframes") or []]
    if not roles:
        return None
    secs = frame_count / float(fps)
    if "first_frame" in roles and "last_frame" in roles:
        return _FIRST_AND_LAST.format(n=shot, secs=secs)
    if "first_frame" in roles:
        return _FIRST_ONLY
    return _LAST_ONLY.format(n=shot, secs=secs)


def with_instruction(prompt: str, instruction: str | None) -> str:
    """The instruction, a blank line, then the prompt — §2.1's required layout.

    Skips when the prompt already opens with an alignment line, so a hand-written prompt that
    follows the guide is not given a second, contradictory one.
    """
    if not instruction:
        return prompt
    head = "\n".join(prompt.strip().splitlines()[:2]).lower()
    if any(marker in head for marker in _ALREADY):
        return prompt
    return f"{instruction}\n\n{prompt.strip()}" if prompt.strip() else instruction
