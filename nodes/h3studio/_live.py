"""H3 Studio's live preview: every sampling step of a scene, as a clip of the whole scene, on the
studio's monitor — with no preview node in the graph.

H3 Studio Outputs hangs an `OUTER_SAMPLE` wrapper on the model it hands the sampler, so whichever
sampler runs it previews. It is Model Preview Override (ComfyUI-NynxzPersonal, same author, MIT)
set up for the scene: as many preview frames as the scene renders, taeh3 from models/vae_approx
when it's there (else the colour matrix), and the scene's sound under the clip when Setup has the
audio VAE. Frames go out as `nynxz.h3studio.preview`, the override's message shape, which the
monitor plays. Another pack's preview override wired after Outputs owns the preview instead,
and this one stands aside. The mechanism is core's public wrapper API, core's previewers and
`PromptServer.send_sync`.
"""

from __future__ import annotations

import logging
import math
import time

LOG = logging.getLogger(__name__)

WRAPPER_KEY = "nynxz_h3studio_preview"
#: Other packs' `OUTER_SAMPLE` preview wrappers, by key. When one is on the model it owns the preview.
OVERRIDE_KEYS = ("nynxz_preview_override", "kj_preview_override", "sampling_preview")

MAX_RESOLUTION = 1024
JPEG_QUALITY = 80
FPS = 24
_ETA_WINDOW = 8


def overridden(model_patcher) -> bool:
    import comfy.patcher_extension

    wrappers = getattr(model_patcher, "wrappers", None) or {}
    keys = wrappers.get(comfy.patcher_extension.WrappersMP.OUTER_SAMPLE, {})
    return any(k in keys for k in OVERRIDE_KEYS)


def tiny_vae(latent_format, picked: str = "") -> str:
    """The tiny VAE to decode with: `picked` when it's in models/vae_approx, else the one core
    pairs with this latent format (taeh3 for H3) when that's installed, else "none"."""
    try:
        import folder_paths

        installed = folder_paths.get_filename_list("vae_approx")
    except Exception:  # noqa: BLE001 - no vae_approx folder means no tiny VAE
        return "none"
    if picked in installed:
        return picked
    paired = getattr(latent_format, "taesd_decoder_name", None)
    return next((f for f in installed if paired and f.startswith(paired)), "none")


def unpack(x0, latent_shapes):
    """The picture stream of a step's x0, in the shape a previewer expects: the first latent of a
    multi-stream run (H3's video, not its sound), and a single packed latent reshaped back."""
    tensors = getattr(x0, "tensors", None)
    if tensors:
        x0 = tensors[0]
    if not latent_shapes:
        return x0
    if len(latent_shapes) > 1:
        try:
            import comfy.utils

            return comfy.utils.unpack_latents(x0, latent_shapes)[0]
        except Exception:  # noqa: BLE001 - previewed in the shape it arrived in
            return x0
    shape = latent_shapes[0]
    if x0.ndim == 3 and len(shape) >= 3:
        try:
            cut = math.prod(shape[1:])
            return x0[:, :, :cut].reshape([x0.shape[0], *list(shape)[1:]])
        except Exception:  # noqa: BLE001 - previewed in the shape it arrived in
            return x0
    return x0


class LivePreview:
    """The `OUTER_SAMPLE` wrapper: one sampling run's preview."""

    def __init__(self, mode: str, frames: int, audio_vae=None, vae_name: str = ""):
        self.mode = mode
        self.frames = max(1, int(frames or 1))
        self.audio_vae = audio_vae
        self.vae_name = vae_name

    def __call__(
        self,
        executor,
        noise,
        latent_image,
        sampler,
        sigmas,
        denoise_mask=None,
        callback=None,
        disable_pbar=False,
        seed=None,
        latent_shapes=None,
        **kwargs,
    ):
        def run(cb):
            return executor(
                noise,
                latent_image,
                sampler,
                sigmas,
                denoise_mask,
                cb,
                disable_pbar,
                seed,
                latent_shapes=latent_shapes,
                **kwargs,
            )

        patcher = executor.class_obj.model_patcher
        if self.mode == "off" or overridden(patcher):
            return run(callback)
        try:
            from . import _live_transport as transport
            from ._live_audio import AudioSource, slice_span
            from ._live_decode import FrameSource

            tiny = (
                tiny_vae(patcher.model.latent_format, self.vae_name)
                if self.mode == "auto"
                else "none"
            )
            source = FrameSource(patcher, tiny, latent_shapes)
            audio = AudioSource(patcher, self.audio_vae if self.frames > 1 else None, latent_shapes)
        except Exception as e:  # noqa: BLE001 - no decoder means no preview, not a failed render
            LOG.warning("H3 Studio preview: unavailable (%s).", e)
            return run(callback)
        if not source.usable():
            return run(callback)

        sigmas_list = sigmas.detach().cpu().tolist() if sigmas is not None else []
        transport.send(
            {
                "step": 0,
                "total": max(0, len(sigmas_list) - 1),
                "sigma": sigmas_list[0] if sigmas_list else None,
                "sigmas": sigmas_list,
                "decoder": source.label,
            }
        )
        state = {"prev": None, "last_time": time.perf_counter(), "window": []}
        encoder = transport.AsyncEncoder()

        def preview(step, x0, x, total):
            try:
                view = unpack(x0, latent_shapes)
                frames, span = source.decode_clip(view, self.frames)
                sound = None
                if len(frames) > 1 and audio.usable():
                    wave = audio.decode(x0)
                    if wave is not None:
                        sound = slice_span(wave, span, audio.sample_rate)
                if frames:
                    self._emit(
                        transport, encoder, state, frames, view, step, total, sigmas_list,
                        sound, audio.sample_rate,
                    )  # fmt: skip
            except Exception as e:  # noqa: BLE001 - nothing about a preview may break the sampler
                LOG.warning("H3 Studio preview: step %s failed (%s).", step, e)
            if callback is not None:
                callback(step, x0, x, total)

        try:
            return run(preview)
        finally:
            encoder.shutdown(drain_timeout=5.0)

    @staticmethod
    def _emit(
        transport, encoder, state, frames, view, step, total, sigmas_list, sound, sample_rate
    ):
        now_x0 = view.detach().cpu().float()
        prev_x0, state["prev"] = state["prev"], now_x0
        now = time.perf_counter()
        step_ms = (now - state["last_time"]) * 1000.0
        state["last_time"] = now
        window = state["window"]
        window.append(step_ms)
        del window[:-_ETA_WINDOW]
        avg_ms = sum(window) / len(window)
        sigma = sigmas_list[step] if 0 <= step < len(sigmas_list) else None

        def encode_and_send():
            with_audio = None
            if sound is not None:
                with_audio = transport.encode_clip_with_audio(
                    frames, sound, sample_rate, MAX_RESOLUTION
                )
            fps = FPS
            if with_audio is not None:
                b64, w, h, mime, fps = with_audio
            else:
                b64, w, h, mime = transport.encode(frames, FPS, JPEG_QUALITY, MAX_RESOLUTION)
            if not b64:
                return
            delta = None
            if prev_x0 is not None and prev_x0.shape == now_x0.shape:
                diff = now_x0 - prev_x0
                delta = (diff.norm() / max(1, diff.numel()) ** 0.5).item()
            transport.send(
                {
                    "image": b64,
                    "mime": mime,
                    "w": w,
                    "h": h,
                    "step": step + 1,
                    "total": total,
                    "sigma": sigma,
                    "sigmas": None,
                    "delta": delta,
                    "step_ms": step_ms,
                    "avg_step_ms": avg_ms,
                    "fps": fps if mime != "image/jpeg" else None,
                    "audio": with_audio is not None,
                }
            )

        encoder.submit(encode_and_send)


def attach(model, settings: dict, frames: int, audio_vae=None):
    """`model` with the live preview the studio's settings ask for (`preview`, `preview_vae`,
    `preview_sound`), or as it came when there's nothing to attach."""
    mode = settings.get("preview") or "auto"
    if model is None or mode == "off":
        return model
    import comfy.patcher_extension

    patched = model.clone()
    patched.add_wrapper_with_key(
        comfy.patcher_extension.WrappersMP.OUTER_SAMPLE,
        WRAPPER_KEY,
        LivePreview(
            mode,
            frames,
            audio_vae if settings.get("preview_sound", True) else None,
            settings.get("preview_vae") or "",
        ),
    )
    return patched
