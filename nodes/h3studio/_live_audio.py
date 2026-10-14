"""x0 -> the sound under the preview, for models that sample audio and video together.

Vendored from Model Preview Override in ComfyUI-NynxzPersonal (same author, MIT), so H3 Studio
previews on its own without that pack. Keep the two in step when either changes.

MiniMax H3's AV model denoises one packed latent holding both streams, so every step's x0 already
contains the audio as it currently stands. With an audio VAE connected, decoding that stream each
step lets the animated preview play with its sound — and a model that gets the picture right while
the audio is still noise is something you want to hear before the run finishes, not after.

Three things have to line up with what core does, or the result is quietly wrong rather than
broken:

  * **which stream** — the LAST one, the convention `comfy_extras.nodes_audio.vae_decode_audio`
    uses (the picture is the first, which is what `preview_override._unpack` hands the decoders);
  * **its scale** — the sampler carries H3's audio multiplied by `model.audio_scale()`, and only
    `process_latent_out` divides it back out. x0 in a callback is before that, so we divide here;
  * **the loudness normalisation** — `vae_decode_audio` divides by 5x the waveform's std (floored
    at 1). Skipping it previews noise-stage audio painfully loud.

The decode itself is core's public `VAE.decode`, the same call `VAEDecodeAudio` makes, so device
placement and memory accounting are core's problem.
"""

from __future__ import annotations

import logging

import comfy.model_management
import comfy.utils
import numpy as np
import torch

LOG = logging.getLogger(__name__)


def audio_stream(x0: torch.Tensor, latent_shapes) -> torch.Tensor | None:
    """The audio latent out of a step's x0, or None if this run has no second stream."""
    tensors = getattr(x0, "tensors", None)
    if tensors:
        return tensors[-1] if len(tensors) > 1 else None
    if not latent_shapes or len(latent_shapes) < 2:
        return None
    try:
        return comfy.utils.unpack_latents(x0, latent_shapes)[-1]
    except Exception:  # noqa: BLE001 - a buffer we cannot unpack has no audio we can find
        return None


def audio_stream_shape(latent_shapes) -> tuple:
    """The audio stream's latent shape, batch 1: the last of the run's streams."""
    return (1, *tuple(latent_shapes[-1])[1:])


class AudioSource:
    """Decodes the audio stream of each step. Built once per sampling call, like `FrameSource`."""

    def __init__(self, model_patcher, audio_vae, latent_shapes):
        self.vae = None
        self.latent_shapes = latent_shapes
        self.sample_rate = 0
        self._model = model_patcher.model
        if audio_vae is None:
            return
        if not latent_shapes or len(latent_shapes) < 2:
            # Connected to a model that samples one stream: nothing to decode, and nothing wrong.
            LOG.info("H3 Studio preview: audio_vae connected, but this run has no audio stream.")
            return
        # vae_decode_audio prefers the output rate; some audio VAEs only set that one.
        rate = getattr(audio_vae, "audio_sample_rate_output", None) or getattr(
            audio_vae, "audio_sample_rate", 0
        )
        if not rate:
            LOG.warning("H3 Studio preview: audio_vae has no sample rate; previews stay silent.")
            return
        # Loaded once, here, before sampling starts: `VAE.decode` would run the model manager on
        # every step, mid-sampling, where moving models about can crash the sampler (see
        # `Decoder._decode_direct`). Each step then calls the decoder itself.
        try:
            shape = tuple(audio_stream_shape(latent_shapes))
            comfy.model_management.load_models_gpu(
                [audio_vae.patcher],
                memory_required=audio_vae.memory_used_decode(shape, audio_vae.vae_dtype),
                force_full_load=getattr(audio_vae, "disable_offload", False),
            )
        except Exception as e:  # noqa: BLE001 - no audio preview, but the run goes on
            LOG.warning(
                "H3 Studio preview: could not load the audio VAE; previews stay silent (%s).", e
            )
            return
        self.vae = audio_vae
        self.sample_rate = int(rate)

    def usable(self) -> bool:
        return self.vae is not None

    def _scale(self) -> float:
        # Read per call, not cached: it depends on the model's latent_shapes, which the sampler
        # sets for the run. 1.0 when the model has no such notion.
        fn = getattr(self._model, "audio_scale", None)
        try:
            scale = float(fn()) if callable(fn) else 1.0
        except Exception:  # noqa: BLE001 - no scale we can read means the stream is unscaled
            scale = 1.0
        return scale if scale else 1.0

    def decode(self, x0: torch.Tensor) -> np.ndarray | None:
        """`[channels, samples]` float32 in -1..1 for the whole clip, or None.

        A failure disables audio for the rest of the run: an audio decode that failed once (OOM,
        a VAE that doesn't fit this latent) will fail every step, and each attempt costs time the
        sampler is waiting on.
        """
        if self.vae is None:
            return None
        latent = audio_stream(x0, self.latent_shapes)
        if latent is None:
            return None
        try:
            vae = self.vae
            with torch.no_grad():
                z = (latent[:1] / self._scale()).to(device=vae.device, dtype=vae.vae_dtype)
                wave = vae.process_output(vae.first_stage_model.decode(z)).float().cpu()
                del z
            std = torch.std(wave, dim=[1, 2], keepdim=True) * 5.0
            std[std < 1.0] = 1.0
            wave = (wave / std)[0].clamp(-1, 1)
            if wave.shape[0] == 1:
                wave = wave.expand(2, -1)  # AAC is muxed stereo; mono plays from both sides
            return wave[:2].cpu().numpy().astype(np.float32, copy=False)
        except Exception as e:  # noqa: BLE001 - audio is a bonus; losing it must not cost the picture
            LOG.warning("H3 Studio preview: audio decode failed, previews stay silent (%s).", e)
            self.vae = None
            return None


def slice_span(wave: np.ndarray, span: tuple[float, float], sample_rate: int) -> np.ndarray | None:
    """The part of the clip's audio under frames that show `span` of it. None if too short."""
    total = wave.shape[1]
    start = round(max(0.0, span[0]) * total)
    end = round(min(1.0, span[1]) * total)
    # Under ~50ms there is nothing to hear and AAC's priming delay would be most of it.
    if end - start < sample_rate // 20:
        return None
    return wave[:, start:end]
