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
    before = project["scenes"][index - 1]
    _, latent_t, audio_t = h3.temporal_shape(frames_for(before["seconds"]))
    video, audio = latent["samples"].unbind()
    return {
        "seed": before["seed"],
        "video_shape": [video.shape[0], video.shape[1], latent_t, *video.shape[-2:]],
        "audio_shape": [audio.shape[0], *audio.shape[1:-1], audio_t],
        "tokens": context_tokens(context) if picture else 0,
        "audio_tokens": audio_tokens(context),
    }


# --- beside a saved clip: its latent and its regenerated head, so a reused clip carries them too ---


def save_sidecar(clip_path: str, latent, head) -> None:
    from safetensors.torch import save_file

    tensors, meta = {}, {}
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
    for images, audio, head in parts:
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
            if sound and head_audio is not None and like is not None:
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
            sound.append(audio["waveform"])
    out_audio = (
        {"waveform": torch.cat(sound, dim=-1), "sample_rate": like["sample_rate"]}
        if sound and like is not None
        else None
    )
    film_frames = sum(f.shape[0] for f in frames)
    if music is not None:
        out_audio = _under(out_audio, music, film_frames / FPS, music_volume, music_fade)
    return InputImpl.VideoFromComponents(
        Types.VideoComponents(images=torch.cat(frames), frame_rate=Fraction(FPS), audio=out_audio)
    )


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
