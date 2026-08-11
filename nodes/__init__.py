"""The nodes, grouped by what they do to a run.

    _base.py    the pack's namespace and menu category, and the `PackNode` base class
    inputs/     the wire the asset nodes speak — a socket type and a payload, no node of its own
    assets/     H3 Image / H3 Video / H3 Audio
    encode/     H3 Encode
    extras/     H3 Extras
    h3/         the model side — Block Cache, Depth Skip, Detail Schedule, Decode Frames, Slice

A module named `_something.py` holds the logic its node is thin over, so the reasoning has
somewhere to live that is not a schema definition. Adding a node is: write it, then add it to
`NODES` in the pack's `__init__.py`.
"""
