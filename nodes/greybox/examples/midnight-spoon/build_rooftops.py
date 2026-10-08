"""A rooftop run for testing height, slopes and air: Ren runs across a roof, jumps the gap to the
next, slides down a pitched roof, drops off its eave to a lower roof and runs on, with a drone on
his tail. Writes the set, the drone prop and the scene.

    python build_rooftops.py .

The run goes along +z, the roofs side by side down it: A (flat, 12 m up), a 3.5 m gap, B (flat,
11 m), C (pitched 20° down toward +z, from 11 m to about 7.4 m at its eave), a 1.5 m gap, D (flat,
6 m). The street is far below; taller towers stand around for depth and edges."""

import json
import math
import sys
from pathlib import Path

PITCH = 20.0  # roof C's slope, degrees
SLOPE = math.tan(math.radians(PITCH))
C_TOP, C_Z0, C_Z1 = 11.0, 38.0, 48.0  # roof C: its ridge height and where it starts and ends


def r(v):
    return [round(x, 3) for x in v]


def slope_y(z):
    """Roof C's surface height at `z`."""
    return C_TOP - SLOPE * (z - C_Z0)


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


def roof(name, top, z0, z1, x0=-5.0, x1=5.0):
    """A building of height `top` from z0 to z1, its roof a little darker, a parapet down each
    side (the run goes along the middle)."""
    span(f"{name}-building", x0, x1, 0, top - 0.15, z0, z1, 0.5)
    span(f"{name}-roof", x0, x1, top - 0.15, top, z0, z1, 0.4)
    span(f"{name}-parapet-l", x1 - 0.25, x1, top, top + 0.45, z0, z1, 0.55)
    span(f"{name}-parapet-r", x0, x0 + 0.25, top, top + 0.45, z0, z1, 0.55)


span("street", -40, 40, -0.12, 0, -40, 120, 0.2)
roof("a", 12.0, -6.0, 20.0)
roof("b", 11.0, 23.5, C_Z0)
roof("d", 6.0, 49.5, 75.0)

# Roof C: a building to the eave, and the pitched roof on it as one tilted slab.
span("c-building", -5, 5, 0, slope_y(C_Z1) - 0.2, C_Z0, C_Z1, 0.5)
run = (C_Z1 - C_Z0) / math.cos(math.radians(PITCH))  # the slab's length along the slope
mid_z = (C_Z0 + C_Z1) / 2
S.append(
    {
        "id": "c-roof",
        "type": "box",
        # Its top surface runs along the slope; the 0.3 m slab hangs under it.
        "at": r((0, slope_y(mid_z) - 0.15 / math.cos(math.radians(PITCH)), mid_z)),
        "size": r((10.4, 0.3, run)),
        "tilt": PITCH,
        "tone": 0.36,
    }
)
# The gable walls under the slope's sides, so it doesn't float.
for side, x in (("l", 4.9), ("r", -4.9)):
    span(
        f"c-gable-{side}", x - 0.1, x + 0.1, slope_y(C_Z1) - 0.2, C_TOP - 0.3, C_Z0, C_Z0 + 1.0, 0.5
    )

# What's on the roofs: a stair bulkhead and AC units on A, a water tank on B, an antenna on D.
span("a-bulkhead", 1.6, 4.2, 12.0, 14.6, 0.0, 3.0, 0.62)
span("a-door", 2.2, 3.4, 12.0, 14.1, 2.98, 3.04, 0.2)
for i, z in enumerate((8.0, 13.0)):
    span(f"a-ac-{i}", 2.6, 4.2, 12.0, 13.1, z, z + 1.4, 0.72)
S.append(
    {
        "id": "b-tank",
        "type": "cylinder",
        "at": [-3.0, 11.0, 30.0],
        "radius": 1.0,
        "height": 2.6,
        "tone": 0.66,
    }
)
span("b-pipe-rack", -4.6, -3.6, 11.0, 11.6, 25.0, 36.0, 0.58)
S.append(
    {
        "id": "d-antenna",
        "type": "capsule",
        "a": [3.4, 6.0, 66.0],
        "b": [3.4, 10.5, 66.0],
        "radius": 0.06,
        "tone": 0.8,
    }
)
span("d-ac", -4.2, -2.4, 6.0, 7.0, 60.0, 62.0, 0.72)

# Towers around the roofs, for depth and edges: taller across the street, lower beyond.
for i, (x0, x1, z0, z1, h) in enumerate(
    [
        (-30, -16, -10, 8, 34),
        (-30, -18, 12, 30, 26),
        (-28, -16, 34, 56, 40),
        (-30, -17, 60, 84, 22),
        (16, 30, -8, 14, 30),
        (17, 32, 18, 40, 44),
        (16, 28, 46, 70, 28),
        (-12, 12, 90, 104, 48),
        (-14, 14, -40, -26, 36),
    ]
):
    span(f"tower-{i}", x0, x1, 0, h, z0, z1, 0.46 + 0.04 * (i % 3))

SET = {
    "name": "Rooftops",
    "notes": "The run goes along +z down the middle (x = 0). Roof A flat at 12 m to z = 20, a 3.5 m "
    "gap, roof B flat at 11 m (z 23.5-38), roof C pitched 20° down to its eave at z = 48 "
    "(about 7.4 m), a 1.5 m gap, roof D flat at 6 m from z = 49.5. +x is on the left looking "
    "down +z.",
    "shapes": S,
    "marks": {
        "a-start": [0, 12.0, 4.0],
        "a-edge": [0, 12.0, 19.6],
        "b-landing": [0, 11.0, 24.4],
        "slope-top": [0, 11.0, 38.0],
        "eave": r((0, slope_y(47.6), 47.6)),
        "d-landing": [0, 6.0, 52.0],
    },
    "cameras": {
        "across-the-gap": {"at": [-12, 13.5, 14], "look": [0, 12, 22], "lens": 28},
        "up-the-slope": {"at": [2.5, 6.8, 60], "look": [0, 9, 43], "lens": 30},
    },
}

# --- the drone --------------------------------------------------------------------------------
DRONE = {
    "name": "Drone",
    "notes": "A quadcopter, origin under its middle, +z its front (the camera pod).",
    "shapes": [
        {"id": "body", "type": "box", "at": [0, 0.12, 0], "size": [0.34, 0.14, 0.46], "tone": 0.3},
        {"id": "pod", "type": "sphere", "at": [0, 0.03, 0.2], "radius": 0.07, "tone": 0.15},
        *[
            item
            for i, (x, z) in enumerate([(0.38, 0.38), (-0.38, 0.38), (0.38, -0.38), (-0.38, -0.38)])
            for item in (
                {
                    "id": f"arm-{i}",
                    "type": "capsule",
                    "a": [0, 0.15, 0],
                    "b": [x, 0.17, z],
                    "radius": 0.025,
                    "tone": 0.3,
                },
                {
                    "id": f"rotor-{i}",
                    "type": "cylinder",
                    "at": [x, 0.18, z],
                    "radius": 0.2,
                    "height": 0.02,
                    "tone": 0.55,
                },
            )
        ],
        {"id": "light", "type": "sphere", "at": [0, 0.2, -0.22], "radius": 0.03, "tone": 0.98},
    ],
}

# --- the scene --------------------------------------------------------------------------------


def key(t, at, face="path", **more):
    return {"t": t, "at": r(at), "face": face, **more}


def cam(t, at, look, lens, ease="smooth"):
    return {
        "t": t,
        "at": r(at),
        "look": look if isinstance(look, str) else r(look),
        "lens": lens,
        "ease": ease,
    }


def along(t0, t1, z0, z1, height, pose=None, step=0.1):
    """Keys every `step` seconds while Ren is on a surface (`height(z)` under him), so the smooth
    path through his keys can't dip into the roof between them."""
    n = max(1, round((t1 - t0) / step))
    out = []
    for i in range(n + 1):
        u = i / n
        z = z0 + (z1 - z0) * u
        k = key(t0 + (t1 - t0) * u, (0, height(z), z))
        if pose and i == 0:
            k["pose"] = pose
        out.append(k)
    return out


def flat(y):
    return lambda z: y


ren = [
    *along(0.0, 2.0, 6.0, 19.6, flat(12.0)),  # across A to its edge
    key(2.35, (0, 12.9, 21.9)),  # over the gap
    *along(2.7, 2.95, 24.4, 25.6, flat(11.0), "crouch", step=0.05),  # lands on B
    *along(3.0, 4.15, 25.85, 37.6, flat(11.0), "stand"),
    *along(4.3, 5.4, 38.8, 47.5, slope_y, "crouch"),  # the slide, down to the eave
    key(5.65, (0, slope_y(48.0) + 0.45, 49.4), pose="stand"),  # off it
    *along(5.95, 6.2, 52.0, 53.2, flat(6.0), "crouch", step=0.05),  # lands on D
    *along(6.25, 7.0, 53.45, 58.6, flat(6.0), "stand"),
]
drone = [
    key(0.0, (3.0, 16.5, -2.0), "@ren"),
    key(2.0, (2.5, 16.0, 12.0), "@ren"),
    key(3.5, (1.5, 15.2, 24.0), "@ren"),
    key(5.0, (0.5, 13.0, 36.0), "@ren"),
    key(7.0, (0.0, 10.5, 49.0), "@ren"),
]
SCENE = {
    "name": "Rooftop run",
    "set": "rooftops",
    "fps": 24,
    "cast": {"@drone": {"prop": "drone", "height": 0.15}},
    "actors": [{"id": "@ren", "keys": ren}, {"id": "@drone", "keys": drone}],
    "shots": [
        {
            # Side on from across the gap: the run and the jump.
            "name": "3A",
            "start": 0,
            "end": 2.7,
            "camera": [
                cam(0, (-7.5, 13.4, 9.0), "@ren", 38),
                cam(2.7, (-7.0, 13.6, 23.0), "@ren", 34),
            ],
        },
        {
            # From the drone's side, behind and above: Ren running for the slope.
            "name": "3B",
            "start": 2.7,
            "end": 4.6,
            "camera": [
                cam(2.7, (1.4, 14.4, 18.5), "@ren", 28),
                cam(4.6, (0.8, 13.6, 33.0), "@ren", 28),
            ],
        },
        {
            # Low on roof D, looking back up the slope: the slide, the drop and the landing.
            "name": "3C",
            "start": 4.6,
            "end": 7.0,
            "camera": [
                cam(4.6, (2.6, 7.0, 66.0), "@ren", 32),
                cam(7.0, (2.2, 6.8, 65.0), "@ren", 30),
            ],
        },
    ],
}

if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    for path, data in (
        (out / "sets" / "rooftops.json", SET),
        (out / "props" / "drone.json", DRONE),
        (out / "scenes" / "rooftop-run.json", SCENE),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print("wrote", path)
