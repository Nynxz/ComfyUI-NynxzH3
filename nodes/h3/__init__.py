"""The model side — what a step costs, and how much of the result you have to decode.

The rest of this pack is conditioning: what the model is *told*. This folder is the other side.

H3 is a **single-stream packed DiT**: text, reference blocks, audio and video all in one sequence
and one dense self-attention, 50 layers deep, with `mask=None` on every block. Everything attends
to everything, every step. A real profile came back **compute-bound** — the whole model resident,
306 TFLOP/s achieved, blocks holding 99.5% of the forward — so the memory-side toolkit buys
nothing here. The only thing that buys time is **issuing less arithmetic**:

    steps       cache.py       Block Cache measures block 0's residual drift and skips blocks
                               1..49 when it is small. 80s -> 30s on a real clip at aggressive
                               settings, and the best-evidenced node in the pack.
    depth       depthskip.py   Depth Skip drops named blocks outright. Two independent
                               measurements with opposite biases agree that blocks 3-17 carry
                               ~1.3% of residual movement; this is the instrument for acting on
                               that, and it decides nothing on its own.
    schedule    schedule.py    Detail Schedule budgets the refinement phase separately from the
                               structure phase, without changing the shift curve.
    budget      scheduled.py   Scheduled Sampler decides what each step is worth and tells the
                               other three, which until now could not see each other.

**Why the fourth one exists.** The first three answer overlapping questions in four different
coordinate systems — sigma, denoise-percent, log-sigma and log-SNR — and the disagreements are
not cosmetic. Block Cache's window is a percentage resolved on the model's *unsplit* curve, so a
split schedule silently moves it: at `detail_steps` 16 the default excludes ten of thirty-one
steps, all refinement. And the steps are nothing like equal — four of a 15/8 split's twenty-two
carry 97% of its local truncation error, the smallest twelve carry 0.07% — so effort spread evenly
across them is almost entirely spent where it cannot matter. `_plan.py` is the one place that
converts between the coordinates and hands out a single per-step budget; `_scheduled.py` runs it
and publishes it where the block patches can read it.

**The distinction the whole group turns on.** Step density, integration order and how much of the
stack runs all converge on the *same* answer, the exact solution of the model's own ODE. Buying
more of any of them buys fidelity to that answer — cleaner, more converged, sometimes flatter. The
only lever that changes *which* answer you get is stochasticity, which is why `detail_eta` is
banded separately and kept out of the error budget entirely.

Coming back out:

    decode.py   one frame costs at most two chunk decodes, because the VAE decodes in overlapping
                17-frame chunks and a frame depends on at most two of them.
    slice.py    the cheap, general half of the same idea: plain slicing on the token axis.

**The 5-frame floor is a VAE chunk, not a duration choice.** `time_down=(1,2,2,1,1,1)` gives 4x
temporal compression and `clip_length=17`, so the encoder atom is 17 pixel frames -> `ceil(17/4)`
= 5 latent tokens, of which `token_drop=3` discards three. 3 x 4 = 12, and 17 - 12 = 5. So
`n % 17 == 5` is just `17k - 12`, and `video_latent_t` is exactly `5*ceil(n/17) - 3`. A
consequence worth knowing: the DiT never sees 24 fps — it works on 7.06 tokens per second, and
everything between them is the decoder's invention.

`_h3.py` and `_patch.py` are the shared seam onto ComfyUI's H3 model — locating the DiT and
installing block patches. They are **duplicated in ComfyUI-NynxzVideo rather than shared**,
because a cross-pack import would make one pack fail to load without the other.
"""
