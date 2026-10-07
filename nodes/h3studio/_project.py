"""The H3 Studio project: one document for a whole film, and how one scene of it becomes an H3 request.

A project is scenes on one clock. A scene is one H3 generation (H3 is trained on roughly 5-15s), and
inside it shots are written into the prompt as H3's own `[Shot N] At MM:SS.mmm,` markers — so the
timeline and the prompt are two views of the same data, never two copies to keep in sync.

    project
      canvas      width, height (24 fps is H3's)
      style       the look, the opening sentence of every scene
      direction   how it's made, after the style in every scene ("animated on twos, held poses");
                  a scene can override it
      soundscape  / music: defaults a scene can override
      refs        pictures with a name (`@hero`), a role, a retention marker, and the scenes they serve
      scenes      seconds, shots[{at, text, lines}], keyframes[{at, media}], continuation, overrides
      cast        the voices that speak the shots' lines (see `_dialogue`)

Media is a ComfyUI file ref (`input/sub/name.png`, `output/...`), the same string ZenKit's media
refs use, so a project survives a reload and moves between machines that share those folders.

`compile_scene` is pure — no tensors, no models — so the node and the editor's live preview (the
`/nynxz/h3studio/compile` route) build the identical prompt. The task follows from the scene:
references in scope → ref2va; keyframes at the start / end → i2va / l2va / fl2va; otherwise t2va.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from typing import Any

from ._dialogue import Dialogue, normalize_cast, normalize_lines

FPS = 24
MIN_SECONDS = 1.0
MAX_SECONDS = 30.0
CONTEXT_FRAMES = (5, 22, 39)
SEED_MAX = 2**64 - 1


def seed_of(scene_id: str) -> int:
    """A scene's seed when it has none of its own: FNV-1a of its id, the same as the editor's
    `seedOf`, so a project saved before seeds renders the same every time."""
    h = 0x811C9DC5
    for ch in scene_id:
        h = ((h ^ ord(ch)) * 0x01000193) & 0xFFFFFFFF
    return h


#: How a scene follows the one before: start fresh; carry its last frames in (motion continues);
#: open on its last frame (a first-frame keyframe); or show its last frame as a reference picture
#: (the same place and light, a new shot); or cut the picture while the sound carries on ("sound":
#: its last moments of audio lead in, so music and ambience continue across the cut).
CONTINUATIONS = ("cut", "guide", "first_frame", "reference", "sound")
#: The media of a keyframe or reference that is the previous scene's last frame, filled in when the
#: scene renders.
PREVIOUS_FRAME = "previous:last"
RETENTION = ("fully_preserved", "partially_preserved", "attribute_transfer", "weak_reference")
AUDIO_RETENTION = ("fully_copy", "partially_copy", "reference", "weak_reference")
ROLES = ("reference", "semantic", "blocking")
#: What each kind of reference may be used as: a picture for its look (or only its meaning); a
#: video for its look and motion, or only as blocking — its staging, timing and camera.
ROLES_FOR = {"image": ("reference", "semantic"), "video": ("reference", "blocking")}
KINDS = ("image", "video", "audio")
#: H3's reference limits per generation.
LIMITS = {"image": 9, "video": 3, "audio": 3}
_VIDEO = re.compile(r"\.(mp4|webm|mov|mkv|m4v|avi|gif)$", re.I)
_AUDIO = re.compile(r"\.(mp3|wav|flac|ogg|oga|m4a|aac|opus)$", re.I)


def kind_of(media: str) -> str:
    return "video" if _VIDEO.search(media) else "audio" if _AUDIO.search(media) else "image"


DEFAULT_PROJECT: dict[str, Any] = {
    "v": 2,
    "canvas": {"width": 1344, "height": 768},
    "style": "",
    "direction": "",
    "soundscape": "",
    "music": "",
    "refs": [],
    "scenes": [
        {
            "id": "s1",
            "title": "",
            "seconds": 5.0,
            "shots": [{"id": "sh1", "at": 0.0, "text": "", "lines": [], "transition": "cut"}],
            "keyframes": [],
            "direction": "",
            "soundscape": "",
            "music": "",
            "continuation": {"mode": "cut", "frames": 22},
        }
    ],
    "active": 0,
}


def align_frame_count(n: int) -> int:
    """H3's frame grid: lengths are 17k + 5 at 24 fps (124 = 5.17s)."""
    n = max(5, int(n))
    while n % 17 != 5:
        n += 1
    return n


def frames_for(seconds: float) -> int:
    return align_frame_count(round(float(seconds) * FPS))


def _num(value: Any, default: float, lo: float, hi: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return min(hi, max(lo, v))


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def normalize(raw: Any) -> dict[str, Any]:
    """A complete, valid project from whatever the widget (or a hand-edited workflow) holds."""
    import json

    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except ValueError:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}

    version = raw.get("v") if isinstance(raw.get("v"), int) else 1
    canvas = raw.get("canvas") if isinstance(raw.get("canvas"), dict) else {}
    width = max(64, round(_num(canvas.get("width"), 1344, 64, 4096) / 32) * 32)
    height = max(64, round(_num(canvas.get("height"), 768, 64, 4096) / 32) * 32)

    refs = []
    for i, ref in enumerate(raw.get("refs") or []):
        # A reference with no media yet is a proxy: a name and a description standing in for it.
        if not isinstance(ref, dict) or not (_str(ref.get("media")) or _str(ref.get("name"))):
            continue
        media = _str(ref.get("media"))
        scenes = ref.get("scenes")
        kind = (
            ref.get("kind") if ref.get("kind") in KINDS else (kind_of(media) if media else "image")
        )
        markers = AUDIO_RETENTION if kind == "audio" else RETENTION
        refs.append(
            {
                "id": _str(ref.get("id")) or f"r{i + 1}",
                "media": media,
                "kind": kind,
                "name": re.sub(r"[^\w-]", "", _str(ref.get("name"))) or f"ref{i + 1}",
                "note": _str(ref.get("note")),
                "role": ref.get("role")
                if ref.get("role") in ROLES_FOR.get(kind, ())
                else "reference",
                "retain": ref.get("retain")
                if ref.get("retain") in markers
                else markers[0 if kind != "audio" else 2],
                # A video brings its own sound unless told not to.
                "soundtrack": ref.get("soundtrack") is not False,
                "size": ref.get("size") if ref.get("size") in REF_SIZES else 1.0,
                # Scenes that show it without using it (see `refs_in_scene`): a list of scene ids, or
                # "all". Before version 2 every reference was "all" by default, so that is read as none.
                "scenes": scenes
                if isinstance(scenes, list) or (scenes == "all" and version >= 2)
                else [],
            }
        )

    scenes = []
    for i, scene in enumerate(raw.get("scenes") or []):
        if not isinstance(scene, dict):
            continue
        # Stored snapped to H3's frame grid, so the length the editor shows is the length rendered.
        seconds = round(
            frames_for(_num(scene.get("seconds"), 5.0, MIN_SECONDS, MAX_SECONDS)) / FPS, 3
        )
        shots = []
        for j, shot in enumerate(scene.get("shots") or []):
            if isinstance(shot, dict):
                at = 0.0 if j == 0 else _num(shot.get("at"), 0.0, 0.0, seconds)
                shots.append(
                    {
                        "id": _str(shot.get("id")) or f"sh{j + 1}",
                        "at": at,
                        "text": _str(shot.get("text")),
                        "transition": shot.get("transition")
                        if j > 0 and shot.get("transition") in TRANSITIONS
                        else "cut",
                        "lines": normalize_lines(shot.get("lines")),
                    }
                )
        shots.sort(key=lambda s: s["at"])
        if not shots:
            shots = [{"id": "sh1", "at": 0.0, "text": "", "lines": [], "transition": "cut"}]
        shots[0]["at"] = 0.0
        shots[0]["transition"] = "cut"
        keyframes = [
            {
                "id": _str(k.get("id")) or f"k{j + 1}",
                "at": _num(k.get("at"), 0.0, 0.0, seconds),
                "media": k["media"],
                "fit": k.get("fit") if k.get("fit") in FITS else "crop",
            }
            for j, k in enumerate(scene.get("keyframes") or [])
            if isinstance(k, dict) and _str(k.get("media"))
        ]
        keyframes.sort(key=lambda k: k["at"])
        cont = scene.get("continuation") if isinstance(scene.get("continuation"), dict) else {}
        frames = int(cont.get("frames", 22)) if str(cont.get("frames", "")).isdigit() else 22
        scenes.append(
            {
                "id": _str(scene.get("id")) or f"s{i + 1}",
                "title": _str(scene.get("title")),
                "seconds": seconds,
                "shots": shots,
                "keyframes": keyframes,
                "direction": _str(scene.get("direction")),
                "soundscape": _str(scene.get("soundscape")),
                "music": _str(scene.get("music")),
                "render": _str(scene.get("render")),
                "seed": scene["seed"]
                if isinstance(scene.get("seed"), int) and 0 <= scene["seed"] <= SEED_MAX
                else seed_of(_str(scene.get("id")) or f"s{i + 1}"),
                "continuation": {
                    "mode": cont.get("mode") if cont.get("mode") in CONTINUATIONS else "cut",
                    "frames": frames if frames in CONTEXT_FRAMES else 22,
                },
            }
        )
    if not scenes:
        scenes = [dict(DEFAULT_PROJECT["scenes"][0])]

    loras = []
    for i, lane in enumerate(raw.get("loras") or []):
        if not isinstance(lane, dict) or not _str(lane.get("name")):
            continue
        loras.append(
            {
                "id": _str(lane.get("id")) or f"l{i + 1}",
                "name": _str(lane.get("name")),
                "enabled": lane.get("enabled") is not False,
                "strength": _num(lane.get("strength"), 1.0, -4.0, 4.0),
                "scenes": {
                    str(k): _num(v, 1.0, -4.0, 4.0)
                    for k, v in (lane.get("scenes") or {}).items()
                    if isinstance(v, (int, float))
                }
                if isinstance(lane.get("scenes"), dict)
                else {},
                "steps": {
                    str(k): _points(v, "p", 0.0, 1.0, 0.0, 2.0)
                    for k, v in (lane.get("steps") or {}).items()
                    if isinstance(v, list)
                }
                if isinstance(lane.get("steps"), dict)
                else {},
                "film": _points(lane.get("film"), "t", 0.0, 3600.0, -4.0, 4.0),
                "sampling": _points(lane.get("sampling"), "p", 0.0, 1.0, 0.0, 2.0),
            }
        )

    active = int(_num(raw.get("active"), 0, 0, len(scenes) - 1))
    return {
        "v": 2,
        "canvas": {"width": width, "height": height},
        "style": _str(raw.get("style")),
        "direction": _str(raw.get("direction")),
        "soundscape": _str(raw.get("soundscape")),
        "music": _str(raw.get("music")),
        "refs": refs,
        "cast": normalize_cast(raw.get("cast")),
        "scenes": scenes,
        "loras": loras,
        "active": active,
        "settings": normalize_settings(raw.get("settings")),
        # A partial render: the ids of the scenes to render this run; the others play their latest
        # clip (see studio.render_scene). None renders every scene.
        "render_only": _render_only(raw.get("renderOnly"), {sc["id"] for sc in scenes}),
    }


def _render_only(raw: Any, ids: set[str]) -> list[str] | None:
    if not isinstance(raw, list):
        return None
    chosen = [x for x in raw if isinstance(x, str) and x in ids]
    return chosen or None


#: How LoRA step shapes are applied. Hooks sample on a non-dynamic copy of the model, which next to
#: dynamic VRAM (ComfyUI's default) is a second copy of a big model — H3 on a 32 GB card runs out of
#: memory. "auto" (the default) uses hooks only when dynamic VRAM is off and otherwise applies each
#: shape at its average; "fast" and "low_vram" always use hooks, caching patched weights on the GPU
#: (MaxSpeed) or re-patching from system RAM at each change (MinVram).
#: A reference picture or video shown to H3 at this fraction of the canvas size: smaller is lighter
#: on memory and time, at some cost to likeness.
REF_SIZES = (1.0, 0.75, 0.5)
#: A keyframe picture of another shape than the canvas: cropped to fill it, or stretched onto it.
FITS = ("crop", "stretch")
HOOK_MODES = ("auto", "fast", "low_vram")


def normalize_settings(raw: Any) -> dict[str, Any]:
    """Studio settings that change how a scene renders (the editor's own live in the browser)."""
    raw = raw if isinstance(raw, dict) else {}
    return {
        "hooks": raw.get("hooks") if raw.get("hooks") in HOOK_MODES else "auto",
        #: The most changes a step shape is split into (only where its strength really changes).
        "step_detail": int(_num(raw.get("step_detail"), 8, 2, 24)),
        "verbose": raw.get("verbose") is True,
    }


def _points(
    raw: Any, key: str, lo: float, hi: float, vlo: float, vhi: float
) -> list[dict[str, float]]:
    """A curve's points `[{key, v}]`, clamped and sorted along `key`."""
    pts = [
        {key: _num(p.get(key), lo, lo, hi), "v": _num(p.get("v"), 1.0, vlo, vhi)}
        for p in (raw if isinstance(raw, list) else [])
        if isinstance(p, dict)
    ]
    return sorted(pts, key=lambda p: p[key])


def curve_at(points: list[dict[str, float]], key: str, x: float, default: float) -> float:
    """A curve's value at `x`: linear between points, held flat past the ends; `default` if empty."""
    if not points:
        return default
    if x <= points[0][key]:
        return points[0]["v"]
    for a, b in itertools.pairwise(points):
        if x <= b[key]:
            span = b[key] - a[key]
            f = (x - a[key]) / span if span > 0 else 1.0
            return a["v"] + (b["v"] - a["v"]) * f
    return points[-1]["v"]


def scene_loras(project: dict[str, Any], index: int) -> list[dict[str, Any]]:
    """The LoRAs a scene renders with: each enabled lane's strength for the scene (its own, else the
    lane's; an older film curve is read at the scene's middle — one generation can't vary it between
    frames), and its curve over the sampling steps (a multiplier, high noise → low noise) if any."""
    start = sum(s["seconds"] for s in project["scenes"][:index])
    mid = start + project["scenes"][index]["seconds"] / 2
    out = []
    for lane in project.get("loras", []):
        if not lane["enabled"]:
            continue
        own = lane["scenes"].get(project["scenes"][index]["id"])
        strength = round(
            own if own is not None else curve_at(lane["film"], "t", mid, lane["strength"]), 3
        )
        if strength == 0:
            continue
        sampling = lane["steps"].get(project["scenes"][index]["id"], lane["sampling"])
        flat = not sampling or all(abs(p["v"] - 1.0) < 1e-6 for p in sampling)
        out.append(
            {
                "id": lane["id"],
                "name": lane["name"],
                "strength": strength,
                "sampling": [] if flat else sampling,
            }
        )
    return out


@dataclass
class Compiled:
    """One scene as an H3 request."""

    task: str
    prompt: str
    frames: int
    seconds: float
    #: The scene's noise seed (H3 Studio Outputs' `seed`).
    seed: int
    width: int
    height: int
    #: In the order H3 is shown them, each with its tag (see `tag_refs`).
    refs: list[dict[str, Any]] = field(default_factory=list)
    #: `[{frame, media}]`; frame 0 is the first frame, `frames - 1` the last.
    keyframes: list[dict[str, Any]] = field(default_factory=list)
    continuation: dict[str, Any] = field(default_factory=dict)
    #: `[{id, name, strength, sampling}]` — see `scene_loras`.
    loras: list[dict[str, Any]] = field(default_factory=list)
    #: The project's render settings (`normalize_settings`).
    settings: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


#: How a shot follows the one before. The first four start a new [Shot N]; dissolves, fades and
#: wipes are named, as the H3 guide allows when asked for. "continue" and "continue_timed" carry on
#: the shot before without a cut — joined with "Then," or with the moment it starts.
TRANSITIONS = ("cut", "dissolve", "fade", "wipe", "continue", "continue_timed")
CONTINUOUS = ("continue", "continue_timed")
TRANSITION_WORDS = {
    "dissolve": "the shot cross-dissolves",
    "fade": "the shot fades out and fades back in",
    "wipe": "the shot wipes to the next view",
}


def _lower_first(text: str) -> str:
    """'She turns' → 'she turns', for joining a sentence after "Then,"; names and tags stay."""
    if len(text) > 1 and text[0].isupper() and (text[1].islower() or text.startswith("A ")):
        return text[0].lower() + text[1:]
    return text


def _timestamp(seconds: float) -> str:
    minutes, rest = divmod(max(0.0, seconds), 60)
    return f"{int(minutes):02d}:{rest:06.3f}"


def _sentence(text: str) -> str:
    text = text.strip()
    if text and text[-1] not in ".!?\"'":
        text += "."
    return text


def mentions_ref(project: dict[str, Any], scene: dict[str, Any], ref: dict[str, Any]) -> bool:
    """Whether a scene uses a reference: a shot @mentions it, or a voice it gives a face or a timbre
    to speaks there."""
    mention = re.compile(rf"@{re.escape(ref['name'])}(?![\w-])", re.I)
    if any(mention.search(s["text"]) for s in scene["shots"]):
        return True
    voices = {v["id"] for v in project["cast"] if ref["id"] in (v.get("ref"), v.get("timbre"))}
    return any(set(line["speakers"]) & voices for s in scene["shots"] for line in s["lines"])


def refs_in_scene(project: dict[str, Any], scene: dict[str, Any]) -> list[dict[str, Any]]:
    """The references a scene shows H3: every one it uses (see `mentions_ref`), and those marked
    for it, or for every scene, without being used."""
    return [
        r
        for r in project["refs"]
        if mentions_ref(project, scene, r) or r["scenes"] == "all" or scene["id"] in r["scenes"]
    ]


def tag_refs(
    refs: list[dict[str, Any]], has_audio=None, warnings: list[str] | None = None
) -> list[dict[str, Any]]:
    """The scene's references in the order H3 is shown them, each with its tag.

    Core presents pictures, then videos (a video's soundtrack takes an `<Audio j>` label just before
    its `<Video k>`), then standalone audio, counting each kind from 1. Pictures that carry a latent
    come first: the DiT matches reference latents to `<Picture N>` by order alone. Pictures and
    videos are the scene's subjects (`<Subject n>`, in that order); audio is referred to by its tag.

    `has_audio(media)` says whether a video file has a soundtrack (assumed when not given), so the
    audio numbering here matches what the node actually encodes.

    References that share one file (same kind, role and sound) are one picture to H3: the first is
    tagged and encoded, the others take its tag and subject and are marked `alias`, so every name
    still resolves while H3 is shown it once.
    """
    first: dict[tuple, dict[str, Any]] = {}
    aliases: list[tuple[dict[str, Any], tuple]] = []
    unique = []
    for r in refs:
        key = (r["media"], r["kind"], r["role"], r["soundtrack"], r.get("size", 1.0))
        if key in first:
            aliases.append((r, key))
        else:
            first[key] = r
            unique.append(r)
    refs = unique

    def capped(kind: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(items) > LIMITS[kind] and warnings is not None:
            warnings.append(
                f"H3 takes {LIMITS[kind]} {kind} references per scene; {len(items) - LIMITS[kind]} left out."
            )
        return items[: LIMITS[kind]]

    images = [r for r in refs if r["kind"] == "image"]
    images = capped(
        "image",
        [r for r in images if r["role"] == "reference"]
        + [r for r in images if r["role"] == "semantic"],
    )
    videos = capped("video", [r for r in refs if r["kind"] == "video"])
    audios = capped("audio", [r for r in refs if r["kind"] == "audio"])

    out: list[dict[str, Any]] = []
    audio_n = subject = 0
    for i, r in enumerate(images, start=1):
        subject += 1
        out.append({**r, "tag": f"<Picture {i}>", "subject": subject, "soundtrack_tag": None})
    for i, r in enumerate(videos, start=1):
        # Blocking is direction, not a subject: it's named by its tag, and brings no sound.
        if r["role"] == "blocking":
            out.append({**r, "tag": f"<Video {i}>", "subject": None, "soundtrack_tag": None})
            continue
        subject += 1
        track = None
        if r["soundtrack"] and (has_audio is None or has_audio(r["media"])):
            audio_n += 1
            track = f"<Audio {audio_n}>"
        out.append({**r, "tag": f"<Video {i}>", "subject": subject, "soundtrack_tag": track})
    for r in audios:
        audio_n += 1
        out.append({**r, "tag": f"<Audio {audio_n}>", "subject": None, "soundtrack_tag": None})
    tagged = {r["id"]: r for r in out}
    for r, key in aliases:
        same = tagged.get(first[key]["id"])
        if same:
            out.append(
                {**r, **{k: same[k] for k in ("tag", "subject", "soundtrack_tag")}, "alias": True}
            )
    return out


def compile_scene(project: dict[str, Any], index: int, has_audio=None) -> Compiled:
    project = normalize(project)
    scenes = project["scenes"]
    scene = scenes[max(0, min(index, len(scenes) - 1))]
    frames = frames_for(scene["seconds"])
    seconds = frames / FPS
    width, height = project["canvas"]["width"], project["canvas"]["height"]
    warnings: list[str] = []

    carry = scene["continuation"]["mode"] if index > 0 else "cut"
    in_scene = refs_in_scene(project, scene)
    setting = None
    if carry == "reference":
        taken = {r["name"].lower() for r in in_scene}
        setting = {
            "id": "previous",
            "media": PREVIOUS_FRAME,
            "kind": "image",
            "name": "setting" if "setting" not in taken else "previous_setting",
            "note": "the place and light where the previous scene ends",
            "role": "reference",
            "retain": RETENTION[1],
            "soundtrack": False,
            "scenes": "all",
        }
        in_scene = [*in_scene, setting]
    # Proxies (no media yet) aren't shown to H3; where they are mentioned, their description is
    # written instead, so a script cast with placeholders still renders — from words alone.
    proxies = [r for r in in_scene if not r["media"]]
    refs = tag_refs([r for r in in_scene if r["media"]], has_audio, warnings)
    # What an @mention becomes: a picture or video is a <Subject n>; audio is named by its tag.
    named = {
        r["name"].lower(): (f"<Subject {r['subject']}>" if r["subject"] else r["tag"]) for r in refs
    }
    # A placeholder's full description the first time it's mentioned in the scene, its first clause
    # after that ("a woman in her thirties, a red coat" → "the woman in her thirties").
    described: dict[str, tuple[str, str]] = {}
    for r in proxies:
        full = r["note"].strip().rstrip(".") or r["name"]
        short = re.sub(r"^(a|an)\s+", "the ", full.split(",")[0].strip(), flags=re.I)
        described.setdefault(r["name"].lower(), (full, short))
    seen: set[str] = set()
    used_proxies = [
        r["name"]
        for r in proxies
        if any(f"@{r['name'].lower()}" in s["text"].lower() for s in scene["shots"])
    ]
    # A placeholder only shown with `with:` (never mentioned) adds nothing, not even words.
    silent = [
        r["name"]
        for r in proxies
        if r["name"] not in used_proxies and r["id"] != "previous" and r["kind"] != "audio"
    ]
    if silent:
        warnings.append(
            "No media yet, so H3 isn't shown "
            + ", ".join(f"@{n}" for n in silent)
            + " in this scene: add the file to the reference."
        )
    if used_proxies:
        warnings.append(
            "Described in words until they get a picture: "
            + ", ".join(f"@{n}" for n in used_proxies)
            + "."
        )

    def mentions(text: str) -> str:
        def swap(match: re.Match) -> str:
            key = match.group(1).lower()
            tag = named.get(key)
            if tag is None and key in described:
                full, short = described[key]
                tag = short if key in seen else full
                seen.add(key)
                # At the start of a sentence it starts with a capital.
                before = text[: match.start()].rstrip()
                if not before or before[-1] in ".!?":
                    tag = tag[:1].upper() + tag[1:]
            if tag is None:
                warnings.append(f"@{match.group(1)} is not a reference in this scene.")
                return match.group(0)
            return tag

        return re.sub(r"@([\w-]+)", swap, text)

    shots = [s for s in scene["shots"] if s["at"] < seconds or s is scene["shots"][0]]
    dialogue = Dialogue(project["cast"], refs, warnings, subjects=bool(refs))
    # A shot either starts a new [Shot N] (a cut, or a dissolve / fade / wipe) or carries on the
    # one before without a cut — so H3's shot numbers count only the former.
    numbers = []
    for i, shot in enumerate(shots):
        numbers.append(1 if i == 0 else numbers[-1] + (shot["transition"] not in CONTINUOUS))
    paragraphs: list[str] = []
    carried: list[dict[str, Any]] = []
    for i, shot in enumerate(shots):
        final = i == len(shots) - 1
        cut_after = not final and shots[i + 1]["transition"] not in CONTINUOUS
        spoken = dialogue.shot(
            shot["lines"], carried, cut_after=cut_after, final=final, start=shot["at"]
        )
        carried = [line for line in shot["lines"] if line["words"] and line["next"] and cut_after]
        own = _sentence(mentions(shot["text"]))
        text = " ".join(t for t in (own, spoken) if t)
        when = _timestamp(shot["at"])
        if i == 0:
            paragraphs.append(f"[Shot 1] {text or 'The scene continues.'}")
        elif shot["transition"] == "continue":
            if text:
                paragraphs[-1] += f" Then, {_lower_first(text)}"
        elif shot["transition"] == "continue_timed":
            if text:
                paragraphs[-1] += f" At {when}, {_lower_first(text)}"
        else:
            how = TRANSITION_WORDS.get(shot["transition"])
            opening = f"At {when}, {how}. " if how else f"At {when}, "
            body_text = text or "The scene continues."
            if not how:  # "At 00:03.000, the camera cuts to…", not "…, The camera…"
                body_text = _lower_first(body_text)
            paragraphs.append(f"[Shot {numbers[i]}] {opening}{body_text}")
    body = "\n".join(paragraphs)
    final_shot = numbers[-1]
    speaking = dialogue.speaking_refs([line for s in shots for line in s["lines"]])
    style = " ".join(
        s
        for s in (
            _sentence(project["style"]),
            _sentence(scene["direction"] or project["direction"]),
        )
        if s
    )
    soundscape = (
        _sentence(scene["soundscape"] or project["soundscape"])
        or "Natural ambient sound fitting the scene."
    )
    music = _sentence(scene["music"] or project["music"]) or "N/A"

    keyframes = []
    for k in scene["keyframes"]:
        # A keyframe at the end of the scene is its last frame, whatever rounding says.
        frame = (
            frames - 1 if k["at"] >= seconds - 1 / FPS else min(frames - 1, round(k["at"] * FPS))
        )
        keyframes.append({"frame": frame, "media": k["media"], "fit": k["fit"]})
    if carry == "first_frame":
        if any(k["frame"] == 0 for k in keyframes):
            warnings.append(
                "This scene has its own first frame, so the previous scene's last frame isn't used."
            )
        else:
            keyframes.insert(0, {"frame": 0, "media": PREVIOUS_FRAME, "fit": "crop"})
    has_first = any(k["frame"] == 0 for k in keyframes)
    has_last = any(k["frame"] == frames - 1 for k in keyframes)

    if refs:
        task = "ref2va"
        shown = [r for r in refs if not r.get("alias")]
        subjects = [r for r in shown if r["subject"]]
        blocking = [r for r in shown if r["role"] == "blocking"]
        sounds = [r for r in shown if r["kind"] == "audio" or r["soundtrack_tag"]]

        def sharing(r: dict[str, Any]) -> list[dict[str, Any]]:
            """`r` and the references that are the same file under other names."""
            return [x for x in refs if x["tag"] == r["tag"]]

        def note(r: dict[str, Any]) -> str:
            notes = list(dict.fromkeys(x["note"].strip() for x in sharing(r) if x["note"].strip()))
            return f", {'; '.join(notes)}" if notes else ""

        def names(r: dict[str, Any]) -> str:
            return " / ".join(dict.fromkeys(x["name"] for x in sharing(r)))

        definitions = (
            "\n".join(
                [
                    f"<Subject {r['subject']}> is the subject shown in {r['tag']}{note(r)}."
                    + (f" Its sound is {r['soundtrack_tag']}." if r["soundtrack_tag"] else "")
                    for r in subjects
                ]
                + [
                    f"{r['tag']} is blocking{note(r)}: it shows only where everyone stands and how "
                    "they move, the timing of the action, and where the camera is and how it moves. "
                    "Follow its staging, timing and camera exactly, and take nothing else from it: "
                    "its plain shapes and colours stand in for the people and places described here."
                    for r in blocking
                ]
                + dialogue.timbres
            )
            or "N/A"
        )
        used = [
            r
            for r in subjects
            if any(x["id"] in speaking for x in sharing(r))
            or any(f"@{x['name'].lower()}" in s["text"].lower() for x in sharing(r) for s in shots)
        ] or subjects
        # The carried-over setting frames every shot, mentioned or not.
        used += [r for r in subjects if r["id"] == "previous" and r not in used]
        features = ", ".join(f"<Subject {r['subject']}>" for r in used) or (
            "the referenced sound" if sounds else "the scene described below"
        )
        retention = [
            f"<Subject {r['subject']}> (appears in [Shot {_first_shot(sharing(r), shots, numbers)}]): {r['retain']} - "
            f"{names(r)} stays consistent with {r['tag']}."
            for r in subjects
        ] + [
            f"{r['tag']} (appears in [Shot {_first_shot(sharing(r), shots, numbers)}]): {r['retain']} - "
            f"{note(r)[2:] or names(r)} guides the sound."
            for r in shown
            if r["kind"] == "audio"
        ]
        retention += [
            f"{r['tag']} (staging, cuts and camera movement): fully_preserved - where everyone "
            f"stands and moves, when the shots cut, and the camera's position and movement follow "
            f"{r['tag']}; nothing of its look is kept."
            for r in blocking
        ]
        directive = "reference generation + audio reference" if sounds else "reference generation"
        follows = (
            " Its staging, cuts and camera movement follow "
            + " and ".join(r["tag"] for r in blocking)
            + "."
            if blocking
            else ""
        )
        lead = style or "The target video uses a cinematic live-action style."
        # Blocking no shot mentions still directs the whole scene.
        unmentioned = [
            r
            for r in blocking
            if not any(
                f"@{x['name'].lower()}" in s["text"].lower() for x in sharing(r) for s in shots
            )
        ]
        if unmentioned:
            tags = " and ".join(r["tag"] for r in unmentioned)
            lead += f" The staging, timing and camera movement follow {tags}."
        prompt = (
            f"subject_definitions:\n{definitions}\n\n"
            f"summary:\n[{directive}] The target video features {features}.{follows}\n\n"
            f"retention_analysis:\n{chr(10).join(retention) or 'N/A'}\n\n"
            f"detailed_description:\n{lead}\n{body}\n\n"
            f"overall_soundscape:\n{soundscape}\n\n"
            f"non_diegetic_music:\n{music}"
        )
        if keyframes:
            warnings.append(
                "Keyframes in a reference scene guide the latent only; the prompt cannot mention them."
            )
    else:
        if has_first and has_last:
            task = "fl2va"
            first_line = (
                "How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the "
                f"0.00-second mark of the target video; Picture 2 (from Shot {final_shot}) aligns with the "
                f"{(frames - 1) / FPS:.2f}-second mark of the target video."
            )
        elif has_first:
            task = "i2va"
            first_line = "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced."
        elif has_last:
            task = "l2va"
            first_line = (
                f"How the reference pictures align with the target video — <Picture 1> (from [Shot {final_shot}]) "
                f"aligns with the {(frames - 1) / FPS:.2f}-second mark of the target video."
            )
        else:
            task = "t2va"
            first_line = ""
        first_shot = body.replace("[Shot 1] ", f"[Shot 1] {style} ", 1) if style else body
        prompt = (
            (f"{first_line}\n\n" if first_line else "")
            + f"integrated_multimodal_description: {first_shot}\n\n"
            + f"overall_soundscape: {soundscape}\n\n"
            + f"non_diegetic_music: {music}"
        )

    if not any(s["text"].strip() or any(line["words"] for line in s["lines"]) for s in shots):
        warnings.append("No shot has any text yet.")
    if seconds > 15.5:
        warnings.append(f"{seconds:.1f}s is past H3's trained range (about 5-15s per generation).")

    return Compiled(
        loras=scene_loras(project, scenes.index(scene)),
        settings=project["settings"],
        task=task,
        prompt=prompt,
        frames=frames,
        seconds=round(seconds, 3),
        seed=scene["seed"],
        width=width,
        height=height,
        refs=[
            {
                "id": r["id"],
                "name": r["name"],
                "media": r["media"],
                "kind": r["kind"],
                "role": r["role"],
                "tag": r["tag"],
                "soundtrack_tag": r["soundtrack_tag"],
                "alias": bool(r.get("alias")),
                "size": r.get("size", 1.0),
            }
            for r in refs
        ],
        keyframes=keyframes,
        continuation=dict(scene["continuation"]) if index > 0 else {"mode": "cut", "frames": 0},
        warnings=list(dict.fromkeys(warnings)),
    )


def _first_shot(refs: list[dict[str, Any]], shots: list[dict[str, Any]], numbers: list[int]) -> int:
    """The first shot that mentions any of `refs` (one file under several names), else shot 1."""
    for shot, n in zip(shots, numbers, strict=True):
        if any(f"@{r['name'].lower()}" in shot["text"].lower() for r in refs):
            return n
    return 1
