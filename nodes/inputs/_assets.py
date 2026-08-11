"""Frame-rate resampling for wired IMAGE batches.

H3 presents reference video at 24 fps and derives its `<T.T seconds>` timestamps from that, so
frames arriving at another rate are presented at the wrong speed with timestamps wrong by the
same factor. A wired IMAGE batch does not know its own rate, which is why H3 Video asks.
"""

from __future__ import annotations

import torch

TARGET_FPS = 24.0


def resample_to_fps(frames: torch.Tensor, source_fps: float, target_fps: float = TARGET_FPS):
    """Nearest-neighbour resample of a frame batch onto `target_fps`.

    Nearest-neighbour and not interpolation on purpose: these frames become reference *latents*
    and Qwen vision blocks, and a blended frame is a picture that was never in the video. Losing
    or repeating a frame is honest; inventing one is not.
    """
    if source_fps <= 0 or abs(source_fps - target_fps) < 1e-3 or frames.shape[0] < 2:
        return frames
    duration = frames.shape[0] / source_fps
    count = max(1, round(duration * target_fps))
    index = (torch.arange(count, dtype=torch.float64) * (source_fps / target_fps)).round().long()
    return frames[index.clamp(max=frames.shape[0] - 1)]
