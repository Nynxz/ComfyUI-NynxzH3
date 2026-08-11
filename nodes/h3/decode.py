"""MiniMax H3 Decode Frames — one frame out of a video latent, at one frame's cost.

Wire it where a VAE Decode would go. It returns the frames you asked for and decodes only the
latent tokens those frames are made of, which for a 124-frame clip is one seventh of the work per
frame — and one seventh of the peak VRAM, because a chunk decode is all that is ever resident.

**Why this is not "slice the latent, then decode".** The H3 decoder is a ViT that attends across
the whole window it is handed, with rope coordinates that start at zero. Feed it one latent token
and it decodes a picture that believes it is the first frame of a clip: no neighbours to attend to,
and `decode_temporal`'s cross-fade between chunks missing entirely. The frames here are the ones a
full decode would have written, because the chunk boundaries, the three dropped lead-in frames and
the five-frame cross-fade are all reproduced from the VAE's own constants (see `_frames.py`).

**Why you want it.** A video model used as an edit model generates a clip to obtain one picture.
H3's shortest legal clip is 5 frames, so a stock decode renders five and throws four away — and on
a real generation it renders 124. Pulling frame 0 or frame -1 out directly makes "H3 as an image
editor" cost what an image editor costs at the VAE, and makes checking a long clip's last frame
something you do without waiting for the whole thing.

`index` is a **pixel frame**, negative counting from the end, so -1 is the last frame whatever the
clip length. For latent-space work — trimming a clip, feeding a shorter latent onward — use
MiniMax H3 Latent Slice instead, whose indices are latent tokens.
"""

from __future__ import annotations

from comfy_api.latest import io

from .._base import CATEGORY, PackNode
from . import _decode


class H3DecodeFrames(PackNode):
    CATEGORY = f"{CATEGORY}/Latent"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3DecodeFrames",
            display_name="H3 Decode Frames",
            description="Decodes chosen frames of an H3 video latent without decoding the clip. "
            "Exact — it reproduces the VAE's temporal chunking and cross-fade — and costs one "
            "chunk per frame, so pulling the last frame of a 124-frame clip is ~1/7th of a full "
            "decode. The point of it is using a video model as an edit model.",
            inputs=[
                io.Latent.Input(
                    "samples",
                    tooltip="An H3 latent. The audio stream of an AV latent is ignored.",
                ),
                io.Vae.Input("vae", tooltip="The MiniMax H3 video VAE."),
                io.Int.Input(
                    "index",
                    default=-1,
                    min=-4096,
                    max=4096,
                    tooltip="Pixel frame to decode. Negative counts from the end, so -1 is the "
                    "last frame and 0 the first — the two an edit workflow usually wants.",
                ),
                io.Int.Input(
                    "count",
                    default=1,
                    min=1,
                    max=256,
                    tooltip="How many frames to take. Each costs its own chunk decode unless it "
                    "shares one with a neighbour, so consecutive frames are much cheaper than "
                    "spread-out ones.",
                ),
                io.Int.Input(
                    "stride",
                    default=1,
                    min=1,
                    max=1024,
                    tooltip="Gap between them. count=6 stride=20 samples a clip at six points; "
                    "count=8 stride=1 gives eight consecutive frames out of one or two chunks.",
                ),
            ],
            outputs=[
                io.Image.Output(),
                io.Int.Output(
                    display_name="total_frames",
                    tooltip="Frames a full decode of this latent would produce.",
                ),
            ],
        )

    @classmethod
    def execute(cls, samples, vae, index=-1, count=1, stride=1) -> io.NodeOutput:
        _decode.require_h3(vae)
        latent = _decode.video_stream(samples)
        total = _decode.frame_count(vae, latent)

        start = index + total if index < 0 else index
        if not 0 <= start < total:
            raise ValueError(
                f"index {index} is outside this latent's {total} frames "
                f"(valid: 0..{total - 1}, or -1..-{total} from the end)"
            )

        # Clamp rather than raise: a filmstrip that runs off the end of a shorter-than-expected
        # clip should hand back the frames that exist, not fail the run.
        indices = list(range(start, total, stride))[:count]
        return io.NodeOutput(_decode.decode_images(vae, latent, indices), total)
