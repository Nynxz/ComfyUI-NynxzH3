"""H3 Studio — a whole film as one project, rendered a scene at a time.

Three nodes, so the studio's own header stays clean:

    H3 Studio Setup ──setup──▶ H3 Studio ──render──▶ H3 Studio Outputs
    clip, vae, audio_vae,       the project            positive, latent, prompt,
    previous scene              (H3Studio.vue)         trim_frames, frames, size

H3 Studio turns one scene of the project into what MiniMax H3 samples from: positive conditioning
and an empty AV latent sized to that scene. Use its outputs in place of core's MiniMax H3 Image to
Video / Reference to Video; the sampler, model and decode stay yours.

**Continuation.** Wire the previous scene's decoded frames (and audio) into `previous_frames` /
`previous_audio`, set the scene's continuation to *guide*, and its last 5/22/39 frames are
anchored at frame 0 of this scene — through the same keyframe conditioning core's Add Guide
writes, so nothing in H3 is patched. Those frames are regenerated at the head of this scene;
`trim_frames` says how many to cut after decoding so the scenes butt-join cleanly.
"""

from __future__ import annotations

import logging
import math

import node_helpers
from comfy_api.latest import io

from .._base import NynxzNode
from . import _carry, _reuse
from ._loras import apply as apply_loras
from ._media import has_audio, load_audio, load_image, load_video, path_of
from ._project import FPS, PREVIOUS_FRAME, compile_scene, normalize
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
    video, _ = load_video(ref, FPS)
    return video[-1:], _reuse.digest(_reuse.media_stat(ref))


def _from_latest(setup: dict, scene_id: str) -> dict:
    """`setup` with the previous scene's latest clip as the one to continue from — for a scene
    rendered on its own, outside a loop that would carry the previous scene in."""
    record = _reuse.latest(scene_id)
    if record is None:
        return setup
    frames, audio = load_video(record["ref"], FPS)
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
        "frames": plan.frames,
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
            carried = None
            if i > 0 and plan.continuation.get("mode") not in (None, "cut"):
                previous = _reuse.latest(proj["scenes"][i - 1]["id"])
                carried = previous.get("key") if previous else None
            now = _reuse.scene_key(plan.as_dict(), i, carried)
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
        carried = None
        if i > 0 and (scene.get("continuation") or {}).get("mode") not in (None, "cut"):
            previous = _reuse.latest(proj["scenes"][i - 1]["id"])
            carried = previous.get("key") if previous else None
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


def render_scene(setup: dict, project, scene: int | None) -> dict:
    """One scene of the project as H3 conditioning, a sized AV latent and the head trim."""
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
    if (
        index > 0
        and setup.get("previous_frames") is None
        and plan.continuation.get("mode") not in (None, "cut")
    ):
        setup = _from_latest(setup, proj["scenes"][index - 1]["id"])
        previous_frames, previous_audio = setup.get("previous_frames"), setup.get("previous_audio")
    width, height = plan.width, plan.height
    latent, frame_count = h3._empty_av_latent(width, height, plan.frames)
    last_frame, last_key = None, None
    if plan.continuation.get("mode") in ("first_frame", "reference"):
        last_frame, last_key = _previous_last_frame(setup, proj, index)

    def picture(media: str):
        return last_frame if media == PREVIOUS_FRAME else load_image(media)

    def snap(n: float) -> int:
        return max(h3.CANVAS_MULTIPLE, round(n / h3.CANVAS_MULTIPLE) * h3.CANVAS_MULTIPLE)

    keyframes = []
    for k in plan.keyframes:
        # A keyframe fills the canvas: cropped to its shape, or stretched onto it.
        fit = "disabled" if k.get("fit") == "stretch" else "center"
        image = h3._resize(picture(k["media"]), width, height, fit)
        keyframes.append({"resolved_frame_index": min(k["frame"], frame_count - 1), "image": image})

    if plan.task == "ref2va":
        # Same presentation and payload as core's MiniMax H3 Reference to Video, per reference:
        # pictures, then videos (a soundtrack's <Audio j> label right before its <Video k>), then
        # standalone audio. Only a 'semantic' picture skips its latent.
        ref_items, ref_blocks = [], []
        for ref in plan.refs:
            if ref["alias"]:
                continue
            if ref["kind"] == "image":
                image = picture(ref["media"])
                h, w = image.shape[1], image.shape[2]
                scale = min(1.0, math.sqrt((width * height) / (w * h))) * ref["size"]
                tw, th = snap(w * scale), snap(h * scale)
                resized = h3._resize(image, tw, th, "disabled")
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
                if audio_vae is not None:
                    audio_latent, ref_audio_t = h3._encode_ref_audio(
                        audio_vae, load_audio(ref["media"])
                    )
                    ref_blocks.append(
                        {"kind": "audio", "ref_audio_t": ref_audio_t, "audio_latent": audio_latent}
                    )
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

    trim = 0
    noise_carry = None
    carried = last_key
    mode = plan.continuation.get("mode")
    if mode in ("guide", "sound") and previous_frames is not None:
        # "guide" carries the picture and the sound; "sound" only the sound: the picture cuts, and
        # its first `context` frames (unguided) are cut off with the regenerated sound under them.
        picture = mode == "guide"
        context = min(plan.continuation["frames"], previous_frames.shape[0])
        while context > 5 and context % 17 != 5:
            context -= 1
        if context < 5:
            context = 1
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
            # The carried head is cut off after decoding; a keyframe inside it would fight it.
            keyframes = [k for k in keyframes if k["resolved_frame_index"] >= context]
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
    if plan.settings.get("verbose"):
        LOG.info(
            "H3 Studio scene %d (%s, %d frames) prompt:\n%s",
            index + 1,
            plan.task,
            frame_count,
            plan.prompt,
        )
    return {
        "model": model,
        "positive": positive,
        "latent": latent,
        "prompt": plan.prompt,
        "trim_frames": trim,
        "frames": frame_count,
        "width": width,
        "height": height,
        "scene": index,
        "scene_id": scene_id,
        "seed": plan.seed,
        "noise_carry": noise_carry,
        "carries_picture": mode == "guide",
        "scene_key": _reuse.scene_key(plan.as_dict(), index, carried),
    }


#: Sent when the studio renders a scene, so its editor can show that scene's sampling previews live.
RENDER_EVENT = "nynxz.h3studio.render"
#: Sent when H3 Studio Clip has saved a scene's finished clip, so the editor can play it.
CLIP_EVENT = "nynxz.h3studio.clip"


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
    CATEGORY = f"{NynxzNode.CATEGORY}/H3"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3.StudioSetup",
            display_name="H3 Studio Setup",
            description="The models H3 Studio renders with, and the previous scene it continues from, "
            "gathered onto one wire.",
            inputs=[
                io.Clip.Input("clip", tooltip="The MiniMax H3 text encoder."),
                io.Vae.Input(
                    "vae", tooltip="The H3 video VAE, for keyframes, references and continuation."
                ),
                io.Vae.Input(
                    "audio_vae",
                    optional=True,
                    tooltip="The H3 audio VAE. Needed to carry the previous scene's sound across a continuation.",
                ),
                io.Image.Input(
                    "previous_frames",
                    optional=True,
                    tooltip="The previous scene's decoded frames. When the scene continues, their tail is "
                    "anchored at frame 0 so motion carries across the cut.",
                ),
                io.Audio.Input(
                    "previous_audio", optional=True, tooltip="The previous scene's audio."
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
                    "render the film scene by scene. Unwired, the scene selected in the studio renders.",
                ),
                io.Model.Input(
                    "model",
                    optional=True,
                    tooltip="The H3 model, for the studio's LoRA lanes. H3 Studio Outputs gives it back with "
                    "the scene's LoRAs applied — sample with that model.",
                ),
            ],
            outputs=[H3StudioSetupType.Output(display_name="setup")],
        )

    @classmethod
    def execute(
        cls,
        clip,
        vae,
        audio_vae=None,
        previous_frames=None,
        previous_audio=None,
        previous=None,
        scene=None,
        model=None,
    ):
        previous_key = previous_latent = None
        if previous_frames is None and previous is not None:
            components = previous.get_components()
            previous_frames, previous_audio = components.images, previous_audio or components.audio
            previous_key = getattr(previous, "h3_key", None)
            previous_latent = getattr(previous, "h3_latent", None)
        return io.NodeOutput(
            {
                "previous_key": previous_key,
                "previous_latent": previous_latent,
                "scene": scene,
                "model": model,
                "clip": clip,
                "vae": vae,
                "audio_vae": audio_vae,
                "previous_frames": previous_frames,
                "previous_audio": previous_audio,
            }
        )


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
    CATEGORY = f"{NynxzNode.CATEGORY}/H3"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3.StudioScenes",
            display_name="H3 Studio Scenes",
            description="How many scenes an H3 Studio has, for the loop that renders them — without a "
            "wire from the studio (which sits inside the loop, so a wire would be a cycle). Put it "
            "outside the loop: `scene` into Start Loop in List mode (one pass per scene), or `count` "
            "into its iteration count. Pick the studio on the node.",
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
            ],
            hidden=[io.Hidden.dynprompt],
        )

    @classmethod
    def execute(cls, link=None):
        link = link if isinstance(link, dict) else {}
        studio, count = str(link.get("studio") or ""), int(link.get("count") or 1)
        project = _linked_project(cls.hidden.dynprompt, str(studio).strip())
        if project is not None:
            count = len(normalize(project)["scenes"])
        elif studio:
            LOG.warning(
                "H3 Studio Scenes: no H3 Studio #%s in this workflow; using count %d", studio, count
            )
        count = max(1, int(count))
        return io.NodeOutput(list(range(count)), count)


class NynxzH3Studio(NynxzNode):
    CATEGORY = f"{NynxzNode.CATEGORY}/H3"

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
_SAMPLER_OUTPUTS = {0, 1, 7, 9}


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
    CATEGORY = f"{NynxzNode.CATEGORY}/H3"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3.StudioOutputs",
            display_name="H3 Studio Outputs",
            description="Breaks an H3 Studio render out into conditioning, latent and the scene's details.",
            inputs=[H3StudioRenderType.Input("render", tooltip="From H3 Studio.")],
            outputs=[
                io.Conditioning.Output(display_name="positive"),
                io.Latent.Output(display_name="latent"),
                io.String.Output(
                    display_name="prompt", tooltip="The scene's prompt, as H3 receives it."
                ),
                io.Int.Output(
                    display_name="trim_frames",
                    tooltip="Frames to cut from the head of the decoded video: the carried-over context of a "
                    "continuation. 0 for a cut.",
                ),
                io.Int.Output(
                    display_name="frames", tooltip="The scene's length in frames, at 24 fps."
                ),
                io.Int.Output(display_name="width"),
                io.Int.Output(display_name="height"),
                io.Model.Output(
                    display_name="model",
                    tooltip="The model from H3 Studio Setup with this scene's LoRAs applied (lanes with a "
                    "curve over the steps ride on `positive` as hooks).",
                ),
                io.Int.Output(
                    display_name="seed",
                    tooltip="The scene's own noise seed — wire it to Random Noise's noise_seed. Re-roll "
                    "a scene in the studio and only that scene (and those continuing from it) renders "
                    "again.",
                ),
                io.Noise.Output(
                    display_name="noise",
                    tooltip="The scene's noise, from its seed — wire it to the sampler's noise. A "
                    "continuation's first tokens get the very noise the previous scene drew for "
                    "the frames they regenerate, so the two start from one field.",
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
            render["positive"],
            render["latent"],
            render["prompt"],
            render["trim_frames"],
            render["frames"],
            render["width"],
            render["height"],
            render.get("model"),
            render["seed"],
            _carry.SceneNoise(render["seed"], render.get("noise_carry")),
        )


#: `audio` left unwired, as opposed to wired but not evaluated yet (None).
_UNWIRED = object()


class NynxzH3StudioClip(NynxzNode):
    CATEGORY = f"{NynxzNode.CATEGORY}/H3"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3.StudioClip",
            display_name="H3 Studio Clip",
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
            hidden=[io.Hidden.unique_id, io.Hidden.dynprompt],
        )

    @classmethod
    def _key(cls, render) -> str | None:
        if not render.get("scene_key") or cls.hidden.dynprompt is None:
            return None
        chain = _reuse.chain_key(cls.hidden.dynprompt, cls.hidden.unique_id, ("images", "audio"))
        return f"{render['scene_key'][:32]}{chain[:32]}"

    @classmethod
    def _saved(cls, render, keep, reuse) -> tuple[str | None, str | None]:
        """This scene's fingerprint, and the clip saved under it when it can be reused — or, for a
        scene left out of a partial render, its latest clip."""
        if render.get("hold"):
            return render.get("hold_key"), render["hold"]
        key = cls._key(render)
        return key, (_reuse.lookup(key) if key and keep and reuse else None)

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
            video.h3_key = key
            video.h3_latent, video.h3_head = _carry.load_sidecar(path_of(saved))
            if render.get("studio_node") is not None:
                _send(
                    CLIP_EVENT,
                    {
                        "node_id": render["studio_node"],
                        "scene": render.get("scene"),
                        "media": saved,
                    },
                )
            return io.NodeOutput(video)
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
        video = InputImpl.VideoFromComponents(
            Types.VideoComponents(images=frames, frame_rate=Fraction(FPS), audio=audio)
        )
        samples = latent["samples"] if latent is not None else None
        video.h3_key = key
        video.h3_latent = (
            tuple(t.detach().cpu() for t in samples.unbind())
            if getattr(samples, "is_nested", False)
            else None
        )
        video.h3_head = head
        if keep and render.get("studio_node") is not None:
            ref = _save_clip(video, render)
            _carry.save_sidecar(path_of(ref), video.h3_latent, head)
            if key:
                _reuse.remember(key, ref)
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
                {"node_id": render["studio_node"], "scene": render.get("scene"), "media": ref},
            )
        return io.NodeOutput(video)


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
    video.h3_blank = True
    return video


def _save_clip(video, render: dict) -> str:
    """Save a scene's clip under output/h3studio; its media ref (`output/h3studio/…`)."""
    import os

    import folder_paths

    scene = int(render.get("scene") or 0) + 1
    folder, name, counter, subfolder, _ = folder_paths.get_save_image_path(
        f"h3studio/scene{scene:02}", folder_paths.get_output_directory()
    )
    file = f"{name}_{counter:05}_.mp4"
    video.save_to(os.path.join(folder, file))
    return "/".join(p for p in ("output", subfolder, file) if p)


class NynxzH3StudioJoin(NynxzNode):
    CATEGORY = f"{NynxzNode.CATEGORY}/H3"

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
