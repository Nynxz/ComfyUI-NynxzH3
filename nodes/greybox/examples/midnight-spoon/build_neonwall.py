"""Down a neon wall: Ren climbs down a building's drainpipe, edges along a ledge, leaps out to a bar
between two blade signs, swings and lets go, lands on a shop marquee and drops to the street, the
drone on his tail. Writes the set and the scene (the drone prop comes from build_rooftops.py).

    python build_neonwall.py .

The wall faces +z, its face at z = 0, 30 m tall, across x = -10..10. Ledges run along it every six
metres; the bar hangs out from the wall at 17.6 m between two blade signs; the marquee juts 4.5 m
over the street at 7 m."""

import json
import math
import sys
from pathlib import Path

BAR_Y, BAR_Z = 17.6, 1.5  # the bar: its height, how far it stands out from the wall
HANG = 2.15  # from the bar down to the feet of someone hanging from it
MARQUEE_Y = 7.2


def r(v):
    return [round(x, 3) for x in v]


# --- the set ----------------------------------------------------------------------------------
S = []


def span(id, x0, x1, y0, y1, z0, z1, tone):
    S.append(
        {
            "id": id,
            "type": "box",
            "at": r(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)),
            "size": r((x1 - x0, y1 - y0, z1 - z0)),
            "tone": tone,
        }
    )


span("street", -40, 40, -0.12, 0, -20, 60, 0.2)
span("sidewalk", -24, 24, 0, 0.15, 0, 4.8, 0.32)
span("wall", -10, 10, 0, 30, -8, 0, 0.5)
span("roof", -10, 10, 30, 30.2, -8, 0, 0.4)
span("parapet", -10, 10, 30.2, 30.8, -0.3, 0, 0.55)
# Windows, a little proud of the wall and dark; the shop front at the bottom.
for floor, y in enumerate(range(9, 29, 3)):
    for i, x in enumerate((-8.4, -5.6, -0.9, 1.9, 5.4, 8.2)):
        span(f"window-{floor}-{i}", x - 0.65, x + 0.65, y, y + 1.6, 0, 0.06, 0.2)
span("shop-front", -3.0, 3.0, 0.15, 6.6, 0, 0.08, 0.18)
# Ledges every six metres, the drainpipe Ren climbs down.
for y in (8, 14, 20, 26):
    span(f"ledge-{y}", -10, 10, y - 0.25, y, 0, 0.45, 0.62)
S.append({"id": "drainpipe", "type": "cylinder", "a": [4.7, 0.15, 0.16], "b": [4.7, 30.4, 0.16], "radius": 0.08, "tone": 0.66})

# Blade signs standing out from the wall; the two either side of the bar hold it up.
for id, x, y0, y1, depth in (
    ("sign-bar-l", -2.7, 14.6, 20.0, 2.0),
    ("sign-bar-r", 2.7, 14.6, 20.0, 2.0),
    ("sign-tall-l", -7.0, 8.6, 24.0, 1.6),
    ("sign-tall-r", 7.6, 15.0, 27.5, 1.8),
):
    span(id, x - 0.14, x + 0.14, y0, y1, 0, depth, 0.86)
S.append({"id": "bar", "type": "capsule", "a": [-2.55, BAR_Y, BAR_Z], "b": [2.55, BAR_Y, BAR_Z], "radius": 0.045, "tone": 0.8})
# Billboards flat on the wall, and the marquee over the shop.
span("billboard-high", -6.0, -1.2, 21.0, 25.0, 0, 0.2, 0.9)
span("billboard-low", 4.0, 9.2, 9.4, 12.6, 0, 0.2, 0.88)
span("marquee", -3.4, 3.4, MARQUEE_Y - 0.3, MARQUEE_Y, 0, 4.5, 0.74)
for side, x in (("l", -3.25), ("r", 3.25)):
    span(f"marquee-strut-{side}", x - 0.05, x + 0.05, MARQUEE_Y - 2.4, MARQUEE_Y - 0.3, 0, 0.1, 0.6)

# Neighbours: buildings either side of the wall, and across the street for depth.
for i, (x0, x1, h) in enumerate(((-24, -10.2, 22), (10.2, 23, 34))):
    span(f"neighbour-{i}", x0, x1, 0, h, -10, -0.6, 0.46)
for i, (x0, x1, h) in enumerate(((-26, -9, 26), (-8, 6, 18), (7, 26, 30))):
    span(f"across-{i}", x0, x1, 0, h, 18, 30, 0.44)
span("across-sign", -1.5, 0.5, 9.0, 15.0, 17.6, 18.0, 0.88)

SET = {
    "name": "Neon wall",
    "notes": "A building's front faces +z, its face at z = 0, 30 m tall across x = -10..10. Ledges "
    "at 8, 14, 20 and 26 m; a drainpipe at x = 4.7; a bar at 17.6 m standing 1.5 m out from the "
    "wall between two blade signs (x = -2.7 and 2.7); a marquee 7.2 m up over the shop, 4.5 m deep. "
    "The street runs along x in front; +x is on the left looking at the wall from the street.",
    "shapes": S,
    "marks": {
        "pipe-top": [4.25, 28.0, 0.38],
        "ledge-20": [4.25, 20.0, 0.3],
        "under-bar": [0.0, BAR_Y - HANG, BAR_Z],
        "marquee": [0.0, MARQUEE_Y, 3.8],
        "street": [0.0, 0.0, 7.0],
    },
    "cameras": {
        "up-the-wall": {"at": [-1.0, 1.4, 15.0], "look": [0.5, 19.0, 0.0], "lens": 22},
        "along-the-wall": {"at": [-9.0, 16.5, 4.5], "look": [0.0, 16.5, 1.8], "lens": 30},
    },
}


# --- the scene --------------------------------------------------------------------------------


def key(t, at, face="path", **more):
    return {"t": t, "at": r(at), "face": face, **more}


def cam(t, at, look, lens, ease="smooth"):
    return {"t": t, "at": r(at), "look": look if isinstance(look, str) else r(look), "lens": lens, "ease": ease}


def hanging(angle):
    """Ren's feet hanging from the bar, swung `angle` degrees out from the wall (negative: in)."""
    a = math.radians(angle)
    return (0.0, BAR_Y - HANG * math.cos(a), BAR_Z + HANG * math.sin(a))


def swing(t0, peaks, step=0.07):
    """Keys through a swing: `peaks` is [(time, angle)] — catch, then the peaks either way. Between
    peaks the angle eases like a pendulum (slow at the ends, fast through the bottom)."""
    out = []
    t_prev, a_prev = t0, peaks[0][1]
    for t1, a1 in peaks[1:]:
        n = max(1, round((t1 - t_prev) / step))
        for i in range(n):
            u = i / n
            eased = (1 - math.cos(math.pi * u)) / 2
            out.append(key(t_prev + (t1 - t_prev) * u, hanging(a_prev + (a1 - a_prev) * eased), 0))
        t_prev, a_prev = t1, a1
    out.append(key(t_prev, hanging(a_prev), 0))
    return out


ren = [
    # Down the drainpipe in reaches, facing the wall, then drops onto the ledge.
    key(0.0, (4.25, 28.0, 0.38), 180),
    key(0.45, (4.25, 26.6, 0.38), 180),
    key(0.6, (4.25, 26.4, 0.38), 180),
    key(1.0, (4.25, 24.6, 0.38), 180),
    key(1.15, (4.25, 24.4, 0.38), 180),
    key(1.5, (4.25, 22.4, 0.38), 180),
    key(1.75, (4.25, 20.0, 0.3), 180, pose="crouch"),
    key(1.9, (4.25, 20.0, 0.3), 90, pose="stand"),
    # Along the ledge toward the bar, then out over the drop to catch it.
    key(2.2, (3.0, 20.0, 0.3), 90),
    key(2.45, (1.6, 20.0, 0.3), 90),
    key(2.62, (0.7, 20.2, 0.75), 0),
    *swing(
        2.85,
        [(2.85, -15.0), (3.3, 50.0), (3.8, -40.0), (4.35, 72.0)],
    ),
    # Let go at the top of the swing, out over the street and down onto the marquee.
    key(4.55, (0.0, BAR_Y - 0.4, 3.95), 0),
    key(4.85, (0.0, 13.2, 4.05), 0),
    key(5.2, (0.0, MARQUEE_Y, 3.9), 0, pose="crouch"),
    key(5.3, (0.0, MARQUEE_Y, 3.95), 0, pose="crouch"),
    key(5.45, (0.0, MARQUEE_Y, 4.15), 0, pose="stand"),
    # Off the front of the marquee to the street, and away toward the camera.
    key(5.65, (0.1, MARQUEE_Y + 0.35, 5.1), 0),
    key(6.0, (0.3, 0.0, 6.7), 0, pose="crouch"),
    key(6.1, (0.35, 0.0, 6.95), 0, pose="crouch"),
    key(6.25, (0.45, 0.0, 7.4), 0, pose="stand"),
    key(7.0, (1.2, 0.0, 11.2), 0),
]
drone = [
    key(0.0, (8.5, 26.5, 9.0), "@ren"),
    key(2.5, (5.5, 21.0, 8.0), "@ren"),
    key(4.5, (2.0, 16.0, 9.0), "@ren"),
    key(7.0, (1.0, 6.0, 13.0), "@ren"),
]
SCENE = {
    "name": "Down the neon wall",
    "set": "neon-wall",
    "fps": 24,
    "cast": {"@drone": {"prop": "drone", "height": 0.15}},
    "actors": [{"id": "@ren", "keys": ren}, {"id": "@drone", "keys": drone}],
    "shots": [
        {
            # From a window across the street: the climb down the pipe and the ledge.
            "name": "4A",
            "start": 0,
            "end": 2.5,
            "camera": [cam(0, (3.5, 24.0, 12.0), "@ren", 32), cam(2.5, (2.6, 20.5, 11.5), "@ren", 32)],
        },
        {
            # Three-quarters from the street side, up at the bar between the signs: the leap and the swing.
            "name": "4B",
            "start": 2.5,
            "end": 4.9,
            "camera": [cam(2.5, (-4.5, 16.2, 9.5), "@ren", 30), cam(4.9, (-4.0, 14.0, 10.5), "@ren", 30)],
        },
        {
            # Street level: the drop onto the marquee, off it, and the run toward the camera.
            "name": "4C",
            "start": 4.9,
            "end": 7.0,
            "camera": [cam(4.9, (3.4, 1.5, 15.0), "@ren", 30), cam(7.0, (3.0, 1.4, 15.5), "@ren", 30)],
        },
    ],
}

if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    for path, data in ((out / "sets" / "neon-wall.json", SET), (out / "scenes" / "neon-wall.json", SCENE)):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.new")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        print("wrote", path)
