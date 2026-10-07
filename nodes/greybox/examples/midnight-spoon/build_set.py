"""Midnight Spoon, from the episode 01 reference sheet (top-down plan + cutaway).

Writes the set: python build_set.py sets/midnight-spoon.json"""

import json
import sys

S = []


def box(id, at, size, tone, yaw=None):
    d = {
        "id": id,
        "type": "box",
        "at": [round(v, 3) for v in at],
        "size": [round(v, 3) for v in size],
        "tone": tone,
    }
    if yaw:
        d["yaw"] = yaw
    S.append(d)


def span(id, x0, x1, y0, y1, z0, z1, tone):
    """A box from its extents."""
    box(id, [(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2], [x1 - x0, y1 - y0, z1 - z0], tone)


def cyl(id, at, r, h, tone):
    S.append(
        {
            "id": id,
            "type": "cylinder",
            "at": [round(v, 3) for v in at],
            "radius": r,
            "height": h,
            "tone": tone,
        }
    )


def sph(id, at, r, tone):
    S.append(
        {"id": id, "type": "sphere", "at": [round(v, 3) for v in at], "radius": r, "tone": tone}
    )


X0, X1, Z0, Z1, H, T = -5.0, 5.0, -3.3, 3.3, 3.0, 0.15
WALL, FLOOR = 0.6, 0.42

# --- ground ------------------------------------------------------------------------------------
span("floor", X0, X1, -0.1, 0, Z0, Z1, FLOOR)
span("sidewalk", -9, 9, -0.1, 0.1, Z1, 5.6, 0.5)
span("road", -9, 9, -0.15, -0.05, 5.6, 9.5, 0.28)
span("alley", -5.5, 8, -0.15, -0.02, -6.8, Z0, 0.33)

# --- shell -------------------------------------------------------------------------------------
span("wall-left", X0 - T, X0, 0, H, Z0, Z1, WALL)
span("wall-right", X1, X1 + T, 0, H, Z0, Z1, WALL)
# back wall, with the rear door at the right
span("wall-back", X0, 4.0, 0, H, Z0 - T, Z0, WALL)
span("wall-back-right", 4.9, X1, 0, H, Z0 - T, Z0, WALL)
span("wall-back-over-door", 4.0, 4.9, 2.1, H, Z0 - T, Z0, WALL)
span("rear-door", 4.0, 4.9, 0, 2.1, Z0 - T - 0.02, Z0 - T + 0.03, 0.35)
# storefront: door at the left, windows the rest of the way (a low wall, posts, a header)
DOOR = (-4.6, -3.6)
span("front-left", X0, DOOR[0], 0, H, Z1, Z1 + T, WALL)
span("front-over-door", DOOR[0], DOOR[1], 2.2, H, Z1, Z1 + T, WALL)
span("front-low", DOOR[1], X1, 0, 0.8, Z1, Z1 + T, WALL)
span("front-header", DOOR[1], X1, 2.3, H, Z1, Z1 + T, WALL)
for i, x in enumerate([DOOR[1], -1.4, 0.8, 3.0, X1 - 0.08]):
    span(f"window-post-{i + 1}", x, x + 0.08, 0.8, 2.3, Z1, Z1 + T, WALL)
for s, x in (("l", DOOR[0]), ("r", DOOR[1] - 0.06)):
    span(f"door-frame-{s}", x, x + 0.06, 0, 2.2, Z1, Z1 + T, 0.25)  # the glass door stands open
span("doormat", -4.5, -3.7, 0, 0.015, 2.6, 3.25, 0.3)

# --- storage (back left) -----------------------------------------------------------------------
SX, SZ = -2.5, -1.7
span("storage-wall", X0, -3.4, 0, H, SZ - T, SZ, WALL)  # with a doorway -3.4..-2.6
span("storage-wall-over", -3.4, SX, 2.1, H, SZ - T, SZ, WALL)
span("storage-wall-post", -2.6, SX, 0, 2.1, SZ - T, SZ, WALL)
span("storage-side", SX, SX + T, 0, H, Z0, SZ, WALL)
span("storage-shelf-back", X0, -3.0, 0, 2.1, Z0, Z0 + 0.45, 0.55)
span("storage-shelf-left", X0, X0 + 0.45, 0, 2.1, -2.8, -2.0, 0.55)
span("crates", -3.0, -2.6, 0, 0.8, -3.2, -2.7, 0.62)

# --- kitchen (back) ----------------------------------------------------------------------------
span("back-bench", SX + T, 2.6, 0, 0.9, Z0, Z0 + 0.65, 0.66)
span("stoves", -2.1, -0.4, 0.9, 0.98, Z0 + 0.05, Z0 + 0.6, 0.38)
cyl("stock-pot", [-1.65, 0.98, Z0 + 0.32], 0.2, 0.36, 0.72)
cyl("pot", [-0.9, 0.98, Z0 + 0.32], 0.15, 0.2, 0.72)
span("hood", -2.25, -0.25, 2.1, 2.55, Z0, Z0 + 0.75, 0.5)
span("wall-shelf", -0.1, 2.5, 1.6, 1.65, Z0, Z0 + 0.32, 0.6)
span("menu-board", 0.4, 1.9, 1.85, 2.65, Z0, Z0 + 0.04, 0.22)
span("fridge", 2.7, 3.6, 0, 2.0, Z0, Z0 + 0.75, 0.82)
span("sink", 3.65, 3.95, 0, 0.9, Z0, Z0 + 0.65, 0.7)  # dishwashing by the rear door
span("prep-table", -1.6, 0.6, 0, 0.88, -2.2, -1.75, 0.68)

# --- counter -----------------------------------------------------------------------------------
CZ = -1.0  # the counter's middle; customers at +z, kitchen at -z
span("counter", -2.5, 3.6, 0, 1.0, CZ - 0.3, CZ + 0.3, 0.55)
span("counter-top", -2.6, 3.7, 1.0, 1.05, CZ - 0.38, CZ + 0.42, 0.78)
span("counter-flap", 3.7, X1, 1.0, 1.05, CZ - 0.38, CZ + 0.42, 0.78)  # lifts: staff way through
STOOLS = [-1.7 + i * 0.95 for i in range(6)]
for i, x in enumerate(STOOLS):
    cyl(f"stool-{i + 1}", [x, 0, CZ + 0.62], 0.05, 0.66, 0.35)
    cyl(f"stool-{i + 1}-seat", [x, 0.66, CZ + 0.62], 0.19, 0.08, 0.5)
# TV hung over the counter, left end; pendant lamps along it
span("tv", -2.2, -1.5, 2.05, 2.55, CZ - 0.25, CZ + 0.2, 0.3)
span("tv-mount", -1.9, -1.8, 2.55, H, CZ - 0.05, CZ + 0.05, 0.4)
for i, x in enumerate([-0.6, 0.8, 2.2]):
    cyl(f"lamp-{i + 1}-cord", [x, 2.3, CZ], 0.01, 0.7, 0.4)
    sph(f"lamp-{i + 1}", [x, 2.25, CZ], 0.14, 0.95)


# --- dining (front) ----------------------------------------------------------------------------
def booth(name, cx, cz, along_x):
    """Two benches facing over a table; along_x: the benches face each other along x."""
    if along_x:
        span(f"{name}-table", cx - 0.4, cx + 0.4, 0.72, 0.76, cz - 0.55, cz + 0.55, 0.78)
        cyl(f"{name}-table-leg", [cx, 0, cz], 0.06, 0.72, 0.4)
        for s, side in (("l", -1), ("r", 1)):
            x = cx + side * 0.85
            span(f"{name}-bench-{s}", x - 0.25, x + 0.25, 0, 0.45, cz - 0.7, cz + 0.7, 0.36)
            xb = x + side * 0.25
            span(
                f"{name}-back-{s}",
                min(xb, xb + side * 0.12),
                max(xb, xb + side * 0.12),
                0,
                1.15,
                cz - 0.7,
                cz + 0.7,
                0.36,
            )
    else:
        span(f"{name}-table", cx - 0.55, cx + 0.55, 0.72, 0.76, cz - 0.4, cz + 0.4, 0.78)
        cyl(f"{name}-table-leg", [cx, 0, cz], 0.06, 0.72, 0.4)
        for s, side in (("f", -1), ("b", 1)):
            z = cz + side * 0.85
            span(f"{name}-bench-{s}", cx - 0.7, cx + 0.7, 0, 0.45, z - 0.25, z + 0.25, 0.36)
            zb = z + side * 0.25
            span(
                f"{name}-back-{s}",
                cx - 0.7,
                cx + 0.7,
                0,
                1.15,
                min(zb, zb + side * 0.12),
                max(zb, zb + side * 0.12),
                0.36,
            )


booth("booth-a", -1.9, 2.3, True)
booth("booth-b", 3.9, 2.15, False)
for name, x in (("table-1", 0.55), ("table-2", 1.95)):
    span(name, x - 0.35, x + 0.35, 0.72, 0.76, 1.95, 2.65, 0.78)
    cyl(f"{name}-leg", [x, 0, 2.3], 0.05, 0.72, 0.4)
    for s, dx in (("l", -0.6), ("r", 0.6)):
        span(f"{name}-chair-{s}", x + dx - 0.2, x + dx + 0.2, 0, 0.46, 2.1, 2.5, 0.45)
cyl("plant-pot", [2.95, 0, 3.0], 0.18, 0.45, 0.4)
sph("plant", [2.95, 0.95, 3.0], 0.36, 0.5)
cyl("plant-2-pot", [-4.65, 0, -1.25], 0.18, 0.4, 0.4)
sph("plant-2", [-4.65, 0.85, -1.25], 0.35, 0.5)

# --- outside: the building, the street, the neighbours -----------------------------------------
span("facade", X0 - T, X1 + T, H, 7.5, Z1, Z1 + T, 0.5)
span("eave", X0, X1, 2.85, 3.0, Z1 + T, Z1 + 0.9, 0.45)
span("sign", -3.0, 3.0, 3.25, 4.05, Z1 + T, Z1 + 0.3, 0.9)
span("noren", DOOR[0], DOOR[1], 1.7, 2.2, Z1 + 0.18, Z1 + 0.2, 0.75)
for i, x in enumerate([DOOR[0] - 0.25, DOOR[1] + 0.25]):
    cyl(f"lantern-{i + 1}", [x, 1.9, Z1 + 0.35], 0.15, 0.5, 0.9)
span("laundromat", -9, X0 - T, 0, 6.0, -6.8, Z1 + T, 0.48)
span("repair-shop", X1 + T, 9, 0, 9.0, Z0 - T, Z1 + T, 0.46)
span("vending-1", 5.5, 6.3, 0.1, 1.95, Z1 + T, Z1 + 0.9, 0.85)
span("vending-2", 6.4, 7.2, 0.1, 1.95, Z1 + T, Z1 + 0.9, 0.8)
span("rail", -3.0, 3.5, 0.85, 0.92, 5.3, 5.36, 0.7)
for i, x in enumerate([-3.0, -0.8, 1.4, 3.5]):
    cyl(f"rail-post-{i + 1}", [x, 0.1, 5.33], 0.03, 0.78, 0.7)
# the alley behind: the van, the bins
span("van", -3.6, 1.0, 0.25, 2.25, -6.4, -4.5, 0.85)
span("bins", 5.1, 6.6, 0, 1.2, -4.3, -3.45, 0.4)
span("back-building", -9, 8, 0, 8.0, -7.6, -6.8, 0.45)


def r(*v: float) -> list[float]:
    return [round(x, 2) for x in v]


marks = {
    "street": r(-4.1, 0, 7.5),
    "sidewalk": r(-4.1, 0, 4.4),
    "door": r(-4.1, 0, 2.6),
    "middle": r(0.6, 0, 0.6),
    **{f"stool-{i + 1}": r(x, 0, CZ + 0.62) for i, x in enumerate(STOOLS)},
    # sitting on a stool: the sit pose assumes a 0.45 m chair; the stools are 0.74 m
    **{f"seat-{i + 1}": r(x, 0.29, CZ + 0.66) for i, x in enumerate(STOOLS)},
    "stove": r(-1.25, 0, -2.35),
    "line": r(1.3, 0, -2.3),
    "behind-counter": r(1.0, 0, -1.6),
    "fridge": r(3.15, 0, -2.25),
    "rear-door": r(4.45, 0, -2.75),
    "alley": r(4.45, 0, -4.2),
    "storage": r(-3.9, 0, -2.5),
    "booth-a": r(-2.75, 0, 2.3),
    "booth-a-2": r(-1.05, 0, 2.3),
    "booth-b": r(3.9, 0, 1.3),
    "table-1": r(-0.05, 0, 2.3),
    "table-2": r(1.35, 0, 2.3),
}
cameras = {
    "counter-main": {"at": r(0.6, 1.35, 2.6), "look": r(0.3, 1.45, -3.2), "lens": 26},
    "from-kitchen": {"at": r(4.3, 1.7, -1.7), "look": r(-4.1, 1.2, 2.6), "lens": 24},
    "entrance-angle": {"at": r(-3.3, 1.55, -1.2), "look": r(-4.1, 1.2, 3.3), "lens": 28},
    "kitchen": {"at": r(3.3, 1.7, -1.55), "look": r(-1.8, 1.0, -3.0), "lens": 22},
    "exterior-front": {"at": r(-0.5, 1.6, 12.0), "look": r(0.0, 2.6, 3.3), "lens": 26},
    "rear-service": {"at": r(2.4, 1.6, -6.5), "look": r(4.6, 1.1, -3.4), "lens": 24},
    "cutaway": {"at": r(-4.0, 20.0, 5.0), "look": r(0.0, 0.0, -0.3), "lens": 30},
}
out = {
    "name": "Midnight Spoon",
    "notes": (
        "From the episode 01 reference sheet. A ramen shop on the street (+z), wider than deep: "
        "storage in the back-left corner, the kitchen line along the back wall with the rear door "
        "to the alley at back-right, a long counter with six stools across the middle (the staff "
        "way through is its right end), and the dining room at the front — two booths, two "
        "tables, the entrance at front-left. The TV hangs over the counter's left end."
    ),
    "shapes": S,
    "marks": marks,
    "cameras": cameras,
}
with open(sys.argv[1], "w") as f:
    json.dump(out, f, indent=1)
print(len(S), "shapes")
