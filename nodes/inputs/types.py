"""The wire type the H3 nodes pass assets along.

`NYNXZH3_INPUT` carries `{version, items, canvas}` (see `_payload.py`). No frontend widget is
registered for it, so ComfyUI renders it as an ordinary socket, and the asset nodes chain through
it in either direction — items concatenate upstream-first, and the canvas is whichever node is
nearest the encode.

`items` are loaded tensors: large, and never serialized with the graph. That is why the asset
nodes take sockets rather than file pickers — content that only exists mid-graph has no file to
point at.
"""

from __future__ import annotations

from comfy_api.latest import io

from .._base import WIRE_TYPE

#: Wire type carrying assets + canvas between the H3 nodes.
H3InputData = io.Custom(WIRE_TYPE)
