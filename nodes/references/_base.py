"""Shared base for the MiniMax H3 group — the menu category, in one place."""

from __future__ import annotations

from .._base import NynxzNode


class H3Node(NynxzNode):
    """MiniMax H3 reference conditioning."""

    CATEGORY = f"{NynxzNode.CATEGORY}/H3"
