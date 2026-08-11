"""MiniMax H3 Row Chunk — the node that lifts the int32 ceiling on long or high-resolution runs.

Wire it between the model and the sampler. It is exact: the operations it splits are row-wise, so
the result is the same arithmetic in a different order, not an approximation. Leave it wired —
below the threshold it detects that chunking is unnecessary and every call takes the unchunked
path, so it costs nothing on runs that were already fine.

See `_rowchunk.py` for the wall it exists for and why it patches module `forward`s rather than
joining the block-replace chain.
"""

from __future__ import annotations

from comfy_api.latest import io

from .._base import CATEGORY, PackNode
from . import _h3, _rowchunk


class H3RowChunk(PackNode):
    CATEGORY = f"{CATEGORY}/Sampling"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3RowChunk",
            display_name="H3 Row Chunk",
            description="Splits the attention qkv projection and the MLP into row chunks so their "
            "intermediates never exceed CUDA's int32 element limit. Fixes 'CUDA error: an illegal "
            "memory access was encountered' on sequences past ~75k rows, and lowers peak "
            "activation memory. These projections are row-wise, so this computes the same "
            "function — it is not an approximation and costs no quality.",
            is_experimental=True,
            inputs=[
                io.Model.Input("model", tooltip="A MiniMax H3 model."),
                io.Int.Input(
                    "chunk_rows",
                    default=0,
                    min=0,
                    max=1_000_000,
                    tooltip="Rows per chunk. 0 picks a size from the sequence: small enough to "
                    "stay under the int32 limit with margin AND to hold each widened intermediate "
                    "near 1 GiB. Set a smaller number only if a run still faults — some kernels "
                    "allocate workspace beyond their output.",
                ),
            ],
            outputs=[
                io.Model.Output(),
                io.String.Output(
                    display_name="report",
                    tooltip="Where the int32 ceiling falls for this model, and what chunking does "
                    "at a few clip lengths.",
                ),
            ],
        )

    @classmethod
    def execute(cls, model, chunk_rows=0) -> io.NodeOutput:
        if not _h3.is_h3(model):
            wired = type(_h3.diffusion_model(model)).__name__
            raise ValueError(
                "MiniMax H3 Row Chunk only understands MiniMax H3 — the wired model's DiT is "
                f"{wired!r}. It splits H3's fused qkv projection and swiglu MLP specifically."
            )

        m = model.clone()
        dit = _h3.diffusion_model(m)
        dims = _h3.dims(dit)
        blocks = _rowchunk.install(m, dit, chunk_rows)

        qkv_w = dims["heads"] * dims["head_dim"] * 3
        fc1_w = dims["ffn"] * 2
        widest = max(qkv_w, fc1_w)
        ceiling = _rowchunk.INT32_ELEMENTS // widest

        lines = [
            f"row chunking installed on {blocks} blocks"
            + (f", {chunk_rows} rows (manual)" if chunk_rows > 0 else ", auto"),
            f"  widest intermediate: mlp.fc1 [S x {fc1_w}], attn.qkv_proj [S x {qkv_w}]",
            f"  int32 ceiling without chunking: S = {ceiling:,} rows",
            "",
            f"  {'sequence':>10} {'fc1 elements':>14} {'':>6} {'chunk':>8} {'pieces':>7} {'peak/GiB':>9}",
        ]
        for seq in (66_000, 128_000, 190_000, 260_000):
            info = _rowchunk.plan(dims, seq, chunk_rows)["mlp.fc1"]
            lines.append(
                f"  {seq:>10,} {info['elements'] / 1e9:>13.2f}e9 "
                f"{'OVER' if info['over_int32'] else 'ok':>6} "
                f"{info['chunk']:>8,} {info['pieces']:>7} "
                f"{info['bytes_chunked'] / 2**30:>9.2f}"
            )
        lines += [
            "",
            "  row-wise, so this computes the same function — no approximation. Chunk boundaries "
            "move the last bits only (matmul accumulation order, ~1e-7 relative).",
            "  composes with Block Cache (block-level) and Sliding Window (attention override) — "
            "three different hooks.",
        ]
        return io.NodeOutput(m, "\n".join(lines))
