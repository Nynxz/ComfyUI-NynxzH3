"""A grey box scene: its set, its cast, where everyone is at each moment, and each shot's camera.

Units are metres, Y is up, the floor is y = 0. An actor's `yaw` is the way it faces, in degrees
around Y: 0 faces +Z, 90 faces +X. Times are seconds from the start of the scene.

    scene = load("…/scenes/ep01-03.json")          # resolves its set and cast
    state = scene.at(1.5)                           # actors' positions, poses and facing
    cam = scene.camera(scene.shots[0], 1.5)         # the shot's camera then
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

Vec = tuple[float, float, float]

DEFAULT_HEIGHT = 1.7
DEFAULT_LENS = 35.0
#: Where a camera looking "at" an actor aims: this far below the top of its head.
LOOK_DROP = 0.12


class SceneError(ValueError):
    """Something in a scene (or its set or cast) that can't be used; the message says what."""


# --- shapes ----------------------------------------------------------------------------------


@dataclass
class Shape:
    """A plain shape: `box` (size), `cylinder` (radius, height; stands on `at`), `sphere`
    (radius), or `capsule` (radius, from `a` to `b`). `tone` is its grey, 0 to 1."""

    kind: str
    at: Vec = (0.0, 0.0, 0.0)
    size: Vec = (1.0, 1.0, 1.0)
    radius: float = 0.5
    height: float = 1.0
    a: Vec = (0.0, 0.0, 0.0)
    b: Vec = (0.0, 1.0, 0.0)
    yaw: float = 0.0
    tone: float = 0.7
    id: str = ""
    #: Which object it belongs to (an actor's mention, or the shape's own id), for masks.
    owner: str = ""


def _vec(v: Any, what: str, default: Vec | None = None) -> Vec:
    if v is None and default is not None:
        return default
    if isinstance(v, (list, tuple)) and len(v) == 3 and all(isinstance(x, (int, float)) for x in v):
        return (float(v[0]), float(v[1]), float(v[2]))
    raise SceneError(f"{what} should be [x, y, z] in metres, not {v!r}.")


def _num(v: Any, default: float, lo: float = -1e9, hi: float = 1e9) -> float:
    return min(max(float(v), lo), hi) if isinstance(v, (int, float)) else default


def _shape(raw: dict, where: str) -> Shape:
    kind = raw.get("type", "box")
    sid = str(raw.get("id", ""))
    label = f"{where} shape {sid or kind}"
    tone = _num(raw.get("tone"), 0.7, 0, 1)
    if kind == "box":
        return Shape(
            "box",
            at=_vec(raw.get("at"), f"{label}: at"),
            size=_vec(raw.get("size"), f"{label}: size", (1.0, 1.0, 1.0)),
            yaw=_num(raw.get("yaw"), 0.0),
            tone=tone,
            id=sid,
            owner=sid,
        )
    if kind == "cylinder":
        return Shape(
            "cylinder",
            at=_vec(raw.get("at"), f"{label}: at"),
            radius=_num(raw.get("radius"), 0.5, 0.001),
            height=_num(raw.get("height"), 1.0, 0.001),
            tone=tone,
            id=sid,
            owner=sid,
        )
    if kind == "sphere":
        return Shape(
            "sphere",
            at=_vec(raw.get("at"), f"{label}: at"),
            radius=_num(raw.get("radius"), 0.5, 0.001),
            tone=tone,
            id=sid,
            owner=sid,
        )
    if kind == "capsule":
        return Shape(
            "capsule",
            a=_vec(raw.get("a"), f"{label}: a"),
            b=_vec(raw.get("b"), f"{label}: b"),
            radius=_num(raw.get("radius"), 0.2, 0.001),
            tone=tone,
            id=sid,
            owner=sid,
        )
    raise SceneError(f"{label}: type should be box, cylinder, sphere or capsule, not {kind!r}.")


# --- sets and cast ---------------------------------------------------------------------------


@dataclass
class Set:
    name: str
    shapes: list[Shape]
    #: Named spots on the floor ("stove", "door"): what actors' keys and cameras can name.
    marks: dict[str, Vec]
    #: Named camera set-ups ("wide": at, look, lens) a shot can start from.
    cameras: dict[str, dict]


@dataclass
class Member:
    """A cast member's figure: how tall, how broad, and its grey."""

    height: float = DEFAULT_HEIGHT
    build: float = 1.0
    tone: float = 0.88


def load_set(path: Path) -> Set:
    return set_from(_read(path), path.stem)


def load_cast(path: Path | None) -> dict[str, Member]:
    if path is None or not path.exists():
        return {}
    return cast_from(_read(path))


def cast_from(raw: dict) -> dict[str, Member]:
    return {_mention(k): _member(v) for k, v in raw.items() if isinstance(v, dict)}


def _member(raw: dict) -> Member:
    return Member(
        height=_num(raw.get("height"), DEFAULT_HEIGHT, 0.3, 3.0),
        build=_num(raw.get("build"), 1.0, 0.4, 2.5),
        tone=_num(raw.get("tone"), 0.88, 0, 1),
    )


def _mention(name: str) -> str:
    return name if name.startswith("@") else f"@{name}"


def _read(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise SceneError(f"No file at {path}.") from e
    except json.JSONDecodeError as e:
        raise SceneError(f"{path} isn't valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise SceneError(f"{path} should hold a JSON object.")
    return data


# --- keys and motion -------------------------------------------------------------------------


@dataclass
class Key:
    t: float
    #: A point, or a target name resolved later (a mark, an actor) — positions and look-ats.
    at: Any = None
    look: Any = None
    face: Any = None
    pose: str | None = None
    lens: float | None = None
    ease: str = "linear"


def _keys(raw: Any, what: str, ease: str) -> list[Key]:
    if not isinstance(raw, list) or not raw:
        raise SceneError(f"{what} needs a list of keys, each with a time `t`.")
    keys = []
    for k in raw:
        if not isinstance(k, dict) or not isinstance(k.get("t"), (int, float)):
            raise SceneError(f"{what}: every key needs a time `t` in seconds ({k!r}).")
        keys.append(
            Key(
                t=float(k["t"]),
                at=k.get("at"),
                look=k.get("look"),
                face=k.get("face"),
                pose=k.get("pose") if isinstance(k.get("pose"), str) else None,
                lens=_num(k.get("lens"), 0.0, 8, 400) or None,
                ease=str(k.get("ease", ease)),
            )
        )
    return sorted(keys, key=lambda k: k.t)


def _ease(u: float, kind: str) -> float:
    if kind == "smooth":
        return u * u * (3 - 2 * u)
    if kind == "in":
        return u * u
    if kind == "out":
        return 1 - (1 - u) * (1 - u)
    return u


def _catmull(p0: Vec, p1: Vec, p2: Vec, p3: Vec, u: float) -> Vec:
    u2, u3 = u * u, u * u * u
    return tuple(
        0.5
        * (
            2 * p1[i]
            + (-p0[i] + p2[i]) * u
            + (2 * p0[i] - 5 * p1[i] + 4 * p2[i] - p3[i]) * u2
            + (-p0[i] + 3 * p1[i] - 3 * p2[i] + p3[i]) * u3
        )
        for i in range(3)
    )  # type: ignore[return-value]


def path_at(times: list[float], points: list[Vec], eases: list[str], t: float) -> Vec:
    """A smooth path through `points` (one per time): Catmull-Rom between neighbours, each
    segment eased by its starting key; held before the first and after the last."""
    if t <= times[0]:
        return points[0]
    if t >= times[-1]:
        return points[-1]
    i = max(j for j in range(len(times) - 1) if times[j] <= t)
    span = max(times[i + 1] - times[i], 1e-9)
    u = _ease((t - times[i]) / span, eases[i])
    p0 = points[max(i - 1, 0)]
    p3 = points[min(i + 2, len(points) - 1)]
    return _catmull(p0, points[i], points[i + 1], p3, u)


def _lerp(a: float, b: float, u: float) -> float:
    return a + (b - a) * u


def _angle_lerp(a: float, b: float, u: float) -> float:
    d = (b - a + 180) % 360 - 180
    return a + d * u


# --- the scene -------------------------------------------------------------------------------


@dataclass
class Actor:
    id: str
    member: Member
    keys: list[Key]


@dataclass
class ActorState:
    id: str
    at: Vec
    yaw: float
    pose: str
    member: Member

    @property
    def eye(self) -> Vec:
        """Where a camera looking at it aims (its face)."""
        h = self.member.height * (0.72 if self.pose == "sit" else 1.0)
        return (self.at[0], self.at[1] + h - LOOK_DROP, self.at[2])


@dataclass
class Shot:
    name: str
    start: float
    end: float
    camera: list[Key]


@dataclass
class Camera:
    at: Vec
    look: Vec
    lens: float

    #: Vertical field of view in degrees (a 35 mm-equivalent lens on a 24 mm tall frame).
    @property
    def fov(self) -> float:
        return math.degrees(2 * math.atan(12.0 / self.lens))


@dataclass
class Scene:
    set: Set
    actors: list[Actor]
    shots: list[Shot]
    name: str = ""
    fps: float = 24.0
    extra: list[Shape] = field(default_factory=list)

    @property
    def length(self) -> float:
        ends = [s.end for s in self.shots] + [k.t for a in self.actors for k in a.keys]
        return max(ends, default=0.0)

    def shot(self, name: str | None) -> Shot | None:
        if not name:
            return None
        return next((s for s in self.shots if s.name == name), None)

    # positions and look targets ---------------------------------------------------------------

    def point(self, ref: Any, t: float, what: str) -> Vec:
        """A point named in a key: [x, y, z], a set mark ("stove" or "mark:stove"), or an actor
        ("@ren") — its feet for positions; use `target` for where to look."""
        if isinstance(ref, (list, tuple)):
            return _vec(ref, what)
        if isinstance(ref, str):
            name = ref.removeprefix("mark:")
            if name in self.set.marks:
                return self.set.marks[name]
            if ref.startswith("@"):
                return self.actor_at(ref, t).at
        raise SceneError(
            f"{what}: {ref!r} isn't a point, a mark of the set "
            f"({', '.join(self.set.marks) or 'it has none'}) or an actor."
        )

    def target(self, ref: Any, t: float, what: str) -> Vec:
        """Where to look: an actor's face, else a point or mark (at eye height when on the floor)."""
        if isinstance(ref, str) and ref.startswith("@"):
            return self.actor_at(ref, t).eye
        p = self.point(ref, t, what)
        return p if isinstance(ref, (list, tuple)) else (p[0], 1.2, p[2])

    # actors -----------------------------------------------------------------------------------

    def actor_at(self, aid: str, t: float, _depth: int = 0) -> ActorState:
        actor = next((a for a in self.actors if a.id == aid), None)
        if actor is None:
            raise SceneError(f"There's no actor {aid} in this scene.")
        if _depth > 4:
            raise SceneError(f"{aid}'s keys look at each other in a loop.")
        keys = actor.keys
        times = [k.t for k in keys]
        points = [self.point(k.at, k.t, f"{aid} at {k.t}s") for k in keys]
        at = path_at(times, points, [k.ease for k in keys], t)
        prev = [k for k in keys if k.t <= t] or keys[:1]
        pose = next((k.pose for k in reversed(prev) if k.pose), "stand")
        return ActorState(
            aid, at, self._yaw(actor, keys, times, points, t, _depth), pose, actor.member
        )

    def _yaw(self, actor, keys, times, points, t, depth) -> float:
        before = [k for k in keys if k.t <= t]
        face = next((k.face for k in reversed(before) if k.face is not None), None)
        if face is None:
            face = next((k.face for k in keys if k.face is not None), "path")
        if isinstance(face, (int, float)):
            # Between two keys that both give a yaw, it turns from one to the other.
            after = [k for k in keys if k.t > t and isinstance(k.face, (int, float))]
            last = next(k for k in reversed(before or keys[:1]) if k.face is not None)
            if after and isinstance(last.face, (int, float)):
                nxt = after[0]
                u = (t - last.t) / max(nxt.t - last.t, 1e-9)
                return _angle_lerp(float(last.face), float(nxt.face), min(max(u, 0), 1))
            return float(face)
        here = path_at(times, points, [k.ease for k in keys], t)
        if face == "path":
            # Facing where it's going (looking a moment ahead; a moment back once it stops).
            for dt in (0.05, -0.05):
                there = path_at(times, points, [k.ease for k in keys], t + dt)
                dx, dz = (
                    (there[0] - here[0]) * math.copysign(1, dt),
                    (there[2] - here[2]) * math.copysign(1, dt),
                )
                if dx * dx + dz * dz > 1e-8:
                    return math.degrees(math.atan2(dx, dz))
            return 0.0
        if isinstance(face, str) and face.startswith("@"):
            other = self.actor_at(face, t, depth + 1).at
        else:
            other = self.point(face, t, f"{actor.id}'s face")
        return math.degrees(math.atan2(other[0] - here[0], other[2] - here[2]))

    def at(self, t: float) -> list[ActorState]:
        return [self.actor_at(a.id, t) for a in self.actors]

    # cameras ----------------------------------------------------------------------------------

    def camera(self, shot: Shot, t: float) -> Camera:
        keys = shot.camera
        times = [k.t for k in keys]
        name = f"shot {shot.name}'s camera"
        spots = [self._camera_key(k, t, name) for k in keys]
        eases = [k.ease for k in keys]
        at = path_at(times, [s[0] for s in spots], eases, t)
        look = path_at(times, [s[1] for s in spots], eases, t)
        if t <= times[0]:
            lens = spots[0][2]
        elif t >= times[-1]:
            lens = spots[-1][2]
        else:
            i = max(j for j in range(len(times) - 1) if times[j] <= t)
            u = _ease((t - times[i]) / max(times[i + 1] - times[i], 1e-9), eases[i])
            lens = _lerp(spots[i][2], spots[i + 1][2], u)
        return Camera(at, look, lens)

    def _camera_key(self, k: Key, t: float, what: str) -> tuple[Vec, Vec, float]:
        base = self.set.cameras.get(str(k.at)) if isinstance(k.at, str) else None
        if base is not None:
            at = _vec(base.get("at"), f"{what}: set camera {k.at}")
            look_ref = k.look if k.look is not None else base.get("look")
            lens = k.lens or _num(base.get("lens"), DEFAULT_LENS, 8, 400)
        else:
            at = self.point(k.at, t, f"{what} at {k.t}s")
            if not isinstance(k.at, (list, tuple)):
                at = (at[0], 1.6, at[2])
            look_ref = k.look
            lens = k.lens or DEFAULT_LENS
        if look_ref is None:
            raise SceneError(f"{what} at {k.t}s needs `look`: a point, a mark or an actor.")
        return at, self.target(look_ref, t, f"{what} at {k.t}s: look"), lens


def set_from(raw: dict, name: str) -> Set:
    """A set from its JSON (`name` is used when it gives none)."""
    where = f"set {name}"
    return Set(
        name=str(raw.get("name", name)),
        shapes=[_shape(s, where) for s in raw.get("shapes", [])],
        marks={str(k): _vec(v, f"{where}: mark {k}") for k, v in raw.get("marks", {}).items()},
        cameras={str(k): v for k, v in raw.get("cameras", {}).items() if isinstance(v, dict)},
    )


def build(
    raw: dict, the_set: Set | None, cast: dict[str, Member] | None = None, name: str = "scene"
) -> Scene:
    """A scene from its JSON, its set and its cast (already loaded). Bad references are caught
    here, not mid-render."""
    if not isinstance(raw, dict):
        raise SceneError("A scene should be a JSON object.")
    if isinstance(raw.get("set"), dict):
        the_set = set_from(raw["set"], "inline")
    cast = dict(cast or {})
    for k, v in (raw.get("cast") or {}).items():
        if isinstance(v, dict):
            cast[_mention(k)] = _member(v)
    actors = []
    for a in raw.get("actors", []):
        aid = _mention(str(a.get("id", "")))
        if aid == "@":
            raise SceneError('Every actor needs an `id`, like "@ren".')
        actors.append(
            Actor(aid, cast.get(aid, Member()), _keys(a.get("keys"), f"actor {aid}", "linear"))
        )
    shots = []
    for i, s in enumerate(raw.get("shots", [])):
        sname = str(s.get("name", f"shot{i + 1}"))
        start = _num(s.get("start"), 0.0, 0)
        end = _num(s.get("end"), start + 3.0, start + 0.05)
        shots.append(
            Shot(sname, start, end, _keys(s.get("camera"), f"shot {sname}'s camera", "smooth"))
        )
    if not shots:
        raise SceneError("A scene needs at least one shot, each with a camera.")
    scene = Scene(
        the_set or Set("empty", [], {}, {}),
        actors,
        shots,
        name=str(raw.get("name", name)),
        fps=_num(raw.get("fps"), 24.0, 1, 120),
        extra=[_shape(s, "scene") for s in raw.get("shapes", [])],
    )
    for s in shots:
        scene.camera(s, s.start)
    for a in actors:
        scene.actor_at(a.id, 0.0)
    return scene


def load(path: str | Path, search: list[Path] | None = None) -> Scene:
    """A scene file with its set and cast found: the set by name in `sets/` beside the scene's
    folder (or beside the scene), the cast in `cast.json` there."""
    path = Path(path)
    raw = _read(path)
    roots = [*(search or []), path.parent, path.parent.parent]
    set_ref = raw.get("set")
    the_set = None
    if isinstance(set_ref, str):
        found = next(
            (
                r / "sets" / f"{set_ref}.json"
                for r in roots
                if (r / "sets" / f"{set_ref}.json").exists()
            ),
            None,
        )
        if found is None:
            raise SceneError(
                f"No set called {set_ref!r}: looked for sets/{set_ref}.json beside {path}."
            )
        the_set = load_set(found)
    cast_file = next((r / "cast.json" for r in roots if (r / "cast.json").exists()), None)
    return build(raw, the_set, load_cast(cast_file), path.stem)


# --- figures ---------------------------------------------------------------------------------


def figure(state: ActorState) -> list[Shape]:
    """An actor as plain shapes: a body and a head, and a small block on the face so which way it
    faces reads at a glance. Seated, it's lower and its legs reach forward."""
    m = state.member
    h = m.height * (0.72 if state.pose == "sit" else 1.0)
    r = 0.17 * m.build * m.height / DEFAULT_HEIGHT
    x, y, z = state.at
    yaw = math.radians(state.yaw)
    fx, fz = math.sin(yaw), math.cos(yaw)
    head_r = 0.115 * m.height / DEFAULT_HEIGHT
    head_y = y + h - head_r
    shapes = [
        Shape(
            "capsule",
            a=(x, y + r, z),
            b=(x, y + h - 2 * head_r - r * 0.6, z),
            radius=r,
            tone=m.tone,
            owner=state.id,
        ),
        Shape("sphere", at=(x, head_y, z), radius=head_r, tone=m.tone, owner=state.id),
        Shape(
            "box",
            at=(x + fx * head_r * 0.95, head_y - head_r * 0.15, z + fz * head_r * 0.95),
            size=(head_r * 0.7, head_r * 0.45, head_r * 0.5),
            yaw=state.yaw,
            tone=min(1.0, m.tone + 0.1),
            owner=state.id,
        ),
    ]
    if state.pose == "sit":
        knee = (
            x + fx * 0.42 * m.height / DEFAULT_HEIGHT,
            y + 0.48 * m.height / DEFAULT_HEIGHT,
            z + fz * 0.42 * m.height / DEFAULT_HEIGHT,
        )
        shapes.append(
            Shape(
                "capsule",
                a=(x, y + 0.5 * m.height / DEFAULT_HEIGHT, z),
                b=knee,
                radius=r * 0.7,
                tone=m.tone,
                owner=state.id,
            )
        )
    return shapes


def shapes_at(scene: Scene, t: float) -> list[Shape]:
    """Everything visible at `t`: the set, the scene's own shapes, and every actor's figure."""
    out = [*scene.set.shapes, *scene.extra]
    for state in scene.at(t):
        out.extend(figure(state))
    return out
