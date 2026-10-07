"""H3 Image / H3 Video / H3 Audio — the wire side of H3 Inputs, one node per kind.

H3 Inputs reaches files on disk, which is what makes thumbnails, muting and reordering possible.
These reach **sockets**, for the content that has no file: a keyframe out of a text-to-image
pass, frames from a Load Video, a soundtrack from a Load Audio. Chain them onto an H3 Inputs in
either direction and they contribute assets to the same list.

Three nodes rather than one with three optional inputs, because the three kinds genuinely differ.
An image has a role; a video has a frame rate and an optional soundtrack; audio has neither. One
node covering all three would carry two dead widgets whatever you wired into it — which is the
same complaint that retired the `extra_image` + `extra_role` pair these replace.

**The frame rate is the one number worth setting.** H3 presents reference video to Qwen3-VL at
24 fps with `<T.T seconds>` timestamps derived from it, so frames arriving at some other rate
are presented at the wrong speed with the wrong timestamps. A file knows its own rate and H3
Inputs reads it; a wired IMAGE batch does not, so `fps` says what it is and the frames are
resampled onto 24 the same way.
"""

from __future__ import annotations

from comfy_api.latest import io

from .. import _core
from .._base import CATEGORY, PackNode
from ..inputs import _assets, _payload, _rows
from ..inputs.types import H3InputData

CHAIN = "Another H3 node upstream. Its assets come first, then this one's."


class H3Image(PackNode):
    CATEGORY = f"{CATEGORY}/Conditioning"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3Image",
            display_name="H3 Image",
            description="A wired IMAGE as an H3 reference or keyframe. For pictures that have no "
            "file to drop — anything generated upstream. Chains onto H3 Inputs.",
            inputs=[
                io.Image.Input(
                    "image", tooltip="One picture. A batch contributes its first frame."
                ),
                io.Combo.Input(
                    "role",
                    options=list(_rows.ROLES),
                    default="reference",
                    tooltip="reference supplies identity or style with no position. first_frame / "
                    "last_frame anchor this picture to a position in the generated clip, which "
                    "switches H3 Encode to the keyframe task.",
                ),
                io.Combo.Input(
                    "size",
                    options=list(_rows.SIZES),
                    default="auto",
                    tooltip="How much detail this reference is fed in at. auto follows the "
                    "setting on H3 Inputs; match uses the generation's own pixel budget; max "
                    "feeds it at up to 2048px for the best identity, and costs several times "
                    "more — reference rows ride every sampling step. Ignored for a keyframe, "
                    "which is always canvas-sized.",
                ),
                H3InputData.Input("h3_inputs", optional=True, tooltip=CHAIN),
            ],
            outputs=[H3InputData.Output(display_name="h3_inputs")],
        )

    @classmethod
    def execute(cls, image, role="reference", size="auto", h3_inputs=None) -> io.NodeOutput:
        if role not in _rows.ROLES:
            role = "reference"
        item = {
            "kind": "image",
            "role": role,
            "label": f"H3 Image ({role})",
            # A keyframe is one picture by definition; a reference batch would silently become
            # several <Picture i> blocks, so both paths take the first frame.
            "image": image[:1],
            "audio": None,
            "fps": None,
            "size": size if size in _rows.SIZES else "auto",
        }
        return io.NodeOutput(_payload.merge(h3_inputs, _payload.make([item])))


class H3Video(PackNode):
    CATEGORY = f"{CATEGORY}/Conditioning"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3Video",
            display_name="H3 Video",
            description="Wired video frames as an H3 reference, with an optional soundtrack. "
            "Set fps to the frames' real rate — H3 presents reference video at 24 fps with "
            "timestamps derived from it. Chains onto H3 Inputs.",
            inputs=[
                io.Image.Input("frames", tooltip="The video as an IMAGE batch, in order."),
                io.Float.Input(
                    "fps",
                    default=24.0,
                    min=1.0,
                    max=240.0,
                    step=0.01,
                    tooltip="The frames' actual frame rate. They are resampled onto H3's 24 fps "
                    "from this, so a wrong value plays the reference at the wrong speed and "
                    "mislabels its <T.T seconds> timestamps.",
                ),
                io.Audio.Input(
                    "audio",
                    optional=True,
                    tooltip="Soundtrack for these frames. Packs the reference as video+audio, "
                    "and needs H3's audio VAE on the encode node.",
                ),
                io.Combo.Input(
                    "detail",
                    options=list(_core.REFERENCE_DETAIL),
                    default="full",
                    tooltip="How much resolution this reference is fed in at — a pure cost dial. "
                    "Reference rows ride every sampling step, and a video reference is usually a "
                    "third of the whole sequence, so 'half' takes roughly a quarter off the run "
                    "and a similar amount off peak VRAM. It costs no alignment: H3's spatial rope "
                    "depends on aspect ratio alone, so a half-resolution reference sits in the "
                    "identical coordinate box and stays registered to the target. Use 'full' when "
                    "the reference is the only source of fine detail.",
                ),
                io.Latent.Input(
                    "latent",
                    optional=True,
                    tooltip="This same video as an H3 latent, when you already have one — the "
                    "output of an earlier sampler. H3 Encode then skips the VAE encode and uses "
                    "it directly, which is what a regenerate pass wants: the first pass's own "
                    "latent, with no decode/re-encode round trip to lose detail through. The "
                    "frames are still needed, because Qwen3-VL reads pixels.",
                ),
                H3InputData.Input("h3_inputs", optional=True, tooltip=CHAIN),
            ],
            outputs=[H3InputData.Output(display_name="h3_inputs")],
        )

    @classmethod
    def execute(
        cls, frames, fps=24.0, detail="full", audio=None, latent=None, h3_inputs=None
    ) -> io.NodeOutput:
        # The latent is carried as a bare video tensor, not as a LATENT dict: an AV latent's audio
        # stream is the *generated* soundtrack of an earlier pass, which is not the same thing as
        # this reference's `audio` (that one goes through the audio VAE alongside). Unbinding here
        # keeps the two from being confused downstream, where only one of them has a home.
        video_latent = None
        if latent is not None:
            samples = latent["samples"]
            video_latent = samples.unbind()[0] if getattr(samples, "is_nested", False) else samples
            if video_latent.ndim != 5:
                raise ValueError(
                    f"H3 Video: 'latent' is not an H3 video latent [B, C, T, H, W] — got "
                    f"{tuple(video_latent.shape)}. Wire a sampler's H3 output, or leave it empty "
                    "and let H3 Encode encode the frames."
                )

        item = {
            "kind": "video",
            "role": "reference",
            "label": f"H3 Video ({frames.shape[0]} frames @ {float(fps):g} fps)",
            "image": _assets.resample_to_fps(frames, float(fps)),
            "audio": audio,
            "fps": float(fps),
            "size": "auto",
            "detail": detail,
            "latent": video_latent,
        }
        return io.NodeOutput(_payload.merge(h3_inputs, _payload.make([item])))


class H3Audio(PackNode):
    CATEGORY = f"{CATEGORY}/Conditioning"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3Audio",
            display_name="H3 Audio",
            description="Wired AUDIO as a standalone H3 reference — an <Audio j> the prompt can "
            "refer to. Needs H3's audio VAE on the encode node. Chains onto H3 Inputs.",
            inputs=[
                io.Audio.Input("audio"),
                H3InputData.Input("h3_inputs", optional=True, tooltip=CHAIN),
            ],
            outputs=[H3InputData.Output(display_name="h3_inputs")],
        )

    @classmethod
    def execute(cls, audio, h3_inputs=None) -> io.NodeOutput:
        item = {
            "kind": "audio",
            "role": "reference",
            "label": "H3 Audio",
            "image": None,
            "audio": audio,
            "fps": None,
            "size": "auto",
        }
        return io.NodeOutput(_payload.merge(h3_inputs, _payload.make([item])))
