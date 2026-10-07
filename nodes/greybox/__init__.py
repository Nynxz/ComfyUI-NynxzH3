"""Grey box — simple 3D blocking for shots, rendered as grey video for MiniMax H3 to follow.

`core/` is the format, the renderer and the contact sheet (no ComfyUI); `greybox.py` the node;
`cli.py` the command line agents use to look at a scene while they build it. docs/GREYBOX.md.
"""

from . import api  # noqa: F401  (registers /nynxz/greybox/* routes on import)
