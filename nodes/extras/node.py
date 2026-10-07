"""H3 Extras — the canvas back out as plain numbers.

The canvas lives on H3 Inputs because that is where it belongs next to the assets it frames, but
plenty of graphs still want the numbers: an upscale that needs the width, a save node naming
files by duration, a preview sized to match. This breaks them out rather than making you keep a
second copy in sync by hand.

**Three of the outputs are the interesting ones**, because they are what the request became
rather than what it asked for:

  * `frame_count` — `length` snapped **up** onto the model's `17k+5` grid. Ask for 130 and you
    get 141. Nothing warns you about this anywhere else.
  * `latent_t` / `audio_t` — the video and audio latent lengths that follow, which is what the
    sequence length and therefore the sampling cost are actually made of.
  * `seconds` — `frame_count / 24`, the real duration.

Wire `h3_inputs` in anywhere along the chain; it reads the canvas, not the assets.
"""

from __future__ import annotations

from comfy_api.latest import io

from .. import _core
from .._base import CATEGORY, PackNode
from ..encode import _encode
from ..inputs import _payload
from ..inputs.types import H3InputData


class H3Extras(PackNode):
    CATEGORY = f"{CATEGORY}/Conditioning"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3Extras",
            display_name="H3 Extras",
            description="The canvas from an h3_inputs wire, as plain numbers: width, height, the "
            "requested length and the frame count it snaps up to, the video and audio latent "
            "lengths, and the real duration in seconds.",
            inputs=[
                H3InputData.Input(
                    "h3_inputs",
                    tooltip="From H3 Inputs, or anywhere along the chain.",
                ),
                io.Combo.Input(
                    "mode",
                    options=list(_encode.MODES),
                    default="auto",
                    tooltip="Match whatever H3 Encode is set to, so the task reported here is the "
                    "task that will actually run.",
                ),
            ],
            outputs=[
                io.Int.Output(display_name="width"),
                io.Int.Output(display_name="height"),
                io.Int.Output(display_name="length", tooltip="The length the canvas asked for."),
                io.Int.Output(
                    display_name="frame_count",
                    tooltip="What it snaps up to on the model's 17k+5 grid — the frames you "
                    "actually get.",
                ),
                io.Int.Output(display_name="latent_t", tooltip="Video latent frames."),
                io.Int.Output(display_name="audio_t", tooltip="Audio latent frames (40 Hz)."),
                io.Float.Output(display_name="seconds", tooltip="frame_count / 24."),
                io.String.Output(
                    display_name="task",
                    tooltip="t2va, fl2va or ref2va — what the same list will make H3 Encode do.",
                ),
                io.Boolean.Output(
                    display_name="is_keyframes",
                    tooltip="True for fl2va — a first and/or last frame is driving the clip. "
                    "Wire into a switch to branch a graph on it.",
                ),
                io.Boolean.Output(
                    display_name="is_references",
                    tooltip="True for ref2va — <Picture i> / <Video k> / <Audio j> references.",
                ),
                io.String.Output(
                    display_name="summary",
                    tooltip="One line naming all of it, for a text preview.",
                ),
            ],
        )

    @classmethod
    def execute(cls, h3_inputs, mode="auto") -> io.NodeOutput:
        canvas = _payload.canvas_of(h3_inputs)
        task = _encode.plan(_payload.items_of(h3_inputs), mode)["task"]
        width, height, length = canvas["width"], canvas["height"], canvas["length"]
        frame_count, latent_t, audio_t = _core.temporal_shape(length)
        fps = _core.constants()["fps"]
        seconds = frame_count / float(fps)
        snapped = "" if frame_count == length else f" (asked {length})"
        summary = (
            f"{task} · {width}x{height} · {frame_count} frames{snapped} · {seconds:.2f}s @ "
            f"{fps}fps · latent_t {latent_t}, audio_t {audio_t} · refs {canvas['ref_image_size']}"
        )
        return io.NodeOutput(
            width,
            height,
            length,
            frame_count,
            latent_t,
            audio_t,
            round(seconds, 3),
            task,
            task == "fl2va",
            task == "ref2va",
            summary,
        )
