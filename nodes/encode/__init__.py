"""H3 Encode — the three MiniMax H3 conditioning tasks behind one node.

    node.py     the node — schema + execute. This is what discovery looks for.
    _encode.py  task selection and the two presentations, kept out of the node so the rule
                that t2va / fl2va / ref2va are mutually exclusive has somewhere to be explained
    _core.py    the seam onto ComfyUI's own H3 helpers (latent geometry, canvas, audio VAE)

No frontend: every input is a plain widget or a wire, so there is nothing to draw.
"""
