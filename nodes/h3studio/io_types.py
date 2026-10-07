"""IO types for H3 Studio.

- ``NYNXZ_H3_STUDIO_SETUP`` / ``NYNXZ_H3_STUDIO_RENDER`` — the wires to and from the breakout nodes,
  which keep the studio's own header to one input and one output.
- ``NYNXZ_H3_STUDIO`` — the socketless on-node WIDGET (frontend/widgets/H3Studio.vue) holding the
  whole project document. See `_project.py` for its shape.
"""

from __future__ import annotations

from comfy_api.latest import io

from .._zenkit.io_types import widget_type

#: H3 Studio Setup -> H3 Studio: the models and the previous scene, on one wire.
H3StudioSetupType = io.Custom("NYNXZ_H3_STUDIO_SETUP")
#: H3 Studio -> H3 Studio Outputs: everything a rendered scene produces, on one wire.
H3StudioRenderType = io.Custom("NYNXZ_H3_STUDIO_RENDER")

H3StudioType = widget_type(
    "H3Studio",
    dict,
    doc="On-node H3 Studio WIDGET value (socketless): the project document.",
)

H3StudioLinkType = widget_type(
    "H3StudioLink",
    dict,
    doc="On-node H3 Studio Scenes WIDGET value: `{studio, count}` — the studio it follows (its node "
    "id) and that studio's scene count, kept in step by the widget.",
)
