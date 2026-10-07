"""A long night street for chases: two lanes along z, sidewalks, buildings both sides with two
side alleys on the left (-x), street lamps and parked cars (props from build_props.py).

    python build_street.py sets/night-street.json"""

import json
import sys

S = []


def r(v):
    return [round(x, 3) for x in v]


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


def prop(id, name, at, yaw=0):
    S.append({"id": id, "type": "prop", "prop": name, "at": r(at), "yaw": yaw})


Z0, Z1 = -70.0, 90.0
ROAD, WALK = 4.0, 6.5
# Alleys off the left side: where the sedan waits, and where the van gets away.
ALLEYS = [(10.0, 16.0), (55.0, 61.0)]

span("ground", -40, 40, -0.12, -0.05, Z0 - 20, Z1 + 20, 0.22)
span("road", -ROAD, ROAD, -0.05, 0, Z0, Z1, 0.3)
for i, z in enumerate(range(int(Z0), int(Z1), 6)):
    span(f"lane-dash-{i}", -0.06, 0.06, 0, 0.01, z, z + 3, 0.62)
for s, x0, x1 in (("l", -WALK, -ROAD), ("r", ROAD, WALK)):
    span(f"sidewalk-{s}", x0, x1, 0, 0.14, Z0, Z1, 0.42)
for a, (z0, z1) in enumerate(ALLEYS):
    span(f"alley-{a + 1}-floor", -26, -WALK, -0.04, 0.01, z0, z1, 0.27)

# Buildings: blocks of varied height and grey, broken by the alleys on the left.
heights = [9, 14, 7, 11, 16, 8, 12, 10, 18, 9, 13, 7]
tones = [0.5, 0.44, 0.56, 0.47, 0.52, 0.42]


def blocks(side, x0, x1, gaps):
    z, i = Z0, 0
    while z < Z1:
        depth = 12.0 + (i % 3) * 3
        z1 = min(z + depth, Z1)
        for g0, g1 in gaps:
            if z < g1 and z1 > g0:
                if z < g0:
                    z1 = g0
                else:
                    z, z1 = g1, min(g1 + depth, Z1)
        h = heights[i % len(heights)]
        span(f"building-{side}{i + 1}", x0, x1, 0, h, z, z1 - 0.4, tones[i % len(tones)])
        # A strip of lit windows on the street face, one floor up.
        face = x1 + 0.02 if side == "l" else x0 - 0.02
        if i % 2 == 0:
            span(
                f"windows-{side}{i + 1}", face - 0.01, face + 0.01, 3.2, 4.4, z + 1.5, z1 - 2, 0.86
            )
        z, i = z1, i + 1


blocks("l", -20, -WALK, ALLEYS)
blocks("r", WALK, 20, [])

# Street lamps every 16 m, alternating sides, their heads over the road.
for i, z in enumerate(range(int(Z0) + 6, int(Z1), 16)):
    side = 1 if i % 2 else -1
    prop(f"lamp-{i + 1}", "lamp", (side * 4.6, 0.14, z), yaw=-90 * side)
# Cars parked along the right kerb.
for i, z in enumerate((-30, -4, 38, 46, 70)):
    prop(f"parked-{i + 1}", "car", (3.0, 0, z), yaw=0 if i % 2 else 180)

out = {
    "name": "Night street",
    "notes": "A two-lane street along z (the van drives toward +z), sidewalks both sides, buildings broken by two alleys on the left (-x): the first at z 10-16 (where the sedan waits), the second at z 55-61 (where the van turns off). Lamps alternate sides every 16 m; cars are parked along the right kerb.",
    "shapes": S,
    "marks": {
        "van-start": [-1.8, 0, -22],
        "alley-1": [-12, 0, 13],
        "alley-2": [-16, 0, 58],
    },
    "cameras": {
        "street-low": {"at": [0.3, 0.5, 30], "look": [-1.8, 1.0, -20], "lens": 35},
        "alley-mouth": {"at": [-12.5, 1.25, 17], "look": [-2, 1.0, 9], "lens": 28},
        "across-alley-2": {"at": [5.8, 4.5, 47], "look": [-4, 1, 57], "lens": 22},
    },
}
with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(out, f, indent=1)
print(len(S), "shapes")
