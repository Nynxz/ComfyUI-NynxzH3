"""What an agent (or a person) looks at to check a scene: a contact sheet of each shot's frames
beside a plan from above, with the set's marks, every actor's path and each shot's camera.
Also: the frames of a shot, ready to save as a video.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont

from .render import bounds, camera_rays, depth_image, plan_rays, render
from .scene import Scene, Shot, shapes_at

INK = (235, 235, 240)
MUTED = (150, 150, 160)
PANEL = (24, 24, 28)
ACTOR_COLORS = [
    (255, 140, 90),
    (110, 180, 255),
    (140, 220, 120),
    (240, 200, 90),
    (220, 130, 230),
    (90, 220, 210),
]


def _font(size: int):
    for name in ("DejaVuSans.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def to_image(t: torch.Tensor) -> Image.Image:
    return Image.fromarray((t.clamp(0, 1) * 255).round().byte().cpu().numpy())


def shot_frames(
    scene: Scene,
    shot: Shot,
    width: int,
    height: int,
    device="cpu",
    fps: float | None = None,
    depth: bool = False,
    start: float | None = None,
    count: int | None = None,
) -> torch.Tensor:
    """Every frame of a shot `[N, H, W, 3]` (or its depth pictures with `depth`). With `start` and
    `count`: that many frames from that time instead, which may run past the shot's end (its
    camera then holds its last key)."""
    rate = fps or scene.fps
    t0 = shot.start if start is None else start
    n = count or max(1, round((shot.end - shot.start) * rate))
    out = torch.empty(n, height, width, 3)
    for i in range(n):
        t = t0 + i / rate
        o, d = camera_rays(scene.camera(shot, t), width, height, device)
        f = render(shapes_at(scene, t), o, d, width, height)
        out[i] = (depth_image(f.depth) if depth else f.image).cpu()
    return out


def scene_frames(
    scene: Scene,
    width: int,
    height: int,
    device="cpu",
    fps: float | None = None,
    depth: bool = False,
) -> torch.Tensor:
    """The whole scene as it cuts: every shot in order, each through its own camera."""
    shots = sorted(scene.shots, key=lambda s: s.start)
    if not shots:
        raise ValueError("The scene has no shots.")
    return torch.cat([shot_frames(scene, s, width, height, device, fps, depth) for s in shots])


def h3_frames(n: int) -> int:
    """The fewest frames, at least `n`, that MiniMax H3 takes whole as a reference video (17k + 5):
    it trims anything else down, losing the end."""
    return n if n % 17 == 5 else n + (5 - n % 17) % 17


def pad_to(frames: torch.Tensor, n: int, more) -> torch.Tensor:
    """`frames` made `n` long with `more(k)`, k extra frames continuing it."""
    return frames if frames.shape[0] >= n else torch.cat([frames, more(n - frames.shape[0])])


def actor_mask(
    scene: Scene,
    shot: Shot,
    actor: str,
    width: int,
    height: int,
    device="cpu",
    fps: float | None = None,
) -> torch.Tensor:
    """Where `actor` is in each frame of the shot: `[N, H, W]`, 1 on it."""
    rate = fps or scene.fps
    n = max(1, round((shot.end - shot.start) * rate))
    out = torch.zeros(n, height, width)
    for i in range(n):
        t = shot.start + i / rate
        o, d = camera_rays(scene.camera(shot, t), width, height, device)
        f = render(shapes_at(scene, t), o, d, width, height, shadows=False, edges=False)
        if actor in f.owners:
            out[i] = (f.owner == f.owners.index(actor)).float().cpu()
    return out


def still(scene: Scene, shot: Shot, t: float, width: int, height: int, device="cpu") -> Image.Image:
    """One frame of a shot, labelled with the shot, the time and the lens."""
    cam = scene.camera(shot, t)
    o, d = camera_rays(cam, width, height, device)
    img = to_image(render(shapes_at(scene, t), o, d, width, height).image).convert("RGB")
    ImageDraw.Draw(img).text(
        (8, 6), f"{shot.name}  {t:.2f}s  {cam.lens:.0f}mm", fill=INK, font=_font(15)
    )
    return img


def plan(scene: Scene, size: int = 520, device="cpu", t: float = 0.0) -> Image.Image:
    """The set from above at `t`, with marks, actors' paths (start dot → end arrow) and every
    shot's camera (its position, which way it points and its spread)."""
    shapes = shapes_at(scene, t)
    cams = [scene.camera(s, s.start) for s in scene.shots]
    lo, hi = bounds(shapes, [c.at for c in cams])
    span_x, span_z = hi[0] - lo[0], hi[1] - lo[1]
    w = size
    h = max(160, int(size * span_z / max(span_x, 1e-6)))
    if h > size * 1.6:
        h = int(size * 1.6)
        w = max(160, int(h * span_x / max(span_z, 1e-6)))
    o, d = plan_rays(lo, hi, w, h, device)
    img = to_image(render(shapes, o, d, w, h, fog=0).image).convert("RGB")
    g = ImageDraw.Draw(img)
    font = _font(12)

    def px(p) -> tuple[float, float]:
        return ((p[0] - lo[0]) / span_x * w, (p[2] - lo[1]) / span_z * h)

    for name, p in scene.set.marks.items():
        x, y = px(p)
        g.line((x - 5, y, x + 5, y), fill=MUTED, width=1)
        g.line((x, y - 5, x, y + 5), fill=MUTED, width=1)
        g.text((x + 6, y - 7), name, fill=MUTED, font=font)
    for ai, actor in enumerate(scene.actors):
        color = ACTOR_COLORS[ai % len(ACTOR_COLORS)]
        t0, t1 = actor.keys[0].t, max(actor.keys[-1].t, scene.length)
        steps = max(2, int((t1 - t0) * 8))
        pts = [
            px(scene.actor_at(actor.id, t0 + (t1 - t0) * i / steps).at) for i in range(steps + 1)
        ]
        if len(set(pts)) > 1:
            g.line(pts, fill=color, width=2)
        x0, y0 = pts[0]
        g.ellipse((x0 - 4, y0 - 4, x0 + 4, y0 + 4), fill=color)
        end = scene.actor_at(actor.id, t1)
        x1, y1 = px(end.at)
        a = math.radians(end.yaw)
        tip = (x1 + math.sin(a) * 12, y1 + math.cos(a) * 12)
        g.line((x1, y1, *tip), fill=color, width=3)
        g.text((x0 + 6, y0 + 2), actor.id, fill=color, font=font)
    for shot, cam in zip(scene.shots, cams, strict=True):
        x, y = px(cam.at)
        lx, ly = px(cam.look)
        a = math.atan2(ly - y, lx - x)
        spread = math.radians(cam.fov) * 0.5 * 1.5
        for side in (-1, 1):
            g.line(
                (x, y, x + math.cos(a + side * spread) * 26, y + math.sin(a + side * spread) * 26),
                fill=INK,
                width=1,
            )
        g.rectangle((x - 4, y - 4, x + 4, y + 4), fill=INK)
        g.text((x + 6, y + 4), f"cam {shot.name}", fill=INK, font=font)
    return img


def contact_sheet(scene: Scene, per_shot: int = 4, width: int = 320, device="cpu") -> Image.Image:
    """Each shot as a row of `per_shot` frames (first to last), labelled with its name and the
    time; the plan on the right."""
    height = int(width * 9 / 16)
    rows = []
    font = _font(13)
    for shot in scene.shots:
        tiles = []
        for i in range(per_shot):
            t = shot.start + (shot.end - shot.start) * (i / max(per_shot - 1, 1)) * 0.999
            o, d = camera_rays(scene.camera(shot, t), width, height, device)
            tile = to_image(render(shapes_at(scene, t), o, d, width, height).image).convert("RGB")
            ImageDraw.Draw(tile).text((6, 4), f"{shot.name}  {t:.1f}s", fill=INK, font=font)
            tiles.append(tile)
        rows.append(tiles)
    gap = 6
    grid_w = per_shot * width + (per_shot - 1) * gap
    grid_h = len(rows) * height + (len(rows) - 1) * gap
    pl = plan(scene, size=max(360, min(560, grid_h)), device=device)
    sheet = Image.new("RGB", (grid_w + gap * 3 + pl.width, max(grid_h, pl.height) + 34), PANEL)
    g = ImageDraw.Draw(sheet)
    g.text(
        (gap, 8),
        f"{scene.name} — set: {scene.set.name} — {scene.length:.1f}s",
        fill=INK,
        font=_font(15),
    )
    for r, tiles in enumerate(rows):
        for c, tile in enumerate(tiles):
            sheet.paste(tile, (gap + c * (width + gap), 30 + r * (height + gap)))
    sheet.paste(pl, (grid_w + gap * 2, 30))
    return sheet


def save_video(frames: torch.Tensor, path: Path, fps: float) -> Path:
    """Frames `[N, H, W, 3]` as an H.264 mp4 (ffmpeg)."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("Saving a video needs ffmpeg on the PATH.")
    _, h, w, _ = frames.shape
    path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [
            ffmpeg,
            "-loglevel",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{w}x{h}",
            "-r",
            f"{fps}",
            "-i",
            "-",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            str(path),
        ],
        stdin=subprocess.PIPE,
    )
    assert proc.stdin is not None
    proc.stdin.write((frames.clamp(0, 1) * 255).round().byte().numpy().astype(np.uint8).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg couldn't write {path}.")
    return path
