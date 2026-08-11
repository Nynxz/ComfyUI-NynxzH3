"""ComfyUI custom node pack — MiniMax H3.

    nodes/_base.py   the pack's namespace and menu category, and the node base class
    nodes/<group>/   the nodes, grouped by what they do to a run
    NODES            every node in the pack, listed below

**No frontend and no build step.** Every node is a model passthrough, a conditioning builder or a
text report, so there is nothing to draw and nothing to compile — drop the folder in
`custom_nodes/` and restart.

Adding a node is: write it, then add it to `NODES`. The list is deliberately explicit rather than
discovered by walking the tree — at this size a reader can see the whole pack in one screen, and a
node cannot go missing because a file was named wrong.
"""

from comfy_api.latest import ComfyExtension, io

from .nodes.assets.node import H3Audio, H3Image, H3Video
from .nodes.canvas.node import H3Canvas
from .nodes.encode.node import H3Encode
from .nodes.extras.node import H3Extras
from .nodes.h3.cache import H3BlockCache
from .nodes.h3.decode import H3DecodeFrames
from .nodes.h3.depthskip import H3DepthSkip
from .nodes.h3.isolate import H3ReferenceIsolate
from .nodes.h3.rowchunk import H3RowChunk
from .nodes.h3.schedule import H3DetailSchedule
from .nodes.h3.slice import H3LatentSlice
from .nodes.h3.window import H3SlidingWindow
from .nodes.inputs.node import H3Inputs

#: Every node this pack registers.
NODES: list[type[io.ComfyNode]] = [
    # Conditioning — what the model is told.
    H3Canvas,
    H3Inputs,
    H3Image,
    H3Video,
    H3Audio,
    H3Encode,
    H3Extras,
    # Sampling — what a step costs.
    H3BlockCache,
    H3DepthSkip,
    H3DetailSchedule,
    # Sequence-length work — experimental, and only bites on longer clips.
    H3RowChunk,
    H3SlidingWindow,
    H3ReferenceIsolate,
    # Latent — what comes back out.
    H3DecodeFrames,
    H3LatentSlice,
]


class PackExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return NODES


async def comfy_entrypoint() -> ComfyExtension:
    return PackExtension()


__all__ = ["NODES", "PackExtension", "comfy_entrypoint"]
