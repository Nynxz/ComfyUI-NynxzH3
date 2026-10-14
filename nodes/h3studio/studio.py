"""H3 Studio — a whole film as one project, rendered a scene at a time.

Three nodes, so the studio's own header stays clean:

    H3 Studio Setup ──setup──▶ H3 Studio ──render──▶ H3 Studio Outputs
    model, clip, vae,           the project            model, positive, noise,
    audio_vae, previous         (H3Studio.vue)         latent, frames, prompt

H3 Studio turns one scene of the project into what MiniMax H3 samples from: positive conditioning
and an empty AV latent sized to that scene. Use its outputs in place of core's MiniMax H3 Image to
Video / Reference to Video; the sampler, model and decode stay yours.

**Continuation.** Wire the previous scene (H3 Studio Clip's video, carried round a loop) into
`previous`, set the scene's continuation to *guide*, and its last 5/22/39 frames are anchored at
frame 0 of this scene — through the same keyframe conditioning core's Add Guide writes, so nothing
in H3 is patched. Those frames are regenerated at the head of this scene; H3 Studio Clip cuts them
after decoding so the scenes butt-join cleanly.
"""

from __future__ import annotations

import logging
import math

import node_helpers
from comfy_api.latest import io

from .._base import NynxzNode
from . import _carry, _control, _live, _marks, _reuse, _track
from ._loras import apply as apply_loras
from ._media import (
    has_audio,
    load_audio,
    load_image,
    load_video,
    load_video_tail,
    path_of,
    video_tail,
)
from ._project import (
    CONTEXT_FRAMES,
    FPS,
    PREVIOUS_FRAME,
    PREVIOUS_SOUND,
    compile_scene,
    normalize,
)
from .io_types import H3StudioLinkType, H3StudioRenderType, H3StudioSetupType, H3StudioType

LOG = logging.getLogger(__name__)


def _core():
    """Core's H3 sizing and encoding helpers, imported rather than copied so they cannot drift."""
    try:
        from comfy_extras import nodes_minimax_h3 as h3
    except ImportError as error:  # pragma: no cover - depends on the installed ComfyUI
        raise ValueError(
            f"H3 Studio needs ComfyUI's MiniMax H3 support ({error}). Update ComfyUI."
        ) from error
    return h3


def _previous_last_frame(setup: dict, project: dict, index: int):
    """The previous scene's last frame, for a scene that opens on it or keeps its setting, and a
    fingerprint of where it came from: the clip a loop carried in (Setup's `previous`), else the
    previous scene's saved render."""
    frames = setup.get("previous_frames")
    if frames is not None:
        last = frames[-1:]
        return last, setup.get("previous_key") or _reuse.frames_key(last, None)
    ref = project["scenes"][index - 1].get("render") if index > 0 else ""
    if not ref:
        raise ValueError(
            f"H3 Studio: scene {index + 1} starts from scene {index}'s last frame, but scene {index} "
            "hasn't been rendered. Render it first, or wire the previous scene into H3 Studio Setup "
            "(Start Loop's current_iteration_value into `previous`)."
        )
    video, _ = load_video_tail(ref, 1, FPS)
    return video, _reuse.digest(_reuse.media_stat(ref))


#: A sound reference's length: 39 frames (1.6 s), the longest of H3's short-clip lengths.
SOUND_SNIPPET = 39


def _mem(label: str) -> None:
    """TEMPORARY: ComfyUI's memory at a step, to find what runs it out of RAM."""
    try:
        with open("/proc/self/status") as status:
            for line in status:
                if line.startswith("VmRSS:"):
                    LOG.info("H3MEM %-34s %6.1f GB", label, int(line.split()[1]) / 1048576)
    except OSError:
        pass


#: The most of the previous clip's end a scene uses: its longest carried head.
TAIL_FRAMES = max(CONTEXT_FRAMES)


def _whole_clip(plan) -> bool:
    """Whether a scene needs all of the previous clip: sound snippets spread across it (placed by
    its length in frames). Everything else uses only its end, and its sound."""
    cont = plan.continuation
    return bool(cont.get("sound_refs")) and cont.get("sound_picture") != "guides"


def _previous_clip(setup: dict, project: dict, index: int, whole: bool = True):
    """The previous scene's clip (frames, audio) and a fingerprint of it: the one a loop carried in
    (Setup's `previous`), else the previous scene's latest render — all of its pictures, or with
    `whole` False only its last few (its sound is always whole)."""
    frames = setup.get("previous_frames")
    if frames is not None and setup.get("previous_scene") in (None, index - 1):
        key = setup.get("previous_key") or _reuse.frames_key(
            frames[-1:], setup.get("previous_audio")
        )
        return frames, setup.get("previous_audio"), key
    record = _reuse.latest(project["scenes"][index - 1]["id"])
    if record is None:
        raise ValueError(
            f"H3 Studio: scene {index + 1} carries scene {index}'s sound, but scene {index} hasn't "
            "been rendered. Render it first."
        )
    if whole:
        frames, audio = load_video(record["ref"], FPS)
    else:
        frames, audio = load_video_tail(record["ref"], TAIL_FRAMES, FPS)
    return frames, audio, _clip_key(record)


def _clip_key(record: dict) -> str:
    """A saved clip's fingerprint: the one it was made under, else its file's."""
    return record.get("key") or _reuse.digest(_reuse.media_stat(record["ref"]))


def _sound_snippet(clip, media: str, black: bool):
    """The k-th of n snippets of the previous clip (`previous:sound:k/n`), spread across it so the
    last ends where the clip does: frames (black when only the sound is wanted) and its sound."""
    import torch

    frames, audio, _ = clip
    k, n = (int(x) for x in media[len(PREVIOUS_SOUND) :].split("/"))
    length = min(SOUND_SNIPPET, frames.shape[0])
    start = round((frames.shape[0] - length) * (k + 1) / max(n, 1))
    part = frames[start : start + length]
    if black:
        part = torch.zeros_like(part)
    track = None
    if audio is not None:
        rate = audio["sample_rate"]
        a, b = round(start / FPS * rate), round((start + length) / FPS * rate)
        track = {"waveform": audio["waveform"][..., a:b], "sample_rate": rate}
    return part, track


#: An audio guide's length: 22 frames (0.9 s), one of H3's short-clip lengths.
GUIDE_SNIPPET = 22
#: The guides' level against the previous scene's sound: a bed under this scene's own.
GUIDE_GAIN = 0.7
#: Where the guides' snippets come from: the previous clip's last seconds, the sound at the cut.
GUIDE_SOURCE_SECONDS = 3.0


def _sound_guides(clip, n: int, frame_count: int, after: int, audio_vae, h3) -> list[dict]:
    """The previous scene's sound pinned through this one: n snippets from its last seconds, as
    audio-only guides from where the carried head ends (`after` frames) on through the scene. H3
    reproduces a guide where it's placed, so the sound world can't drop away between them."""
    _, audio, _ = clip
    if audio is None:
        return []
    rate = audio["sample_rate"]
    total = audio["waveform"].shape[-1]
    length = round(GUIDE_SNIPPET / FPS * rate)
    first = max(0, total - round(GUIDE_SOURCE_SECONDS * rate))
    room = frame_count - after - GUIDE_SNIPPET
    if room <= 0 or total < length:
        return []
    out = []
    for k in range(n):
        a = first + round((total - length - first) * (k / (n - 1) if n > 1 else 1.0))
        snippet = {
            "waveform": audio["waveform"][..., a : a + length] * GUIDE_GAIN,
            "sample_rate": rate,
        }
        latent, _ = h3._encode_ref_audio(audio_vae, snippet)
        # The first starts as the carried head ends (where H3 lets the sound go), the rest spread on.
        at = after + round(room * k / n)
        out.append({"resolved_frame_index": at, "audio_latent": latent, "image": None})
    return out


def _decoded(setup: dict, whole: bool = True) -> dict:
    """`setup` with the previous clip (Setup's `previous`) decoded into frames and sound — a copy
    for this scene alone, dropped when it has rendered. A clip saved to a file is decoded only at
    its end unless the scene needs all of it (`_whole_clip`)."""
    from comfy_api.latest import InputImpl

    video = setup.get("previous_video")
    if video is None or setup.get("previous_frames") is not None:
        return setup
    source = video.get_stream_source() if isinstance(video, InputImpl.VideoFromFile) else None
    if not whole and isinstance(source, str) and video.get_active_trim_window() == (0.0, 0.0):
        frames, audio = video_tail(source, TAIL_FRAMES, FPS)
        return {**setup, "previous_frames": frames, "previous_audio": audio}
    components = video.get_components()
    return {**setup, "previous_frames": components.images, "previous_audio": components.audio}


def _from_latest(setup: dict, scene_id: str, whole: bool) -> dict:
    """`setup` with the previous scene's latest clip as the one to continue from — for a scene
    rendered on its own, outside a loop that would carry the previous scene in. Only its end is
    decoded unless the scene needs all of it (`_whole_clip`)."""
    record = _reuse.latest(scene_id)
    if record is None:
        return setup
    if whole:
        frames, audio = load_video(record["ref"], FPS)
    else:
        frames, audio = load_video_tail(record["ref"], TAIL_FRAMES, FPS)
    latent, _head = _carry.load_sidecar(path_of(record["ref"]))
    return {
        **setup,
        "previous_frames": frames,
        "previous_audio": audio,
        "previous_key": record.get("key"),
        "previous_latent": latent,
    }


def _held(plan, index: int, scene_id: str, record: dict, setup: dict) -> dict:
    """A scene left out of a partial render: it plays its latest clip (H3 Studio Clip hands it
    back), so nothing is encoded for it and its sampler never runs."""
    return {
        "hold": record["ref"],
        "hold_key": record.get("key"),
        "model": setup.get("model"),
        "positive": None,
        "latent": None,
        "prompt": plan.prompt,
        "trim_frames": 0,
        "frames": plan.keep,
        "width": plan.width,
        "height": plan.height,
        "scene": index,
        "scene_id": scene_id,
        "seed": plan.seed,
        "noise_carry": None,
        "carries_picture": False,
        "scene_key": None,
    }


def _continues(scene: dict) -> bool:
    return (scene.get("continuation") or {}).get("mode") not in (None, "cut")


def _needed(proj: dict, only: list[str]) -> set[int]:
    """The scenes a partial render must sample although they weren't picked: those a picked scene
    continues from (directly or through others) that have no clip to continue from."""
    scenes, needed = proj["scenes"], set()
    for c, scene in enumerate(scenes):
        if scene["id"] not in only:
            continue
        j = c
        while j > 0 and _continues(scenes[j]):
            previous = scenes[j - 1]["id"]
            if previous in only or _reuse.latest(previous):
                break
            needed.add(j - 1)
            j -= 1
    return needed


def scenes_to_run(proj: dict) -> list[int]:
    """The scenes a run samples, in order: every one, or for a partial render the picked scenes and
    those `_needed` to continue from. A loop in List mode over these runs one pass per scene that
    actually renders, instead of passing through every scene up to it."""
    only = proj.get("render_only")
    if not only:
        return list(range(len(proj["scenes"])))
    picked = {i for i, sc in enumerate(proj["scenes"]) if sc["id"] in only}
    return sorted(picked | _needed(proj, only))


def _blank(plan, index: int, scene_id: str, setup: dict) -> dict:
    """A scene left out of a partial render that has never been rendered (and no picked scene
    continues from): black frames and silence for its length, so the film keeps its timing."""
    audio_vae = setup.get("audio_vae")
    return {
        **_held(plan, index, scene_id, {"ref": None}, setup),
        "hold": None,
        "blank": True,
        "audio_rate": getattr(audio_vae, "audio_sample_rate", None) if audio_vae else None,
    }


def _carried_now(proj: dict, i: int, plan) -> str | None:
    """What scene `i` continues from, as `render_scene` fingerprints it, from the previous scene's
    latest clip: its key when the scene carries on from it, and that clip's own key too when its
    sound is brought in — as snippets, or as guides (which the music track replaces)."""
    if i == 0:
        return None
    previous = _reuse.latest(proj["scenes"][i - 1]["id"])
    cont = plan.continuation
    carried = None
    if cont.get("mode") not in (None, "cut"):
        carried = previous.get("key") if previous else None
    guides = cont.get("sound_picture") == "guides"
    if cont.get("sound_refs") and not (guides and plan.track):
        carried = f"{carried}|{_clip_key(previous) if previous else None}"
    return carried


def scene_status(project) -> list[dict]:
    """Each scene's latest clip and whether it's up to date: its scene half (see _reuse) as the
    scene stands now — continuing from the previous scene's latest clip — against the one it was
    made under. The render chain (model, sampler) isn't known outside a run, so it isn't compared."""
    proj = normalize(project)
    out = []
    for i, scene in enumerate(proj["scenes"]):
        record = _reuse.latest(scene["id"])
        state = "none"
        if record:
            plan = compile_scene(proj, i, has_audio)
            now = _reuse.scene_key(plan.as_dict(), i, _carried_now(proj, i, plan))
            state = "current" if now == record.get("scene_key") else "stale"
        out.append(
            {
                "id": scene["id"],
                "state": state,
                "ref": record["ref"] if record else None,
                "time": record.get("time") if record else None,
            }
        )
    return out


def takes_fit(project, takes: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Each take marked with whether it fits its scene as the scene stands now — apart from its
    seed, which using the take brings back. A take that doesn't was made from an earlier version
    of the scene (its shots, keyframes, length…), and using it leaves the scene out of date."""
    import copy

    proj = normalize(project)
    out: dict[str, list[dict]] = {}
    for i, scene in enumerate(proj["scenes"]):
        rows = takes.get(scene["id"])
        if not rows:
            continue
        carried = _carried_now(proj, i, compile_scene(proj, i, has_audio))
        keys: dict[int, str] = {}
        marked = []
        for t in rows:
            seed = t.get("seed") if isinstance(t.get("seed"), int) else scene["seed"]
            if seed not in keys:
                trial = copy.deepcopy(proj)
                trial["scenes"][i]["seed"] = seed
                keys[seed] = _reuse.scene_key(
                    compile_scene(trial, i, has_audio).as_dict(), i, carried
                )
            fits = t.get("scene_key") is None or t.get("scene_key") == keys[seed]
            marked.append({**t, "fits": fits})
        out[scene["id"]] = marked
    return out


def _audio_tail(audio: dict, seconds: float) -> dict:
    waveform = audio["waveform"]
    keep = max(1, round(seconds * audio["sample_rate"]))
    return {"waveform": waveform[..., -keep:], "sample_rate": audio["sample_rate"]}


def _film_after(proj: dict, index: int) -> dict | None:
    """The project, when the film is to be saved once this scene's clip lands: the last scene of a
    full render, with the film's saving left on."""
    if proj.get("render_only") or not proj["film"]["auto"] or index != len(proj["scenes"]) - 1:
        return None
    return proj


def render_scene(setup: dict, project, scene: int | None) -> dict:
    """One scene of the project as H3 conditioning, a sized AV latent and the head trim."""
    _mem("render_scene start")
    clip, vae = setup["clip"], setup["vae"]
    audio_vae = setup.get("audio_vae")
    previous_frames, previous_audio = setup.get("previous_frames"), setup.get("previous_audio")
    h3 = _core()
    proj = normalize(project)
    index = proj["active"] if scene is None else scene
    if index >= len(proj["scenes"]):
        raise ValueError(
            f"H3 Studio: scene {index + 1} does not exist; the project has {len(proj['scenes'])}."
        )
    plan = compile_scene(proj, index, has_audio)
    scene_id = proj["scenes"][index]["id"]
    only = proj.get("render_only")
    if only and scene_id not in only:
        if record := _reuse.latest(scene_id):
            return _held(plan, index, scene_id, record, setup)
        if index not in _needed(proj, only):
            return _blank(plan, index, scene_id, setup)
    setup = _decoded(setup, _whole_clip(plan))
    _mem("previous clip decoded")
    carried = setup.get("previous_scene")
    if setup.get("previous_frames") is not None and carried is not None and carried != index - 1:
        # A loop over only the picked scenes carries the clip of the pass before, which isn't the
        # previous scene when that one didn't render this run: continue from its latest clip.
        setup = {
            **setup,
            "previous_frames": None,
            "previous_audio": None,
            "previous_key": None,
            "previous_latent": None,
        }
        previous_frames = previous_audio = None
    if (
        index > 0
        and setup.get("previous_frames") is None
        and plan.continuation.get("mode") not in (None, "cut")
    ):
        setup = _from_latest(setup, proj["scenes"][index - 1]["id"], _whole_clip(plan))
        previous_frames, previous_audio = setup.get("previous_frames"), setup.get("previous_audio")
    width, height = plan.width, plan.height
    latent, frame_count = h3._empty_av_latent(width, height, plan.frames)
    _mem("latent made")
    last_frame, last_key = None, None
    if plan.continuation.get("mode") in ("first_frame", "reference"):
        last_frame, last_key = _previous_last_frame(setup, proj, index)

    def picture(media: str):
        return last_frame if media == PREVIOUS_FRAME else load_image(media)

    def snap(n: float) -> int:
        return max(h3.CANVAS_MULTIPLE, round(n / h3.CANVAS_MULTIPLE) * h3.CANVAS_MULTIPLE)

    #: What each reference was given to H3 as (size, frames, sound), by tag: for the summary,
    #: kept off the references themselves, which make up the scene's fingerprint.
    given: dict[str, dict] = {}
    keyframes = []
    for k in plan.keyframes:
        # A keyframe fills the canvas: cropped to its shape, or stretched onto it.
        fit = "disabled" if k.get("fit") == "stretch" else "center"
        image = h3._resize(picture(k["media"]), width, height, fit)
        # Scene time, after the carried head of a continued scene.
        keyframes.append(
            {"resolved_frame_index": min(k["frame"] + plan.lead, frame_count - 1), "image": image}
        )

    previous_clip = None
    if plan.task == "ref2va":
        # Same presentation and payload as core's MiniMax H3 Reference to Video, per reference:
        # pictures, then videos (a soundtrack's <Audio j> label right before its <Video k>), then
        # standalone audio. Only a 'semantic' picture skips its latent.
        ref_items, ref_blocks = [], []
        for ref in plan.refs:
            if ref["alias"]:
                continue
            shown_as = given.setdefault(ref["tag"], {})
            if ref["kind"] == "image":
                image = picture(ref["media"])
                h, w = image.shape[1], image.shape[2]
                scale = min(1.0, math.sqrt((width * height) / (w * h))) * ref["size"]
                tw, th = snap(w * scale), snap(h * scale)
                resized = h3._resize(image, tw, th, "disabled")
                shown_as["size"] = (tw, th)
                ref_items.append({"type": "image", "data": resized})
                if ref["role"] == "reference":
                    ref_blocks.append(
                        {
                            "kind": "image",
                            "latent_h": th // 16,
                            "latent_w": tw // 16,
                            "latent": vae.encode(resized),
                        }
                    )
            elif ref["kind"] == "video":
                if ref["media"].startswith(PREVIOUS_SOUND):
                    if previous_clip is None:
                        previous_clip = _previous_clip(setup, proj, index)
                    video_frames, track = _sound_snippet(
                        previous_clip,
                        ref["media"],
                        proj["scenes"][index]["continuation"]["sound_picture"] == "black",
                    )
                else:
                    video_frames, track = load_video(ref["media"], h3.FPS)
                soundtrack = track if ref["soundtrack_tag"] else None
                vh, vw = video_frames.shape[1], video_frames.shape[2]
                cw, ch = h3.adapt_canvas(vw, vh)
                if vw * vh < cw * ch:
                    cw, ch = snap(vw), snap(vh)
                cw, ch = snap(cw * ref["size"]), snap(ch * ref["size"])
                frames = h3._resize(video_frames, cw, ch, "disabled")[:frame_count]
                n = frames.shape[0]
                if n < 5:
                    raise ValueError(
                        f"H3 Studio: @{ref['name']} is too short — reference videos need at least 5 frames."
                    )
                while n % 17 != 5:
                    n -= 1
                frames = frames[:n]
                shown_as.update(size=(cw, ch), frames=n, sound=soundtrack is not None)
                if soundtrack is not None:
                    ref_items.append({"type": "audio"})
                sample_idx = list(range(0, frames.shape[0], h3.FPS // 2))
                ref_items.append(
                    {
                        "type": "video",
                        "data": frames[sample_idx],
                        "timestamps": [i / 2.0 for i in range(len(sample_idx))],
                    }
                )
                z = vae.encode(frames)
                audio_latent, ref_audio_t = (None, 0)
                if soundtrack is not None and audio_vae is not None:
                    audio_latent, ref_audio_t = h3._encode_ref_audio(audio_vae, soundtrack)
                ref_blocks.append(
                    {
                        "kind": "video_audio" if ref_audio_t else "video",
                        "latent_t": z.shape[2],
                        "latent_h": ch // 16,
                        "latent_w": cw // 16,
                        "ref_audio_t": ref_audio_t,
                        "latent": z,
                        "audio_latent": audio_latent,
                    }
                )
            else:
                ref_items.append({"type": "audio"})
                if ref["media"].startswith(PREVIOUS_SOUND):
                    if previous_clip is None:
                        previous_clip = _previous_clip(setup, proj, index)
                    sound = _sound_snippet(previous_clip, ref["media"], black=True)[1]
                    if sound is None:
                        raise ValueError(
                            f"H3 Studio: scene {index + 1} carries scene {index}'s sound, but "
                            f"scene {index}'s clip has none."
                        )
                else:
                    sound = load_audio(ref["media"])
                if audio_vae is not None and sound is not None:
                    audio_latent, ref_audio_t = h3._encode_ref_audio(audio_vae, sound)
                    ref_blocks.append(
                        {"kind": "audio", "ref_audio_t": ref_audio_t, "audio_latent": audio_latent}
                    )
        _mem("references encoded")
        tokens = clip.tokenize(plan.prompt, minimax_ref_items=ref_items)
    else:
        # i2va/l2va/fl2va present their keyframes to the text encoder as <Picture 1..2>, in
        # time order — the order the prompt's alignment line names them in.
        pictures = [
            k["image"] for k in keyframes if k["resolved_frame_index"] in (0, frame_count - 1)
        ]
        tokens = clip.tokenize(plan.prompt, images=pictures)
        ref_blocks = []
    positive = clip.encode_from_tokens_scheduled(tokens)
    _mem("text encoded")

    trim = 0
    noise_carry = None
    carried = last_key
    mode = plan.continuation.get("mode")
    context = 0
    if mode in ("guide", "sound") and previous_frames is not None:
        # The carried head is cut off after decoding, so at least one grid step stays new.
        context = min(plan.continuation["frames"], previous_frames.shape[0], frame_count - 17)
        while context > 5 and context % 17 != 5:
            context -= 1
        if context < 5:
            plan.warnings.append(
                "This scene or the previous clip is too short to carry anything over, so it cuts."
            )
    if context >= 5:
        # "guide" carries the picture and the sound; "sound" only the sound: the picture cuts, and
        # its first `context` frames (unguided) are cut off with the regenerated sound under them.
        picture = mode == "guide"
        carried_latent = setup.get("previous_latent")
        tail = (
            _carry.latent_tail(carried_latent, context, width=width, height=height)
            if carried_latent is not None
            else None
        )
        if tail is not None:
            # The previous scene's own sampled tokens: no decode and re-encode in between.
            guide = {"resolved_frame_index": 0, "latent": tail[0], "audio_latent": tail[1]}
        else:
            guide = {"resolved_frame_index": 0}
            if picture:
                frames_tail = h3._resize(previous_frames[-context:], width, height, "center")
                guide["latent"] = vae.encode(frames_tail)
            if previous_audio is not None and audio_vae is not None:
                audio_latent, _ = h3._encode_ref_audio(
                    audio_vae, _audio_tail(previous_audio, context / h3.FPS)
                )
                guide["audio_latent"] = audio_latent
        if not picture:
            guide.pop("latent", None)
        if "latent" in guide or "audio_latent" in guide:
            # The previous clip's tail ends where this scene starts, after the head.
            guide["resolved_frame_index"] = max(0, plan.lead - context)
            # The carried head is cut off after decoding; a keyframe inside it would fight it.
            keyframes = [
                k for k in keyframes if k["resolved_frame_index"] >= max(context, plan.lead)
            ]
            keyframes.insert(0, {**guide, "image": None})
            trim = context
            noise_carry = _carry.noise_carry(proj, index, context, latent, picture=picture)
            carried = setup.get("previous_key") or _reuse.frames_key(
                previous_frames[-context:], previous_audio
            )
        else:
            plan.warnings.append(
                "The previous scene has no sound to carry over, so this scene just cuts."
            )

    # A continued scene's head is cut off whatever it was guided by: the scene starts after it.
    if plan.lead:
        trim = plan.lead
    cont = plan.continuation
    if (
        cont.get("sound_refs")
        and cont.get("sound_picture") == "guides"
        and audio_vae is not None
        and not plan.track
    ):
        if previous_clip is None:
            previous_clip = _previous_clip(setup, proj, index, whole=False)
        guides = _sound_guides(
            previous_clip, cont["sound_refs"], trim + plan.keep, trim, audio_vae, h3
        )
        keyframes += guides
        LOG.info(
            "H3 Studio: scene %d carries scene %d's sound: %d guide(s) at %s into the scene",
            index + 1,
            index,
            len(guides),
            ", ".join(f"{(g['resolved_frame_index'] - trim) / FPS:.1f}s" for g in guides)
            or "none (too short)",
        )

    if plan.track:
        if audio_vae is None:
            plan.warnings.append(
                "The music track needs Setup's audio_vae; this scene renders without it."
            )
        elif music := _track.guide(plan.track, latent, audio_vae, h3, plan.warnings):
            keyframes.append(music)

    conditioning_keyframes = []
    for k in keyframes:
        entry = {key: value for key, value in k.items() if key != "image"}
        if k.get("image") is not None:
            entry["latent"] = vae.encode(k["image"])
        conditioning_keyframes.append(entry)
    values = {}
    if conditioning_keyframes:
        values["minimax_keyframes"] = conditioning_keyframes
    if ref_blocks:
        values["minimax_refs"] = ref_blocks
    if values:
        positive = node_helpers.conditioning_set_values(positive, values)
    model, positive = apply_loras(
        setup.get("model"), positive, plan.loras, plan.warnings, plan.settings
    )
    control_note = None
    if plan.controls:
        before = model
        model = _apply_control(setup, model, vae, plan.controls[0], trim, plan.warnings)
        c = plan.controls[0]
        span = _control.describe(c.get("from"), c.get("to"))
        control_note = (
            f"@{c['name']} through {setup.get('controlnet')}, strength {c['strength']:.2f} "
            f"until {round(c['until'] * 100)}%{f', {span} of the scene' if span else ''}"
            if model is not before
            else f"@{c['name']} skipped (see warnings)"
        )
    if plan.settings.get("verbose"):
        LOG.info(
            "%s",
            _summary(
                proj, index, plan, frame_count, keyframes, trim, mode, setup, control_note, given
            ),
        )
    if plan.settings.get("log_prompt"):
        LOG.info("H3 Studio scene %d prompt:\n%s", index + 1, plan.prompt)
    for warning in dict.fromkeys(plan.warnings):
        LOG.warning("H3 Studio scene %d: %s", index + 1, warning)
    return {
        "model": model,
        "audio_vae": setup.get("audio_vae"),
        #: The live preview's settings, for H3 Studio Outputs.
        "preview": {k: plan.settings.get(k) for k in ("preview", "preview_vae", "preview_sound")},
        "positive": positive,
        "latent": latent,
        "prompt": plan.prompt,
        "trim_frames": trim,
        "frames": frame_count,
        #: The scene's own frames, kept after the head: H3's grid can make the render longer.
        "keep_frames": plan.keep,
        #: Frames of handle after them, whose sound is kept beside the clip.
        "tail_frames": plan.tail,
        "width": width,
        "height": height,
        "scene": index,
        "scene_id": scene_id,
        "seed": plan.seed,
        "noise_carry": noise_carry,
        "carries_picture": mode == "guide",
        # A scene carrying the previous one's sound is out of date when that clip changes.
        "scene_key": _reuse.scene_key(
            plan.as_dict(),
            index,
            f"{carried}|{previous_clip[2]}" if previous_clip is not None else carried,
        ),
        "film": _film_after(proj, index),
        #: The scene's title and shots, marked in the saved clip's `h3studio` tag.
        "marks": proj["scenes"][index],
    }


#: Sent when the studio renders a scene, so its editor can show that scene's sampling previews live.
RENDER_EVENT = "nynxz.h3studio.render"
#: Sent when H3 Studio Clip has saved a scene's finished clip, so the editor can play it.
CLIP_EVENT = "nynxz.h3studio.clip"
#: Sent when a film is saved, so the studio's Renders sidebar shows it.
FILM_EVENT = "nynxz.h3studio.film"


def _send(event: str, payload: dict) -> None:
    try:
        from server import PromptServer

        PromptServer.instance.send_sync(event, payload, PromptServer.instance.client_id)
    except Exception:  # noqa: BLE001 - the editor's view is a nicety; never fail the render over it
        pass


def _announce(unique_id, dynprompt, render: dict) -> None:
    """Tell the editor which scene this run (or loop pass) is rendering, and remember which studio
    node made the render so H3 Studio Clip can report back to it. The id is the one on the canvas:
    inside a loop the studio runs as a generated copy."""
    node_id = dynprompt.get_display_node_id(unique_id) if dynprompt is not None else unique_id
    render["studio_node"] = str(node_id)
    _send(
        RENDER_EVENT,
        {"node_id": str(node_id), "scene": render["scene"], "frames": render["frames"]},
    )


class NynxzH3StudioSetup(NynxzNode):
    CATEGORY = f"{NynxzNode.CATEGORY}/H3/Studio"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3.StudioSetup",
            display_name="H3 Studio Setup",
            description="The models H3 Studio renders with, and the previous scene it continues from, "
            "gathered onto one wire.",
            inputs=[
                io.Model.Input(
                    "model",
                    tooltip="The H3 model. H3 Studio Outputs gives it back with the scene's LoRAs and "
                    "control video applied — sample with that model.",
                ),
                io.Clip.Input("clip", tooltip="The MiniMax H3 text encoder."),
                io.Vae.Input(
                    "vae", tooltip="The H3 video VAE, for keyframes, references and continuation."
                ),
                io.Vae.Input(
                    "audio_vae",
                    optional=True,
                    tooltip="The H3 audio VAE. Needed to carry the previous scene's sound across a continuation.",
                ),
                io.Combo.Input(
                    "controlnet",
                    options=_controlnets(),
                    default="none",
                    optional=True,
                    tooltip="The MiniMax H3 Fun ControlNet, from models/model_patches. Loaded only when a "
                    "scene has a control video (a video reference used as Control), which then steers its "
                    "layout and camera. Needs the model wired.",
                ),
                io.Video.Input(
                    "previous",
                    optional=True,
                    tooltip="The previous scene as one video (frames and sound), e.g. Start Loop's "
                    "current_iteration_value carrying H3 Studio Clip. Empty on a loop's first pass, which "
                    "then starts fresh. Used when previous_frames isn't wired.",
                ),
                io.Int.Input(
                    "scene",
                    default=0,
                    min=0,
                    max=999,
                    optional=True,
                    force_input=True,
                    tooltip="Which scene to render, counting from 0 — wire Start Loop's iteration_index to "
                    "render the film scene by scene (or its list_item, looping over H3 Studio Scenes' "
                    "`picked`). Unwired, the scene selected in the studio renders.",
                ),
                io.Clip.Input(
                    "rewrite_clip",
                    optional=True,
                    lazy=True,
                    tooltip="The text model the studio's shot writer (Rewrite on a shot) drafts with, "
                    "e.g. CLIPLoader on Qwen3-VL, through H3 CLIP LoRA. Each draft queues this chain on "
                    "its own; renders never load it. Unwired, the writer uses the model picked in the "
                    "studio's settings.",
                ),
            ],
            outputs=[H3StudioSetupType.Output(display_name="setup")],
        )

    @classmethod
    def check_lazy_status(cls, **kwargs) -> list[str]:
        # rewrite_clip is read by the shot writer's own jobs, never by a render.
        return []

    @classmethod
    def execute(
        cls,
        model,
        clip,
        vae,
        audio_vae=None,
        controlnet="none",
        previous=None,
        scene=None,
        rewrite_clip=None,
    ):
        previous_key = previous_latent = previous_scene = None
        # The previous clip goes on as it came (a saved file, not decoded): this output stays in a
        # loop's cache for the whole render, and decoded frames there ran full renders out of RAM.
        # The scene decodes it when it needs its frames.
        if previous is not None:
            previous_key = getattr(previous, "h3_key", None)
            previous_latent = getattr(previous, "h3_latent", None)
            previous_scene = getattr(previous, "h3_scene", None)
        return io.NodeOutput(
            {
                "previous_key": previous_key,
                "previous_latent": previous_latent,
                "previous_scene": previous_scene,
                "scene": scene,
                "model": model,
                "controlnet": controlnet if controlnet and controlnet != "none" else None,
                "clip": clip,
                "vae": vae,
                "audio_vae": audio_vae,
                "previous_frames": None,
                "previous_audio": None,
                "previous_video": previous,
            }
        )


ROLE_WORDS = {
    ("image", "reference"): "look + meaning",
    ("image", "semantic"): "meaning only",
    ("video", "reference"): "look + motion",
    ("video", "blocking"): "blocking",
    ("audio", "reference"): "sound",
}


def _summary(
    proj, index, plan, frame_count, keyframes, trim, mode, setup, control_note, given
) -> str:
    """One scene's render in a few readable lines: what H3 is given, and what steers it."""
    scene = proj["scenes"][index]
    title = f' "{scene["title"]}"' if scene.get("title") else ""
    lines = [
        f"H3 Studio · scene {index + 1}{title} · {plan.task} · {frame_count} frames "
        f"({frame_count / FPS:.2f}s) · {plan.width}x{plan.height} · seed {plan.seed}"
    ]

    shown = [r for r in plan.refs if not r.get("alias")]
    if shown:
        lines.append(f"  references — H3 sees {len(shown)}:")
        width = max(len(r["tag"]) for r in shown)
        for r in shown:
            names = " / ".join(
                dict.fromkeys(f"@{x['name']}" for x in plan.refs if x["tag"] == r["tag"])
            )
            role = ROLE_WORDS.get((r["kind"], r["role"]), r["role"])
            seen = given.get(r["tag"], {})
            detail = []
            if "size" in seen:
                detail.append("{}x{}".format(*seen["size"]))
            if "frames" in seen:
                detail.append(f"{seen['frames']} frames")
            if seen.get("sound"):
                detail.append(f"its sound as {r['soundtrack_tag']}")
            lines.append(
                f"    {r['tag'].ljust(width)}  {names:<22} {role}"
                + (f" — {', '.join(detail)}" if detail else "")
            )
    else:
        lines.append("  references — none (H3 works from the text alone)")
    edges = []
    for k in keyframes:
        if k.get("image") is None:
            continue
        f = k["resolved_frame_index"]
        edges.append("first" if f == 0 else "last" if f == frame_count - 1 else f"frame {f}")
    if edges:
        lines.append(f"  keyframes: {', '.join(edges)}")
    guides = [
        k["resolved_frame_index"]
        for k in keyframes
        if k.get("image") is None
        and "latent" not in k
        and k["resolved_frame_index"] > 0
        and k["resolved_frame_index"] >= trim
    ]
    if guides:
        at = ", ".join(f"{(f - trim) / FPS:.1f}s" for f in guides)
        lines.append(f"  carry sound: the previous scene's sound pinned at {at} into the scene")

    if trim:
        what = "picture and sound" if mode == "guide" else "sound only"
        source = (
            "its sampled latent"
            if setup.get("previous_latent") is not None
            else "its decoded frames"
        )
        lines.append(f"  continues the previous scene: {trim} frames of {what}, from {source}")
    elif index > 0:
        lines.append(f"  from the previous scene: {mode or 'cut'}")

    if plan.loras:
        lines.append(
            "  LoRAs: "
            + ", ".join(
                f"{lane['name']} {lane['strength']:g}" + (" (shaped)" if lane["sampling"] else "")
                for lane in plan.loras
            )
        )
    if control_note:
        lines.append(f"  ControlNet: {control_note}")
    lines.append(
        f"  prompt: {len(plan.prompt):,} characters (Log the prompt in Settings prints it)"
    )
    for w in dict.fromkeys(plan.warnings):
        lines.append(f"  ! {w}")
    return "\n".join(lines)


def _controlnets() -> list[str]:
    try:
        import folder_paths

        return ["none", *folder_paths.get_filename_list("model_patches")]
    except Exception:  # noqa: BLE001 - no ComfyUI (tests)
        return ["none"]


#: The loaded Fun ControlNet, kept between scenes: (file name, model patch).
_control_cache: tuple[str, object] | None = None


def _control_patch(name: str):
    global _control_cache
    if _control_cache is None or _control_cache[0] != name:
        from comfy_extras.nodes_model_patch import ModelPatchLoader

        _control_cache = (name, ModelPatchLoader().load_model_patch(name)[0])
    return _control_cache[1]


class _ControlLog:
    """What a control video actually did while sampling, step by step: when it was on, and how
    far it pushed the model's stream (the change at the first injected block, as a share of the
    stream there). Logged when it switches off, and when sampling ends if it never did."""

    def __init__(self, name: str, until: float, strength: float, sigma_end: float):
        self.name, self.until, self.strength, self.sigma_end = name, until, strength, sigma_end
        self.sigmas: list[float] = []
        self.on: list[bool] = []
        self.nudges: list = []
        self.reported = False

    def step(self, sigma: float, active: bool) -> None:
        if self.sigmas and abs(self.sigmas[-1] - sigma) < 1e-6:
            return
        if active and not any(self.on):
            LOG.info(
                "H3 Studio: @%s control on at step %d (sigma %.3f), strength %.2f",
                self.name,
                len(self.sigmas) + 1,
                sigma,
                self.strength,
            )
        if not active and self.on and self.on[-1]:
            LOG.info(
                "H3 Studio: @%s control off from step %d (sigma %.3f < %.3f, until %d%%) — %s",
                self.name,
                len(self.sigmas) + 1,
                sigma,
                self.sigma_end,
                round(self.until * 100),
                self.summary(),
            )
            self.reported = True
        self.sigmas.append(sigma)
        self.on.append(active)

    def summary(self) -> str:
        steered = sum(self.on)
        nudges = [float(n) for n in self.nudges]
        push = (
            f", moving the stream {100 * sum(nudges) / len(nudges):.1f}% on average"
            if nudges
            else ""
        )
        return f"steered {steered} of {len(self.on)} steps so far{push}"

    def end(self) -> None:
        if self.on and not self.reported:
            LOG.info(
                "H3 Studio: @%s control finished: %s",
                self.name,
                self.summary().replace(" so far", ""),
            )
        self.sigmas, self.on, self.nudges, self.reported = [], [], [], False


def _WatchedControl(
    name: str,
    until: float,
    model_patch,
    vae,
    video,
    mask,
    source,
    strength,
    sigma_start,
    sigma_end,
    window: tuple[float | None, float | None] = (None, None),
    lead: int = 0,
):
    """Core's MiniMaxH3FunControlPatch, logging what it does (see `_ControlLog`), and — when the
    control steers only a stretch of the scene (`window`, seconds) — scaling its push on each
    latent frame by how far into that stretch the frame is (`_control.latent_weights`)."""
    from comfy_extras.nodes_minimax_h3 import MiniMaxH3FunControlPatch

    class Watched(MiniMaxH3FunControlPatch):
        weights_for: tuple | None = None
        row_weights = None

        def _rows(self, layout, skip):
            """A weight per packed row: the target video's rows by their latent frame, 1 elsewhere."""
            key = (layout.signature, skip.device, skip.dtype)
            if self.weights_for != key:
                import torch

                latent_t = layout.signature[1]
                start, stop = next((a, b) for a, b, kind in layout.segments if kind == "video")
                per_frame = torch.tensor(
                    _control.latent_weights(latent_t, *window, lead=lead), dtype=skip.dtype
                )
                rows = torch.ones(skip.shape[-2], dtype=skip.dtype)
                rows[start:stop] = per_frame.repeat_interleave((stop - start) // latent_t)
                self.row_weights = rows.to(skip.device).unsqueeze(-1)
                self.weights_for = key
                LOG.info(
                    "H3 Studio: @%s steers %d of %d latent frames: %s of the scene; its video's "
                    "first frame is at %.2f s",
                    name,
                    sum(1 for w in per_frame.tolist() if w > 0),
                    latent_t,
                    _control.landed(per_frame.tolist(), lead),
                    window[0] or 0.0,
                )
            return self.row_weights

        def _step(self, block_index, args, out):
            if window == (None, None) or not self.active:
                return super().after_block(block_index, args, out)
            # Core's after_block, with the ControlNet's push weighted per row before it's added.
            control_index = self.model_patch.model.injection_layers.index(block_index)
            if control_index == 0:
                self.control_latent = self.control_latent.to(out["img"].device)
                self.control_stream = self.model_patch.model.init_stream(
                    self.pristine_stream, self.control_latent, args["layout"], args["t_emb"]
                )
                self.pristine_stream = None
            self.control_stream, skip = self.model_patch.model.step(
                control_index,
                self.control_stream,
                args["t_emb"],
                args["mod_segments"],
                args["rope_freqs"],
                transformer_options=args["transformer_options"],
            )
            skip[args["layout"].audio_pos.to(skip.device)] = 0
            skip.mul_(self._rows(args["layout"], skip))
            out["img"].add_(skip, alpha=self.strength)
            return out

        def diffusion_model_wrapper(
            self, executor, x, timestep, context, transformer_options=None, **kwargs
        ):
            transformer_options = transformer_options or {}
            sigmas = transformer_options.get("sigmas")
            sigma = float(sigmas[0]) if sigmas is not None else float(timestep.flatten()[0]) / 1000
            self.log.step(sigma, self.sigma_end <= sigma <= self.sigma_start)
            return super().diffusion_model_wrapper(
                executor, x, timestep, context, transformer_options, **kwargs
            )

        def after_block(self, block_index, args, out):
            first = self.active and block_index == self.model_patch.model.injection_layers[0]
            if not first:
                return self._step(block_index, args, out)
            import torch

            before = out["img"][:, :1024].detach().clone()
            out = self._step(block_index, args, out)
            moved = torch.linalg.vector_norm((out["img"][:, :1024] - before).float())
            self.log.nudges.append(moved / torch.linalg.vector_norm(before.float()).clamp_min(1e-6))
            return out

        def cleanup(self):
            self.log.end()
            super().cleanup()

    patch = Watched(model_patch, vae, video, mask, source, strength, sigma_start, sigma_end)
    patch.log = _ControlLog(name, until, strength, sigma_end)
    return patch


def _apply_control(setup: dict, model, vae, control: dict, trim: int, warnings: list[str]):
    """The scene's model steered by its control video through H3's Fun ControlNet — core's Apply
    MiniMax H3 Fun ControlNet, done here so it follows each scene's own video."""
    _mem("control start")
    if not setup.get("controlnet"):
        warnings.append(
            f"@{control['name']} is a control video, but no ControlNet is picked on H3 Studio Setup; "
            "it's left out."
        )
        return model
    if model is None:
        warnings.append(
            f"@{control['name']} needs the model wired into H3 Studio Setup; it's left out."
        )
        return model
    import torch

    frames, _ = load_video(control["media"], FPS)
    # The video starts where its stretch of the scene does (`from`, like a clip placed on the
    # timeline), and a continuation's carried head comes first in the latent: hold the video's first
    # frame under both, so its frame 0 meets the scene at `from`.
    hold = trim + round((control.get("from") or 0.0) * FPS)
    if hold:
        frames = torch.cat([frames[:1].repeat(hold, 1, 1, 1), frames])
    patched = model.clone()
    sampling = patched.get_model_object("model_sampling")
    window = (control.get("from"), control.get("to"))
    LOG.info(
        "H3 Studio: @%s steers the scene through %s (strength %.2f until %d%%, %d frames%s). "
        "Sample with H3 Studio Outputs' model — a 'control on' line follows once sampling starts; "
        "without one, the sampler isn't using it.",
        control["name"],
        setup["controlnet"],
        control["strength"],
        round(control["until"] * 100),
        frames.shape[0],
        f", {_control.describe(*window)} of the scene" if window != (None, None) else "",
    )
    _WatchedControl(
        control["name"],
        control["until"],
        _control_patch(setup["controlnet"]),
        vae,
        frames[..., :3].movedim(-1, 1),
        None,
        None,
        control["strength"],
        float(sampling.percent_to_sigma(0.0)),
        float(sampling.percent_to_sigma(control["until"])),
        window,
        trim,
    ).register(patched)
    return patched


def _linked_project(dynprompt, studio: str):
    """The project on the H3 Studio node `studio` (its id in the graph), from the prompt itself —
    read, never wired, so a node outside a loop can know about a studio inside it. Inside a subgraph
    the prompt's id carries the subgraph's prefix (`<subgraph>:<id>`)."""
    if dynprompt is None or not studio:
        return None
    prompt = getattr(dynprompt, "original_prompt", {}) or {}
    for node_id, node in prompt.items():
        if node.get("class_type") != "nynxz.H3.Studio":
            continue
        if str(node_id) == studio or str(node_id).endswith(f":{studio}"):
            project = node.get("inputs", {}).get("project")
            return project if isinstance(project, (dict, str)) else None
    return None


class NynxzH3StudioScenes(NynxzNode):
    CATEGORY = f"{NynxzNode.CATEGORY}/H3/Studio"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3.StudioScenes",
            display_name="H3 Studio Scenes",
            description="How many scenes an H3 Studio has, for the loop that renders them — without a "
            "wire from the studio (which sits inside the loop, so a wire would be a cycle). Put it "
            "outside the loop: `scene` into Start Loop in List mode (one pass per scene), or `count` "
            "into its iteration count. For a loop that runs only the scenes being rendered, use "
            "`picked` instead, with Start Loop's list_item into H3 Studio Setup's scene. Pick the "
            "studio on the node.",
            search_aliases=["h3 loop", "scene count", "number of scenes"],
            inputs=[
                H3StudioLinkType.Input(
                    "link",
                    optional=True,
                    tooltip="The H3 Studio it follows, picked from the workflow's studios. Its scene "
                    "count rides along so ComfyUI notices when scenes are added or removed.",
                ),
            ],
            outputs=[
                io.Int.Output(
                    display_name="scene",
                    is_output_list=True,
                    tooltip="Each scene's index, 0 up: into Start Loop's `list` (List mode).",
                ),
                io.Int.Output(
                    display_name="count", tooltip="How many scenes: Start Loop's iteration count."
                ),
                io.Int.Output(
                    display_name="picked",
                    is_output_list=True,
                    tooltip="Only the scenes a Render ▸ scene renders (every scene for a full render): "
                    "into Start Loop's `list`, with its list_item — not iteration_index — into H3 "
                    "Studio Setup's scene. The loop then makes one pass per scene that renders.",
                ),
            ],
            hidden=[io.Hidden.dynprompt],
        )

    @classmethod
    def execute(cls, link=None):
        link = link if isinstance(link, dict) else {}
        studio, count = str(link.get("studio") or ""), int(link.get("count") or 1)
        project = _linked_project(cls.hidden.dynprompt, str(studio).strip())
        picked = None
        if project is not None:
            proj = normalize(project)
            count = len(proj["scenes"])
            # Only the scenes that render this run: the rest keep their latest clips.
            picked = scenes_to_run(proj)
        elif studio:
            LOG.warning(
                "H3 Studio Scenes: no H3 Studio #%s in this workflow; using count %d", studio, count
            )
        count = max(1, int(count))
        every = list(range(count))
        return io.NodeOutput(every, count, picked or every)


class NynxzH3Studio(NynxzNode):
    CATEGORY = f"{NynxzNode.CATEGORY}/H3/Studio"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3.Studio",
            display_name="H3 Studio",
            description="Plan a MiniMax H3 film on a timeline — scenes, shots, keyframes and references — "
            "and render it a scene at a time. Feed it from H3 Studio Setup; break its render out with "
            "H3 Studio Outputs.",
            search_aliases=["minimax", "h3", "video timeline", "storyboard", "long video"],
            inputs=[
                H3StudioSetupType.Input("setup", tooltip="From H3 Studio Setup."),
                H3StudioType.Input("project", optional=True),
            ],
            outputs=[
                H3StudioRenderType.Output(display_name="render", tooltip="Into H3 Studio Outputs.")
            ],
            hidden=[io.Hidden.unique_id, io.Hidden.dynprompt],
        )

    @classmethod
    def execute(cls, setup, project=None):
        render = render_scene(setup, project, setup.get("scene"))
        _announce(cls.hidden.unique_id, cls.hidden.dynprompt, render)
        return io.NodeOutput(render)


#: H3 Studio Outputs' sampler side: positive, latent, model, noise.
_SAMPLER_OUTPUTS = {0, 1, 2, 3}


def _samples_on_every_pass(dynprompt) -> bool:
    """Whether a node on an End Loop's terminations (run on every pass) depends on H3 Studio
    Outputs' sampler side — other than through H3 Studio Clip, which only asks for its decoded
    frames when it renders. A scene a partial render skips can't skip its sampler then."""
    prompt = getattr(dynprompt, "original_prompt", None) or {}
    stack = [
        value[0]
        for node in prompt.values()
        if node.get("class_type") == "EndLoop"
        for name, value in node.get("inputs", {}).items()
        if name.startswith("termination") and isinstance(value, list) and len(value) == 2
    ]
    seen = set()
    while stack:
        node_id = str(stack.pop())
        if node_id in seen or node_id not in prompt:
            continue
        seen.add(node_id)
        node = prompt[node_id]
        if node.get("class_type") == "nynxz.H3.StudioClip":
            continue
        for value in node.get("inputs", {}).values():
            if not (isinstance(value, list) and len(value) == 2):
                continue
            source = prompt.get(str(value[0]), {})
            if (
                source.get("class_type") == "nynxz.H3.StudioOutputs"
                and value[1] in _SAMPLER_OUTPUTS
            ):
                return True
            stack.append(value[0])
    return False


class NynxzH3StudioOutputs(NynxzNode):
    CATEGORY = f"{NynxzNode.CATEGORY}/H3/Studio"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3.StudioOutputs",
            display_name="H3 Studio Outputs",
            description="Breaks an H3 Studio render out into conditioning, latent and the scene's details.",
            inputs=[H3StudioRenderType.Input("render", tooltip="From H3 Studio.")],
            outputs=[
                io.Model.Output(
                    display_name="model",
                    tooltip="The model from H3 Studio Setup with this scene's LoRAs (lanes with a curve "
                    "over the steps ride on `positive` as hooks) and its control video applied. Sampling with it "
                    "plays each step on the studio's monitor (Live preview in Studio Settings).",
                ),
                io.Conditioning.Output(display_name="positive"),
                io.Noise.Output(
                    display_name="noise",
                    tooltip="The scene's noise, from its own seed — wire it to the sampler's noise. Re-roll "
                    "a scene in the studio and only that scene (and those continuing from it) renders "
                    "again. A continuation's first tokens get the very noise the previous scene drew "
                    "for the frames they regenerate, so the two start from one field.",
                ),
                io.Latent.Output(display_name="latent"),
                io.Int.Output(
                    display_name="frames", tooltip="The scene's length in frames, at 24 fps."
                ),
                io.String.Output(
                    display_name="prompt", tooltip="The scene's prompt, as H3 receives it."
                ),
            ],
            hidden=[io.Hidden.dynprompt],
        )

    @classmethod
    def execute(cls, render):
        if (render.get("hold") or render.get("blank")) and _samples_on_every_pass(
            cls.hidden.dynprompt
        ):
            raise ValueError(
                f"H3 Studio: scene {render['scene'] + 1} isn't in this render, but something on End "
                "Loop's terminations needs its sampler (a Save Video fed from the decoded frames, "
                "say), so it can't be skipped. Feed per-scene saves and previews from H3 Studio "
                "Clip's video instead — it plays a skipped scene's clip — or render every scene."
            )
        return io.NodeOutput(
            _live.attach(
                render.get("model"),
                render.get("preview") or {},
                render["frames"],
                render.get("audio_vae"),
            ),
            render["positive"],
            _carry.SceneNoise(render["seed"], render.get("noise_carry")),
            render["latent"],
            render["frames"],
            render["prompt"],
        )


#: `audio` left unwired, as opposed to wired but not evaluated yet (None).
_UNWIRED = object()


class NynxzH3StudioClip(NynxzNode):
    CATEGORY = f"{NynxzNode.CATEGORY}/H3/Studio"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3.StudioClip",
            display_name="H3 Studio Clip",
            # It saves each scene's clip, and the film after a full render, so a looped render that
            # ends at End Loop has an output without a Save or Preview node after it.
            is_output_node=True,
            description="A rendered scene as one video: the decoded frames and sound at 24 fps, with the "
            "continuation's carried-over head cut off so scenes join cleanly. In a loop, wire it to End "
            "Loop's next_iteration_value (the next scene continues from it) and output_value with "
            "accumulate on (every scene, for Concatenate Video). A scene whose saved clip still "
            "matches everything that shapes it is reused, and its sampler doesn't run.",
            inputs=[
                H3StudioRenderType.Input(
                    "render", tooltip="From H3 Studio — says how much head to cut."
                ),
                io.Image.Input("images", lazy=True, tooltip="The scene's decoded frames."),
                io.Audio.Input(
                    "audio", optional=True, lazy=True, tooltip="The scene's decoded audio."
                ),
                io.Latent.Input(
                    "latent",
                    optional=True,
                    lazy=True,
                    tooltip="The scene's sampled latent. The next scene continues from its last "
                    "tokens directly, without decoding and re-encoding them.",
                ),
                io.Boolean.Input(
                    "keep",
                    default=True,
                    tooltip="Save the clip to output/h3studio, so the studio's Render view can play it "
                    "(and it's still there after a restart).",
                ),
                io.Boolean.Input(
                    "reuse",
                    default=True,
                    tooltip="When this scene's saved clip was rendered from the same scene, models, "
                    "sampler and seed, play that clip instead of rendering it again. Needs keep. Turn "
                    "off to re-render (or change the seed).",
                ),
            ],
            outputs=[io.Video.Output(display_name="video")],
            hidden=[
                io.Hidden.unique_id,
                io.Hidden.dynprompt,
                io.Hidden.prompt,
                io.Hidden.extra_pnginfo,
            ],
        )

    @classmethod
    def _key(cls, render) -> str | None:
        if not render.get("scene_key") or cls.hidden.dynprompt is None:
            return None
        chain = _reuse.chain_key(cls.hidden.dynprompt, cls.hidden.unique_id, ("images", "audio"))
        return f"{render['scene_key'][:32]}{chain[:32]}"

    @classmethod
    def _metadata(cls) -> dict | None:
        """The workflow and prompt, embedded in the saved clip as core's Save Video does, so a clip
        dropped back onto ComfyUI opens the workflow that made it."""
        from comfy.cli_args import args

        if args.disable_metadata:
            return None
        metadata = dict(cls.hidden.extra_pnginfo or {})
        if cls.hidden.prompt is not None:
            metadata["prompt"] = cls.hidden.prompt
        return metadata or None

    @classmethod
    def _saved(cls, render, keep, reuse) -> tuple[str | None, str | None]:
        """This scene's fingerprint, and the clip saved under it when it can be reused — or, for a
        scene left out of a partial render, its latest clip."""
        if render.get("hold"):
            return render.get("hold_key"), render["hold"]
        key = cls._key(render)
        if not (key and keep and reuse):
            return key, None
        saved = _reuse.lookup(key, cls._models(render))
        # The clip the scene uses, when it was made under this same fingerprint: a take made
        # current again, or a mix of takes (which shares its last part's fingerprint).
        current = _reuse.latest(render.get("scene_id")) if saved else None
        if current and current.get("key") == key:
            saved = current["ref"]
        return key, saved

    @classmethod
    def _models(cls, render) -> str | None:
        """The models the clip is rendered with (H3 Studio Setup's), noted beside it."""
        if not render.get("scene_key") or cls.hidden.dynprompt is None:
            return None
        chain = _reuse.chain_key(
            cls.hidden.dynprompt, cls.hidden.unique_id, ("images", "audio"), models=True
        )
        return chain[:32]

    @classmethod
    def check_lazy_status(
        cls, render, images=None, audio=_UNWIRED, latent=_UNWIRED, keep=True, reuse=True
    ):
        if render.get("blank") or cls._saved(render, keep, reuse)[1]:
            return []
        wired = (("images", images), ("audio", audio), ("latent", latent))
        return [name for name, value in wired if value is None]

    @classmethod
    def execute(cls, render, images=None, audio=None, latent=None, keep=True, reuse=True):
        _mem(f"clip start (images {'yes' if images is not None else 'no'})")
        from fractions import Fraction

        from comfy_api.latest import InputImpl, Types

        if render.get("blank"):
            return io.NodeOutput(_blank_video(render))
        key, saved = cls._saved(render, keep, reuse)
        if images is None and saved:
            LOG.info(
                "H3 Studio: scene %d %s %s",
                int(render.get("scene") or 0) + 1,
                "not in this render, playing" if render.get("hold") else "unchanged, reusing",
                saved,
            )
            if not render.get("hold"):
                _reuse.remember_scene(render.get("scene_id"), saved, key, render.get("scene_key"))
            video = InputImpl.VideoFromFile(path_of(saved))
            video.h3_scene = render.get("scene")
            video.h3_key = key
            video.h3_latent, video.h3_head = _carry.load_sidecar(path_of(saved))
            video.h3_tail = _carry.load_tail(path_of(saved))
            if render.get("studio_node") is not None:
                _send(
                    CLIP_EVENT,
                    {
                        "node_id": render["studio_node"],
                        "scene": render.get("scene"),
                        "scene_id": render.get("scene_id"),
                        "media": saved,
                    },
                )
            return cls._output(video, render, keep, None if render.get("hold") else saved)
        if audio is _UNWIRED:
            audio = None
        if latent is _UNWIRED:
            latent = None

        trim = min(int(render.get("trim_frames") or 0), max(0, images.shape[0] - 1))
        frames = images[trim:]
        # The head it regenerated over the end of the previous scene: H3 Studio Join fades into it.
        head = None
        if trim:
            head_audio = None
            if audio is not None:
                cut = round(trim / FPS * audio["sample_rate"])
                head_audio = {**audio, "waveform": audio["waveform"][..., :cut]}
                audio = {**audio, "waveform": audio["waveform"][..., cut:]}
            head = (images[:trim], head_audio, bool(render.get("carries_picture", True)))
        # Just the scene's own length (H3's grid can make the render longer), and the sound of its
        # handle past it, kept beside the clip for the cut into the next scene.
        scene_frames = int(render.get("keep_frames") or 0)
        rendered = frames.shape[0]
        tail_sound = None
        if scene_frames and frames.shape[0] > scene_frames:
            frames = frames[:scene_frames]
            if audio is not None:
                rate = audio["sample_rate"]
                end = round(scene_frames / FPS * rate)
                handle = int(render.get("tail_frames") or 0)
                if handle:
                    tail_sound = {
                        **audio,
                        "waveform": audio["waveform"][..., end : end + round(handle / FPS * rate)],
                    }
                audio = {**audio, "waveform": audio["waveform"][..., :end]}
        video = InputImpl.VideoFromComponents(
            Types.VideoComponents(images=frames, frame_rate=Fraction(FPS), audio=audio)
        )
        samples = latent["samples"] if latent is not None else None
        video.h3_scene = render.get("scene")
        video.h3_key = key
        # The next scene continues from this latent's last tokens: only when they are the clip's
        # own end (no head, no grid padding or handle after it); else from the decoded clip.
        video.h3_latent = (
            tuple(t.detach().cpu() for t in samples.unbind())
            if getattr(samples, "is_nested", False) and not trim and rendered == frames.shape[0]
            else None
        )
        video.h3_tail = tail_sound
        video.h3_head = head
        if keep and render.get("studio_node") is not None:
            _mem("clip: before save")
            ref = _save_clip(video, render, cls._metadata(), frames.shape[0])
            _mem("clip: saved")
            _carry.save_sidecar(path_of(ref), video.h3_latent, head, tail_sound)
            if key:
                _reuse.remember(key, ref, cls._models(render))
            _reuse.remember_scene(render.get("scene_id"), ref, key, render.get("scene_key"))
            _reuse.add_take(
                render.get("scene_id"),
                ref,
                {
                    "key": key,
                    "scene_key": render.get("scene_key"),
                    "seed": render.get("seed"),
                    "seconds": round(frames.shape[0] / FPS, 3),
                    "prompt": str(render.get("prompt") or "")[:400],
                },
            )
            _send(
                CLIP_EVENT,
                {
                    "node_id": render["studio_node"],
                    "scene": render.get("scene"),
                    "scene_id": render.get("scene_id"),
                    "media": ref,
                },
            )
            # Handed on as the saved file, not its decoded frames: a loop's cache keeps every pass's
            # outputs, and a few GB of frames per scene ran a full render out of memory.
            video = _as_file(video, ref)
            _mem("clip: handed on as file")
            return cls._output(video, render, keep, ref)
        return cls._output(video, render, keep, None)

    @classmethod
    def _output(cls, video, render: dict, keep: bool, clip: str | None):
        """The clip, with what was saved (the clip, and the film after a full render) listed as the
        node's results, so they show in ComfyUI's outputs."""
        saved = [ref for ref in (clip, cls._finish(render, keep)) if ref]
        if not saved:
            return io.NodeOutput(video)
        return io.NodeOutput(video, ui=_saved_results(saved))

    @classmethod
    def _finish(cls, render: dict, keep: bool) -> str | None:
        """After the last scene of a full render, the film saved; its media ref."""
        if keep and render.get("film") and render.get("studio_node") is not None:
            from . import film

            try:
                _mem("film: before save")
                record = film.save(render["film"], cls._metadata())
                _send(FILM_EVENT, {"node_id": render["studio_node"], **record})
                return record.get("ref")
            except Exception:
                LOG.exception("H3 Studio: couldn't save the film (Renders ▸ Export film retries)")
        return None


def _saved_results(refs: list[str]):
    """`output/…` media refs as a video preview of saved files, as core's Save Video reports them."""
    from comfy_api.latest import ui

    results = []
    for ref in refs:
        if not ref.startswith("output/"):
            continue
        subfolder, _, file = ref[len("output/") :].rpartition("/")
        results.append(ui.SavedResult(file, subfolder, io.FolderType.output))
    return ui.PreviewVideo(results) if results else None


def _as_file(video, ref: str):
    """`video` as its saved file, decoded only when something reads it, keeping what the studio
    hangs on it (its scene, fingerprint, latent, head and handle)."""
    from comfy_api.latest import InputImpl

    saved = InputImpl.VideoFromFile(path_of(ref))
    for name in ("h3_scene", "h3_key", "h3_latent", "h3_head", "h3_tail", "h3_blank"):
        if hasattr(video, name):
            setattr(saved, name, getattr(video, name))
    return saved


def _blank_video(render: dict):
    """Black frames and silence standing in for a scene this partial render skipped."""
    from fractions import Fraction

    import torch
    from comfy_api.latest import InputImpl, Types

    LOG.info(
        "H3 Studio: scene %d not in this render and never rendered, black", render["scene"] + 1
    )
    frames = torch.zeros((render["frames"], render["height"], render["width"], 3))
    rate = render.get("audio_rate")
    audio = (
        {"waveform": torch.zeros((1, 2, round(render["frames"] / FPS * rate))), "sample_rate": rate}
        if rate
        else None
    )
    video = InputImpl.VideoFromComponents(
        Types.VideoComponents(images=frames, frame_rate=Fraction(FPS), audio=audio)
    )
    video.h3_key, video.h3_latent, video.h3_head = None, None, None
    video.h3_scene = render.get("scene")
    video.h3_blank = True
    return video


def _save_clip(video, render: dict, metadata: dict | None, frames: int) -> str:
    """Save a scene's clip (`frames` long) under output/h3studio, its shots in the `h3studio` tag;
    its media ref (`output/h3studio/…`). Core's saver writes tags only, so no chapters."""
    import os

    import folder_paths

    if scene := render.get("marks"):
        mark = _marks.tag("take", [_marks.scene(scene, 0, frames)])
        metadata = {**(metadata or {}), _marks.TAG: mark}
    scene = int(render.get("scene") or 0) + 1
    folder, name, counter, subfolder, _ = folder_paths.get_save_image_path(
        f"h3studio/scene{scene:02}", folder_paths.get_output_directory()
    )
    file = f"{name}_{counter:05}_.mp4"
    video.save_to(os.path.join(folder, file), metadata=metadata)
    return "/".join(p for p in ("output", subfolder, file) if p)


class NynxzH3StudioFilm(NynxzNode):
    CATEGORY = f"{NynxzNode.CATEGORY}/H3/Studio"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3.StudioFilm",
            display_name="H3 Studio Film",
            description="The film as it's rendered so far: every scene's current take (its latest "
            "render, or the take you made current), joined like H3 Studio Join — without a loop "
            "and without sampling anything. A scene never rendered plays as black for its length. "
            "The studio already saves the film after a full render (and Renders ▸ Export film "
            "saves it any time); use this node to put a score under it or feed it on.",
            search_aliases=["h3 film", "join takes", "export film", "rendered scenes"],
            inputs=[
                H3StudioLinkType.Input(
                    "link", optional=True, tooltip="The H3 Studio whose scenes it joins."
                ),
                io.Int.Input(
                    "crossfade",
                    default=8,
                    min=0,
                    max=39,
                    tooltip="Frames each continuation fades in over, as on H3 Studio Join.",
                ),
                io.Audio.Input("music", optional=True, tooltip="A score under the whole film."),
                io.Float.Input("music_volume", default=0.8, min=0.0, max=2.0, step=0.05),
                io.Float.Input("music_fade", default=2.0, min=0.0, max=10.0, step=0.25),
            ],
            outputs=[io.Video.Output(display_name="video")],
            hidden=[io.Hidden.dynprompt],
        )

    @classmethod
    def fingerprint_inputs(
        cls, link=None, crossfade=8, music=None, music_volume=0.8, music_fade=2.0
    ):
        # A new take changes the film without changing the node's inputs.
        import os

        try:
            return os.path.getmtime(_reuse._scenes_path())
        except OSError:
            return 0

    @classmethod
    def execute(cls, link=None, crossfade=8, music=None, music_volume=0.8, music_fade=2.0):
        from . import film

        studio = str((link if isinstance(link, dict) else {}).get("studio") or "").strip()
        project = _linked_project(cls.hidden.dynprompt, studio)
        if project is None:
            raise ValueError("H3 Studio Film: pick the H3 Studio on the node.")
        proj = normalize(project)
        proj["film"] = {**proj["film"], "crossfade": int(crossfade)}
        video, _ = film.assemble(proj, music, float(music_volume), float(music_fade))
        return io.NodeOutput(video)


class NynxzH3StudioJoin(NynxzNode):
    CATEGORY = f"{NynxzNode.CATEGORY}/H3/Studio"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3.StudioJoin",
            display_name="H3 Studio Join",
            description="Every scene's clip as one film — in place of Concatenate Video. Where a "
            "scene continues the one before, the end of that one crossfades into the head the "
            "continuation regenerated over it, picture and sound, instead of butt-joining; cuts "
            "stay cuts. The film keeps its length.",
            is_input_list=True,
            inputs=[
                io.Video.Input(
                    "videos", tooltip="The scenes' clips: End Loop's output, accumulate on."
                ),
                io.Int.Input(
                    "crossfade",
                    default=8,
                    min=0,
                    max=39,
                    tooltip="Frames each continuation fades in over (at most the frames it "
                    "carries). 0 butt-joins, like Concatenate Video. A cut whose sound carries on "
                    "fades only its sound.",
                ),
                io.Audio.Input(
                    "music",
                    optional=True,
                    tooltip="A score to play under the whole film, one piece across every cut. Leave "
                    "the studio's music empty so H3 doesn't write its own into each scene.",
                ),
                io.Float.Input(
                    "music_volume",
                    default=0.8,
                    min=0.0,
                    max=2.0,
                    step=0.05,
                    tooltip="The score's level under the film's own sound.",
                ),
                io.Float.Input(
                    "music_fade",
                    default=2.0,
                    min=0.0,
                    max=10.0,
                    step=0.25,
                    tooltip="Seconds the score fades out over at the end of the film.",
                ),
            ],
            outputs=[io.Video.Output(display_name="video")],
        )

    @classmethod
    def execute(cls, videos, crossfade, music=None, music_volume=(0.8,), music_fade=(2.0,)):
        return io.NodeOutput(
            _carry.join(
                list(videos),
                int(crossfade[0]),
                music[0] if music else None,
                float(music_volume[0]),
                float(music_fade[0]),
            )
        )
