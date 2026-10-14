"""x0 -> preview frames, for H3 Studio's live preview (see `_live.py`).

Vendored from Model Preview Override in ComfyUI-NynxzPersonal (same author, MIT), so the studio
previews on its own without that pack. Keep the two in step when either changes.

The decoders are core's public ones —
`comfy.taesd.taesd.TAESD`, `comfy.sd.VAE`, `latent_preview.Latent2RGBPreviewer` — and the shape
handling is written against the core `latent_format` API.
"""

from __future__ import annotations

import contextlib
import logging

import comfy.model_management
import comfy.sd
import comfy.utils
import folder_paths
import latent_preview
import numpy as np
import torch
from comfy.taesd.taesd import TAESD
from PIL import Image

try:
    import comfy.model_prefetch
except ImportError:  # an older core, without the allocation graph
    comfy.model_prefetch = None

LOG = logging.getLogger(__name__)


def _pick_frames(count: int, want: int) -> list[int]:
    """`want` indices spread evenly across `count`, endpoints included."""
    if want <= 0 or want >= count:
        return list(range(count))
    return np.linspace(0, count - 1, want).round().astype(int).tolist()


def _to_pil(rgb: torch.Tensor) -> list[Image.Image]:
    """[N, H, W, 3] in 0..1 -> PIL. One `.cpu()` for the whole stack, deliberately.

    Copying frame-by-frame (or with `non_blocking=True`) is how a high-resolution video preview
    ends up with torn frames: the encode thread reads the buffer while the copy is still in
    flight. One blocking bulk copy costs a sync we can afford once per step.
    """
    arr = rgb.clamp(0, 1).mul(255).to(torch.uint8).cpu().numpy()
    return [Image.fromarray(arr[i]) for i in range(arr.shape[0])]


# ── time: how many pixel frames each latent token stands for ─────────────────────────────────
#
# Needed twice: to know what stretch of the clip a prefix decode actually shows (so the matching
# slice of audio can go with it), and to spread colour-matrix frames evenly in TIME rather than in
# tokens. The two are not the same thing for MiniMax H3, whose VAE codes every 17 pixel frames as
# 5 tokens — one frame, then four, four, four, four — so a token-uniform pick bunches up at every
# chunk boundary.

#: A token -> pixel-frame layout: `head` once, then `cycle` repeating.
Timing = tuple[tuple[int, ...], tuple[int, ...]]


def token_timing(latent_format) -> Timing:
    """The layout for this latent format. Keys on core's own data, not on class names."""
    # taeh3 is the decoder core pairs with both H3 formats (video-only and AV).
    if getattr(latent_format, "taesd_decoder_name", None) == "taeh3":
        return (), (1, 4, 4, 4, 4)
    ratio = int(getattr(latent_format, "temporal_downscale_ratio", 1) or 1)
    # The causal video VAEs: the first token is one frame, every later one is `ratio`.
    return (1,), (max(1, ratio),)


def pixel_frames(tokens: int, timing: Timing) -> int:
    """Pixel frames covered by the first `tokens` latent tokens."""
    head, cycle = timing
    n_head = min(tokens, len(head))
    rest = max(0, tokens - n_head)
    return sum(head[:n_head]) + sum(cycle[i % len(cycle)] for i in range(rest))


def _pick_tokens_by_time(count: int, want: int, timing: Timing) -> list[int]:
    """`want` token indices whose frames are evenly spaced through the clip's real duration."""
    if want <= 0 or want >= count:
        return list(range(count))
    ends = [pixel_frames(i + 1, timing) for i in range(count)]
    picks = []
    for target in np.linspace(0, ends[-1] - 1, want):
        # The first token whose span reaches past `target` is the one that frame belongs to.
        picks.append(next(i for i, end in enumerate(ends) if end > target))
    return picks


def h3_prefix_tokens(take: int, total: int) -> int:
    """The nearest prefix length core's H3 decode trims correctly.

    `TAEHV.decode` undoes H3's chunking assuming the latent ENDS the way a whole encoded clip
    does: with the encoder's 3-token tail pad, so the token count is 2 more than a multiple of 5.
    True for a full clip, false for most prefixes — and then it drops 12 frames that weren't pad.
    Measured against core: 3, 4 and 5 tokens all came back as 5 frames instead of 9, 13 and 17.
    One token, or any count ≡ 2 (mod 5), comes back exact. So round up to one of those, or back
    down when that would overrun the clip; it costs at most four extra tokens of decode.
    """
    if take <= 1 or take >= total:
        return min(take, total)
    up = take + (2 - take) % 5
    return up if up <= total else up - 5


class Decoder:
    """A REAL decoder — one that produces pixels rather than approximating them from 4 channels.

    Wraps the two shapes core hands out, because they disagree about everything that matters here:
    `comfy.sd.VAE` for the temporal TAEs (taehv / taew / lighttae / taeh3) returns
    `[B, T, H, W, C]` in 0..1, while `comfy.taesd.taesd.TAESD` returns `[B, C, H, W]` in -1..1,
    and neither takes a frame count. Normalizing both here is what lets `FrameSource.decode` ask
    for N frames without caring where the decoder came from.
    """

    def __init__(self, *, vae=None, tae=None, latent_channels: int = 0, label: str = ""):
        self.vae = vae
        self.tae = tae
        self.latent_channels = latent_channels
        #: Shown on the node, so "why is this blocky" is answerable by looking at it.
        self.label = label
        #: The model's latent format asks for previews to be decoded in their own allocation
        #: scope (`compile_preview`, as MiniMax H3's does); set by `FrameSource`.
        self.compile = False
        self._prepared = False

    @property
    def temporal(self) -> bool:
        return self.vae is not None

    @property
    def is_h3(self) -> bool:
        # Core's own flag on the TAEHV it built — set from the 24-channel width, so it holds for
        # taeh3 picked by hand and for the one core's previewer loaded alike.
        return bool(getattr(getattr(self.vae, "first_stage_model", None), "is_h3", False))

    def prefix_tokens(self, total: int, want: int) -> int:
        """How many latent tokens a decode of `want` frames will consume, from the start.

        Public because `FrameSource` needs the same number to say what stretch of the clip the
        frames cover; computing it in one place is what keeps the two from disagreeing.
        """
        if not self.temporal:
            return 1
        take = max(1, min(total, want))
        return h3_prefix_tokens(take, total) if self.is_h3 else take

    def decode(self, x0: torch.Tensor, want: int) -> list[Image.Image]:
        if self.temporal:
            return self._decode_video(x0, want)
        if x0.ndim == 5:
            x0 = x0[:, :, 0]
        # The latent goes to the decoder, wherever it is.
        device = next(self.tae.parameters()).device
        # TAESD.decode returns -1..1; every other path here is 0..1.
        rgb = self.tae.decode(x0[:1].to(device)).movedim(1, -1)
        return _to_pil(rgb.add(1).mul(0.5))

    def _decode_video(self, x0: torch.Tensor, want: int) -> list[Image.Image]:
        if x0.ndim == 4:
            x0 = x0.unsqueeze(2)
        # Temporal TAEs carry state forward frame to frame, so a frame in the middle of the clip
        # can't be decoded without decoding everything before it. Taking a PREFIX of `want` latent
        # frames keeps the per-step cost bounded and proportional to what was asked for; the clip
        # then gets subsampled, since temporal upscaling returns more pixel frames than we fed in.
        take = self.prefix_tokens(int(x0.shape[2]), want)
        out = self._decode_direct(x0[:1, :, :take])
        if out.ndim == 5:
            out = out[0]
        if out.ndim != 4:
            return []
        picks = _pick_frames(int(out.shape[0]), want)
        return _to_pil(out[picks])

    def _decode_direct(self, samples: torch.Tensor) -> torch.Tensor:
        """`VAE.decode`, minus the model management it runs on every call.

        `VAE.decode` loads its model through ComfyUI's model manager each time, and a preview
        decodes between every step. Instead the VAE is loaded once, through core's own entry
        point for callers that decode directly (`prepare_decode`, which lets the model patcher
        place and cast the weights — under dynamic VRAM they're stored in a different dtype than
        they compute in), and each later step calls the decoder itself. Under `compile_preview` the decode runs in its own allocation scope and
        leaves nothing on the GPU when the scope closes, as core's previewer does.
        """
        vae = self.vae
        if not self._prepared:
            pause = (
                comfy.model_prefetch.pause_malloc_graph()
                if comfy.model_prefetch is not None
                else contextlib.nullcontext()
            )
            with pause:
                vae.prepare_decode(tuple(samples.shape))
            self._prepared = True
        scoped = (
            self.compile
            and comfy.model_prefetch is not None
            and comfy.model_prefetch.malloc_graph_enabled(vae.device)
        )
        if scoped:
            comfy.model_prefetch.malloc_graph_begin(vae.device)
        try:
            with torch.no_grad():
                x = samples.to(device=vae.device, dtype=vae.vae_dtype)
                out = vae.first_stage_model.decode(x).to(
                    device="cpu", dtype=vae.vae_output_dtype(), copy=True
                )
                del x
        finally:
            if scoped:
                comfy.model_prefetch.malloc_graph_end()
        vae.process_output(out)
        return out.movedim(1, -1)


def _decode_in_sampler_space(vae) -> None:
    """Stop comfy.sd.VAE re-normalizing a latent that is ALREADY in the sampler's space.

    `comfy.sd.VAE` exists to serve `VAEDecode`, whose input is a LATENT off the graph — raw,
    un-normalized. So for the temporal TAEs it hangs a latent format on the model and
    `TAEHV.decode` runs `process_in` (raw -> model space) before decoding. What a previewer holds
    is x0, which the sampler has ALREADY put through that same transform, so letting it run again
    normalizes the latent twice.

    And the format it runs is guessed from the CHECKPOINT, not taken from the model: core reads
    the dtype of `decoder.1.weight` and calls every 16-channel fp16 decoder HunyuanVideo. That is
    what `taew2_1` is — a Wan 2.1 decoder, 16-channel, fp16 — so its previews came out with every
    latent scaled by Hunyuan's 0.476986. The symptom is colour: washed-out, desaturated, low
    contrast, correct only in composition.

    One answer covers both: a tiny VAE in this family decodes the latent space its own model
    samples in, which is the space x0 is already in, so the transform has to be identity.
    """
    model = getattr(vae, "first_stage_model", None)
    if getattr(model, "process_in", None) is not None:
        model.process_in = lambda latent: latent


def _decoder_from_state_dict(sd: dict, declared_channels: int, label: str) -> Decoder:
    # Core's own marker for the temporal family (see latent_preview.VIDEO_TAES): those
    # checkpoints go through comfy.sd.VAE, which knows how to size and run them.
    if "decoder.22.bias" in sd:
        vae = comfy.sd.VAE(sd=sd)
        vae.first_stage_model.show_progress_bar = False
        _decode_in_sampler_space(vae)
        return Decoder(vae=vae, latent_channels=int(vae.latent_channels), label=label)

    # Flat TAESD. Decoder module 1 is `conv(latent_channels, 64)`, so its input width is the
    # checkpoint's own channel count — but Flux2's decoder lies about it (it declares 128 and
    # packs 2x2 into 32), so try what the MODEL says first and fall back to the checkpoint.
    ckpt_channels = int(sd["1.weight"].shape[1]) if "1.weight" in sd else declared_channels
    last_err: Exception | None = None
    for channels in dict.fromkeys([declared_channels, ckpt_channels]):
        if not channels:
            continue
        try:
            tae = TAESD(None, None, latent_channels=channels)
            tae.taesd_decoder.load_state_dict(sd)
            return Decoder(
                tae=tae.to(comfy.model_management.get_torch_device()),
                latent_channels=channels,
                label=label,
            )
        except Exception as e:  # noqa: BLE001 - wrong architecture for this channel count; try the next
            last_err = e
    raise RuntimeError(f"no TAESD decoder shape fits this checkpoint ({last_err})")


def load_tiny_vae(name: str, declared_channels: int) -> Decoder | None:
    """Load by `models/vae_approx` filename. Returns None (and logs why) if it can't be used."""
    path = folder_paths.get_full_path("vae_approx", name)
    if path is None:
        LOG.warning("H3 Studio preview: '%s' is not in models/vae_approx.", name)
        return None
    try:
        decoder = _decoder_from_state_dict(
            comfy.utils.load_torch_file(path, safe_load=True), declared_channels, name
        )
    except Exception as e:  # noqa: BLE001 - an unreadable checkpoint means "no tiny VAE", not a failed render
        LOG.warning("H3 Studio preview: could not load '%s' (%s).", name, e)
        return None
    if declared_channels and decoder.latent_channels != declared_channels:
        LOG.warning(
            "H3 Studio preview: '%s' decodes %d-channel latents but this model's are %d-channel; "
            "ignoring it.",
            name,
            decoder.latent_channels,
            declared_channels,
        )
        return None
    return decoder


def adopt_core_decoder(previewer) -> Decoder | None:
    """Borrow the decoder core's previewer already built, so it can serve MORE than one frame.

    Core's previewers decode exactly one frame and are not parameterised — `TAEHVPreviewerImpl`
    hard-slices `x0[:1, :, :1]`. Reaching past the previewer to the decoder it holds is what lets
    an animated preview of a video model use the real decoder instead of dropping to the colour
    matrix, which is an 8x resolution cliff and reads as "blocky".

    Returns None for anything unrecognised — including a custom pack's previewer — and the
    caller then keeps using it the one-frame way.
    """
    inner = getattr(previewer, "taesd", None)
    if inner is None:
        return None
    # TAEHVPreviewerImpl SUBCLASSES TAESDPreviewerImpl, so it has to be tested first.
    if isinstance(previewer, latent_preview.TAEHVPreviewerImpl):
        return Decoder(
            vae=inner, latent_channels=int(getattr(inner, "latent_channels", 0) or 0), label="taehv"
        )
    if isinstance(previewer, latent_preview.TAESDPreviewerImpl):
        return Decoder(tae=inner, label="taesd")
    return None


def _core_previewer(model_patcher):
    """The core previewer, reached past any custom-node hook on `get_previewer`.

    Other packs wrap `latent_preview.get_previewer` to install previewers of their own. Calling
    the wrapped function would hand us whatever they decided to return — including, in the video
    case, an object whose `decode_latent_to_preview` doesn't produce a PIL image at all. Walking
    `__wrapped__` gets the function core actually defined. The `seen` set is not paranoia: a pack
    that wraps twice can leave the chain pointing at itself.
    """
    fn = latent_preview.get_previewer
    seen: set[int] = set()
    while hasattr(fn, "__wrapped__") and id(fn) not in seen:
        seen.add(id(fn))
        fn = fn.__wrapped__
    try:
        return fn(model_patcher.load_device, model_patcher.model.latent_format)
    except Exception as e:  # noqa: BLE001 - another pack's previewer can raise anything; we just go without one
        LOG.warning("H3 Studio preview: core previewer unavailable (%s).", e)
        return None


def _stream_channels(latent_format, latent_shapes) -> int:
    """Channel count of the stream we actually preview — the first one `_unpack` hands us.

    `latent_format.latent_channels` is NOT that for a multi-stream model. MiniMax H3's AV format
    declares 32 (the max of video 24 and audio 32, so per-stream slices stay whole), while the
    video stream a tiny VAE like taeh3 decodes is 24-channel. The sampler's `latent_shapes` know
    the real per-stream shape, so they win; the latent format is the fallback when they're absent.
    """
    if latent_shapes:
        shape = latent_shapes[0]
        if len(shape) >= 2 and int(shape[1]) > 0:
            return int(shape[1])
    return int(getattr(latent_format, "latent_channels", 0) or 0)


class FrameSource:
    """Everything needed to turn this run's x0 into frames, built once per sampling call."""

    def __init__(self, model_patcher, tiny_vae_name: str = "none", latent_shapes=None):
        lf = model_patcher.model.latent_format
        self.latent_format = lf
        self.timing = token_timing(lf)

        self.tiny: Decoder | None = None
        if tiny_vae_name and tiny_vae_name != "none":
            self.tiny = load_tiny_vae(tiny_vae_name, _stream_channels(lf, latent_shapes))

        self.core = _core_previewer(model_patcher)
        # Only consulted when more than one frame is wanted: for a single frame the core
        # previewer is already the right call and stays the one we make, so the common path is
        # byte-for-byte what ComfyUI itself would have produced.
        self.core_decoder = adopt_core_decoder(self.core)
        for decoder in (self.tiny, self.core_decoder):
            if decoder is not None:
                decoder.compile = bool(getattr(lf, "compile_preview", False))

        # Kept separately from `core` even when core IS a Latent2RGBPreviewer: it's the fallback
        # for when the core previewer returns something that isn't a PIL image, which is exactly
        # what a TAESD previewer does when handed a 5D video latent.
        self.rgb = None
        factors = getattr(lf, "latent_rgb_factors", None)
        if factors is not None:
            try:
                self.rgb = latent_preview.Latent2RGBPreviewer(
                    factors,
                    getattr(lf, "latent_rgb_factors_bias", None),
                    getattr(lf, "latent_rgb_factors_reshape", None),
                )
            except Exception as e:  # noqa: BLE001 - a latent format with odd factors costs us the fallback, not the run
                LOG.warning("H3 Studio preview: latent2rgb fallback unavailable (%s).", e)

    def usable(self) -> bool:
        return self.tiny is not None or self.core is not None or self.rgb is not None

    @property
    def label(self) -> str:
        """What the preview is actually being decoded with, for display on the node.

        Worth surfacing because the failure it diagnoses is silent and looks like a bug in this
        node: with the preview method set to TAESD but no decoder in `models/vae_approx`, core
        falls back to the colour matrix, and the only symptom is a preview at latent resolution.
        """
        if self.tiny is not None:
            return self.tiny.label
        if self.core_decoder is not None:
            return self.core_decoder.label
        if self.core is not None and not isinstance(self.core, latent_preview.Latent2RGBPreviewer):
            return type(self.core).__name__
        return "latent2rgb"

    def decode(self, x0: torch.Tensor, want: int = 1) -> list[Image.Image]:
        """Frames for one step. Empty list means "we have nothing" — caller should stand down."""
        return self.decode_clip(x0, want)[0]

    def decode_clip(
        self, x0: torch.Tensor, want: int = 1
    ) -> tuple[list[Image.Image], tuple[float, float]]:
        """Frames for one step, plus the stretch of the clip they show, as fractions 0..1.

        The span is what lets audio go with the picture. A temporal decoder only ever decodes a
        PREFIX (see `Decoder._decode_video`), so its frames cover the start of the clip, not all
        of it; the colour matrix samples the whole thing. Whatever plays under the frames has to
        be cut to the same stretch, or a preview of the first second plays the whole clip's sound.
        """
        tokens = int(x0.shape[2]) if x0.ndim == 5 else 1
        total = pixel_frames(tokens, self.timing)

        def prefix(decoder: Decoder | None, n: int) -> tuple[float, float]:
            used = decoder.prefix_tokens(tokens, n) if decoder is not None else 1
            return 0.0, (pixel_frames(used, self.timing) / total) if total else 1.0

        if self.tiny is not None:
            try:
                frames = self.tiny.decode(x0, want)
                if frames:
                    return frames, prefix(self.tiny, want)
            except Exception as e:  # noqa: BLE001 - usually OOM — the point is to drop the decoder, not to diagnose it
                # Almost always OOM: a tiny VAE upscales 8-16x, so the activations are the peak,
                # not the weights. Drop it permanently rather than retry-and-fail every step.
                LOG.warning("H3 Studio preview: tiny VAE decode failed, falling back (%s).", e)
                self.tiny = None

        if want > 1 and x0.ndim == 5:
            # Prefer core's real decoder over the colour matrix — the matrix previews at LATENT
            # resolution, so choosing it when a decoder exists throws away an 8x.
            if self.core_decoder is not None:
                try:
                    frames = self.core_decoder.decode(x0, want)
                    if frames:
                        return frames, prefix(self.core_decoder, want)
                except Exception as e:  # noqa: BLE001 - usually OOM on a long clip; the matrix still works
                    LOG.warning(
                        "H3 Studio preview: %s could not decode %d frames, using latent2rgb (%s).",
                        self.core_decoder.label,
                        want,
                        e,
                    )
                    self.core_decoder = None
            frames = self._rgb_video(x0, want)
            if frames:
                return frames, (0.0, 1.0)

        for previewer in (self.core, self.rgb):
            if previewer is None:
                continue
            try:
                out = previewer.decode_latent_to_preview(x0)
            except Exception as e:  # noqa: BLE001 - a previewer that raises is one we skip; there is another to try
                if previewer is self.core:
                    LOG.warning(
                        "H3 Studio preview: core previewer raised (%s); using latent2rgb.", e
                    )
                continue
            if isinstance(out, Image.Image):
                return [out], prefix(None, 1)
            if previewer is self.core:
                LOG.warning(
                    "H3 Studio preview: %s returned %s, not a PIL image; using latent2rgb.",
                    type(previewer).__name__,
                    type(out).__name__,
                )
        return [], (0.0, 1.0)

    def _rgb_video(self, x0: torch.Tensor, want: int) -> list[Image.Image]:
        """N frames of a 5D latent through the colour matrix, in one batched matmul.

        Core's Latent2RGBPreviewer hard-slices `x0[0, :, 0]` — the first frame, always. This is
        the same arithmetic applied to a selection of frames instead, which is what makes an
        animated preview cost about as much as a still one.
        """
        factors = getattr(self.latent_format, "latent_rgb_factors", None)
        if factors is None:
            return []
        try:
            reshape = getattr(self.latent_format, "latent_rgb_factors_reshape", None)
            if reshape is not None:
                x0 = reshape(x0)
            bias = getattr(self.latent_format, "latent_rgb_factors_bias", None)
            weight = torch.tensor(factors, device=x0.device, dtype=x0.dtype).transpose(0, 1)
            bias_t = (
                torch.tensor(bias, device=x0.device, dtype=x0.dtype) if bias is not None else None
            )

            x = x0[0]  # [C, T, H, W]
            # Evenly spaced in TIME, not in tokens: for H3 those differ (see `token_timing`).
            x = x[:, _pick_tokens_by_time(int(x.shape[1]), want, self.timing)]
            rgb = torch.nn.functional.linear(x.movedim(0, -1), weight, bias=bias_t)
            return _to_pil(rgb.add(1).mul(0.5))
        except Exception as e:  # noqa: BLE001 - a shape we cannot colour-map means no frames, not a crash
            LOG.warning("H3 Studio preview: latent2rgb video decode failed (%s).", e)
            return []
