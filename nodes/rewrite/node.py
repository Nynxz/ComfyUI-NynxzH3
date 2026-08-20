"""The three nodes that drive the MiniMax-H3 prompt rewriter.

A rewrite graph is: a Qwen3-VL-8B text encoder, the rewriter LoRA on top of it, the prompt this
group builds, and ComfyUI's own Generate Text doing the sampling. Generation is core's job —
nothing here reimplements it.

    CLIPLoader -> H3 CLIP LoRA -> Generate Text -> H3 Rewrite Clean
                                    ^ prompt / reference_images from H3 Rewrite Prompt

**CLIPLoader's `type` has no qwen3vl entry**, and it does not need one: anything other than
`ideogram4`, `boogu`, `krea2` or `flux2` falls through to the plain Qwen3-VL encoder, which is
the build with `generate` and the vision tower. Leave it on the default.
"""

from __future__ import annotations

import comfy.sd
import comfy.utils
import folder_paths
from comfy_api.latest import io

from .._base import CATEGORY, PackNode
from . import _rewrite
from ._prompt import (
    MAX_DURATION,
    MIN_DURATION,
    RESOLUTION_OPTIONS,
    TASK_OPTIONS,
    build_chat_prompt,
)

# One loaded LoRA, kept across runs. The core LoraLoader does the same per instance; a
# text-encoder LoRA is big enough (the rewriter is 1.3 GiB) that re-reading it on every
# execution is felt.
_CACHE: dict[str, object] = {"path": None, "lora": None, "metadata": None}


class H3ClipLora(PackNode):
    CATEGORY = f"{CATEGORY}/Prompt"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3ClipLora",
            display_name="H3 CLIP LoRA",
            description="Applies a LoRA to a CLIP / text encoder with no MODEL input — the "
            "CLIP-side counterpart of LoraLoaderModelOnly. For text-encoder LoRAs keyed as "
            "text_encoders.transformer.*, in graphs that have no diffusion model. Chain two of "
            "these to stack, for example an abliteration LoRA under the rewriter.",
            # The only node here carrying aliases, because it is the only one whose name does not
            # describe it to someone who is not already thinking about H3. Everything else in the
            # pack is findable by typing "H3".
            search_aliases=[
                "lora",
                "clip lora",
                "load lora clip only",
                "text encoder lora",
                "llm lora",
            ],
            inputs=[
                io.Clip.Input("clip", tooltip="The text encoder the LoRA is applied to."),
                io.Combo.Input(
                    "lora_name",
                    options=folder_paths.get_filename_list("loras"),
                    tooltip="A LoRA from the loras folder.",
                    display_name="LoRA Name",
                ),
                io.Float.Input(
                    "strength",
                    default=1.0,
                    min=-100.0,
                    max=100.0,
                    step=0.01,
                    tooltip="How strongly the LoRA modifies the encoder.",
                    display_name="Strength",
                ),
            ],
            outputs=[io.Clip.Output(display_name="clip")],
        )

    @classmethod
    def execute(cls, clip, lora_name, strength) -> io.NodeOutput:
        if strength == 0:
            return io.NodeOutput(clip)

        path = folder_paths.get_full_path_or_raise("loras", lora_name)
        if _CACHE["path"] != path:
            lora, metadata = comfy.utils.load_torch_file(path, safe_load=True, return_metadata=True)
            _CACHE.update(path=path, lora=lora, metadata=metadata)

        _, patched = comfy.sd.load_lora_for_models(
            None, clip, _CACHE["lora"], 0, strength, lora_metadata=_CACHE["metadata"]
        )
        return io.NodeOutput(patched)


class H3RewritePrompt(PackNode):
    CATEGORY = f"{CATEGORY}/Prompt"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3RewritePrompt",
            display_name="H3 Rewrite Prompt",
            description="Builds the chat prompt the MiniMax-H3 prompt-rewriter LoRA was trained "
            "on — system prompt, task header, and reference-frame placeholders — plus the "
            "reference images batched in placeholder order. Feed both into Generate Text on a "
            "Qwen3-VL-8B encoder carrying the rewriter LoRA. ref2va is not supported by the "
            "adapter.",
            inputs=[
                io.String.Input(
                    "prompt",
                    multiline=True,
                    default="",
                    tooltip="The short request to rewrite.",
                ),
                io.Combo.Input(
                    "task",
                    options=TASK_OPTIONS,
                    default="t2va",
                    tooltip="t2va: text only. i2va: first frame. l2va: last frame. fl2va: both.",
                    display_name="Task",
                ),
                io.Combo.Input(
                    "resolution",
                    options=RESOLUTION_OPTIONS,
                    default="16:9",
                    tooltip="Target aspect. Upstream defaults to 16:9 for t2va and adaptive for "
                    "the image-conditioned tasks.",
                    display_name="Resolution",
                ),
                io.Int.Input(
                    "duration",
                    default=10,
                    min=MIN_DURATION,
                    max=MAX_DURATION,
                    tooltip="Target duration in seconds. The rewriter paces the shot timeline to "
                    "fit it.",
                    display_name="Duration (s)",
                ),
                io.Image.Input(
                    "first_frame",
                    optional=True,
                    tooltip="Required by i2va and fl2va.",
                    display_name="First Frame",
                ),
                io.Image.Input(
                    "last_frame",
                    optional=True,
                    tooltip="Required by l2va and fl2va.",
                    display_name="Last Frame",
                ),
                io.String.Input(
                    "system_prompt",
                    multiline=True,
                    default="",
                    optional=True,
                    tooltip="Overrides the trained system prompt. Leave empty — the adapter was "
                    "trained on the built-in one, and replacing it moves the rewriter off the "
                    "format it learned.",
                    display_name="System Prompt Override",
                ),
            ],
            outputs=[
                io.String.Output(
                    display_name="prompt",
                    tooltip="Already chat-templated, so Generate Text's use_default_template has "
                    "no effect on it.",
                ),
                io.Image.Output(
                    display_name="reference_images",
                    tooltip="In placeholder order. None for t2va — leave it unwired.",
                ),
            ],
        )

    @classmethod
    def execute(
        cls,
        prompt,
        task,
        resolution,
        duration,
        first_frame=None,
        last_frame=None,
        system_prompt="",
    ) -> io.NodeOutput:
        if not prompt.strip():
            raise ValueError("H3 Rewrite Prompt: prompt must not be empty.")
        images = _rewrite.frames_for(
            task,
            _rewrite.single_frame(first_frame, "first_frame"),
            _rewrite.single_frame(last_frame, "last_frame"),
        )
        rendered = build_chat_prompt(
            prompt,
            task=task,
            resolution=resolution,
            duration=duration,
            system_prompt=system_prompt,
        )
        return io.NodeOutput(rendered, images)


class H3RewriteClean(PackNode):
    CATEGORY = f"{CATEGORY}/Prompt"

    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3RewriteClean",
            display_name="H3 Rewrite Clean",
            description="Trims a rewriter response down to the production prompt — dropping chat "
            "tokens, code fences and any preamble — and splits out its three fields. Text it "
            "does not recognise is passed through unchanged.",
            inputs=[
                io.String.Input(
                    "generated_text",
                    multiline=True,
                    default="",
                    tooltip="Straight from Generate Text.",
                ),
            ],
            outputs=[
                io.String.Output(display_name="prompt"),
                io.String.Output(display_name="integrated_multimodal_description"),
                io.String.Output(display_name="overall_soundscape"),
                io.String.Output(display_name="non_diegetic_music"),
            ],
        )

    @classmethod
    def execute(cls, generated_text) -> io.NodeOutput:
        prompt, fields = _rewrite.clean_response(generated_text)
        return io.NodeOutput(prompt, *(fields[name] for name in _rewrite.FIELDS))
