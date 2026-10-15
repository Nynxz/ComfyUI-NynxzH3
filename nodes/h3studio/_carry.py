"""What a scene hands the scene that continues it, and how the two are joined.

**The latent tail.** H3's video encoder works in independent 17-frame clips from frame 0 and drops
its last 3 tokens, so a scene's last 17m+5 frames (the 5/22/39 a continuation carries) are exactly
its last 5m+2 latent tokens. H3 Studio Clip keeps the scene's sampled latent on the clip it outputs
(and beside the clip it saves), and the next scene guides from that tail directly: what was
sampled, without a decode and re-encode in between.

**One noise field.** A continuation regenerates the previous scene's last frames at its head. Its
noise (`SceneNoise`) gives those head tokens exactly the noise the previous scene drew for its last
tokens, so both start from the same field, and the rest of the scene its own seed's noise.

**The join.** Each continuing clip also keeps the head it regenerated (the frames Clip cuts off).
H3 Studio Join crossfades the end of the previous clip into that head, frames and sound, instead
of butt-joining: the film keeps its length, and a cut scene still joins on a hard cut.
"""

from __future__ import annotations

import math
import os
from typing import Any

import torch

FPS = 24
AUDIO_LATENT_FPS = 40
SIDECAR = ".h3.safetensors"


def context_tokens(frames: int) -> int:
    """The latent tokens that hold a scene's last `frames` (17m+5) frames: 5m+2."""
    return (frames - 5) // 17 * 5 + 2


def audio_tokens(frames: int) -> int:
    return max(1, round(frames / FPS * AUDIO_LATENT_FPS))


def latent_tail(latent: tuple[torch.Tensor, torch.Tensor], frames: int, height: int, width: int):
    """The tokens of a scene's last `frames` frames, video and audio, or None when the latent
    doesn't fit this canvas (it was rendered at another size) or is too short."""
    video, audio = latent
    if frames < 5:
        return None
    tokens = context_tokens(frames)
    if video.shape[2] < tokens or tuple(video.shape[-2:]) != (height // 16, width // 16):
        return None
    return video[:, :, -tokens:].contiguous(), audio[..., -audio_tokens(frames) :].contiguous()


class SceneNoise:
    """Core's Random Noise for a scene, except that a continuation's first tokens get exactly the
    noise the previous scene drew for the frames they regenerate. `carry` describes the previous
    scene: its seed, the shapes of its video and audio latents, and how many tokens carry over."""

    def __init__(self, seed: int, carry: dict[str, Any] | None = None):
        self.seed = seed
        self.carry = carry

    def generate_noise(self, input_latent):
        import comfy.nested_tensor
        import comfy.sample

        samples = input_latent["samples"]
        inds = input_latent.get("batch_index")
        noise = comfy.sample.prepare_noise(samples, self.seed, inds)
        if not self.carry or not getattr(samples, "is_nested", False):
            return noise
        video, audio = noise.unbind()
        batch = video.shape[0]
        before = comfy.sample.prepare_noise(
            comfy.nested_tensor.NestedTensor(
                (
                    torch.empty([batch, *self.carry["video_shape"][1:]], dtype=video.dtype),
                    torch.empty([batch, *self.carry["audio_shape"][1:]], dtype=audio.dtype),
                )
            ),
            self.carry["seed"],
            inds,
        )
        prev_video, prev_audio = before.unbind()
        t = min(self.carry["tokens"], video.shape[2], prev_video.shape[2])
        a = min(self.carry["audio_tokens"], audio.shape[-1], prev_audio.shape[-1])
        video, audio = video.clone(), audio.clone()
        if t:
            video[:, :, :t] = prev_video[:, :, -t:]
        audio[..., :a] = prev_audio[..., -a:]
        return comfy.nested_tensor.NestedTensor((video, audio))


def noise_carry(
    project: dict, index: int, context: int, latent, *, picture: bool = True
) -> dict[str, Any] | None:
    """`SceneNoise`'s description of the previous scene, for a scene continuing over `context`
    frames; `latent` is this scene's empty latent, for the channel layout. Without the `picture`
    (a cut whose sound carries on) only the audio tokens share the previous scene's noise."""
    from comfy_extras import nodes_minimax_h3 as h3

    from ._project import frames_for

    if index < 1 or context < 5:
        return None
    from ._project import compile_scene

    before = project["scenes"][index - 1]
    # The previous scene's noise is drawn again at the shape it rendered; when it rendered more than
    # its own length (a head of its own, or a handle), its last tokens aren't its end: no sharing.
    previous = compile_scene(project, index - 1)
    if previous.frames != previous.keep:
        return None
    _, latent_t, audio_t = h3.temporal_shape(frames_for(before["seconds"]))
    video, audio = latent["samples"].unbind()
    return {
        "seed": before["seed"],
        "video_shape": [video.shape[0], video.shape[1], latent_t, *video.shape[-2:]],
        "audio_shape": [audio.shape[0], *audio.shape[1:-1], audio_t],
        "tokens": context_tokens(context) if picture else 0,
        "audio_tokens": audio_tokens(context),
    }


# --- experimental, after TaoMate-H3's FL2VA streaming (github.com/TaoLiveAIGC/TaoMate-H3) ---

#: Audio latents (1 s at 40 Hz) of the lead-in: TaoMate's teacher carries this much of the previous
#: window's clean sound into the next as a frozen prefix (`fl2va/teacher.py`, `ref_audio_t=40`).
LEAD_IN_TOKENS = 40


def lead_in(audio: torch.Tensor, context: int) -> dict[str, Any] | None:
    """The previous scene's sound just before the frames a continuation carries (`context`), as an
    audio reference block: core packs a reference's audio right ahead of the scene's own audio, at
    the reference timestep (1.0), which is where and how TaoMate places its frozen prefix — so H3
    hears the second leading into the head rather than starting the head cold."""
    end = audio.shape[-1] - (audio_tokens(context) if context >= 5 else 0)
    start = max(0, end - LEAD_IN_TOKENS)
    if end - start < 1:
        return None
    z = audio[..., start:end].contiguous()
    return {"kind": "audio", "ref_audio_t": z.shape[-1], "audio_latent": z}


def _channel_stats(video: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    v = video.float().transpose(0, 1).reshape(video.shape[1], -1)
    return v.mean(dim=1), v.std(dim=1, unbiased=False).clamp(min=1e-6)


#: How far the colour match may stretch a channel's spread: the head and the tail it measures are
#: the same frames, so a bigger correction means something other than drift and is held back.
SPREAD_LIMIT = 1.5


def match_colour(model, anchor: torch.Tensor, head_tokens: int):
    """`model` with its last step's video moved so its carried head (its first `head_tokens`) has
    the per-channel mean and spread of `anchor`, the previous scene's tail that head regenerates,
    after TaoMate's per-block renormalization (`prefix_renorm`, alpha 1). Head and tail are the same
    frames, so what differs between them is drift, not content; the one correction it finds moves
    the whole scene. The anchor is the guide itself, so a chain anchors each scene to the one before
    as it finally looks. Audio is left alone; earlier steps are untouched."""
    import comfy.utils

    mean0, std0 = _channel_stats(anchor)

    def post_cfg(args):
        denoised = args["denoised"]
        sigmas = args["model_options"].get("transformer_options", {}).get("sample_sigmas")
        if sigmas is None or sigmas.shape[0] < 2 or float(sigmas[-1]) != 0.0:
            return denoised
        if not math.isclose(float(args["sigma"].flatten()[0]), float(sigmas[-2]), rel_tol=1e-4):
            return denoised
        shapes = getattr(args["model"], "latent_shapes", None)
        if not shapes or len(shapes) < 2:
            return denoised
        streams = comfy.utils.unpack_latents(denoised, shapes)
        video = streams[0]
        if video.shape[1] != mean0.shape[0] or video.shape[2] < head_tokens:
            return denoised
        mean, std = _channel_stats(video[:, :, :head_tokens])
        device = video.device
        ratio = (std0.to(device) / std.to(device)).clamp(1 / SPREAD_LIMIT, SPREAD_LIMIT)
        view = (1, -1) + (1,) * (video.ndim - 2)
        shift = mean0.to(device) - mean.to(device) * ratio
        streams[0] = (video.float() * ratio.view(view) + shift.view(view)).to(video.dtype)
        return comfy.utils.pack_latents(streams)[0]

    model = model.clone()
    model.set_model_sampler_post_cfg_function(post_cfg)
    return model


def picture_stats(frames: torch.Tensor) -> list[list[float]]:
    """Per-channel mean and spread of decoded frames (`[N, H, W, C]`, 0-1), as plain lists."""
    mean, std = _channel_stats(frames[..., :3].movedim(-1, 0).unsqueeze(0).float())
    return [mean.tolist(), std.tolist()]


def match_picture(images: torch.Tensor, anchor, head: int, chunk: int = 16) -> torch.Tensor:
    """`images` moved per channel so their first `head` frames (the carried head) have `anchor`'s
    mean and spread (`picture_stats` of the previous clip's end, the same frames): the drift the
    latent match leaves after decoding, measured where it is seen. Returns a new tensor."""
    if head < 1 or images.shape[0] < head:
        return images
    mean0, std0 = (torch.tensor(v, dtype=torch.float32) for v in anchor)
    mean, std = (torch.tensor(v, dtype=torch.float32) for v in picture_stats(images[:head]))
    ratio = (std0 / std).clamp(1 / SPREAD_LIMIT, SPREAD_LIMIT)
    shift = mean0 - mean * ratio
    out = images.clone()
    ratio, shift = ratio.to(out.device, out.dtype), shift.to(out.device, out.dtype)
    for a in range(0, out.shape[0], chunk):
        part = out[a : a + chunk, ..., :3]
        part.mul_(ratio).add_(shift).clamp_(0.0, 1.0)
    return out


# --- beside a saved clip: its latent and its regenerated head, so a reused clip carries them too ---


def save_sidecar(clip_path: str, latent, head, tail=None) -> None:
    """Beside a clip: its latent, the head it regenerated over the previous scene, and the sound
    past its end (its handle, see `_project.HANDLE`) that the next scene's start can fade over."""
    from safetensors.torch import save_file

    tensors, meta = {}, {}
    if tail is not None:
        tensors["tail_audio"] = tail["waveform"].detach().cpu().float().contiguous()
        meta["tail_rate"] = str(tail["sample_rate"])
    if latent is not None:
        tensors["video"], tensors["audio"] = (t.detach().cpu().contiguous() for t in latent)
    if head is not None:
        frames, sound, picture = head
        meta["head_picture"] = "1" if picture else "0"
        tensors["head"] = (frames.clamp(0, 1) * 255).round().to(torch.uint8).cpu().contiguous()
        if sound is not None:
            tensors["head_audio"] = sound["waveform"].detach().cpu().float().contiguous()
            meta["sample_rate"] = str(sound["sample_rate"])
    if tensors:
        save_file(tensors, clip_path + SIDECAR, metadata=meta)


def load_tail(clip_path: str) -> dict | None:
    """The sound past a clip's end (its handle), saved beside it, or None."""
    from safetensors import safe_open

    path = clip_path + SIDECAR
    if not os.path.isfile(path):
        return None
    with safe_open(path, framework="pt") as f:
        if "tail_audio" not in set(f.keys()):
            return None
        rate = int((f.metadata() or {}).get("tail_rate", 44100))
        return {"waveform": f.get_tensor("tail_audio"), "sample_rate": rate}


def load_sidecar(clip_path: str):
    """(latent, head) saved beside a clip; either may be None."""
    from safetensors import safe_open

    path = clip_path + SIDECAR
    if not os.path.isfile(path):
        return None, None
    with safe_open(path, framework="pt") as f:
        keys, meta = set(f.keys()), f.metadata() or {}
        latent = (f.get_tensor("video"), f.get_tensor("audio")) if "video" in keys else None
        head = None
        if "head" in keys:
            sound = None
            if "head_audio" in keys:
                sound = {
                    "waveform": f.get_tensor("head_audio"),
                    "sample_rate": int(meta.get("sample_rate", 44100)),
                }
            head = (
                f.get_tensor("head").float() / 255.0,
                sound,
                meta.get("head_picture", "1") == "1",
            )
    return latent, head


# --- the join ------------------------------------------------------------------------------------


def _silence(frames: int, like: dict) -> torch.Tensor:
    w = like["waveform"]
    return torch.zeros((*w.shape[:-1], round(frames / FPS * like["sample_rate"])), dtype=w.dtype)


def join(
    videos: list,
    crossfade: int,
    music: dict | None = None,
    music_volume: float = 1.0,
    music_fade: float = 2.0,
):
    """The clips as one video at 24 fps. Where a clip carries the head it regenerated over the end
    of the one before (`h3_head`), the last `crossfade` frames of that one fade into it — the
    picture linearly (unless the picture cut, and only the sound carried), the sound with
    equal-power gains — so the film keeps its length. `music`, when given, plays under the whole
    film at `music_volume`, fading out over its last `music_fade` seconds."""
    from fractions import Fraction

    from comfy_api.latest import InputImpl, Types

    parts = []
    for v in videos:
        c = v.get_components()
        parts.append((c.images, c.audio, getattr(v, "h3_head", None)))
    like = next((p[1] for p in parts if p[1] is not None), None)
    # A skipped scene's black stand-in takes the size of the rendered ones.
    shape = next(
        (
            c.shape[1:]
            for v, (c, _, _) in zip(videos, parts, strict=True)
            if not getattr(v, "h3_blank", False)
        ),
        None,
    )
    if shape is not None:
        parts = [
            (images.new_zeros((images.shape[0], *shape)), audio, head)
            if getattr(v, "h3_blank", False)
            else (images, audio, head)
            for v, (images, audio, head) in zip(videos, parts, strict=True)
        ]

    frames: list[torch.Tensor] = []
    sound: list[torch.Tensor] = []
    # The sound past each clip's end (its handle), where it rendered one.
    tails = [getattr(v, "h3_tail", None) for v in videos]
    for i, (images, audio, head) in enumerate(parts):
        handle = tails[i - 1] if i > 0 and head is not None and crossfade > 0 else None
        if like is not None and audio is None:
            audio = {
                "waveform": _silence(images.shape[0], like),
                "sample_rate": like["sample_rate"],
            }
        k = 0
        if head is not None and frames and crossfade > 0:
            head_frames, head_audio, head_picture = head
            k = min(crossfade, head_frames.shape[0], frames[-1].shape[0])
            if head_picture and head_frames.shape[1:] != frames[-1].shape[1:]:
                k = 0
        if k:
            if head_picture:
                w = torch.linspace(1, k, k, dtype=frames[-1].dtype).div(k + 1).view(k, 1, 1, 1)
                tail = frames[-1][-k:] * (1 - w) + head_frames[-k:].to(frames[-1].dtype) * w
                frames[-1] = torch.cat([frames[-1][:-k], tail])
            # With a handle the previous scene's own sound runs on past the cut instead (below).
            if sound and head_audio is not None and like is not None and handle is None:
                n = min(
                    round(k / FPS * like["sample_rate"]),
                    sound[-1].shape[-1],
                    head_audio["waveform"].shape[-1],
                )
                if n > 0 and head_audio["waveform"].shape[:-1] == sound[-1].shape[:-1]:
                    t = torch.linspace(0, 1, n, dtype=sound[-1].dtype) * (math.pi / 2)
                    faded = sound[-1][..., -n:] * torch.cos(t) + head_audio["waveform"][
                        ..., -n:
                    ].to(sound[-1].dtype) * torch.sin(t)
                    sound[-1] = torch.cat([sound[-1][..., :-n], faded], dim=-1)
        frames.append(images)
        if audio is not None:
            waveform = audio["waveform"]
            if handle is not None and like is not None:
                waveform = _over(waveform, handle, like["sample_rate"])
            sound.append(waveform)
    out_audio = (
        {"waveform": torch.cat(sound, dim=-1), "sample_rate": like["sample_rate"]}
        if sound and like is not None
        else None
    )
    film_frames = sum(f.shape[0] for f in frames)
    if music is not None:
        out_audio = _under(out_audio, music, film_frames / FPS, music_volume, music_fade)
    images = torch.cat(frames)
    return InputImpl.VideoFromComponents(
        Types.VideoComponents(images=images, frame_rate=Fraction(FPS), audio=out_audio)
    )


def _over(scene: torch.Tensor, handle: dict, rate: int) -> torch.Tensor:
    """A scene's start with the previous scene's handle laid over it: the previous scene's own
    sound running on past the cut and fading out (equal-power) as this scene's fades in."""
    import comfy.audio

    tail = handle["waveform"].to(scene.dtype)
    if handle["sample_rate"] != rate:
        tail = comfy.audio.resample(tail, handle["sample_rate"], rate)
    if tail.shape[:-1] != scene.shape[:-1]:
        tail = tail.mean(dim=1, keepdim=True).expand(*scene.shape[:-1], tail.shape[-1])
    n = min(tail.shape[-1], scene.shape[-1])
    if n <= 0:
        return scene
    t = torch.linspace(0, 1, n, dtype=scene.dtype) * (math.pi / 2)
    mixed = scene[..., :n] * torch.sin(t) + tail[..., :n] * torch.cos(t)
    return torch.cat([mixed, scene[..., n:]], dim=-1)


def _under(film: dict | None, music: dict, seconds: float, volume: float, fade: float) -> dict:
    """`music` mixed under the film's sound: resampled and matched in channels to it, cut or padded
    with silence to its length (or to `seconds` when the film is silent), fading out over its last
    `fade` seconds."""
    import comfy.audio

    rate = film["sample_rate"] if film is not None else music["sample_rate"]
    track = music["waveform"][:1].float()
    if music["sample_rate"] != rate:
        track = comfy.audio.resample(track, music["sample_rate"], rate)
    length = film["waveform"].shape[-1] if film is not None else round(seconds * rate)
    channels = film["waveform"].shape[1] if film is not None else track.shape[1]
    if track.shape[1] != channels:
        track = track.mean(dim=1, keepdim=True).expand(-1, channels, -1)
    track = track[..., :length]
    if track.shape[-1] < length:
        track = torch.nn.functional.pad(track, (0, length - track.shape[-1]))
    n = min(round(fade * rate), length)
    if n > 0:
        track = track.clone()
        track[..., -n:] *= torch.linspace(1, 0, n)
    track = track * volume
    if film is None:
        return {"waveform": track, "sample_rate": rate}
    mixed = film["waveform"].float() + track
    return {"waveform": mixed.clamp(-1, 1), "sample_rate": rate}
