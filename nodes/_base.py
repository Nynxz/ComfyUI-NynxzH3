"""The pack's identity, and the base class that saves every node repeating it.

Renaming the pack, or re-rooting where it sits in the node menu, is an edit to the two constants
below and nothing else — node ids, the menu category and the custom socket type all derive from
them.

**Node ids are a contract with every saved workflow**, which is why `make_schema` composes them
from `NAMESPACE` rather than letting each node write its own out in full: a rename can then never
leave half the ids behind, silently turning existing graphs into red "missing node" boxes.
"""

from __future__ import annotations

from comfy_api.latest import io

#: Node-id prefix — `H3Encode` becomes `nynxzh3.H3Encode`.
NAMESPACE = "nynxzh3"

#: Root menu category. Groups extend it: `CATEGORY = f"{CATEGORY}/Sampling"`.
CATEGORY = "Nynxz/H3"

#: The custom socket type the asset nodes chain through. Namespaced because ComfyUI matches
#: sockets on this string globally, so a bare "INPUT" would connect to other packs' wires.
WIRE_TYPE = f"{NAMESPACE.upper()}_INPUT"


class PackNode(io.ComfyNode):
    """Base for every node here. Build the schema with `make_schema`.

    Subclasses override `CATEGORY` to nest themselves in the menu; leave `NAMESPACE` alone so all
    ids share one prefix.
    """

    CATEGORY = CATEGORY

    @classmethod
    def make_schema(cls, node_id: str, display_name: str, **kwargs) -> io.Schema:
        return io.Schema(
            node_id=f"{NAMESPACE}.{node_id}",
            display_name=display_name,
            category=cls.CATEGORY,
            **kwargs,
        )


#: The id namespace H3 Studio, Grey Box and the H3 reference nodes shipped under, in NynxzNodes.
LEGACY_NAMESPACE = "nynxz"


class NynxzNode(io.ComfyNode):
    """Base for the nodes that moved here from NynxzNodes: their ids stay `nynxz.<id>`, because a
    saved workflow names a node by its id and these are already in workflows. Their menu category
    is the pack's."""

    NAMESPACE = LEGACY_NAMESPACE
    CATEGORY = "Nynxz"

    @classmethod
    def make_schema(cls, node_id: str, display_name: str, **kwargs) -> io.Schema:
        return io.Schema(
            node_id=f"{cls.NAMESPACE}.{node_id}",
            display_name=display_name,
            category=cls.CATEGORY,
            **kwargs,
        )
