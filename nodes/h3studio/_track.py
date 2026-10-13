"""The film's music track: one song under the whole film, cut to each scene as it renders.

A scene on the track is shown its own stretch of the song as an audio guide over the whole scene,
so H3 makes the picture to the music — lips, beats and cuts land where the song has them — instead
of writing its own. The finished film then plays the song itself where those scenes are, not what
H3 made of it (or lays it under their sound, or leaves the scenes' sound alone).
"""

from __future__ import annotations

import math

import torch

from ._media import load_audio
from ._project import FPS

#: The song, decoded once per file: every scene of a render cuts from the same one.
_loaded: dict = {}
#: Seconds the song and the scenes' own sound fade across where the film leaves or rejoins it.
JOIN_SECONDS = 0.02


def song(media: str) -> dict:
    from . import _reuse

    key = (media, tuple(_reuse.media_stat(media)))
    if _loaded.get("key") != key:
        _loaded.clear()
        _loaded.update(key=key, audio=load_audio(media))
    return _loaded["audio"]


def guide(track: dict, latent: dict, audio_vae, h3, warnings: list[str]) -> dict | None:
    """The scene's stretch of the song as an audio guide from where the scene starts (after a
    carried head) to the end of what H3 renders, or None when the song has ended by then."""
    audio = song(track["media"])
    rate = audio["sample_rate"]
    total = audio["waveform"].shape[-1]
    a = round(track["start"] * rate)
    b = min(total, round((track["start"] + track["seconds"]) * rate))
    if b - a < round(0.2 * rate):
        warnings.append(
            f"The music track ends before this scene ({total / rate:.1f} s long, the scene starts "
            f"{track['start']:.1f} s in), so it renders without it."
        )
        return None
    if b < round((track["start"] + track["seconds"]) * rate) - round(0.2 * rate):
        warnings.append(
            f"The music track ends {(b - a) / rate:.1f} s into this scene; the rest is H3's own sound."
        )
    part = {"waveform": audio["waveform"][..., a:b], "sample_rate": rate}
    z, rt = h3._encode_ref_audio(audio_vae, part)
    room = math.floor(latent["samples"].unbind()[1].shape[-1] - h3.FRAME_RESCALE * track["frame"])
    if rt > room:
        z = z[..., :room].clone()
    return {"resolved_frame_index": track["frame"], "audio_latent": z, "image": None}


def film_sound(proj: dict, sound, counts: list[int], rate: int, channels: int):
    """The film's sound ([C, L], or None when silent) with the song in it: in place of the scenes on
    the track ("track"), under everything ("mix"), or not at all ("scenes")."""
    import comfy.audio

    track = proj.get("track")
    if not track or track["sound"] == "scenes":
        return sound
    length = round(sum(counts) / FPS * rate)
    audio = song(track["media"])
    wave = audio["waveform"][0].float()
    if audio["sample_rate"] != rate:
        wave = comfy.audio.resample(wave[None], audio["sample_rate"], rate)[0]
    if wave.shape[0] != channels:
        wave = wave.mean(dim=0, keepdim=True).expand(channels, -1)
    start = round(track["offset"] * rate)
    wave = wave[:, start : start + length]
    if wave.shape[-1] < length:
        wave = torch.nn.functional.pad(wave, (0, length - wave.shape[-1]))
    wave = wave * track["volume"]
    base = sound[..., :length] if sound is not None else torch.zeros((channels, length))
    if base.shape[-1] < length:
        base = torch.nn.functional.pad(base, (0, length - base.shape[-1]))
    if track["sound"] == "mix":
        return (base + wave).clamp(-1, 1)
    gain = torch.zeros(length)
    at = 0
    for scene, n in zip(proj["scenes"], counts, strict=True):
        a, b = round(at / FPS * rate), round((at + n) / FPS * rate)
        if scene.get("track", True):
            gain[a:b] = 1.0
        at += n
    k = max(1, round(JOIN_SECONDS * rate))
    smooth = torch.nn.functional.avg_pool1d(gain[None, None], k, stride=1, padding=k // 2)[0, 0]
    smooth = smooth[:length]
    if smooth.shape[-1] < length:
        smooth = torch.nn.functional.pad(smooth, (0, length - smooth.shape[-1]), value=gain[-1])
    t = smooth * (math.pi / 2)
    return base * torch.cos(t) + wave * torch.sin(t)
