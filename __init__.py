"""ComfyUI custom node pack — MiniMax H3.

    nodes/_base.py   the pack's namespace and menu category, and the node base class
    nodes/<group>/   the nodes, grouped by what they do to a run
    NODES            every node in the pack, listed below

The production side — **H3 Studio**, **Grey Box Studio** and the **Codex** — has a Vue frontend
built on ZenKit's nodekit into `web/` (`pnpm build`); the building-block nodes need none of it.
Those three moved here from NynxzNodes and keep their `nynxz.*` node ids and `/nynxz/...` routes,
so workflows and projects made there still open.

Adding a node is: write it, then add it to `NODES`. The list is deliberately explicit rather than
discovered by walking the tree — at this size a reader can see the whole pack in one screen, and a
node cannot go missing because a file was named wrong.
"""

from comfy_api.latest import ComfyExtension, io

# The production side. Importing these packages also registers their routes
# (/nynxz/h3studio/*, /nynxz/greybox/*).
from .nodes import _zenkit
from .nodes.assets.node import H3Audio, H3Image, H3Video
from .nodes.canvas.node import H3Canvas
from .nodes.edit.node import H3Edit
from .nodes.encode.node import H3Encode
from .nodes.extras.node import H3Extras
from .nodes.greybox.greybox import NynxzGreyBoxRender, NynxzGreyBoxShot, NynxzGreyBoxStudio
from .nodes.h3.cache import H3BlockCache
from .nodes.h3.decode import H3DecodeFrames
from .nodes.h3.depthskip import H3DepthSkip
from .nodes.h3.isolate import H3ReferenceIsolate
from .nodes.h3.rowchunk import H3RowChunk
from .nodes.h3.schedule import H3DetailSchedule
from .nodes.h3.scheduled import H3ScheduledSampler
from .nodes.h3.slice import H3LatentSlice
from .nodes.h3.window import H3SlidingWindow
from .nodes.h3studio.studio import (
    NynxzH3Studio,
    NynxzH3StudioClip,
    NynxzH3StudioFilm,
    NynxzH3StudioJoin,
    NynxzH3StudioOutputs,
    NynxzH3StudioScenes,
    NynxzH3StudioSetup,
)
from .nodes.inputs.node import H3Inputs
from .nodes.references.encode import NynxzH3ReferenceToVideo
from .nodes.references.moodboard import NynxzH3MoodBoard
from .nodes.references.reference import NynxzH3Reference
from .nodes.rewrite.node import H3ClipLora, H3RewriteClean, H3RewritePrompt

#: The built Vue frontend (H3 Studio, Grey Box Studio, the Codex), served at /extensions/<pack>/.
WEB_DIRECTORY = "./web"

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
    # Prompt — what the request becomes before any of the above.
    H3Edit,
    H3RewritePrompt,
    H3RewriteClean,
    H3ClipLora,
    # Sampling — what a step costs.
    H3BlockCache,
    H3DepthSkip,
    H3DetailSchedule,
    H3ScheduledSampler,
    # Sequence-length work — experimental, and only bites on longer clips.
    H3RowChunk,
    H3SlidingWindow,
    H3ReferenceIsolate,
    # Latent — what comes back out.
    H3DecodeFrames,
    H3LatentSlice,
    # Production — a film planned, blocked and rendered (ids kept from NynxzNodes: nynxz.*).
    NynxzH3StudioSetup,
    NynxzH3Studio,
    NynxzH3StudioOutputs,
    NynxzH3StudioScenes,
    NynxzH3StudioClip,
    NynxzH3StudioFilm,
    NynxzH3StudioJoin,
    NynxzGreyBoxRender,
    NynxzGreyBoxShot,
    NynxzGreyBoxStudio,
    # Reference conditioning from NynxzNodes (ids kept: nynxz.H3.*).
    NynxzH3Reference,
    NynxzH3MoodBoard,
    NynxzH3ReferenceToVideo,
]


class PackExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        # The media routes the frontend's picker and thumbnails call (/nynxzh3/media).
        _zenkit.setup()
        return NODES


async def comfy_entrypoint() -> ComfyExtension:
    return PackExtension()


__all__ = ["NODES", "WEB_DIRECTORY", "PackExtension", "comfy_entrypoint"]
