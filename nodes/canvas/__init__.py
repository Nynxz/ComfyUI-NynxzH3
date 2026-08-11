"""H3 Canvas — the size and duration numbers, worked out rather than remembered.

    node.py  the node. Three ints out, into H3 Encode's width / height / length.

This is what survives of two things that are gone: the aspect chips and length slider on the old
H3 Inputs widget, and the H3 Canvas Override node from the regenerate pair. Both existed because
H3's shape rules are specific and not guessable — 16:9 is 1344x768 and not 1920x1080, and asking
for 130 frames gets you 141. Neither needed a frontend to say so.

All three rules come from ComfyUI's own H3 helpers rather than being restated here, which is the
point: `adapt_canvas` picks the canvas the model itself would pick for an aspect ratio,
`scale_canvas` moves it while keeping the aspect (the thing rope registration actually depends
on), and `temporal_shape` snaps a length onto the `17k+5` grid. If a ComfyUI release adjusts any
of them, this follows.
"""
