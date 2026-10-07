"""Rendering grey box shapes: exact ray-shape intersection (no meshes, no marching), in torch, so
it runs on the GPU in ComfyUI and on the CPU for an agent's quick look.

Each pixel's ray finds the nearest shape; it's shaded by one soft key light (with shadows) and a
sky fill, so form and depth read in plain grey. Edges between objects get a thin dark line, the
way grey-box renders usually look. Besides the picture: linear depth, and which object each pixel
shows (for per-character masks).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch

from .scene import Camera, Shape, Vec

BACKGROUND = 0.14
LIGHT = (0.45, 0.85, 0.3)
AMBIENT = 0.42
EPS = 1e-4


@dataclass
class Frame:
    image: torch.Tensor  # [H, W, 3] in 0..1
    depth: torch.Tensor  # [H, W] metres; inf where nothing is hit
    owner: torch.Tensor  # [H, W] long: index into `owners`, -1 for nothing
    owners: list[str]


def _norm(v: torch.Tensor) -> torch.Tensor:
    return v / v.norm(dim=-1, keepdim=True).clamp(min=1e-9)


def camera_rays(cam: Camera, width: int, height: int, device) -> tuple[torch.Tensor, torch.Tensor]:
    """One ray per pixel centre: origins `[P, 3]` and directions `[P, 3]`."""
    eye = torch.tensor(cam.at, device=device, dtype=torch.float32)
    look = torch.tensor(cam.look, device=device, dtype=torch.float32)
    fwd = _norm(look - eye)
    up_world = torch.tensor((0.0, 1.0, 0.0), device=device)
    if abs(float(fwd[1])) > 0.999:  # looking straight up or down
        up_world = torch.tensor((0.0, 0.0, -1.0), device=device)
    right = _norm(torch.linalg.cross(fwd, up_world))
    up = torch.linalg.cross(right, fwd)
    half = math.tan(math.radians(cam.fov) / 2)
    ys = (1 - (torch.arange(height, device=device) + 0.5) / height * 2) * half
    xs = ((torch.arange(width, device=device) + 0.5) / width * 2 - 1) * half * width / height
    gy, gx = torch.meshgrid(ys, xs, indexing="ij")
    d = _norm(fwd + gx.reshape(-1, 1) * right + gy.reshape(-1, 1) * up)
    return eye.expand_as(d), d


def plan_rays(
    lo: tuple[float, float], hi: tuple[float, float], width: int, height: int, device
) -> tuple[torch.Tensor, torch.Tensor]:
    """Straight down over the floor rectangle lo..hi (x, z): a plan view. Top of the image is -z."""
    xs = lo[0] + (torch.arange(width, device=device) + 0.5) / width * (hi[0] - lo[0])
    zs = lo[1] + (torch.arange(height, device=device) + 0.5) / height * (hi[1] - lo[1])
    gz, gx = torch.meshgrid(zs, xs, indexing="ij")
    o = torch.stack([gx.reshape(-1), torch.full_like(gx.reshape(-1), 50.0), gz.reshape(-1)], -1)
    d = torch.tensor((0.0, -1.0, 0.0), device=device).expand_as(o)
    return o, d


# --- intersections: each gives the hit distance (inf for a miss) and the surface normal ---------


def _box(o, d, s: Shape):
    c = torch.tensor(s.at, device=o.device)
    yaw = math.radians(s.yaw)
    cy, sy = math.cos(yaw), math.sin(yaw)
    # Into the box's own frame (its yaw undone).
    rot = torch.tensor(((cy, 0.0, -sy), (0.0, 1.0, 0.0), (sy, 0.0, cy)), device=o.device)
    lo_ = (o - c) @ rot.T
    ld = d @ rot.T
    half = torch.tensor(s.size, device=o.device) / 2
    inv = 1.0 / torch.where(ld.abs() < 1e-9, torch.full_like(ld, 1e-9), ld)
    t1 = (-half - lo_) * inv
    t2 = (half - lo_) * inv
    tmin = torch.minimum(t1, t2)
    tmax = torch.maximum(t1, t2)
    tn = tmin.max(dim=-1).values
    tf = tmax.min(dim=-1).values
    hit = (tn <= tf) & (tf > EPS)
    t = torch.where(tn > EPS, tn, tf)
    t = torch.where(hit, t, torch.full_like(t, math.inf))
    axis = tmin.argmax(dim=-1)
    n_local = torch.zeros_like(lo_)
    n_local.scatter_(1, axis.unsqueeze(1), (-torch.sign(ld.gather(1, axis.unsqueeze(1)))))
    return t, n_local @ rot


def _sphere(o, d, s: Shape):
    c = torch.tensor(s.at, device=o.device)
    oc = o - c
    b = (oc * d).sum(-1)
    k = (oc * oc).sum(-1) - s.radius * s.radius
    disc = b * b - k
    sq = disc.clamp(min=0).sqrt()
    t = -b - sq
    t = torch.where(t > EPS, t, -b + sq)
    t = torch.where((disc >= 0) & (t > EPS), t, torch.full_like(t, math.inf))
    return t, _norm(o + d * t.unsqueeze(-1).nan_to_num(0, 0, 0) - c)


def _capsule(o, d, s: Shape):
    a = torch.tensor(s.a, device=o.device)
    b = torch.tensor(s.b, device=o.device)
    r = s.radius
    ba = b - a
    oa = o - a
    baba = float((ba * ba).sum())
    bard = (d * ba).sum(-1)
    baoa = (oa * ba).sum(-1)
    rdoa = (d * oa).sum(-1)
    oaoa = (oa * oa).sum(-1)
    qa = baba - bard * bard
    qb = baba * rdoa - baoa * bard
    qc = baba * oaoa - baoa * baoa - r * r * baba
    h = qb * qb - qa * qc
    tc = (-qb - h.clamp(min=0).sqrt()) / torch.where(qa.abs() < 1e-9, torch.full_like(qa, 1e-9), qa)
    y = baoa + tc * bard
    body = (h >= 0) & (y > 0) & (y < baba) & (tc > EPS)
    # The end caps: spheres at a or b.
    oc = torch.where((y <= 0).unsqueeze(-1), oa, o - b)
    bb = (d * oc).sum(-1)
    cc = (oc * oc).sum(-1) - r * r
    hh = bb * bb - cc
    tcap = -bb - hh.clamp(min=0).sqrt()
    cap = (hh > 0) & (tcap > EPS) & ~body
    t = torch.where(body, tc, torch.where(cap, tcap, torch.full_like(tc, math.inf)))
    p = o + d * t.unsqueeze(-1).nan_to_num(0, 0, 0)
    pa = p - a
    h2 = ((pa * ba).sum(-1) / baba).clamp(0, 1)
    n = _norm(pa - ba * h2.unsqueeze(-1))
    return t, n


def _cylinder(o, d, s: Shape):
    """Upright, standing on `at`, `height` tall: a side and two flat ends."""
    cx, cy0, cz = s.at
    r = s.radius
    ox, oz = o[:, 0] - cx, o[:, 2] - cz
    dx, dz = d[:, 0], d[:, 2]
    qa = dx * dx + dz * dz
    qb = ox * dx + oz * dz
    qc = ox * ox + oz * oz - r * r
    disc = qb * qb - qa * qc
    safe = torch.where(qa < 1e-12, torch.full_like(qa, 1e-12), qa)
    ts = (-qb - disc.clamp(min=0).sqrt()) / safe
    ys = o[:, 1] + d[:, 1] * ts
    side = (disc >= 0) & (qa > 1e-12) & (ts > EPS) & (ys >= cy0) & (ys <= cy0 + s.height)
    t = torch.where(side, ts, torch.full_like(ts, math.inf))
    n = torch.stack([ox + dx * ts, torch.zeros_like(ts), oz + dz * ts], -1) / r
    for y_plane, ny in ((cy0 + s.height, 1.0), (cy0, -1.0)):
        dy = torch.where(d[:, 1].abs() < 1e-9, torch.full_like(d[:, 1], 1e-9), d[:, 1])
        tp = (y_plane - o[:, 1]) / dy
        px, pz = ox + dx * tp, oz + dz * tp
        cap = (tp > EPS) & (px * px + pz * pz <= r * r) & (tp < t)
        t = torch.where(cap, tp, t)
        n = torch.where(
            cap.unsqueeze(-1), torch.tensor((0.0, ny, 0.0), device=o.device).expand_as(n), n
        )
    return t, n


_HIT = {"box": _box, "sphere": _sphere, "capsule": _capsule, "cylinder": _cylinder}


def trace(o: torch.Tensor, d: torch.Tensor, shapes: list[Shape]):
    """The nearest hit of each ray among `shapes`: distance, normal and the shape's index."""
    best = torch.full(o.shape[:1], math.inf, device=o.device)
    normal = torch.zeros_like(o)
    which = torch.full(o.shape[:1], -1, dtype=torch.long, device=o.device)
    for i, s in enumerate(shapes):
        t, n = _HIT[s.kind](o, d, s)
        closer = t < best
        best = torch.where(closer, t, best)
        normal = torch.where(closer.unsqueeze(-1), n, normal)
        which = torch.where(closer, torch.full_like(which, i), which)
    return best, normal, which


def _shadowed(p: torch.Tensor, shapes: list[Shape]) -> torch.Tensor:
    light = _norm(torch.tensor(LIGHT, device=p.device)).expand_as(p)
    t, _, _ = trace(p, light, shapes)
    return torch.isfinite(t)


def render(
    shapes: list[Shape],
    o: torch.Tensor,
    d: torch.Tensor,
    width: int,
    height: int,
    *,
    shadows: bool = True,
    edges: bool = True,
    fog: float = 0.012,
) -> Frame:
    """Shade what each ray hits. `o`, `d`: `[H·W, 3]` rays (from `camera_rays` or `plan_rays`)."""
    dev = o.device
    t, n, which = trace(o, d, shapes)
    hit = torch.isfinite(t)
    # Normals face the camera (a ray can start inside a shape: a camera behind a wall).
    n = torch.where(((n * d).sum(-1) > 0).unsqueeze(-1), -n, n)
    light = _norm(torch.tensor(LIGHT, device=dev))
    lambert = (n @ light).clamp(min=0)
    sky = 0.5 + 0.5 * n[:, 1]
    tones = torch.tensor([s.tone for s in shapes] + [0.0], device=dev)
    tone = tones[which.clamp(min=0)]
    lit = lambert
    if shadows and hit.any():
        p = o + d * t.nan_to_num(0, 0, 0).unsqueeze(-1) + n * 2e-3
        shade = torch.zeros_like(t, dtype=torch.bool)
        shade[hit] = _shadowed(p[hit], shapes)
        lit = torch.where(shade, lit * 0.25, lit)
    value = tone * (AMBIENT * (0.6 + 0.4 * sky) + (1 - AMBIENT) * lit)
    if fog > 0:
        f = torch.exp(-fog * t.nan_to_num(0, 0, 0))
        value = value * f + BACKGROUND * (1 - f)
    value = torch.where(hit, value, torch.full_like(value, BACKGROUND))
    img = value.view(height, width)
    owners = sorted({s.owner or f"shape{i}" for i, s in enumerate(shapes)})
    index = {name: i for i, name in enumerate(owners)}
    shape_owner = torch.tensor(
        [index[s.owner or f"shape{i}"] for i, s in enumerate(shapes)] + [-1], device=dev
    )
    owner = torch.where(hit, shape_owner[which.clamp(min=0)], torch.full_like(which, -1)).view(
        height, width
    )
    depth = torch.where(hit, t, torch.full_like(t, math.inf)).view(height, width)
    if edges:
        img = _edges(img, depth, owner)
    return Frame(
        img.clamp(0, 1).unsqueeze(-1).expand(height, width, 3).contiguous(), depth, owner, owners
    )


def _edges(img: torch.Tensor, depth: torch.Tensor, owner: torch.Tensor) -> torch.Tensor:
    """A thin dark line where one object meets another, or the depth jumps."""
    edge = torch.zeros_like(img, dtype=torch.bool)
    finite = torch.where(torch.isfinite(depth), depth, torch.full_like(depth, 1e4))
    for dy, dx in ((0, 1), (1, 0)):
        a_o, b_o = owner[: owner.shape[0] - dy, : owner.shape[1] - dx], owner[dy:, dx:]
        a_d, b_d = finite[: owner.shape[0] - dy, : owner.shape[1] - dx], finite[dy:, dx:]
        jump = (a_o != b_o) | ((a_d - b_d).abs() > 0.06 * torch.minimum(a_d, b_d).clamp(min=0.5))
        edge[: owner.shape[0] - dy, : owner.shape[1] - dx] |= jump
    return torch.where(edge, img * 0.45, img)


def depth_image(
    depth: torch.Tensor, near: float | None = None, far: float | None = None
) -> torch.Tensor:
    """Depth as a picture: near is white, far is black (nothing hit is black). `[H, W, 3]`."""
    finite = depth[torch.isfinite(depth)]
    if finite.numel() == 0:
        return torch.zeros(*depth.shape, 3, device=depth.device)
    lo = near if near is not None else float(finite.min())
    hi = (
        far
        if far is not None
        else float(finite.quantile(0.98))
        if finite.numel() < 16_000_000
        else float(finite.max())
    )
    v = 1 - ((depth - lo) / max(hi - lo, 1e-6)).clamp(0, 1)
    v = torch.where(torch.isfinite(depth), v, torch.zeros_like(v))
    return v.unsqueeze(-1).expand(*depth.shape, 3).contiguous()


def bounds(
    shapes: list[Shape], extra: list[Vec] = ()
) -> tuple[tuple[float, float], tuple[float, float]]:
    """The floor rectangle (x, z) everything sits in, with a margin."""
    xs, zs = [], []
    for s in shapes:
        if s.kind == "box":
            r = math.hypot(s.size[0], s.size[2]) / 2
            xs += [s.at[0] - r, s.at[0] + r]
            zs += [s.at[2] - r, s.at[2] + r]
        elif s.kind == "capsule":
            xs += [s.a[0] - s.radius, s.b[0] + s.radius, s.a[0] + s.radius, s.b[0] - s.radius]
            zs += [s.a[2] - s.radius, s.b[2] + s.radius, s.a[2] + s.radius, s.b[2] - s.radius]
        else:
            xs += [s.at[0] - s.radius, s.at[0] + s.radius]
            zs += [s.at[2] - s.radius, s.at[2] + s.radius]
    for p in extra:
        xs.append(p[0])
        zs.append(p[2])
    if not xs:
        return (-5.0, -5.0), (5.0, 5.0)
    pad = 0.6
    return (min(xs) - pad, min(zs) - pad), (max(xs) + pad, max(zs) + pad)
