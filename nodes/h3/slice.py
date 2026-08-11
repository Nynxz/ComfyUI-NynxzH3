"""MiniMax H3 Latent Slice — take a range of latent frames out of an AV latent.

The cheap, general half of "decode less". This is plain tensor slicing on the **latent token**
axis: it hands back a shorter LATENT that any downstream node accepts, and drops the audio stream
(or trims it to match) so a stock VAE Decode doesn't have to think about nesting.

Use it to trim a clip, to keep a tail for a continuation, or to feed a shorter latent to another
sampler. Do **not** use it to fish out a single frame for an image: a one-token latent decodes as
its own tiny clip, with no neighbouring tokens to attend to and no cross-fade, which is a different
picture from the one that frame has inside the full clip. That is what MiniMax H3 Decode Frames is
for, and why it exists as a separate node instead of this one plus a VAE Decode.

Audio trimming is proportional on the token axis. Both streams are uniform in time — 5 video tokens
per 17 frames at 24 fps, 40 audio tokens per second — so the two axes are linearly related and a
proportional cut lands within a token of the video cut. Exact audio alignment would need the frame
plan, which needs the VAE, which this node deliberately does not take.
"""

from __future__ import annotations

from comfy_api.latest import io

from .._base import CATEGORY, PackNode


class H3LatentSlice(PackNode):
    CATEGORY = f"{CATEGORY}/Latent"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3LatentSlice",
            display_name="H3 Latent Slice",
            description="Slices an H3 AV latent along the latent-frame axis and drops or trims "
            "the audio stream to match. For a single frame as an image use MiniMax H3 Decode "
            "Frames — a lone latent token does not decode to the frame it was inside a clip.",
            inputs=[
                io.Latent.Input("samples", tooltip="An H3 latent, nested (video+audio) or bare."),
                io.Int.Input(
                    "start",
                    default=0,
                    min=-4096,
                    max=4096,
                    tooltip="First latent frame to keep. Negative counts from the end.",
                ),
                io.Int.Input(
                    "count",
                    default=0,
                    min=0,
                    max=4096,
                    tooltip="How many latent frames to keep. 0 means everything from start on.",
                ),
                io.Combo.Input(
                    "audio",
                    options=["drop", "trim"],
                    default="drop",
                    tooltip="'drop' returns video only, which is what a VAE Decode wants. 'trim' "
                    "keeps a proportionally cut audio stream so the result stays a playable AV "
                    "latent.",
                ),
            ],
            outputs=[
                io.Latent.Output(),
                io.Int.Output(display_name="latent_frames", tooltip="Latent frames in the result."),
            ],
        )

    @classmethod
    def execute(cls, samples, start=0, count=0, audio="drop") -> io.NodeOutput:
        latent = samples["samples"]
        nested = getattr(latent, "is_nested", False)
        video = latent.unbind()[0] if nested else latent
        if video.ndim != 5:
            raise ValueError(f"expected a video latent [B, C, T, H, W], got {tuple(video.shape)}")

        total = video.shape[2]
        begin = start + total if start < 0 else start
        if not 0 <= begin < total:
            raise ValueError(
                f"start {start} is outside this latent's {total} latent frames "
                f"(valid: 0..{total - 1}, or -1..-{total} from the end)"
            )
        end = total if count <= 0 else min(total, begin + count)

        out = video[:, :, begin:end]
        if audio == "trim" and nested and len(latent.unbind()) > 1:
            import comfy.nested_tensor

            sound = latent.unbind()[1]
            length = sound.shape[-1]
            a_begin = round(begin * length / total)
            a_end = max(a_begin + 1, round(end * length / total))
            out = comfy.nested_tensor.NestedTensor((out, sound[..., a_begin:a_end]))

        # noise_mask is sized to the latent it was made for, so it cannot survive the cut.
        result = {k: v for k, v in samples.items() if k not in ("samples", "noise_mask")}
        result["samples"] = out
        return io.NodeOutput(result, end - begin)
