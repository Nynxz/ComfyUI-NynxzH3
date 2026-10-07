"""A scene at one moment as a .glb: every shape a named mesh in its own grey, for looking around
it in any 3D viewer (ComfyUI's Load 3D, Blender). Y is up, metres — glTF's own convention.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path

import numpy as np

from .scene import Scene, Shape, shapes_at

SEGMENTS = 24


def _box(s: Shape):
    hx, hy, hz = (v / 2 for v in s.size)
    faces = [
        ((1, 0, 0), [(hx, -hy, -hz), (hx, hy, -hz), (hx, hy, hz), (hx, -hy, hz)]),
        ((-1, 0, 0), [(-hx, -hy, hz), (-hx, hy, hz), (-hx, hy, -hz), (-hx, -hy, -hz)]),
        ((0, 1, 0), [(-hx, hy, -hz), (-hx, hy, hz), (hx, hy, hz), (hx, hy, -hz)]),
        ((0, -1, 0), [(-hx, -hy, hz), (-hx, -hy, -hz), (hx, -hy, -hz), (hx, -hy, hz)]),
        ((0, 0, 1), [(hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz), (-hx, -hy, hz)]),
        ((0, 0, -1), [(-hx, -hy, -hz), (-hx, hy, -hz), (hx, hy, -hz), (hx, -hy, -hz)]),
    ]
    pos, nor, idx = [], [], []
    for n, quad in faces:
        base = len(pos)
        pos += quad
        nor += [n] * 4
        idx += [base, base + 1, base + 2, base, base + 2, base + 3]
    pos, nor = np.array(pos, np.float32), np.array(nor, np.float32)
    yaw = math.radians(s.yaw)
    c, si = math.cos(yaw), math.sin(yaw)
    rot = np.array(((c, 0, si), (0, 1, 0), (-si, 0, c)), np.float32)
    return pos @ rot.T + np.array(s.at, np.float32), nor @ rot.T, idx


def _sphere_mesh(center, r, rings=12, segs=SEGMENTS):
    pos, nor, idx = [], [], []
    for i in range(rings + 1):
        v = math.pi * i / rings
        for j in range(segs + 1):
            u = 2 * math.pi * j / segs
            n = (math.sin(v) * math.cos(u), math.cos(v), math.sin(v) * math.sin(u))
            nor.append(n)
            pos.append(tuple(center[k] + r * n[k] for k in range(3)))
    for i in range(rings):
        for j in range(segs):
            a = i * (segs + 1) + j
            b = a + segs + 1
            idx += [a, a + 1, b, a + 1, b + 1, b]
    return np.array(pos, np.float32), np.array(nor, np.float32), idx


def _tube(a, b, r, caps: bool, segs=SEGMENTS):
    """A cylinder from `a` to `b` (flat ends when `caps`)."""
    a, b = np.array(a, np.float32), np.array(b, np.float32)
    axis = b - a
    length = float(np.linalg.norm(axis)) or 1e-6
    w = axis / length
    helper = np.array((1, 0, 0), np.float32) if abs(w[0]) < 0.9 else np.array((0, 0, 1), np.float32)
    u = np.cross(w, helper)
    u /= np.linalg.norm(u)
    v = np.cross(w, u)
    pos, nor, idx = [], [], []
    for j in range(segs + 1):
        ang = 2 * math.pi * j / segs
        n = u * math.cos(ang) + v * math.sin(ang)
        pos += [a + n * r, b + n * r]
        nor += [n, n]
    for j in range(segs):
        k = 2 * j
        idx += [k, k + 2, k + 1, k + 1, k + 2, k + 3]
    if caps:
        for end, n in ((a, -w), (b, w)):
            centre = len(pos)
            pos.append(end)
            nor.append(n)
            ring = len(pos)
            for j in range(segs + 1):
                ang = 2 * math.pi * j / segs
                pos.append(end + (u * math.cos(ang) + v * math.sin(ang)) * r)
                nor.append(n)
            for j in range(segs):
                idx += (
                    [centre, ring + j, ring + j + 1]
                    if n @ w > 0
                    else [centre, ring + j + 1, ring + j]
                )
    return np.array(pos, np.float32), np.array(nor, np.float32), idx


def _mesh(s: Shape):
    if s.kind == "box":
        return _box(s)
    if s.kind == "sphere":
        return _sphere_mesh(s.at, s.radius)
    if s.kind == "cylinder":
        x, y, z = s.at
        return _tube((x, y, z), (x, y + s.height, z), s.radius, caps=True)
    parts = [
        _tube(s.a, s.b, s.radius, caps=False),
        _sphere_mesh(s.a, s.radius),
        _sphere_mesh(s.b, s.radius),
    ]
    pos, nor, idx = [], [], []
    for p, n, i in parts:
        base = sum(len(x) for x in pos)
        pos.append(p)
        nor.append(n)
        idx += [base + k for k in i]
    return np.concatenate(pos), np.concatenate(nor), idx


def export(scene: Scene, path: Path, t: float = 0.0) -> Path:
    """The scene at `t` as a binary glTF."""
    shapes = shapes_at(scene, t)
    blob = bytearray()
    views, accessors, meshes, nodes, materials = [], [], [], [], []
    tones: dict[float, int] = {}

    def view(data: bytes, target: int) -> int:
        while len(blob) % 4:
            blob.append(0)
        views.append(
            {"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), "target": target}
        )
        blob.extend(data)
        return len(views) - 1

    for i, s in enumerate(shapes):
        pos, nor, idx = _mesh(s)
        tone = round(s.tone, 3)
        if tone not in tones:
            tones[tone] = len(materials)
            materials.append(
                {
                    "pbrMetallicRoughness": {
                        "baseColorFactor": [tone, tone, tone, 1],
                        "metallicFactor": 0,
                        "roughnessFactor": 0.9,
                    }
                }
            )
        pv = view(pos.astype(np.float32).tobytes(), 34962)
        nv = view(nor.astype(np.float32).tobytes(), 34962)
        iv = view(np.array(idx, np.uint32).tobytes(), 34963)
        accessors += [
            {
                "bufferView": pv,
                "componentType": 5126,
                "count": len(pos),
                "type": "VEC3",
                "min": pos.min(0).tolist(),
                "max": pos.max(0).tolist(),
            },
            {"bufferView": nv, "componentType": 5126, "count": len(nor), "type": "VEC3"},
            {"bufferView": iv, "componentType": 5125, "count": len(idx), "type": "SCALAR"},
        ]
        a = len(accessors) - 3
        meshes.append(
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": a, "NORMAL": a + 1},
                        "indices": a + 2,
                        "material": tones[tone],
                    }
                ]
            }
        )
        nodes.append({"mesh": len(meshes) - 1, "name": s.id or s.owner or f"{s.kind}{i}"})
    doc = {
        "asset": {"version": "2.0", "generator": "NynxzH3 grey box"},
        "scene": 0,
        "scenes": [{"name": scene.name, "nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(blob)}],
    }
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    while len(blob) % 4:
        blob.append(0)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob)))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(blob), 0x004E4942) + bytes(blob))
    return path
