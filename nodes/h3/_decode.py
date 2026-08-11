"""The ComfyUI half of a partial decode: memory reservation, device, dtype.

`_frames.decode_frames` is torch-only and knows nothing about ComfyUI. This wraps it in the same
ceremony `comfy.sd.VAE.decode` performs — reserve VRAM sized for what will actually run, load the
VAE patcher, decode inside the VAE's device context — and nothing else. The memory estimate is the
part worth pointing at: it is computed for **one chunk window**, not for the whole clip, because
that is all that is ever resident. Handing `memory_used_decode` the full latent shape would reserve
for a 124-frame decode to produce one frame, and on a card already holding a 19.5 GB DiT that
reservation is the difference between a preview and an eviction.

No tiled fallback, and none is needed: the H3 VAE tiles spatially inside `_adaptive_decode` on
every path (`tiling=True`, 256px tiles), which is why `comfy.sd` marks it `handles_tiling`.
"""

from __future__ import annotations

import torch

from . import _frames


def video_stream(samples) -> torch.Tensor:
    """The video half of an H3 latent, whether it arrived nested with audio or bare."""
    latent = samples["samples"] if isinstance(samples, dict) else samples
    if getattr(latent, "is_nested", False):
        latent = latent.unbind()[0]
    if latent.ndim != 5:
        raise ValueError(
            f"expected a video latent [B, C, T, H, W], got {tuple(latent.shape)}. Wire the LATENT "
            "from an H3 sampler or Empty MiniMax H3 AV Latent."
        )
    return latent


def frame_count(vae, latent: torch.Tensor) -> int:
    """How many pixel frames a full decode of this latent would produce."""
    return _frames.frame_plan(vae.first_stage_model, latent.shape[2]).output_frames


def require_h3(vae) -> None:
    if not _frames.is_h3_vae(vae):
        wired = type(getattr(vae, "first_stage_model", None)).__name__
        raise ValueError(
            f"this node decodes the MiniMax H3 video VAE; the wired VAE is {wired!r}. It reproduces "
            "H3's temporal chunking exactly to decode single frames, which is not a shape other "
            "VAEs share."
        )


def decode(vae, latent: torch.Tensor, indices) -> torch.Tensor:
    """`[B, 3, len(indices), H*16, W*16]` in [0, 1] — pre-`process_output`, as the VAE emits it.

    [0, 1] rather than the usual [-1, 1] because H3's VAE finalizes to display range itself and
    core gives it an identity `process_output`; see `_frames.decode_frames`.
    """
    import comfy.model_management as model_management

    require_h3(vae)
    vae.throw_exception_if_invalid()
    fsm = vae.first_stage_model

    plan = _frames.frame_plan(fsm, latent.shape[2])
    window = max(1, _frames.window_tokens(plan, [int(i) for i in indices]))
    chunk_shape = (latent.shape[0], latent.shape[1], window, latent.shape[3], latent.shape[4])
    memory_used = vae.memory_used_decode(chunk_shape, vae.vae_dtype)

    model_management.load_models_gpu(
        [vae.patcher], memory_required=memory_used, force_full_load=vae.disable_offload
    )
    with model_management.cuda_device_context(vae.device):
        z = latent.to(device=vae.device, dtype=vae.vae_dtype)
        pixels = _frames.decode_frames(fsm, z, indices)
    return pixels.to(vae.output_device)


def decode_images(vae, latent: torch.Tensor, indices) -> torch.Tensor:
    """The same decode as an IMAGE batch `[N, H, W, 3]` in [0, 1]."""
    pixels = decode(vae, latent, indices)
    processed = vae.process_output(pixels)
    if processed is not None:
        pixels = processed
    pixels = pixels.movedim(1, -1)
    return pixels.reshape(-1, pixels.shape[-3], pixels.shape[-2], pixels.shape[-1])
