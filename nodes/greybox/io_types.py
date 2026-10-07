"""IO types for grey box.

- ``NYNXZ_GREY_BOX_STUDIO`` — the Grey Box Studio editor WIDGET (frontend/widgets/GreyBoxStudio.vue):
  which project, scene and shot the node renders. The scene itself lives in its files.
"""

from __future__ import annotations

from .._zenkit.io_types import widget_type

GreyBoxStudioType = widget_type(
    "GreyBoxStudio",
    dict,
    doc="On-node Grey Box Studio WIDGET value: {project, scene, shot}.",
)
