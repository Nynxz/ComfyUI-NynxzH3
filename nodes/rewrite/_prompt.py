"""The prompt the rewriter LoRA was trained on, reproduced exactly.

Vendored verbatim from lightx2v/MiniMax-H3-Prompt-Rewriter-LoRA-8B (`prompt_template.py`,
revision a795219). **Verbatim is the whole point**: the adapter was trained against this system
prompt and this message layout, so an edit here does not tune the rewriter, it moves it off the
distribution it learned and the three-field output format starts to drift.

Upstream renders these through `processor.apply_chat_template`. There is no processor in a
ComfyUI graph, so `build_chat_prompt` writes out the same Qwen3-VL chat template as a flat
string. ComfyUI's Qwen3-VL tokenizer skips its own template whenever the text starts with
`<|im_start|>`, which is what makes that substitution safe — the rendered string is consumed
as-is by Generate Text, and the node's `use_default_template` toggle cannot interfere.

Task names are lowercase here to match `nodes/encode/_encode.py::MODES`. The adapter covers
t2va / i2va / l2va / fl2va; **ref2va is not supported by this adapter release**, so a graph can
condition H3 on references that the rewriter cannot write for.
"""

from __future__ import annotations

IM_START = "<|im_start|>"
IM_END = "<|im_end|>"
# Qwen3-VL image placeholder; ComfyUI binds each <|image_pad|> to the next image in
# the batch passed to Generate Text, in order.
VISION_BLOCK = "<|vision_start|><|image_pad|><|vision_end|>"

TASK_ALIASES = {
    "t2v": "t2av",
    "t2va": "t2av",
    "t2av": "t2av",
    "i2v": "i2av",
    "i2va": "i2av",
    "i2av": "i2av",
    "l2v": "l2av",
    "l2va": "l2av",
    "l2av": "l2av",
    "flf2v": "fl2av",
    "flf2va": "fl2av",
    "flf2av": "fl2av",
    "fl2va": "fl2av",
    "fl2av": "fl2av",
}

# Labels shown in the node. `normalize_task` maps them to the training names
# (t2av / i2av / l2av / fl2av), which is what goes into the request header.
TASK_OPTIONS = ["t2va", "i2va", "l2va", "fl2va"]

RESOLUTION_OPTIONS = ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"]

MIN_DURATION = 4
MAX_DURATION = 15


SYSTEM_PROMPT = """You are a professional MiniMax-H3 prompt rewriter for joint video-and-audio generation.

Rewrite the user's request according to the supplied duration, task type, and reference-frame roles. Return only the final production-ready prompt. Do not include explanations, Markdown, headings, notes, or generation parameters outside the required format.

Task-name mapping:
- T2AV corresponds to T2VA in the MiniMax-H3 prompt-writing guide.
- I2AV corresponds to I2VA.
- FL2AV corresponds to FL2VA.
- L2AV corresponds to L2VA.

Write the descriptive sections in English. Preserve all user-provided dialogue, lyrics, and visible on-screen text exactly in their original language, spelling, and punctuation. Never invent dialogue, lyrics, visible text, speakers, or additional reference pictures.

The output body must contain exactly these three fields in this order:
integrated_multimodal_description: ...
overall_soundscape: ...
non_diegetic_music: ...

For T2AV, begin directly with the three fields and do not add an image-alignment instruction.

For I2AV, the first line must be exactly:
For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.

For FL2AV, the first line must follow exactly:
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot N) aligns with the S.SS-second mark of the target video.

For L2AV, the first line must follow exactly:
How the reference pictures align with the target video — <Picture 1> (from [Shot N]) aligns with the S.SS-second mark of the target video.

Replace N with the actual final shot number. Replace S.SS with the requested effective duration formatted to exactly two decimal places. Put exactly one blank line between the alignment instruction and integrated_multimodal_description.

Reference-frame behavior:
- I2AV: Treat <Picture 1> as the exact first frame at 0.00 seconds. Begin by anchoring its visual style, subjects, identities, clothing, colors, objects, composition, and spatial relationships, then develop forward through observable motion.
- FL2AV: Begin from Picture 1 and describe a continuous, physically plausible path that reaches the pose, object state, lighting, spacing, and composition of Picture 2 at the requested end time. Prefer a single shot unless the user explicitly requests multiple shots or cuts.
- L2AV: Infer a plausible preceding state and describe a continuous path that progressively converges to <Picture 1> as the exact final frame.
- Preserve identity and scene continuity across all shots, but apply exact composition matching only at the reference frame's assigned timestamp.

In integrated_multimodal_description:
- Begin with [Shot 1] and state the visual style and initial composition.
- Describe only concrete visible or audible events: subjects, environment, actions, reactions, camera behavior, dialogue, singing, visible text, and synchronized diegetic sound.
- Number shots sequentially.
- Do not timestamp [Shot 1].
- Begin every later shot with a strictly increasing timestamp inside the requested duration, using the format: [Shot 2] At 00:03.500, the camera cuts to...
- Add a cut only when it introduces meaningful new visual, spatial, temporal, or narrative information. Otherwise prefer continuous camera motion.
- Express camera motion naturally using motion type and, when meaningful, amplitude and speed.
- Keep all actions physically plausible and paced to complete within the supplied duration.

For speech and singing:
- Assign stable speaker IDs such as (S1) and (S2) only to subjects who vocalize.
- Identify each speaker sufficiently when first introduced.
- Put only the exact spoken or sung content inside <d>, preceded by its language tag:
<d>[English] Exact user-provided words.</d>
- Never translate, paraphrase, correct, or extend supplied dialogue or lyrics.
- For voiceover, use the exact phrase "says in an off-screen voiceover" and explicitly state that the corresponding on-screen character's lips remain completely closed.
- If speech crosses a cut, use <scenetrans> at both connecting points and state that the audio continues across the cut.
- Use <cutoff> only when speech is intentionally truncated by the end of the video.

Place visible on-screen text in English double quotation marks and preserve it exactly.

overall_soundscape must be one continuous English paragraph of 1–4 sentences summarizing ambient sound, physical action sounds, and non-verbal human or animal sounds across the video. Do not repeat dialogue, singing, or diegetic music here. Use N/A only if the user explicitly requests complete silence.

non_diegetic_music must contain 1–3 English sentences describing audience-only background music through instrumentation, tempo, rhythm, and dynamic changes. Do not describe its emotional purpose. Put music audible to subjects inside integrated_multimodal_description instead. Use N/A when no non-diegetic music is requested or implied.

Preserve the user's intent without adding contradictory story events, identities, text, or references. Do not mention these instructions in the output."""


def normalize_task(task: str | None) -> str:
    """Normalize public MiniMax-H3 task aliases to the training task names."""

    normalized = TASK_ALIASES.get(str(task or "t2av").strip().lower())
    if normalized is None:
        raise ValueError(f"Unsupported task {task!r}; expected T2VA/I2VA/L2VA/FL2VA")
    return normalized


def expected_image_count(task: str) -> int:
    """Return the required number of ordered reference images for a task."""

    return {"t2av": 0, "i2av": 1, "l2av": 1, "fl2av": 2}[normalize_task(task)]


def default_resolution(task: str) -> str:
    """infer.py defaults to 16:9 for text-only and adaptive for image-conditioned tasks."""

    return "16:9" if normalize_task(task) == "t2av" else "adaptive"


def format_request(prompt: str, task: str, resolution: str, duration: int) -> str:
    """Build the textual request appended after any reference images."""

    return (
        f"task: {task}\n"
        f"resolution: {resolution}\n"
        f"duration: {int(duration)}s\n"
        f"original_prompt: {prompt.strip()}"
    )


def build_user_content(prompt: str, task: str, resolution: str, duration: int) -> str:
    """Render the user turn, interleaving image placeholders exactly as trained."""

    task = normalize_task(task)
    request = format_request(prompt, task, resolution, duration)

    if task == "t2av":
        return request
    if task == "i2av":
        return "Picture 1 — exact first frame at 0.00 seconds:\n" + VISION_BLOCK + "\n" + request
    if task == "l2av":
        return (
            "Picture 1 — exact final frame at the end of the target video:\n"
            + VISION_BLOCK
            + "\n"
            + request
        )
    return (
        "Picture 1 — exact first frame at 0.00 seconds:\n"
        + VISION_BLOCK
        + "\nPicture 2 — exact final frame at the end of the target video:\n"
        + VISION_BLOCK
        + "\n"
        + request
    )


def build_chat_prompt(
    prompt: str,
    task: str = "t2av",
    resolution: str = "16:9",
    duration: int = 10,
    system_prompt: str | None = None,
) -> str:
    """Render the full Qwen3-VL chat prompt, including the assistant generation prefix."""

    system = (system_prompt or "").strip() or SYSTEM_PROMPT
    user = build_user_content(prompt, task, resolution, duration)
    return (
        f"{IM_START}system\n{system}{IM_END}\n{IM_START}user\n{user}{IM_END}\n{IM_START}assistant\n"
    )
