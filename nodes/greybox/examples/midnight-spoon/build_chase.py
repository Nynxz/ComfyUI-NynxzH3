"""The test chase on the night street: two 7-second scenes, vehicles only (the people are inside).

    python build_chase.py scenes/

Scene 1: the van comes down the street; a black sedan waiting in the first alley pulls out behind it.
Scene 2: through the windscreen, then the cargo bay; the van swerves into the second alley and the
sedan overshoots. Tracking cameras are worked out from the vehicles' own keys, so they hold."""

import itertools
import json
import sys
from pathlib import Path

LANE = -1.8  # the van's lane


def r(v):
    return [round(x, 3) for x in v]


def key(t, at, face="path", **more):
    return {"t": t, "at": r(at), "face": face, **more}


def lerp(keys, t):
    """Where a vehicle is at `t` on straight, linear keys (for cameras that ride along)."""
    for a, b in itertools.pairwise(keys):
        if a["t"] <= t <= b["t"]:
            u = (t - a["t"]) / (b["t"] - a["t"])
            return [a["at"][i] + (b["at"][i] - a["at"][i]) * u for i in range(3)]
    return keys[-1]["at"]


def cam(t, at, look, lens, ease="linear"):
    return {
        "t": t,
        "at": r(at),
        "look": look if isinstance(look, str) else r(look),
        "lens": lens,
        "ease": ease,
    }


def scene1():
    van = [key(0, (LANE, 0, -22)), key(7, (LANE, 0, 50))]  # ~10 m/s
    sedan = [
        key(0, (-15, 0, 13), 90),
        key(3.6, (-10.5, 0, 13), 90),  # creeping to the alley mouth
        key(4.6, (-5.5, 0, 12.4)),  # out across the sidewalk as the van passes
        key(5.4, (LANE + 0.4, 0, 16)),
        key(7, (LANE, 0, 33)),
    ]
    shots = [
        {
            "name": "1A",
            "start": 0,
            "end": 2.5,
            "camera": [
                cam(0, (0.6, 0.45, 15), "@van", 34, "smooth"),
                cam(2.5, (0.6, 0.45, 15), "@van", 24, "smooth"),
            ],
        },
        {
            # From inside the alley, over the sedan's roof: the van flashes past the mouth.
            "name": "1B",
            "start": 2.5,
            "end": 4.5,
            "camera": [
                cam(2.5, (-17.5, 1.9, 13.4), (-3, 1.0, 13), 30),
                cam(4.5, (-14, 1.8, 13.4), (-3, 1.1, 15), 30),
            ],
        },
        {
            # Chase cam: behind and above the sedan as it swings out and closes on the van.
            "name": "1C",
            "start": 4.5,
            "end": 7,
            "camera": [
                cam(4.5, (-6, 2.2, 4), "@van", 26),
                cam(5.5, (LANE + 1.2, 2.0, 8), "@van", 28),
                cam(7, (LANE + 0.6, 1.9, 24), "@van", 32),
            ],
        },
    ]
    return {
        "name": "Chase 1 — Headlights",
        "set": "night-street",
        "fps": 24,
        "notes": "Rain night. The Midnight Spoon van comes down the street fast; a black sedan waiting in the first alley pulls out behind it and gives chase.",
        "actors": [{"id": "@van", "keys": van}, {"id": "@sedan", "keys": sedan}],
        "shots": shots,
    }


def scene2():
    van = [
        key(0, (LANE, 0, 10)),
        key(4.5, (LANE, 0, 50)),  # ~9 m/s
        key(5.2, (LANE - 1.2, 0, 55.5)),
        key(5.9, (-6.5, 0, 58)),
        key(7, (-17, 0, 58)),
    ]
    sedan = [
        key(0, (LANE, 0, -4)),
        key(4.5, (LANE, 0, 41)),
        key(5.6, (LANE + 1.0, 0, 54)),
        key(6.3, (1.2, 0, 60), 25),  # too late: it skids past, sliding sideways
        key(7, (2.2, 0, 63.5), 55),
    ]
    vk = [k for k in van if k["t"] <= 4.5]
    sk = [k for k in sedan if k["t"] <= 4.5]
    ahead = lambda t, d, y: [LANE, y, lerp(vk, t)[2] + d]  # noqa: E731
    behind = lambda t, d, y: [LANE, y, lerp(vk, t)[2] - d]  # noqa: E731
    shots = [
        {
            # Through the windscreen, riding just ahead of the van, looking back into the cab.
            "name": "2A",
            "start": 0,
            "end": 2.5,
            "camera": [
                cam(0, ahead(0, 4.8, 1.75), "@van", 30),
                cam(2.5, ahead(2.5, 4.8, 1.75), "@van", 30),
            ],
        },
        {
            # From the back of the van, looking out at the sedan's headlights behind.
            "name": "2B",
            "start": 2.5,
            "end": 4.5,
            "camera": [
                cam(2.5, behind(2.5, 2.6, 1.45), "@sedan", 30),
                cam(4.5, behind(4.5, 2.6, 1.45), "@sedan", 34),
            ],
        },
        {
            # Wide and high from across the street: the van cuts into the alley, the sedan slides past.
            "name": "2C",
            "start": 4.5,
            "end": 7,
            "camera": [
                cam(4.5, (5.8, 4.5, 51.5), (-3, 1, 55), 22, "smooth"),
                cam(7, (5.8, 4.2, 53), (-6, 1, 59), 24, "smooth"),
            ],
        },
    ]
    _ = sk
    return {
        "name": "Chase 2 — Left. Now.",
        "set": "night-street",
        "fps": 24,
        "notes": "The sedan is right behind them. Ren drives, Mika looks back, Lumi in the cargo bay calls the turn; the van swerves into the second alley and the sedan overshoots, sliding past the mouth.",
        "actors": [{"id": "@van", "keys": van}, {"id": "@sedan", "keys": sedan}],
        "shots": shots,
    }


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "scenes")
    for name, build in (("chase-1", scene1), ("chase-2", scene2)):
        (out / f"{name}.json").write_text(json.dumps(build(), indent=1) + "\n", encoding="utf-8")
        print(name)
