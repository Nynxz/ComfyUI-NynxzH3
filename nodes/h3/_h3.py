"""Recognising a MiniMax H3 DiT, reading its dimensions, and the arithmetic its cost obeys.

Everything here is derived from the model rather than hardcoded, because H3 ships in more than one
shape: `comfy/model_detection.py:362-389` reads every dimension out of the checkpoint, and the
curve-form checkpoints swap the time embedder for a lookup table and shrink `time_embed_dim` to a
small basis rank. Reading `blocks[0]` gives the numbers that actually loaded.

The cost model here is deliberately *analytic* — it counts the FLOPs the architecture must issue
for a given sequence length. Compared against measured wall time it yields achieved throughput,
and that single number is what separates "compute-bound on the quadratic wall" from "stalled on
weight transfer", which is the whole question the profiler is asked.
"""

from __future__ import annotations

#: H3's DiT class, matched by name.
#:
#: By name and not by `isinstance`: importing `comfy.ldm.minimax.model` raises on any ComfyUI
#: build that predates the H3 merge, which would turn "you wired the wrong model in" into a pack
#: that fails to load at all. A string compare degrades to "this isn't H3" instead, which is the
#: honest answer on those builds.
MODEL_CLASS = "MiniMaxH3Model"

#: Segment kinds `PackedLayout` emits, in packing order, with what each one is.
#: Kept short enough to sit in the report's description column without wrapping.
SEGMENT_KINDS = {
    "text": "prompt + vision hidden states",
    "cond": "fl2va keyframe latents",
    "ref_img": "reference image/video latents",
    "ref_audio": "reference audio latents",
    "audio": "target audio (denoised)",
    "video": "target video (denoised)",
}


def diffusion_model(model):
    """The DiT module behind a wired MODEL, or None if there isn't one."""
    inner = getattr(model, "model", None)
    return getattr(inner, "diffusion_model", None)


def is_h3(model) -> bool:
    dit = diffusion_model(model)
    return dit is not None and type(dit).__name__ == MODEL_CLASS


def _feature(linear, attribute: str, axis: int) -> int:
    """`in_features`/`out_features` off a Linear, falling back to the weight's shape.

    Quantized builds swap the Linear class out (`comfy.quant_ops`), and a quantized weight's shape
    doesn't have to match the logical one — packed int4 halves the row. The `_features` attributes
    are plain ints fixed at construction, so they survive that; the shape read is only for a layer
    type that somehow has neither.
    """
    value = getattr(linear, attribute, None)
    if value is not None:
        return int(value)
    return int(linear.weight.shape[axis])


def dims(dit) -> dict:
    """The dimensions the cost model needs, read off the loaded model."""
    block = dit.blocks[0]
    return {
        "layers": len(dit.blocks),
        "hidden": int(dit.hidden_size),
        "heads": int(block.attn.heads),
        "head_dim": int(block.attn.head_dim),
        "ffn": _feature(block.mlp.fc1, "out_features", 0) // 2,  # fc1 is hidden -> ffn*2 (swiglu)
        "refiner_layers": len(dit.token_refiner.blocks),
    }


def flops(d: dict, seq_len: int) -> dict:
    """Analytic FLOPs for one forward at `seq_len` rows. 2 FLOPs per multiply-accumulate.

    adaLN is excluded on purpose and it is not an oversight: `AdalnProj` runs on the handful of
    distinct *timestep* rows (`model.py:541`), not on the sequence, so it is a fixed few-row
    matmul per block however long the video is. It costs parameters and therefore transfer
    bandwidth, but almost no arithmetic — and conflating the two is exactly the confusion this
    profiler is meant to resolve.
    """
    inner = d["heads"] * d["head_dim"]
    hidden, ffn = d["hidden"], d["ffn"]

    qkv = 2 * hidden * inner * 3
    out = 2 * inner * hidden
    fc1 = 2 * hidden * ffn * 2
    fc2 = 2 * ffn * hidden
    linear_per_token = qkv + out + fc1 + fc2

    # QK^T then AV, both [S, inner] x [S, inner] contractions: 2 * 2 * S * inner per query row.
    attn_per_token = 4 * seq_len * inner

    linear = linear_per_token * seq_len * d["layers"]
    attention = attn_per_token * seq_len * d["layers"]
    return {
        "linear": linear,
        "attention": attention,
        "total": linear + attention,
        "attention_share": attention / max(1, linear + attention),
    }


def composition(payload, video_x, audio_x, context) -> tuple[int, list[tuple[str, int]]]:
    """`(seq_len, [(kind, rows), ...])` for the sequence a forward is about to run.

    Preferred source is the `PackedLayout` that `MiniMaxH3.extra_conds` prebuilds once per
    sampling run (`comfy/model_base.py:2176-2180`), because it is the same object the forward will
    use and it accounts for every reference block. The fallback reconstructs only what the tensor
    shapes can prove — a run whose layout wasn't prebuilt still reports its target rows correctly
    and simply can't attribute reference rows.
    """
    layout = payload.get("layout") if isinstance(payload, dict) else None
    segments = getattr(layout, "segments", None)
    if segments:
        rows: dict[str, int] = {}
        for start, stop, kind in segments:
            rows[kind] = rows.get(kind, 0) + (stop - start)
        ordered = [(kind, rows[kind]) for kind in SEGMENT_KINDS if kind in rows]
        return int(layout.seq_len), ordered

    # h/w round up to the DiT's 2x2 patch exactly as `pad_to_patch_size` will.
    latent_t, h, w = int(video_x.shape[2]), int(video_x.shape[3]), int(video_x.shape[4])
    video_rows = latent_t * (((h + 1) // 2 * 2) // 2) * (((w + 1) // 2 * 2) // 2)
    audio_rows = int(audio_x.shape[-1]) * 2
    text_rows = int(context.shape[1])
    ordered = [("text", text_rows), ("audio", audio_rows), ("video", video_rows)]
    return text_rows + audio_rows + video_rows, ordered


def resident_weights(model) -> tuple[int, int] | None:
    """`(bytes resident on the compute device, total bytes)` for this DiT, or None if unknown.

    The gap between the two is the streaming cliff made visible. Matching is on the underlying
    `BaseModel` rather than the patcher: the sampler holds a clone of whatever MODEL was wired in,
    and clones share that object while every patcher around it is a different instance.
    """
    try:
        import comfy.model_management
    except ImportError:  # pragma: no cover - only outside a ComfyUI process
        return None

    target = getattr(model, "model", None)
    for loaded in getattr(comfy.model_management, "current_loaded_models", []):
        patcher = getattr(loaded, "model", None)
        if patcher is None or getattr(patcher, "model", None) is not target:
            continue
        try:
            return int(patcher.loaded_size()), int(patcher.model_size())
        except AttributeError:  # a patcher shape that predates these accessors
            return None
    return None
