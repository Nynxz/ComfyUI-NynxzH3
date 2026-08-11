"""The wire the asset nodes speak, and nothing else.

    types.py     `H3InputData` — the `NYNXZH3_INPUT` socket type
    _payload.py  the wire value: `{version, items, canvas}`, and the canvas coercion
    _rows.py     roles, reference sizes, and the ordinal rule the prompt tags follow
    _assets.py   24 fps resampling for wired IMAGE batches

**This folder registers no node**, and that is deliberate rather than an oversight: discovery
imports a folder's `node.py` if it has one, so a folder without one contributes only its modules.
The nodes that use these live in `nodes/assets/`, `nodes/encode/` and `nodes/extras/`.

**Ordinals are positional, per type**, and getting them wrong is invisible in the graph: a
reference's prompt tag is `<Picture 1>` / `<Video 1>` / `<Audio 1>`, numbered within its own kind
in wire order. `ordinals()` is the authority and `tests/test_inputs.py` pins it, including that
regrouping by type must not renumber anything — a prompt written against the tag a node reported
has to keep pointing at the same asset afterwards.
"""
