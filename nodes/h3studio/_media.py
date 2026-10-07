"""Loading a project's media refs (`input/sub/name.png`) as IMAGE tensors."""

from __future__ import annotations

import os

import numpy as np
import torch
from PIL import Image, ImageOps

try:
    import folder_paths
except ImportError:  # pragma: no cover - outside ComfyUI
    folder_paths = None

FOLDERS = ("input", "output", "temp")


def path_of(ref: str) -> str:
    """The file a ref names, refusing anything outside ComfyUI's input/output/temp folders."""
    folder, _, rest = ref.partition("/")
    if folder not in FOLDERS or not rest or folder_paths is None:
        raise ValueError(
            f"H3 Studio: '{ref}' is not a ComfyUI file (input/..., output/..., temp/...)."
        )
    base = os.path.realpath(folder_paths.get_directory_by_type(folder))
    path = os.path.realpath(os.path.join(base, rest))
    if os.path.commonpath([base, path]) != base:
        raise ValueError(f"H3 Studio: '{ref}' points outside the {folder} folder.")
    if not os.path.isfile(path):
        raise ValueError(f"H3 Studio: '{ref}' does not exist — was it moved or deleted?")
    return path


def load_image(ref: str) -> torch.Tensor:
    """[1, H, W, 3] float in 0..1, EXIF orientation applied."""
    with Image.open(path_of(ref)) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        array = np.asarray(img, dtype=np.float32) / 255.0
    return torch.from_numpy(array)[None]


def load_video(ref: str, fps: int = 24) -> tuple[torch.Tensor, dict | None]:
    """[T, H, W, 3] frames resampled to `fps` (H3 reads reference video at 24 fps), and the
    soundtrack as an AUDIO dict when the file has one."""
    from comfy_api.latest import InputImpl

    components = InputImpl.VideoFromFile(path_of(ref)).get_components()
    images = components.images
    source_fps = float(components.frame_rate) or float(fps)
    if images.shape[0] and abs(source_fps - fps) > 0.01:
        count = max(1, round(images.shape[0] * fps / source_fps))
        index = torch.clamp(
            (torch.arange(count) * source_fps / fps).round().long(), max=images.shape[0] - 1
        )
        images = images[index]
    return images[..., :3], components.audio


def load_audio(ref: str) -> dict:
    """An AUDIO dict ({waveform [1, C, L], sample_rate})."""
    from comfy_extras.nodes_audio import load

    waveform, sample_rate = load(path_of(ref))
    return {"waveform": waveform.unsqueeze(0), "sample_rate": sample_rate}


def has_audio(ref: str) -> bool:
    """Whether a media file carries a soundtrack (False when it cannot be read)."""
    import av

    try:
        with av.open(path_of(ref)) as container:
            return bool(container.streams.audio)
    except Exception:  # noqa: BLE001 - an unreadable file simply has no usable soundtrack
        return False
