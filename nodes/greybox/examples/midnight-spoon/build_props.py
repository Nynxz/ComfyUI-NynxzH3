"""The example's props: the Midnight Spoon delivery van, a sedan and a street lamp.

    python build_props.py props/

Each is built around its own origin (on the road under its middle), +z its front."""

import json
import sys
from pathlib import Path


def r(v):
    return [round(x, 3) for x in v]


class Prop:
    def __init__(self):
        self.shapes = []

    def box(self, id, at, size, tone):
        self.shapes.append({"id": id, "type": "box", "at": r(at), "size": r(size), "tone": tone})

    def rod(self, id, a, b, radius, tone):
        self.shapes.append(
            {"id": id, "type": "cylinder", "a": r(a), "b": r(b), "radius": radius, "tone": tone}
        )

    def post(self, id, at, radius, height, tone):
        self.shapes.append(
            {
                "id": id,
                "type": "cylinder",
                "at": r(at),
                "radius": radius,
                "height": height,
                "tone": tone,
            }
        )

    def wheels(self, x, zs, radius, tone=0.11, hub=0.55):
        for e, z in zip(("front", "rear"), zs, strict=True):
            for s, side in (("l", 1), ("r", -1)):
                self.rod(
                    f"wheel-{e}-{s}",
                    (side * (x - 0.2), radius, z),
                    (side * x, radius, z),
                    radius,
                    tone,
                )
                self.rod(
                    f"hub-{e}-{s}",
                    (side * x, radius, z),
                    (side * (x + 0.01), radius, z),
                    radius * 0.45,
                    hub,
                )


GLASS, TRIM, LAMP = 0.14, 0.27, 0.97


def van():
    """A high-roof panel van, from the Midnight Spoon delivery van sheet: ~4.7 x 1.9 x 2.3 m."""
    p, body, w = Prop(), 0.46, 1.88
    p.box("body", (0, 1.315, -0.3), (w, 1.93, 4.1), body)
    p.box("nose", (0, 0.75, 2.05), (1.84, 0.8, 0.6), body)
    p.box("bonnet-step", (0, 1.17, 1.9), (1.8, 0.06, 0.3), 0.4)
    p.box("windscreen", (0, 1.62, 1.762), (1.7, 0.74, 0.04), GLASS)
    p.box("grille", (0, 0.86, 2.355), (0.9, 0.28, 0.03), 0.2)
    for s, x in (("l", 0.66), ("r", -0.66)):
        p.box(f"headlight-{s}", (x, 0.88, 2.358), (0.32, 0.2, 0.04), LAMP)
    p.box("bumper-front", (0, 0.45, 2.39), (1.92, 0.2, 0.14), TRIM)
    p.box("plate-front", (0, 0.62, 2.366), (0.34, 0.16, 0.02), 0.9)
    for s, x in (("l", 1), ("r", -1)):
        side = x * (w / 2 + 0.005)
        p.box(f"cab-window-{s}", (side, 1.63, 1.27), (0.03, 0.62, 0.74), GLASS)
        p.box(f"door-seam-{s}", (side, 1.1, 0.76), (0.02, 1.45, 0.03), TRIM)
        p.box(f"logo-{s}", (side, 1.45, -0.85), (0.02, 0.85, 1.35), 0.6)
        p.box(f"mirror-{s}", (x * 1.06, 1.55, 1.62), (0.12, 0.24, 0.08), 0.25)
        for e, z in (("front", 1.45), ("rear", -1.45)):
            p.box(f"arch-{e}-{s}", (side, 0.56, z), (0.02, 0.42, 0.86), 0.18)
    p.wheels(0.99, (1.45, -1.45), 0.36)
    p.box("rear-seam", (0, 1.3, -2.356), (0.03, 1.7, 0.02), TRIM)
    for s, x in (("l", 0.84), ("r", -0.84)):
        p.box(f"taillight-{s}", (x, 1.02, -2.358), (0.14, 0.36, 0.03), 0.9)
    p.box("bumper-rear", (0, 0.45, -2.39), (1.92, 0.2, 0.14), TRIM)
    p.box("plate-rear", (0, 0.72, -2.366), (0.34, 0.16, 0.02), 0.9)
    return {
        "name": "Midnight Spoon delivery van",
        "notes": "A high-roof panel van, about 4.7 m long, 1.9 m wide, 2.3 m tall. The lighter panels on its sides are the Midnight Spoon logo; the rear doors open from a centre seam.",
        "shapes": p.shapes,
    }


def car():
    """A four-door sedan: ~4.6 x 1.8 x 1.45 m."""
    p, body, w = Prop(), 0.62, 1.78
    p.box("body", (0, 0.62, 0), (w, 0.6, 4.6), body)
    p.box("cabin", (0, 1.15, -0.25), (1.6, 0.5, 2.3), body)
    p.box("windscreen", (0, 1.13, 0.91), (1.5, 0.42, 0.04), GLASS)
    p.box("rear-window", (0, 1.13, -1.41), (1.5, 0.4, 0.04), GLASS)
    for s, x in (("l", 1), ("r", -1)):
        p.box(f"windows-{s}", (x * 0.805, 1.15, -0.25), (0.02, 0.36, 2.0), GLASS)
        p.box(f"mirror-{s}", (x * 0.98, 0.98, 0.95), (0.14, 0.12, 0.08), 0.3)
    for s, x in (("l", 0.65), ("r", -0.65)):
        p.box(f"headlight-{s}", (x, 0.7, 2.305), (0.34, 0.12, 0.03), LAMP)
        p.box(f"taillight-{s}", (x, 0.75, -2.305), (0.3, 0.12, 0.03), 0.9)
    p.box("grille", (0, 0.62, 2.305), (0.7, 0.14, 0.02), 0.2)
    p.box("bumper-front", (0, 0.4, 2.33), (1.8, 0.16, 0.1), TRIM)
    p.box("bumper-rear", (0, 0.4, -2.33), (1.8, 0.16, 0.1), TRIM)
    p.wheels(0.9, (1.4, -1.4), 0.33)
    return {
        "name": "Sedan",
        "notes": "A plain four-door sedan, about 4.6 m long and 1.45 m tall.",
        "shapes": p.shapes,
    }


def lamp():
    """A street lamp: a pole with its head reaching out over the road (+z)."""
    p = Prop()
    p.post("pole", (0, 0, 0), 0.07, 5.2, 0.35)
    p.box("arm", (0, 5.15, 0.6), (0.08, 0.08, 1.3), 0.35)
    p.box("head", (0, 5.08, 1.25), (0.3, 0.1, 0.55), 0.95)
    p.post("base", (0, 0, 0), 0.14, 0.5, 0.3)
    return {
        "name": "Street lamp",
        "notes": "+z is the side its light reaches over.",
        "shapes": p.shapes,
    }


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "props")
    out.mkdir(parents=True, exist_ok=True)
    for name, build in (("van", van), ("car", car), ("lamp", lamp)):
        prop = build()
        (out / f"{name}.json").write_text(json.dumps(prop, indent=1) + "\n", encoding="utf-8")
        print(name, len(prop["shapes"]), "shapes")
