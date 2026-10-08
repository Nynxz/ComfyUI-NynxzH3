"""Motion verbs for Grey Box scripts: a line like `1.9-2.45 @ren runs on ledge-20 to [1.6, 0.3]`
becomes the keys that make that move — sampled densely enough that the smooth path through keys
can't cut through a roof or overshoot a landing. The engine only ever sees ordinary keys.

Each generator gets the move's span, where the actor is when it starts (`Start`) and a `World` to
ask about places and surfaces, and returns keys from the start time to the end time."""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Vec = tuple[float, float, float]

#: Seconds between generated keys: on a surface, in the air, swinging, and following.
GROUND_STEP, AIR_STEP, SWING_STEP, FOLLOW_STEP = 0.1, 0.04, 0.07, 0.25
#: How far above the higher end a jump rises, by verb.
APEX = {"jumps": 0.8, "leaps": 0.8, "hops": 0.4, "drops": 0.15, "falls": 0.15}
#: From the bar down to the feet of someone hanging from it, as a share of their height.
HANG = 1.236
REACH, REACH_HOLD = 1.5, 0.15  # climbing: metres per reach, and the pause between reaches


class MoveError(ValueError):
    pass


@dataclass
class Start:
    at: Vec
    #: The way it faces as it starts the move, in degrees (from its last key, or its last move).
    yaw: float
    face: Any = None  # its last key's `face`, kept by moves that don't turn it (climbing)


@dataclass
class World:
    """What the moves need to know about the scene: places, surfaces, bars, who's who."""

    place: Callable[[str], Vec]  # a mark, [x, y, z] or "on SHAPE at [x, z]" -> a point
    surface: Callable[[str, float, float], float | None]  # shape, x, z -> its top there
    bar: Callable[[str], tuple[Vec, Vec] | None]  # a lying shape's two ends, or None
    height: Callable[[str], float]  # an actor's height


def split(text: str) -> list[str]:
    """Comma-separated parts, keeping commas inside [ ] together."""
    out, depth, cur = [], 0, ""
    for ch in text:
        depth += ch == "["
        depth -= ch == "]"
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return [*out, cur.strip()] if cur.strip() else out


def r(v) -> list[float]:
    return [round(float(x), 4) for x in v]


def yaw_of(dx: float, dz: float, fallback: float) -> float:
    return math.degrees(math.atan2(dx, dz)) if abs(dx) + abs(dz) > 1e-6 else fallback


def times(t0: float, t1: float, step: float) -> list[float]:
    n = max(1, round((t1 - t0) / step))
    return [t0 + (t1 - t0) * i / n for i in range(n + 1)]


def key(t: float, at, **more) -> dict:
    return {"t": round(t, 4), "at": r(at), **more}


# --- along a surface or straight ------------------------------------------------------------


def travel(verb, t0, t1, start: Start, rest: str, world: World) -> list[dict]:
    """runs / walks / moves [on SHAPE] to PLACE; slides [down|along] SHAPE to [x, z] (crouched)."""
    slide = verb == "slides"
    m = re.fullmatch(r"(?:(?:down|along|across|over)\s+)?(?:on\s+)?([\w./-]+)\s+to\s+(.+)", rest)
    shape = None
    if slide or (m and not rest.startswith("to ")):
        if not m:
            raise MoveError(f"{verb} SHAPE to [x, z]: say which surface, and where to")
        shape, target = m.group(1), m.group(2).strip()
        end_xz = _xz(target, world)
    else:
        m2 = re.fullmatch(r"to\s+(.+)", rest)
        if not m2:
            raise MoveError(f"{verb} to PLACE (or {verb} on SHAPE to [x, z])")
        end = world.place(m2.group(1).strip())
    pose = "crouch" if slide else "stand"
    out = []
    ts = times(t0, t1, GROUND_STEP)
    for i, t in enumerate(ts):
        u = i / (len(ts) - 1)
        if shape:
            x = start.at[0] + (end_xz[0] - start.at[0]) * u
            z = start.at[2] + (end_xz[1] - start.at[2]) * u
            y = world.surface(shape, x, z)
            if y is None:
                raise MoveError(f"the way to [{x:.2f}, {z:.2f}] leaves {shape}")
            p = (x, y, z)
        else:
            p = tuple(start.at[k] + (end[k] - start.at[k]) * u for k in range(3))
        k = key(t, p)
        if i == 0:
            k["pose"] = pose
        out.append(k)
    if shape:
        for k in out:
            k["on"] = shape
    return out


def _xz(target: str, world: World) -> tuple[float, float]:
    if target.startswith("["):
        nums = [float(v) for v in re.split(r"[\s,]+", target.strip("[] ")) if v]
        if len(nums) == 2:
            return nums[0], nums[1]
        if len(nums) == 3:
            return nums[0], nums[2]
        raise MoveError(f"{target}: give [x, z]")
    p = world.place(target)
    return p[0], p[2]


# --- through the air --------------------------------------------------------------------------


def jump(verb, t0, t1, start: Start, rest: str, world: World, actor: str) -> list[dict]:
    """jumps / leaps / hops / drops / falls to TARGET[, height H] — a ballistic arc. TARGET is a
    place (crouched landing) or a bar (catches it and hangs)."""
    parts = split(rest)
    m = re.fullmatch(r"to\s+(.+)", parts[0])
    if not m:
        raise MoveError(f"{verb} to PLACE (or to a bar)[, height N]")
    target = m.group(1).strip()
    apex = APEX[verb]
    for p in parts[1:]:
        h = re.fullmatch(r"height\s+(-?[\d.]+)", p)
        if not h:
            raise MoveError(f"unexpected {p!r} (height N)")
        apex = float(h.group(1))
    hang = None
    if not target.startswith("[") and not target.startswith("on ") and world.bar(target):
        a, b = world.bar(target)
        hang = _closest(a, b, start.at)
        end = (hang[0], hang[1] - HANG * world.height(actor), hang[2])
    else:
        end = world.place(target)
    top = max(start.at[1], end[1]) + apex
    k = _arc_k(start.at[1], end[1], top)
    out = []
    ts = times(t0, t1, AIR_STEP)
    for i, t in enumerate(ts):
        u = i / (len(ts) - 1)
        p = (
            start.at[0] + (end[0] - start.at[0]) * u,
            start.at[1] + (end[1] - start.at[1]) * u + k * u * (1 - u),
            start.at[2] + (end[2] - start.at[2]) * u,
        )
        out.append(key(t, p))
    out[0]["pose"] = "stand"
    if hang is None:
        out[-1]["pose"] = "crouch"
        on = re.fullmatch(r"on\s+([\w./-]+)\s+at\s+.+", target)
        if on:
            out[-1]["on"] = on.group(1)
    return out


def _arc_k(y0: float, y1: float, top: float) -> float:
    """The bulge `k` of y(u) = y0 + (y1 - y0)u + k·u(1 - u) that peaks at `top`."""
    lo, hi = 0.0, 4 * max(top - min(y0, y1), 0.01) + 4 * abs(y1 - y0) + 1
    for _ in range(60):
        k = (lo + hi) / 2
        peak = max(y0 + (y1 - y0) * u + k * u * (1 - u) for u in (i / 200 for i in range(201)))
        lo, hi = (k, hi) if peak < top else (lo, k)
    return (lo + hi) / 2


def _closest(a: Vec, b: Vec, p: Vec) -> Vec:
    ab = [b[i] - a[i] for i in range(3)]
    ap = [p[i] - a[i] for i in range(3)]
    den = sum(x * x for x in ab) or 1e-9
    u = max(0.0, min(1.0, sum(ab[i] * ap[i] for i in range(3)) / den))
    return tuple(a[i] + ab[i] * u for i in range(3))


# --- climbing and swinging ----------------------------------------------------------------------


def climb(verb, t0, t1, start: Start, rest: str, world: World) -> list[dict]:
    """climbs [up|down] to PLACE — in reaches of about 1.5 m with a pause between, facing the way
    it faced (the wall)."""
    m = re.fullmatch(r"(?:(?:up|down|along|across)\s+)?(?:[\w./-]+\s+)?to\s+(.+)", rest)
    if not m:
        raise MoveError("climbs [up|down] to PLACE")
    end = world.place(m.group(1).strip())
    dist = math.dist(start.at, end)
    n = max(1, math.ceil(dist / REACH))
    span = (t1 - t0) / n
    out = []
    for i in range(n):
        a = [start.at[k] + (end[k] - start.at[k]) * i / n for k in range(3)]
        b = [start.at[k] + (end[k] - start.at[k]) * (i + 1) / n for k in range(3)]
        hold = min(REACH_HOLD, span * 0.3) if i else 0.0
        if hold:
            out.append(key(t0 + span * i, a))
        out.append(key(t0 + span * i + hold, a))
        if i == n - 1:
            out.append(key(t1, b))
    face = start.face if start.face is not None else round(start.yaw, 2)
    for k in out:
        k["face"] = face
    # Dedupe the touching keys where one reach ends and the next begins.
    clean = []
    for k in out:
        if clean and abs(clean[-1]["t"] - k["t"]) < 1e-6:
            continue
        clean.append(k)
    return clean


def swing(verb, t0, t1, start: Start, rest: str, world: World, actor: str) -> list[dict]:
    """swings on BAR: A1 A2 A3 … — angles in degrees out from hanging straight down (positive is
    the way it faces), the first where it catches, the rest the peaks either way. Between peaks it
    eases like a pendulum."""
    m = re.fullmatch(r"(?:on|from)\s+([\w./-]+)\s*:\s*(.+)", rest)
    if not m:
        raise MoveError("swings on BAR: -15 50 -40 72 (angles, degrees)")
    ends = world.bar(m.group(1))
    if not ends:
        raise MoveError(f"{m.group(1)} isn't a bar (a capsule or a lying cylinder)")
    angles = [float(v.rstrip("°")) for v in m.group(2).split()]
    if len(angles) < 2:
        raise MoveError("give at least two angles: where it catches, and a peak")
    a, b = ends
    length = HANG * world.height(actor)
    pivot = _closest(a, b, (start.at[0], start.at[1] + length, start.at[2]))
    axis = [b[i] - a[i] for i in range(3)]
    norm = math.sqrt(sum(x * x for x in axis)) or 1.0
    axis = [x / norm for x in axis]
    yaw = math.radians(start.yaw)
    f = [math.sin(yaw), 0.0, math.cos(yaw)]
    dot = sum(f[i] * axis[i] for i in range(3))
    out_dir = [f[0] - dot * axis[0], 0.0, f[2] - dot * axis[2]]
    on = math.hypot(out_dir[0], out_dir[2])
    if on < 1e-6:
        out_dir, on = [axis[2], 0.0, -axis[0]], math.hypot(axis[2], axis[0]) or 1.0
    out_dir = [out_dir[0] / on, 0.0, out_dir[2] / on]
    face = round(math.degrees(math.atan2(out_dir[0], out_dir[2])), 2)

    def feet(deg: float) -> Vec:
        th = math.radians(deg)
        return (
            pivot[0] + length * math.sin(th) * out_dir[0],
            pivot[1] - length * math.cos(th),
            pivot[2] + length * math.sin(th) * out_dir[2],
        )

    seg = (t1 - t0) / (len(angles) - 1)
    out = []
    for i in range(len(angles) - 1):
        a0, a1 = angles[i], angles[i + 1]
        ts = times(t0 + seg * i, t0 + seg * (i + 1), SWING_STEP)
        for j, t in enumerate(ts):
            if out and j == 0:
                continue
            u = j / (len(ts) - 1)
            eased = (1 - math.cos(math.pi * u)) / 2
            out.append(key(t, feet(a0 + (a1 - a0) * eased), face=face))
    out[0]["pose"] = "stand"
    return out


# --- following -------------------------------------------------------------------------------


def offset(text: str) -> tuple[float, float, float]:
    """`6 behind, 4 up, 1 left` -> (forward, up, left) in the target's own frame."""
    fwd = up = left = 0.0
    for part in split(text):
        m = re.fullmatch(r"(-?[\d.]+)\s*m?\s+(behind|ahead|up|down|left|right)", part)
        if not m:
            raise MoveError(
                f"unexpected {part!r} (N behind, N ahead, N up, N down, N left, N right)"
            )
        v, w = float(m.group(1)), m.group(2)
        if w == "behind":
            fwd -= v
        elif w == "ahead":
            fwd += v
        elif w == "up":
            up += v
        elif w == "down":
            up -= v
        elif w == "left":
            left += v
        else:
            left -= v
    return fwd, up, left


def in_frame(at: Vec, yaw_deg: float, off: tuple[float, float, float]) -> Vec:
    """A point offset from `at` in the frame of something facing `yaw_deg`: forward, up, left (its
    left hand: +x for something facing +z)."""
    fwd, up, left = off
    y = math.radians(yaw_deg)
    f = (math.sin(y), math.cos(y))
    lft = (math.cos(y), -math.sin(y))
    return (at[0] + f[0] * fwd + lft[0] * left, at[1] + up, at[2] + f[1] * fwd + lft[1] * left)


VERBS = {
    **dict.fromkeys(("runs", "walks", "moves", "slides"), "travel"),
    **dict.fromkeys(APEX, "jump"),
    "climbs": "climb",
    "swings": "swing",
    "follows": "follow",
}
