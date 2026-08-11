"""Row-chunked attention projection and MLP, for sequences whose intermediates overflow int32.

**The wall this exists for, and it is a hard one.** H3's block widens the sequence twice: the fused
`attn.qkv_proj` produces `[S, 21504]` and `mlp.fc1` produces `[S, 28672]`. Both are *element
counts*, and CUDA kernels that index with int32 top out at 2,147,483,648 elements. So:

    5s   pass-2 regenerate    S =  66,248    fc1 out 1.90e9   under, by 12%
    10s                       S = 128,390    fc1 out 3.68e9   OVER
    15s                       S = 190,532    fc1 out 5.46e9   OVER by 2.5x

Past the line the failure is **not** an OOM. It is `CUDA error: an illegal memory access was
encountered`, usually surfacing at some later, innocent allocation because CUDA reports kernel
faults asynchronously. A quantized checkpoint hits it in `comfy_kitchen`'s int8 path, which is why
the traceback tends to point at `x_qdata = torch.empty(...)` — a line that is itself fine.

**Both walls fall to the same fix, because these two operations are row-wise.** Every output row
of `fc1`, `fc2`, `qkv_proj` and `out_proj` depends only on the matching input row, so splitting the
sequence into row chunks computes *the same function* — no approximation, no quality trade. It
costs one Python loop. Peak activation memory drops to one chunk's worth at the same time, which
is the second wall (fc1 alone is 10.18 GiB at 15s).

Exact in the mathematical sense, not bit-for-bit at every chunk size: a `[m, k]` matmul may
accumulate the k-contraction differently at different `m`, so chunking moves the last bits the way
changing batch size does anywhere in torch. Measured at ~1e-7 relative on the test model, against a
signal the sampler is actively denoising. The pass-through path — chunk >= sequence — *is*
bit-exact, because it calls the original function untouched; that is what makes leaving the node
wired in genuinely free.

Attention itself is untouched: it genuinely needs every row, and its own memory is the attention
backend's problem — flex or Sage, which is what MiniMax H3 Sliding Window is for.

**Why this patches `forward` on the `mlp` and `attn` modules rather than replacing the block.**
The block-replace hook (`patches_replace["dit"][("double_block", i)]`) is a single chain, and
`block_patch` installs each new patch OUTERMOST. A row-chunker installed there would have to run
the block itself and therefore ignore `run`, cutting the Block Cache out of the chain entirely.
Patching the two modules' `forward` is orthogonal: the Block Cache still decides *whether* a block
runs, the Sliding Window still overrides *how* attention is computed, and this decides how widely
the projections are materialized. Three different questions, three hooks, no ordering to get wrong.
`ModelPatcher.add_object_patch` backs up and restores the previous attribute, and setting an
instance-level `forward` shadows the class method exactly the way `nn.Module.__call__` resolves it.

The reimplemented `Attention.forward` mirrors `comfy/ldm/minimax/model.py:156-182` line for line,
including the in-place fused RMSNorm+rope, and still calls `optimized_attention` with the live
`transformer_options` so any attention override composes.
"""

from __future__ import annotations

import torch

#: CUDA's int32 element-count ceiling. Kernels that index with int32 fault past this.
INT32_ELEMENTS = 2**31

#: Safety margin under the ceiling. A kernel may allocate a workspace alongside its output, and
#: landing at 99% of a hard limit to save one loop iteration is a poor trade.
INT32_MARGIN = 0.85

#: Target bytes for one widened intermediate. Well under the int32 bound at these widths, and
#: chosen for the *other* wall: a 3.5 GiB activation is survivable on a 32 GB card only when
#: nothing else wants memory. Chunking to ~1 GiB costs a few extra matmul launches per block.
TARGET_BYTES = 1 << 30


def chunk_rows(seq_len: int, width: int, itemsize: int, override: int = 0) -> int:
    """Rows per chunk for an `[S, width]` intermediate. Returns `seq_len` to mean "don't chunk".

    `override` > 0 is taken literally (clamped to the sequence), because a card that faults
    earlier than the arithmetic predicts needs a way to say so.
    """
    if override > 0:
        return max(1, min(int(override), seq_len))
    by_int32 = int(INT32_ELEMENTS * INT32_MARGIN) // max(1, width)
    by_bytes = TARGET_BYTES // max(1, width * max(1, itemsize))
    return max(1, min(seq_len, by_int32, by_bytes))


def _linear_chunked(layer, x, chunk: int, out=None):
    """`layer(x)` in row chunks. Row-wise, so bit-identical to the unchunked call."""
    rows = x.shape[0]
    if chunk >= rows and out is None:
        return layer(x)
    for a in range(0, rows, chunk):
        b = min(a + chunk, rows)
        piece = layer(x[a:b])
        if out is None:
            out = torch.empty((rows, *piece.shape[1:]), dtype=piece.dtype, device=piece.device)
        out[a:b] = piece
    return out


def mlp_forward(mlp, x, override: int = 0):
    """`MLP.forward` with `fc1 -> swiglu -> fc2` fused per row chunk.

    Chunking `fc1` alone would buy nothing: its `[S, ffn*2]` output is the tensor that overflows,
    and reassembling it before `fc2` would materialize exactly what we are avoiding. The whole
    fc1/act/fc2 path runs inside the loop and only the `[S, hidden]` result is kept.
    """
    import comfy.ops

    rows = x.shape[0]
    width = _out_features(mlp.fc1)
    chunk = chunk_rows(rows, width, x.element_size(), override)
    if chunk >= rows:
        return comfy.ops.linear_input_act(mlp.fc2, mlp.fc1(x), "swiglu")

    out = torch.empty_like(x)
    for a in range(0, rows, chunk):
        b = min(a + chunk, rows)
        out[a:b] = comfy.ops.linear_input_act(mlp.fc2, mlp.fc1(x[a:b]), "swiglu")
    return out


def attention_forward(
    attn,
    x,
    rope_freqs=None,
    # The `{}` default mirrors `comfy/ldm/minimax/model.py:146`, the forward this replaces.
    # Never mutated; changing it to None would make the two signatures disagree.
    transformer_options={},  # noqa: B006
    override: int = 0,
):
    """`Attention.forward` with the fused qkv projection materialized in row chunks.

    Mirrors `comfy/ldm/minimax/model.py:156-182`. The only change is that the `[S, 3*inner]` fused
    tensor is never built: each chunk's q/k/v go straight into three `[S, heads, head_dim]`
    buffers, none of which can overflow (they are a third the width). Everything after that —
    the fused RMSNorm+rope, the transposes, the attention call, the output projection — is core's.
    """
    import comfy.model_management
    import comfy.quant_ops
    from comfy.ldm.modules.attention import optimized_attention

    s = x.shape[0]
    heads, head_dim = attn.heads, attn.head_dim
    inner = heads * head_dim
    chunk = chunk_rows(s, _out_features(attn.qkv_proj), x.element_size(), override)

    if chunk >= s:
        q, k, v = attn.qkv_proj(x).split(inner, dim=-1)
        q = q.view(1, s, heads, head_dim)
        k = k.view(1, s, heads, head_dim)
        v = v.view(s, heads, head_dim)
    else:
        q = k = v = None
        for a in range(0, s, chunk):
            b = min(a + chunk, s)
            qc, kc, vc = attn.qkv_proj(x[a:b]).split(inner, dim=-1)
            if q is None:
                # dtype comes from the projection, not from x: a quantized Linear need not
                # return its input's dtype, and guessing that wrong is a silent precision change.
                kw = {"dtype": qc.dtype, "device": qc.device}
                q = torch.empty(1, s, heads, head_dim, **kw)
                k = torch.empty(1, s, heads, head_dim, **kw)
                v = torch.empty(s, heads, head_dim, **kw)
            q[0, a:b] = qc.view(-1, heads, head_dim)
            k[0, a:b] = kc.view(-1, heads, head_dim)
            v[a:b] = vc.view(-1, heads, head_dim)

    if rope_freqs is not None:
        qw = comfy.model_management.cast_to(attn.q_norm.weight, device=x.device)
        kw_ = comfy.model_management.cast_to(attn.k_norm.weight, device=x.device)
        rot = rope_freqs.shape[-3] * 2
        if comfy.model_management.in_training:
            q, k = comfy.quant_ops.ck.rms_rope_split_half(
                q, k, rope_freqs, qw, kw_, epsilon=attn.q_norm.eps, rot_dim=rot
            )
        else:
            comfy.quant_ops.ck.rms_rope_split_half_(
                q, k, rope_freqs, qw, kw_, epsilon=attn.q_norm.eps, rot_dim=rot
            )
        q, k = q[0], k[0]
    else:
        q = attn.q_norm(q[0])
        k = attn.k_norm(k[0])

    q = q.transpose(0, 1).unsqueeze(0)
    k = k.transpose(0, 1).unsqueeze(0)
    v = v.transpose(0, 1).unsqueeze(0)
    out = optimized_attention(
        q, k, v, heads, mask=None, skip_reshape=True, transformer_options=transformer_options
    )
    out = out.squeeze(0)
    return _linear_chunked(
        attn.out_proj,
        out,
        chunk_rows(s, _out_features(attn.out_proj), out.element_size(), override),
    )


def _out_features(linear) -> int:
    """`out_features` off a Linear, falling back to the weight's shape.

    Same reasoning as `_h3._feature`: a quantized build swaps the Linear class and a packed weight's
    shape need not match the logical one, but `out_features` is a plain int fixed at construction.
    """
    value = getattr(linear, "out_features", None)
    return int(value) if value is not None else int(linear.weight.shape[0])


def plan(dims: dict, seq_len: int, override: int = 0, itemsize: int = 2) -> dict:
    """What chunking would do to one block at `seq_len` — for the node's report, and for tests."""
    qkv_w = dims["heads"] * dims["head_dim"] * 3
    fc1_w = dims["ffn"] * 2
    out = {}
    for name, width in (("attn.qkv_proj", qkv_w), ("mlp.fc1", fc1_w)):
        elems = seq_len * width
        chunk = chunk_rows(seq_len, width, itemsize, override)
        out[name] = {
            "width": width,
            "elements": elems,
            "over_int32": elems >= INT32_ELEMENTS,
            "chunk": chunk,
            "pieces": (seq_len + chunk - 1) // chunk,
            "bytes_full": elems * itemsize,
            "bytes_chunked": chunk * width * itemsize,
        }
    return out


def install(patcher, dit, override: int = 0):
    """Patch every block's `mlp.forward` and `attn.forward`. Returns how many blocks were touched.

    Bound as default arguments rather than closed over: 50 blocks each need their *own* module,
    and a late-binding closure over the loop variable would give all 50 the last block's weights —
    a bug that produces a plausible-looking image and no error at all.
    """
    for index, block in enumerate(dit.blocks):
        patcher.add_object_patch(
            f"diffusion_model.blocks.{index}.mlp.forward",
            lambda x, _m=block.mlp, _o=override: mlp_forward(_m, x, _o),
        )
        patcher.add_object_patch(
            f"diffusion_model.blocks.{index}.attn.forward",
            lambda x, rope_freqs=None, transformer_options={}, _m=block.attn, _o=override: (
                attention_forward(_m, x, rope_freqs, transformer_options, _o)
            ),
        )
    return len(dit.blocks)
