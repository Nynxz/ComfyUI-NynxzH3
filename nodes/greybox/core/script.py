"""Grey Box scripts: sets, props, cast and scenes as readable text, read into the same JSON the
files hold, and written back out. People and agents write these instead of JSON; the editor shows
them in its Script panel. See docs/GREYBOX-SCRIPT.md for the format.

    text = export_scene(scene_json)                 # JSON -> script
    scene_json, errors = import_scene(text, set_json, props)

Errors are lines like "line 12: no mark ledge-21 (marks: ledge-20, ...)": nothing is half-applied.
"""

from __future__ import annotations

import difflib
import math
import re
from typing import Any

import torch

from . import moves as mv
from .render import trace
from .scene import SceneError, build, set_from

KINDS = ("box", "cylinder", "sphere", "capsule", "prop")
POSES = {
    "stand": "stand",
    "standing": "stand",
    "sit": "sit",
    "sitting": "sit",
    "seated": "sit",
    "crouch": "crouch",
    "crouching": "crouch",
    "crouched": "crouch",
}
EASES = ("linear", "smooth", "in", "out")
DRAWN = {"ones": 1, "twos": 2, "threes": 3, "fours": 4}

_TIME = r"(?:\d+:\d+(?:\.\d+)?|\d+(?:\.\d+)?)"
_TOKEN = re.compile(r"\[[^\]]*\]|[^\s,]+")


class ScriptErrors(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("\n".join(errors))
        self.errors = errors


# --- small pieces ---------------------------------------------------------------------------


def num(x: float) -> str:
    """A number as short as it reads: 2, 0.5, 12.25, -1.333."""
    s = f"{round(float(x), 3):.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def vec(v) -> str:
    return "[" + ", ".join(num(x) for x in v) + "]"


def time(t: float) -> str:
    """A time as m:ss with what decimals it needs, to the millisecond: 0:00, 0:02.5, 1:04.125."""
    t = round(max(0.0, float(t)), 3)
    m, s = divmod(t, 60)
    whole, _, frac = f"{s:06.3f}".partition(".")
    frac = frac.rstrip("0")
    return f"{int(m)}:{whole}{'.' + frac if frac else ''}"


def parse_time(text: str) -> float:
    if ":" in text:
        m, s = text.split(":", 1)
        return int(m) * 60 + float(s)
    return float(text)


def parse_vec(text: str, size: int = 3) -> list[float]:
    m = re.fullmatch(r"\[\s*([^\]]*)\]", text.strip())
    if not m:
        raise ValueError(
            f"expected [{', '.join('xyz'[:size]) if size <= 3 else '...'}], not {text!r}"
        )
    parts = [p for p in re.split(r"[\s,]+", m.group(1).strip()) if p]
    if len(parts) != size:
        raise ValueError(f"expected {size} numbers in {text}")
    return [float(p) for p in parts]


def clauses(text: str) -> list[str]:
    """Comma-separated clauses, keeping commas inside [ ] together."""
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def strip_comment(line: str) -> str:
    i = line.find("//")
    return (line[:i] if i >= 0 else line).rstrip()


def suggest(name: str, known) -> str:
    known = list(known)
    close = difflib.get_close_matches(name, known, n=3)
    if close:
        return f" \u2014 did you mean {' or '.join(close)}?"
    return (
        f" ({', '.join(known[:12])}{', …' if len(known) > 12 else ''})" if known else " (none yet)"
    )


# --- shapes (sets, props, a scene's own) -----------------------------------------------------


def export_shape(s: dict) -> str:
    kind = s.get("type", "box")
    sid = f" {s['id']}" if s.get("id") else ""
    parts: list[str] = []
    if kind == "prop":
        parts.append(f"prop{sid} of {s.get('prop', '')}")
        parts.append(f"at {vec(s.get('at', [0, 0, 0]))}")
        if s.get("yaw"):
            parts.append(f"yaw {num(s['yaw'])}")
        if s.get("scale", 1) != 1:
            parts.append(f"scale {num(s['scale'])}")
        return " ".join(parts)
    parts.append(f"{kind}{sid}")
    lying = kind == "capsule" or (kind == "cylinder" and "a" in s and "b" in s)
    if lying:
        parts.append(f"from {vec(s.get('a', [0, 0, 0]))} to {vec(s.get('b', [0, 1, 0]))}")
    else:
        parts.append(f"at {vec(s.get('at', [0, 0, 0]))}")
    if kind == "box":
        parts.append(f"size {vec(s.get('size', [1, 1, 1]))}")
        if s.get("yaw"):
            parts.append(f"yaw {num(s['yaw'])}")
        if s.get("tilt"):
            parts.append(f"tilt {num(s['tilt'])}")
    if kind in ("cylinder", "sphere", "capsule") and "radius" in s:
        parts.append(f"radius {num(s['radius'])}")
    if kind == "cylinder" and not lying and "height" in s:
        parts.append(f"height {num(s['height'])}")
    if "tone" in s:
        parts.append(f"tone {num(s['tone'])}")
    return " ".join(parts)


_SHAPE_NUMBERS = ("yaw", "tilt", "tone", "radius", "height", "scale")


def parse_shape(line: str) -> dict:
    tokens = _TOKEN.findall(line)
    if not tokens or tokens[0] not in KINDS:
        raise ValueError(f"a shape starts with its kind ({', '.join(KINDS)})")
    kind = tokens[0]
    s: dict[str, Any] = {"type": kind}
    i = 1
    keywords = {"at", "size", "from", "to", "of", *_SHAPE_NUMBERS}
    if i < len(tokens) and tokens[i] not in keywords and not tokens[i].startswith("["):
        s["id"] = tokens[i]
        i += 1
    corners: dict[str, list[float]] = {}
    while i < len(tokens):
        word = tokens[i]
        if word not in keywords:
            raise ValueError(f"unexpected {word!r} (a shape takes {', '.join(sorted(keywords))})")
        if i + 1 >= len(tokens):
            raise ValueError(f"{word} needs a value")
        value = tokens[i + 1]
        i += 2
        if word == "of":
            s["prop"] = value
        elif word in ("at", "size"):
            s[word] = parse_vec(value)
        elif word in ("from", "to"):
            corners[word] = parse_vec(value)
        else:
            s[word] = float(value)
    if corners:
        if set(corners) != {"from", "to"}:
            raise ValueError("from needs a to")
        a, b = corners["from"], corners["to"]
        if kind == "box":
            s["at"] = [(a[k] + b[k]) / 2 for k in range(3)]
            s["size"] = [abs(b[k] - a[k]) for k in range(3)]
        elif kind in ("capsule", "cylinder"):
            s["a"], s["b"] = a, b
        else:
            raise ValueError(f"a {kind} has no from/to")
    if kind == "prop" and not s.get("prop"):
        raise ValueError("a placed prop names which one: prop truck-1 of truck at [x, y, z]")
    if kind == "capsule" and not ("a" in s and "b" in s):
        raise ValueError("a capsule runs from [x, y, z] to [x, y, z]")
    if kind != "capsule" and "at" not in s and "a" not in s:
        raise ValueError(f"where is the {kind}? give it at [x, y, z]")
    return {
        k: (
            round(v, 4)
            if isinstance(v, float)
            else [round(x, 4) for x in v]
            if isinstance(v, list)
            else v
        )
        for k, v in s.items()
    }


# --- sections ---------------------------------------------------------------------------------


def _sections(text: str) -> tuple[dict[str, str], list[tuple[str, int, list[tuple[int, str]]]]]:
    """The header (`key: value` lines before any ##, plus the # title) and each ## section with
    its numbered lines."""
    head: dict[str, str] = {}
    sections: list[tuple[str, int, list[tuple[int, str]]]] = []
    for n, raw in enumerate(text.splitlines(), start=1):
        line = strip_comment(raw)
        if not line.strip():
            continue
        if line.startswith("## "):
            sections.append((line[3:].strip(), n, []))
            continue
        if line.startswith("# ") and not sections:
            head["title"] = line[2:].strip()
            continue
        if sections:
            body = line.strip()
            sections[-1][2].append((n, body[2:] if body.startswith("- ") else body))
        else:
            m = re.match(r"\s*([A-Za-z][\w ]*?)\s*:\s*(.*)$", line)
            if m:
                key = m.group(1).lower()
                head[key] = (head[key] + " " + m.group(2)).strip() if key in head else m.group(2)
    return head, sections


def _section(sections, *names):
    names = {n.lower() for n in names}
    return [s for s in sections if s[0].split(" ")[0].lower() in names]


# --- sets and props ---------------------------------------------------------------------------


def export_set(raw: dict, *, prop: bool = False) -> str:
    lines = [f"# {'Prop: ' if prop else ''}{raw.get('name', '')}".rstrip()]
    if raw.get("notes"):
        lines.append(f"notes: {raw['notes']}")
    lines += ["", "## Shapes", *(export_shape(s) for s in raw.get("shapes", []))]
    if not prop:
        if raw.get("marks"):
            lines += ["", "## Marks", *(f"{k}: {vec(v)}" for k, v in raw["marks"].items())]
        if raw.get("cameras"):
            lines += ["", "## Cameras"]
            for k, c in raw["cameras"].items():
                lines.append(f"{k}: " + _camera_text(c, None))
    return "\n".join(lines) + "\n"


def import_set(text: str, *, prop: bool = False) -> tuple[dict, list[str]]:
    head, sections = _sections(text)
    errors: list[str] = []
    title = head.get("title", "")
    if prop and title.lower().startswith("prop:"):
        title = title[5:].strip()
    out: dict[str, Any] = {"name": title}
    if head.get("notes"):
        out["notes"] = head["notes"]
    shapes = []
    for _, _, lines in _section(sections, "shapes"):
        for n, line in lines:
            try:
                shapes.append(parse_shape(line))
            except ValueError as e:
                errors.append(f"line {n}: {e}")
    out["shapes"] = shapes
    if not prop:
        marks = {}
        for _, _, lines in _section(sections, "marks"):
            for n, line in lines:
                m = re.fullmatch(r"([\w.-]+)\s*:\s*(\[.*\])", line)
                if not m:
                    errors.append(f"line {n}: a mark is name: [x, y, z]")
                    continue
                try:
                    marks[m.group(1)] = parse_vec(m.group(2))
                except ValueError as e:
                    errors.append(f"line {n}: {e}")
        out["marks"] = marks
        cameras = {}
        for _, _, lines in _section(sections, "cameras"):
            for n, line in lines:
                m = re.fullmatch(r"([\w.-]+)\s*:\s*(.*)", line)
                if not m:
                    errors.append(
                        f"line {n}: a set camera is name: from [x, y, z], looking at …, 35mm"
                    )
                    continue
                try:
                    cameras[m.group(1)] = _parse_camera(m.group(2), None)
                except ValueError as e:
                    errors.append(f"line {n}: {e}")
        out["cameras"] = cameras
    seen: set[str] = set()
    for s in shapes:
        if s.get("id") in seen:
            errors.append(f"two shapes are called {s['id']}: names must be unique")
        if s.get("id"):
            seen.add(s["id"])
    return out, errors


# --- cast ---------------------------------------------------------------------------------------


def export_member(mention: str, m: dict) -> str:
    parts = []
    if m.get("prop"):
        parts.append(f"prop {m['prop']}")
    for k in ("height", "build", "tone"):
        if k in m:
            parts.append(f"{k} {num(m[k])}")
    return f"{mention}: {', '.join(parts)}".rstrip(": ")


def parse_member(line: str) -> tuple[str, dict]:
    m = re.fullmatch(r"(@[\w-]+)\s*(?::\s*(.*))?", line)
    if not m:
        raise ValueError("a cast member is @name: height 1.74, build 1, tone 0.9 (or prop van)")
    out: dict[str, Any] = {}
    for clause in clauses(m.group(2) or ""):
        words = clause.split()
        if len(words) != 2 or words[0] not in ("prop", "height", "build", "tone"):
            raise ValueError(f"unexpected {clause!r} (prop NAME, height N, build N, tone N)")
        out[words[0]] = words[1] if words[0] == "prop" else float(words[1])
    return m.group(1), out


# --- scenes -------------------------------------------------------------------------------------


def _place_text(at) -> str:
    return vec(at) if isinstance(at, (list, tuple)) else str(at)


def _camera_text(c: dict, t: float | None) -> str:
    parts = [f"from {_place_text(c.get('at', [0, 1.6, 0]))}"]
    if "look" in c:
        parts.append(f"looking at {_place_text(c['look'])}")
    if "lens" in c:
        parts.append(f"{num(c['lens'])}mm")
    # Cameras ease smooth unless told otherwise, so only a different ease is worth writing.
    if c.get("ease") and c["ease"] != "smooth":
        parts.append(f"ease {c['ease']}")
    return (f"{time(t)} " if t is not None else "") + ", ".join(parts)


def _parse_place(text: str):
    text = text.strip()
    if text.startswith("["):
        return parse_vec(text)
    if not re.fullmatch(r"@?[\w.-]+", text):
        raise ValueError(f"{text!r} isn't a place: a mark, [x, y, z] or @someone")
    return text


def _parse_camera(text: str, t: float | None) -> dict:
    key: dict[str, Any] = {} if t is None else {"t": round(t, 4)}
    for clause in clauses(text):
        low = clause.lower()
        if low.startswith("from "):
            key["at"] = _parse_place(clause[5:])
        elif low.startswith("looking at "):
            key["look"] = _parse_place(clause[11:])
        elif re.fullmatch(r"\d+(?:\.\d+)?\s*mm", low):
            key["lens"] = float(low[:-2])
        elif low.startswith("ease "):
            if low[5:] not in EASES:
                raise ValueError(f"ease is one of {', '.join(EASES)}")
            key["ease"] = low[5:]
        else:
            raise ValueError(f"unexpected {clause!r} (from …, looking at …, 35mm, ease …)")
    if "at" not in key:
        raise ValueError("a camera needs from [x, y, z] (or a mark or a set camera)")
    return key


def export_scene(raw: dict) -> str:
    lines = [f"# {raw.get('name', '')}".rstrip()]
    if isinstance(raw.get("set"), str):
        lines.append(f"set: {raw['set']}")
    lines.append(f"fps: {num(raw.get('fps', 24))}")
    if raw.get("on", 1) != 1:
        lines.append(f"drawn on: {next(k for k, v in DRAWN.items() if v == raw['on'])}")
    if raw.get("notes"):
        lines.append(f"notes: {raw['notes']}")
    if raw.get("cast"):
        lines += ["", "## Cast", *(export_member(k, v) for k, v in raw["cast"].items())]
    if raw.get("shapes"):
        lines += ["", "## Shapes", *(export_shape(s) for s in raw["shapes"])]
    lines += ["", "## Action"]
    keyed = []
    for a in raw.get("actors", []):
        for k in a.get("keys", []):
            if k.get("run") and not k.get("move"):
                continue  # part of a move: written once, as its verb
            t0 = float(k["move"]["from"]) if k.get("move") else float(k.get("t", 0))
            keyed.append((t0, a["id"], k))
    for t, aid, k in sorted(keyed, key=lambda x: x[0]):
        if k.get("move"):
            mvd = k["move"]
            lines.append(f"{time(mvd['from'])}\u2013{time(mvd['to'])} {aid} {mvd['text']}")
            continue
        parts = []
        if k.get("on"):
            at = k.get("at", [0, 0, 0])
            parts.append(f"on {k['on']} at [{num(at[0])}, {num(at[2])}]")
        elif "at" in k:
            parts.append(f"at {_place_text(k['at'])}")
        if "face" in k:
            f = k["face"]
            parts.append(f"facing {num(f) if isinstance(f, (int, float)) else f}")
        if k.get("pose"):
            parts.append(k["pose"])
        # Actors move linearly between keys unless told otherwise.
        if k.get("ease") and k["ease"] != "linear":
            parts.append(f"ease {k['ease']}")
        lines.append(f"{time(t)} {aid} " + ", ".join(parts))
    for s in raw.get("shots", []):
        lines += [
            "",
            f"## Shot {s.get('name', '')} ({time(s.get('start', 0))}\u2013{time(s.get('end', 0))})",
        ]
        for c in s.get("camera", []):
            if c.get("move"):
                mvd = c["move"]
                lines.append(f"{time(mvd['from'])}\u2013{time(mvd['to'])} {mvd['text']}")
            elif not c.get("run"):
                lines.append(_camera_text(c, float(c.get("t", s.get("start", 0)))))
    return "\n".join(lines) + "\n"


def r4(v) -> list[float]:
    return [round(float(x), 4) for x in v]


def surface_y(the_set, name: str, x: float, z: float, extra: list | None = None) -> float | None:
    """The top of the shape (a set shape, a placed prop, or one of the scene's own) called `name`
    straight above or below (x, z): where feet on it stand. None when it isn't there."""
    shapes = [
        s
        for s in [*the_set.shapes, *(extra or [])]
        if s.id == name or s.owner == name or s.id.startswith(name + "/")
    ]
    if not shapes:
        return None
    t, _, _ = trace(torch.tensor([[x, 1000.0, z]]), torch.tensor([[0.0, -1.0, 0.0]]), shapes)
    hit = float(t[0])
    return None if math.isinf(hit) else round(1000.0 - hit, 4)


def import_scene(
    text: str, set_raw: dict | None, props: dict | None = None, cast_raw: dict | None = None
) -> tuple[dict, list[str]]:
    """A scene script read into scene JSON, checked against its set (`set_raw`, the set's JSON):
    marks, shapes and set cameras it names must exist."""
    head, sections = _sections(text)
    errors: list[str] = []
    out: dict[str, Any] = {"name": head.get("title", "")}
    if head.get("set"):
        out["set"] = head["set"]
    try:
        out["fps"] = float(head.get("fps", 24))
    except ValueError:
        errors.append("fps should be a number")
    if head.get("drawn on"):
        if head["drawn on"].lower() not in DRAWN:
            errors.append(f"drawn on is one of {', '.join(DRAWN)}")
        else:
            out["on"] = DRAWN[head["drawn on"].lower()]
    if head.get("notes"):
        out["notes"] = head["notes"]

    the_set = None
    try:
        the_set = set_from(set_raw or {}, out.get("set", "set"), props or {})
    except SceneError as e:
        errors.append(f"the set doesn't load: {e}")
    marks = set(the_set.marks) if the_set else set()
    setcams = set(the_set.cameras) if the_set else set()
    shape_names = (
        {s.owner for s in the_set.shapes} | {s.id.split("/")[0] for s in the_set.shapes}
        if the_set
        else set()
    )

    cast: dict[str, dict] = {}
    for _, _, lines in _section(sections, "cast"):
        for n, line in lines:
            try:
                mention, member = parse_member(line)
                cast[mention] = member
            except ValueError as e:
                errors.append(f"line {n}: {e}")
    if cast:
        out["cast"] = cast

    extra_raw = []
    for _, _, lines in _section(sections, "shapes"):
        for n, line in lines:
            try:
                extra_raw.append(parse_shape(line))
            except ValueError as e:
                errors.append(f"line {n}: {e}")
    if extra_raw:
        out["shapes"] = extra_raw
    extra = []
    if extra_raw:
        try:
            extra = set_from({"shapes": extra_raw}, "scene", props or {}).shapes
            shape_names |= {s.owner for s in extra}
        except SceneError as e:
            errors.append(f"the scene's own shapes: {e}")

    def check_place(n: int, place, what: str, allow_setcam: bool = False):
        if isinstance(place, str) and not place.startswith("@"):
            known = marks | (setcams if allow_setcam else set())
            if place not in known:
                errors.append(f"line {n}: {what}: no mark {place}" + suggest(place, sorted(known)))

    # Moves (runs, jumps, swings, follows…) need places, surfaces, bars and heights.
    member_height = {k: float(v.get("height", 1.74)) for k, v in (cast_raw or {}).items()}
    member_height.update({k: float(v.get("height", 1.74)) for k, v in cast.items()})

    def place(text: str):
        text = text.strip()
        on = re.fullmatch(r"on\s+([\w./-]+)\s+at\s+(.+)", text, re.I)
        if on:
            name, where = on.group(1), on.group(2).strip()
            if name not in shape_names:
                raise ValueError(f"no shape {name}" + suggest(name, sorted(shape_names)))
            if where.startswith("["):
                xz = parse_vec(where, 2)
            elif the_set and where in the_set.marks:
                mk = the_set.marks[where]
                xz = [mk[0], mk[2]]
            else:
                raise ValueError(f"on {name} at …: give [x, z] or a mark")
            y = surface_y(the_set, name, xz[0], xz[1], extra) if the_set else None
            if y is None:
                raise ValueError(f"[{num(xz[0])}, {num(xz[1])}] isn't over {name}")
            return (xz[0], y, xz[1])
        if text.startswith("["):
            return tuple(parse_vec(text))
        if the_set and text in the_set.marks:
            return tuple(the_set.marks[text])
        raise ValueError(f"no mark {text}" + suggest(text, sorted(marks)))

    def surface(name, x, z):
        if name not in shape_names:
            raise ValueError(f"no shape {name}" + suggest(name, sorted(shape_names)))
        return surface_y(the_set, name, x, z, extra) if the_set else None

    def bar(name):
        if not the_set:
            return None
        for s in [*the_set.shapes, *extra]:
            if (s.id == name or s.owner == name) and s.kind == "capsule":
                return tuple(s.a), tuple(s.b)
        return None

    world = mv.World(place, surface, bar, lambda aid: member_height.get(aid, 1.74))

    def plain_key(t: float, text: str, prev: list[dict]) -> dict:
        key: dict[str, Any] = {"t": round(t, 4)}
        for clause in clauses(text):
            low = clause.lower()
            if re.fullmatch(r"on\s+([\w./-]+)\s+at\s+(.+)", clause, re.I):
                p = place(clause)
                key["at"] = r4(p)
                key["on"] = re.match(r"on\s+([\w./-]+)", clause, re.I).group(1)
            elif low.startswith("at "):
                key["at"] = _parse_place(clause[3:])
                if (
                    isinstance(key["at"], str)
                    and not key["at"].startswith("@")
                    and key["at"] not in marks
                ):
                    raise ValueError(f"at: no mark {key['at']}" + suggest(key["at"], sorted(marks)))
            elif low.startswith("facing "):
                f = clause[7:].strip()
                try:
                    key["face"] = float(f)
                except ValueError:
                    if f != "path" and not f.startswith("@") and f not in marks:
                        raise ValueError(
                            f"facing: no mark {f}" + suggest(f, sorted(marks))
                        ) from None
                    key["face"] = f
            elif low in POSES:
                key["pose"] = POSES[low]
            elif low.startswith("ease "):
                if low[5:] not in EASES:
                    raise ValueError(f"ease is one of {', '.join(EASES)}")
                key["ease"] = low[5:]
            else:
                verb = low.split()[0] if low.split() else ""
                hint = (
                    f" — {verb} is a move: give it a span, like 1.0\u20132.0 @someone {clause}"
                    if verb in mv.VERBS
                    else ""
                )
                raise ValueError(
                    f"unexpected {clause!r} (at …, on SHAPE at [x, z], facing …, "
                    f"stand/sit/crouch, ease …){hint}"
                )
        if "at" not in key:
            if not prev:
                raise ValueError("the first key needs a place (at … or on … at …)")
            # Where it was: a key that only turns or changes pose stays put.
            key["at"] = prev[-1]["at"]
            if prev[-1].get("on"):
                key["on"] = prev[-1]["on"]
        return key

    def start_of(aid: str, prev: list[dict], t0: float) -> mv.Start:
        if not prev:
            raise ValueError(f"{aid} needs a key before its first move: where it starts")
        last = prev[-1]
        if last["t"] > t0 + 1e-6:
            raise ValueError(f"this starts at {num(t0)}s, before {aid}'s key at {num(last['t'])}s")
        at = last["at"]
        if isinstance(at, str):
            if at.startswith("@"):
                raise ValueError(f"a move can't start from {at} (where someone else is)")
            at = place(at)
        face = last.get("face")
        if isinstance(face, (int, float)):
            yaw = float(face)
        else:
            moving = [k for k in prev if not isinstance(k["at"], str)][-2:]
            if len(moving) == 2:
                yaw = mv.yaw_of(
                    moving[1]["at"][0] - moving[0]["at"][0],
                    moving[1]["at"][2] - moving[0]["at"][2],
                    0.0,
                )
            else:
                yaw = 0.0
        return mv.Start(tuple(at), yaw, face)

    events: dict[str, list] = {}
    for _, _, lines in _section(sections, "action"):
        for n, line in lines:
            span = re.fullmatch(
                rf"({_TIME})\s*[\u2013\u2014-]\s*({_TIME})\s+(@[\w-]+)\s+(.*)", line
            )
            plain = re.fullmatch(rf"({_TIME})\s+(@[\w-]+)\s+(.*)", line)
            if span:
                t0, t1 = parse_time(span.group(1)), parse_time(span.group(2))
                if t1 <= t0:
                    errors.append(f"line {n}: the move ends before it starts")
                    continue
                events.setdefault(span.group(3), []).append((t0, t1, n, span.group(4).strip()))
            elif plain:
                events.setdefault(plain.group(2), []).append(
                    (parse_time(plain.group(1)), None, n, plain.group(3).strip())
                )
            else:
                errors.append(
                    f"line {n}: an action line is TIME @someone at …, or START\u2013END @someone MOVE"
                )

    actors: dict[str, list[dict]] = {}
    follows: list[tuple[str, float, float, int, str]] = []
    runs = 0
    for aid, evs in events.items():
        keys = actors.setdefault(aid, [])
        for t0, t1, n, text in sorted(evs, key=lambda e: (e[0], e[2])):
            try:
                if t1 is None:
                    keys.append(plain_key(t0, text, keys))
                    continue
                verb, _, rest = text.partition(" ")
                kind = mv.VERBS.get(verb.lower())
                if kind is None:
                    raise ValueError(
                        f"unknown move {verb!r} (runs, walks, moves, slides, jumps, leaps, hops, "
                        "drops, falls, climbs, swings, follows)"
                    )
                if kind == "follow":
                    follows.append((aid, t0, t1, n, rest))
                    continue
                start = start_of(aid, keys, t0)
                if kind == "travel":
                    made = mv.travel(verb.lower(), t0, t1, start, rest.strip(), world)
                elif kind == "jump":
                    made = mv.jump(verb.lower(), t0, t1, start, rest.strip(), world, aid)
                elif kind == "climb":
                    made = mv.climb(verb.lower(), t0, t1, start, rest.strip(), world)
                else:
                    made = mv.swing(verb.lower(), t0, t1, start, rest.strip(), world, aid)
                if keys and abs(keys[-1]["t"] - t0) < 1e-6:
                    # A key already marks where the move starts (and may turn or pose it there).
                    made = made[1:]
                runs += 1
                for k in made:
                    k["run"] = runs
                made[0]["move"] = {"from": round(t0, 4), "to": round(t1, 4), "text": text}
                keys.extend(made)
            except ValueError as e:
                errors.append(f"line {n}: {e}")

    def evaluate():
        """The scene as built so far, to ask where someone is (for follows and tracking shots)."""
        try:
            return build(
                {
                    "actors": [{"id": a, "keys": k} for a, k in actors.items() if k],
                    "cast": {**(cast_raw or {}), **cast},
                    "shots": [
                        {"name": "_", "camera": [{"t": 0, "at": [0, 1, 0], "look": [0, 1, 1]}]}
                    ],
                },
                the_set,
            )
        except SceneError as e:
            errors.append(f"the scene doesn't hold together: {e}")
            return None

    if follows:
        built = evaluate()
        for aid, t0, t1, n, rest in follows:
            m = re.fullmatch(r"(@[\w-]+)\s*,?\s*(.*)", rest.strip())
            if not m:
                errors.append(f"line {n}: follows @someone[, 6 behind, 4 up, 1 left]")
                continue
            target = m.group(1)
            if built is None or not actors.get(target):
                errors.append(f"line {n}: {target} has no keys to follow")
                continue
            try:
                off = mv.offset(m.group(2))
            except ValueError as e:
                errors.append(f"line {n}: {e}")
                continue
            made = []
            for t in mv.times(t0, t1, mv.FOLLOW_STEP):
                st = built.actor_at(target, t)
                made.append(
                    {"t": round(t, 4), "at": r4(mv.in_frame(st.at, st.yaw, off)), "face": target}
                )
            runs += 1
            for k in made:
                k["run"] = runs
            made[0]["move"] = {
                "from": round(t0, 4),
                "to": round(t1, 4),
                "text": f"follows {rest.strip()}",
            }
            prev = actors.setdefault(aid, [])
            prev[:] = [k for k in prev if not (t0 - 1e-6 <= k["t"] <= t1 + 1e-6)] + made

    out["actors"] = [
        {"id": aid, "keys": sorted(keys, key=lambda k: k["t"])}
        for aid, keys in actors.items()
        if keys
    ]
    for aid, keys in actors.items():
        for k in keys:
            for field in ("at", "face"):
                v = k.get(field)
                if isinstance(v, str) and v.startswith("@") and v not in actors:
                    errors.append(f"{aid} at {num(k['t'])}s: {field} {v}, who isn't in the scene")

    built = (
        evaluate()
        if any("tracks" in ln for _, _, ls in _section(sections, "shot") for _, ln in ls)
        else None
    )
    shots = []
    for title, n0, lines in _section(sections, "shot"):
        m = re.fullmatch(
            rf"[Ss]hot\s+(\S+)\s*\(\s*({_TIME})\s*[\u2013\u2014-]\s*({_TIME})\s*\)", title
        )
        if not m:
            errors.append(f"line {n0}: a shot heading is ## Shot 1A (0:00\u20132.50)")
            continue
        start, end = parse_time(m.group(2)), parse_time(m.group(3))
        if end <= start:
            errors.append(f"line {n0}: shot {m.group(1)} ends before it starts")
        keys = []
        for n, line in lines:
            track = re.fullmatch(
                rf"({_TIME})\s*[\u2013\u2014-]\s*({_TIME})\s+tracks\s+(@[\w-]+)\s*,?\s*(.*)", line
            )
            if track:
                t0, t1, target = (
                    parse_time(track.group(1)),
                    parse_time(track.group(2)),
                    track.group(3),
                )
                if built is None or not actors.get(target):
                    errors.append(f"line {n}: {target} has no keys to track")
                    continue
                offs, lens, look, ease = [], None, target, None
                try:
                    for clause in clauses(track.group(4)):
                        low = clause.lower()
                        if re.fullmatch(r"\d+(?:\.\d+)?\s*mm", low):
                            lens = float(low[:-2])
                        elif low.startswith("looking at "):
                            look = _parse_place(clause[11:])
                        elif low.startswith("ease "):
                            ease = low[5:]
                        else:
                            offs.append(clause)
                    off = mv.offset(", ".join(offs))
                except ValueError as e:
                    errors.append(f"line {n}: {e}")
                    continue
                runs += 1
                made = []
                for t in mv.times(t0, t1, mv.FOLLOW_STEP):
                    st = built.actor_at(target, t)
                    k = {
                        "t": round(t, 4),
                        "at": r4(mv.in_frame(st.at, st.yaw, off)),
                        "look": look,
                        "run": runs,
                    }
                    if lens:
                        k["lens"] = lens
                    if ease:
                        k["ease"] = ease
                    made.append(k)
                made[0]["move"] = {
                    "from": round(t0, 4),
                    "to": round(t1, 4),
                    "text": f"tracks {target}"
                    + (f", {track.group(4).strip()}" if track.group(4).strip() else ""),
                }
                keys.extend(made)
                continue
            mk = re.fullmatch(rf"({_TIME})\s+(.*)", line)
            if not mk:
                errors.append(
                    f"line {n}: a camera line is TIME from …, looking at …, 35mm "
                    "(or START\u2013END tracks @someone, 4 behind, 1.5 up)"
                )
                continue
            try:
                key = _parse_camera(mk.group(2), parse_time(mk.group(1)))
                check_place(n, key["at"], "from", allow_setcam=True)
                if "look" in key:
                    check_place(n, key["look"], "looking at")
                elif not (isinstance(key["at"], str) and key["at"] in setcams):
                    errors.append(f"line {n}: say where it's looking (looking at …)")
                keys.append(key)
            except ValueError as e:
                errors.append(f"line {n}: {e}")
        if not keys:
            errors.append(f"line {n0}: shot {m.group(1)} needs at least one camera line")
        shots.append(
            {
                "name": m.group(1),
                "start": start,
                "end": end,
                "camera": sorted(keys, key=lambda k: k["t"]),
            }
        )
    if not shots:
        errors.append(
            "a scene needs at least one shot: ## Shot 1A (0:00\u20133.00) and a camera line"
        )
    out["shots"] = shots
    return out, errors


# --- cast files -----------------------------------------------------------------------------


def export_cast(raw: dict) -> str:
    return "# Cast\n\n" + "\n".join(export_member(k, v) for k, v in raw.items()) + "\n"


def import_cast(text: str) -> tuple[dict, list[str]]:
    _, sections = _sections(text)
    cast, errors = {}, []
    lines = [ln for _, _, ls in sections for ln in ls] or [
        (n, strip_comment(raw).strip())
        for n, raw in enumerate(text.splitlines(), 1)
        if strip_comment(raw).strip().startswith("@")
    ]
    for n, line in lines:
        try:
            mention, member = parse_member(line)
            cast[mention] = member
        except ValueError as e:
            errors.append(f"line {n}: {e}")
    return cast, errors
