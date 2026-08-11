"""Cutting the reference prefix out of the denoising target's attention.

H3 packs `[text | references | target audio | target video]` into one sequence and attends over
all of it densely. The references sit in a **contiguous prefix**, and two facts about them make
that prefix special:

  * **Their timestep never moves.** `seg_t["cond"]` and `seg_t["ref_img"]` are `max(t_v, 0.999)`
    and reference audio is pinned at `1.0` (`comfy/ldm/minimax/model.py:538-540`). Sampling runs
    `t_v` from 0 to 1, so `max` holds at the pin until sigma drops under 0.001 — which is to say
    for the entire run. Their adaLN modulation is a constant.
  * **Nothing reads their output.** `final_layer` slices only the target audio and video segments
    (`model.py:634-636`). A prefix row's hidden state matters *only* as key and value for the
    rows that come after it.

So the prefix drifts across steps for exactly one reason: attention lets it read the noisy target.
Cut that edge and the prefix becomes a pure function of `[text | references]` — the same at every
step, by construction rather than by approximation.

**What this buys immediately**, before any caching: the prefix stops attending over the whole
sequence. Attention goes from `S²` to `P² + (S-P)·S`, saving `P·(S-P)`. On a reference-heavy edit
where the prefix is a third of the sequence that is roughly a quarter of all attention, and it
costs no memory at all — the split is two rectangular calls, not a mask. A dense `[S, S]` mask
would be 590 MB at 17k rows and 10 GB at 73k, which is why nothing here builds one.

**What it costs:** references can no longer see the image forming. That is a real deviation from
how the model was trained, which is why `start_percent` exists — let the references watch the
composition get decided, then freeze them for the rest of the run.
"""

from __future__ import annotations

import torch

#: Where the forward wrapper leaves the split point for the attention override.
PREFIX_KEY = "nynxz_h3_prefix"
#: The full packed length, so the override can tell the DiT's attention from the token refiner's.
SEQLEN_KEY = "nynxz_h3_seqlen"

#: Segment kinds that belong to the denoising target rather than the conditioning prefix.
TARGET_KINDS = ("audio", "video")


def prefix_length(layout) -> int | None:
    """Rows before the first target segment, or None if the layout doesn't say.

    The packed order is fixed — text, then conditioning, then target audio, then target video
    (`PackedLayout.__init__`) — so the first target segment's start *is* the prefix length, and
    no scan for "which rows are references" is needed.
    """
    segments = getattr(layout, "segments", None)
    if not segments:
        return None
    for start, _stop, kind in segments:
        if kind in TARGET_KINDS:
            return int(start)
    return None


def has_references(layout) -> bool:
    """Whether anything but text sits in the prefix."""
    segments = getattr(layout, "segments", None) or []
    return any(kind not in TARGET_KINDS and kind != "text" for _, _, kind in segments)


def split_attention(func, args, kwargs, prefix: int):
    """Two rectangular attention calls in place of one square one.

    `q`, `k`, `v` arrive as `[1, heads, S, head_dim]` (the model passes `skip_reshape=True`,
    `model.py:178-181`) and the result comes back as `[1, S, heads*head_dim]`, so the two halves
    concatenate along dim 1.

    The prefix attends to itself; the target attends to everything. Note the target's call passes
    the *full* `k`/`v` — isolation is one-directional on purpose. The generation must still see
    its references; it is only the references that stop seeing the generation.
    """
    q, k, v = args[0], args[1], args[2]
    rest = args[3:]
    out_prefix = func(q[:, :, :prefix], k[:, :, :prefix], v[:, :, :prefix], *rest, **kwargs)
    out_target = func(q[:, :, prefix:], k, v, *rest, **kwargs)
    return torch.cat([out_prefix, out_target], dim=1)


def attention_override(previous, sigma_start: float, sigma_end: float):
    """Route the DiT's self-attention through the split when the prefix is worth splitting."""

    def override(func, *args, **kwargs):
        options = kwargs.get("transformer_options") or {}
        prefix = options.get(PREFIX_KEY)
        seqlen = options.get(SEQLEN_KEY)

        def passthrough():
            if previous is not None:
                return previous(func, *args, **kwargs)
            return func(*args, **kwargs)

        if not prefix or len(args) < 3 or not isinstance(args[0], torch.Tensor):
            return passthrough()
        # The token refiner attends over the text alone and reaches this same override; only the
        # call whose query length is the whole packed sequence is the one to split.
        if args[0].shape[2] != seqlen or prefix >= seqlen:
            return passthrough()
        sigma = options.get("sigmas")
        if sigma is not None:
            value = float(sigma.flatten()[0].item())
            if not (sigma_end <= value <= sigma_start):
                return passthrough()
        # Deliberately does not chain into `previous`: another override would be handed the full
        # square attention this node exists to avoid. Chaining resumes on every passthrough path.
        return split_attention(func, args, kwargs, int(prefix))

    return override
