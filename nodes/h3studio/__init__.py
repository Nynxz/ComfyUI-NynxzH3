"""H3 Studio — plan a MiniMax H3 film on a timeline and render it scene by scene.

Importing `api` registers the /nynxz/h3studio/* route the editor's live preview calls. Node classes
are found by discovery from the modules that define them, so this file does not re-export them.
"""

from . import api  # noqa: F401  (registers /nynxz/h3studio/* routes on import)
