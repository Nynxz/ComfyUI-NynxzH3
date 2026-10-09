"""When in a scene a control video steers it.

A control can be limited to a stretch of the scene (`from` to `to`, seconds of the scene's own clock):
the ControlNet's push on each latent frame is scaled by how much of that frame falls in the
stretch, easing in and out over FADE seconds at its ends so the hand-over doesn't jolt. Pure
arithmetic, kept apart from the patch so it can be tested without a model.
"""

from __future__ import annotations

FPS = 24
#: Seconds over which a limited control eases in before `from` and out after `to`.
FADE = 0.25
#: Pixel frames per latent frame, repeating every five latents (MiniMax H3's VAE: 17 frames / 5).
FRAMES_PER_LATENT = (1, 4, 4, 4, 4)


def window_weight(t: float, start: float | None, end: float | None, fade: float = FADE) -> float:
    """How hard the control steers at scene time `t`: 1 inside the window, 0 well outside it."""
    w = 1.0
    if start is not None:
        w = min(w, max(0.0, (t - start) / fade + 1.0))
    if end is not None:
        w = min(w, max(0.0, (end - t) / fade + 1.0))
    return w


def latent_weights(
    latent_t: int, start: float | None, end: float | None, lead: int = 0, fps: int = FPS
) -> list[float]:
    """One weight per latent frame. `lead` pixel frames (a carried head) come before the scene's
    own frame 0; each latent is weighed at the middle of the pixel frames it covers."""
    out = []
    first = 0
    for k in range(latent_t):
        span = FRAMES_PER_LATENT[k % 5]
        middle = first + (span - 1) / 2
        out.append(window_weight((middle - lead) / fps, start, end))
        first += span
    return out


def describe(start: float | None, end: float | None) -> str:
    """'from 1.5 s to 3 s', 'from 2 s', 'until 2.5 s', or '' for the whole scene."""
    num = lambda s: f"{s:g} s"  # noqa: E731
    if start is not None and end is not None:
        return f"from {num(start)} to {num(end)}"
    if start is not None:
        return f"from {num(start)}"
    if end is not None:
        return f"until {num(end)}"
    return ""
