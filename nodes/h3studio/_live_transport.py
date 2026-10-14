"""Getting a step's frames to the browser without making the sampler wait for it.

Vendored from Model Preview Override in ComfyUI-NynxzPersonal (same author, MIT), so H3 Studio
previews on its own without that pack. Keep the two in step when either changes.

Two problems, one file.

**Encoding must not block the sampler.** The callback runs on the sampling thread, between
denoise steps. Encoding an animated clip there adds its own time to every step — and worse, it
adds it invisibly, so the node would be reporting step times it caused. Everything past the
tensor->PIL decode happens on `AsyncEncoder`'s thread, and its queue is bounded and *drops* when
full: a preview that arrives late is worth less than the step it delayed. Two in flight is enough
to cover one slow encode without ever building a backlog.

**The wire format depends on what the browser will accept.** A still is a JPEG. A clip is an
NVENC-encoded fragmented MP4 when that's available — roughly an order of magnitude faster to
encode and several times smaller than PIL's animated WebP — and an animated WebP when it isn't.
Both arrive base64'd inside the websocket message rather than as a file the browser fetches back,
because a preview is worth nothing by the time a round trip has completed.

PyAV is already a ComfyUI dependency, so encoding runs in-process and needs no ffmpeg on PATH.
"""

from __future__ import annotations

import base64
import contextlib
import fractions
import io as pyio
import logging
import queue
import threading
from collections.abc import Callable

import numpy as np
from PIL import Image, ImageOps

#: NVENC refuses to open below roughly this size and reports it only as `avcodec_open2 ... 22`.
#: Measured in ComfyUI-NynxzNodes' `save_video/encode.py`: 64x64 fails, 256x256 succeeds.
#:
#: Copied rather than imported. It arrived here as `from ..save_video.encode import NVENC_MIN_EDGE`,
#: and save_video is not in this pack — reaching across two installed packs for one integer would
#: make this node fail to import whenever the other pack is absent or renamed. If the measurement
#: is ever revised, both copies want updating.
NVENC_MIN_EDGE = 160

try:
    from server import PromptServer
except ImportError:  # running outside a ComfyUI server (tests)
    PromptServer = None

LOG = logging.getLogger(__name__)

#: Websocket message name. The studio's `frontend/lib/h3live.ts` listens for it.
EVENT = "nynxz.h3studio.preview"


def _probe_nvenc() -> bool:
    # PyPI PyAV wheels are commonly built without NVENC, so its presence is a property of the
    # installed wheel and not of the GPU. Probe once at import rather than per encode.
    try:
        import av

        av.Codec("h264_nvenc", "w")
        return True
    except Exception:  # noqa: BLE001 - no NVENC in this PyAV build; WebP covers it
        return False


def _csp_blocks_video() -> bool:
    # `--disable-api-nodes` installs a Content-Security-Policy with no media-src, which silently
    # kills `blob:` video in the browser — the preview would just never appear. WebP is an <img>
    # and stays allowed, so detect the flag and never offer MP4 under it.
    try:
        from comfy.cli_args import args

        return bool(getattr(args, "disable_api_nodes", False))
    except Exception:  # noqa: BLE001 - no cli_args to read means no such flag
        return False


def _probe_encoder(name: str) -> bool:
    try:
        import av

        av.Codec(name, "w")
        return True
    except Exception:  # noqa: BLE001 - not in this PyAV build
        return False


_HAS_NVENC = _probe_nvenc()
_VIDEO_ALLOWED = not _csp_blocks_video()
NVENC_AVAILABLE = _HAS_NVENC and _VIDEO_ALLOWED
if _HAS_NVENC and not NVENC_AVAILABLE:
    LOG.info("H3 Studio preview: --disable-api-nodes blocks blob: video; using WebP for clips.")

#: A clip with sound has to be an MP4 — WebP has no audio track. NVENC is preferred as always, but
#: a clip with audio is worth a software encode when NVENC is missing or refuses the size, so
#: libx264 is the fallback for those clips only. Silent clips keep the NVENC-or-WebP behaviour.
AUDIO_AVAILABLE = (
    _VIDEO_ALLOWED and _probe_encoder("aac") and (_HAS_NVENC or _probe_encoder("libx264"))
)
_X264 = _probe_encoder("libx264")

_nvenc_warned = False


class AsyncEncoder:
    """Off-thread encode queue. Bounded, drops when full, so sampling never waits on us."""

    _STOP = object()

    def __init__(self, max_in_flight: int = 2):
        self.q: queue.Queue = queue.Queue(maxsize=max_in_flight)
        self.thread = threading.Thread(
            target=self._run, name="h3studio_preview_encoder", daemon=True
        )
        self.thread.start()

    def submit(self, fn: Callable[[], None]) -> bool:
        """Queue an encode. False means it was dropped because the queue was full."""
        try:
            self.q.put_nowait(fn)
            return True
        except queue.Full:
            return False

    def _run(self) -> None:
        while True:
            item = self.q.get()
            if item is self._STOP:
                return
            try:
                item()
            except Exception:
                LOG.exception("H3 Studio preview: encoder thread error")

    def shutdown(self, drain_timeout: float = 5.0) -> None:
        # Best-effort drain: a full queue at shutdown means previews we were going to drop
        # anyway, so there is nothing to recover and nothing to report.
        with contextlib.suppress(queue.Full):
            self.q.put(self._STOP, timeout=drain_timeout)
        self.thread.join(timeout=drain_timeout)


def _fit(frame: Image.Image, max_res: int) -> Image.Image:
    """RGB, and no larger than `max_res` on its long edge. `max_res <= 0` means don't touch it."""
    out = frame if frame.mode == "RGB" else frame.convert("RGB")
    if max_res and max_res > 0 and (out.width > max_res or out.height > max_res):
        out = ImageOps.contain(out, (max_res, max_res), Image.LANCZOS)
    return out


def encode_still(frame: Image.Image, max_res: int, quality: int) -> tuple[str, int, int, str]:
    out = _fit(frame, max_res)
    buf = pyio.BytesIO()
    out.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("ascii"), out.width, out.height, "image/jpeg"


def _encode_mp4(frames: list[Image.Image], fps, max_res: int, audio=None):
    """H.264 in a fragmented MP4. Returns (None, 0, 0) whenever the caller should use WebP.

    Fragmented (`frag_keyframe+empty_moov`) so the browser can start decoding before the whole
    blob has been handed over — with a non-fragmented MP4 the moov atom lands last and a short
    clip shows nothing until it is fully assembled.

    `audio` is `(samples [2, L] float32, sample_rate)`, muxed as an AAC track. With audio, `fps`
    is a Fraction chosen by the caller so the picture lasts exactly as long as the sound.
    """
    global _nvenc_warned
    if not frames:
        return None, 0, 0
    try:
        import av
    except Exception:  # noqa: BLE001 - no PyAV, no MP4
        return None, 0, 0

    fitted = [_fit(f, max_res) for f in frames]
    # yuv420p subsamples chroma 2x2, so both dimensions have to be even.
    w0, h0 = fitted[0].width, fitted[0].height
    out_w, out_h = w0 & ~1, h0 & ~1
    if (out_w, out_h) != (w0, h0):
        fitted = [f.resize((out_w, out_h), Image.LANCZOS) for f in fitted]

    # Which option combinations NVENC accepts varies by driver and card, and a rejection surfaces
    # only as a generic open failure. Try the tuned one, then the bare preset, which always works.
    attempts: list[tuple[str, dict]] = []
    if NVENC_AVAILABLE and min(out_w, out_h) >= NVENC_MIN_EDGE:
        attempts += [
            ("h264_nvenc", {"preset": "p1", "rc": "vbr", "cq": "23"}),
            ("h264_nvenc", {"preset": "p1"}),
        ]
    if audio is not None and _X264 and _VIDEO_ALLOWED and min(out_w, out_h) >= 2:
        attempts.append(("libx264", {"preset": "ultrafast", "crf": "23"}))
    if not attempts:
        return None, 0, 0

    rate = fps if isinstance(fps, fractions.Fraction) else int(max(1, fps))
    last_err: Exception | None = None
    for codec, opts in attempts:
        buf = pyio.BytesIO()
        try:
            container = av.open(
                buf,
                mode="w",
                format="mp4",
                options={"movflags": "frag_keyframe+empty_moov+default_base_moof"},
            )
            stream = container.add_stream(codec, rate=rate)
            stream.width, stream.height = out_w, out_h
            stream.pix_fmt = "yuv420p"
            stream.options = opts
            astream = None
            if audio is not None:
                astream = container.add_stream("aac", rate=int(audio[1]), layout="stereo")
            for f in fitted:
                for packet in stream.encode(av.VideoFrame.from_image(f)):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
            if astream is not None:
                # One frame for the whole slice: PyAV re-chunks it to AAC's 1024-sample frames.
                chunk = av.AudioFrame.from_ndarray(
                    np.ascontiguousarray(audio[0], dtype=np.float32), format="fltp", layout="stereo"
                )
                chunk.sample_rate = int(audio[1])
                chunk.pts = 0
                for packet in astream.encode(chunk):
                    container.mux(packet)
                for packet in astream.encode():
                    container.mux(packet)
            container.close()
            return base64.b64encode(buf.getvalue()).decode("ascii"), out_w, out_h
        except Exception as e:  # noqa: BLE001 - the encoder rejected these options; try the next set
            last_err = e

    if not _nvenc_warned:
        _nvenc_warned = True
        LOG.warning("H3 Studio preview: MP4 encode failed, using WebP (%s).", last_err)
    return None, 0, 0


def _encode_webp(frames: list[Image.Image], fps: int, quality: int, max_res: int):
    if not frames:
        return None, 0, 0
    fitted = [_fit(f, max_res) for f in frames]
    buf = pyio.BytesIO()
    try:
        fitted[0].save(
            buf,
            format="WEBP",
            save_all=True,
            append_images=fitted[1:],
            duration=max(1, round(1000 / max(1, fps))),
            loop=0,
            quality=quality,
            method=4,
        )
    except Exception as e:  # noqa: BLE001 - a frame set PIL will not encode is a dropped preview
        LOG.warning("H3 Studio preview: animated WebP encode failed (%s).", e)
        return None, 0, 0
    return base64.b64encode(buf.getvalue()).decode("ascii"), fitted[0].width, fitted[0].height


def encode_clip(frames: list[Image.Image], fps: int, quality: int, max_res: int):
    """Frames -> (b64, width, height, mime). `(None, 0, 0, None)` if nothing could be encoded."""
    if NVENC_AVAILABLE:
        b64, w, h = _encode_mp4(frames, fps, max_res)
        if b64:
            return b64, w, h, "video/mp4"
    b64, w, h = _encode_webp(frames, fps, quality, max_res)
    return (b64, w, h, "image/webp") if b64 else (None, 0, 0, None)


def encode_clip_with_audio(frames: list[Image.Image], samples, sample_rate: int, max_res: int):
    """Frames + the audio under them -> (b64, width, height, mime, fps), or None to go silent.

    The frame rate is not the widget's: it is whatever makes `len(frames)` last exactly as long
    as the audio, so the clip plays in real time and the picture stays on the sound.
    """
    if not AUDIO_AVAILABLE or len(frames) < 2 or samples is None or samples.shape[1] <= 0:
        return None
    fps = fractions.Fraction(len(frames) * sample_rate, samples.shape[1]).limit_denominator(1000)
    if fps <= 0:
        return None
    b64, w, h = _encode_mp4(frames, fps, max_res, audio=(samples, sample_rate))
    return (b64, w, h, "video/mp4", float(fps)) if b64 else None


def encode(frames: list[Image.Image], fps: int, quality: int, max_res: int):
    """One frame is a still; more than one is a clip."""
    if not frames:
        return None, 0, 0, None
    if len(frames) == 1:
        return encode_still(frames[0], max_res, quality)
    return encode_clip(frames, fps, quality, max_res)


def send(payload: dict) -> None:
    """Push one message to the client that queued this prompt. Never raises."""
    if PromptServer is None:
        return
    try:
        PromptServer.instance.send_sync(EVENT, payload, PromptServer.instance.client_id)
    except Exception as e:  # noqa: BLE001 - a dead websocket must not take the sampler down with it
        LOG.debug("H3 Studio preview: send failed (%s).", e)
