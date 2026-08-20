# ComfyUI-NynxzH3

MiniMax H3 nodes for ComfyUI: conditioning, prompt rewriting, sampling and latent handling.

## Installation

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/Nynxz/ComfyUI-NynxzH3
```

Restart ComfyUI. Requires ComfyUI 0.30.0 or newer.

## Nodes

| node | category | purpose |
|---|---|---|
| H3 Canvas | `Nynxz/H3` | Canvas size and duration |
| H3 Inputs | `Nynxz/H3` | Keyframes and several references on one node |
| H3 Image | `Nynxz/H3` | Image reference or keyframe |
| H3 Video | `Nynxz/H3` | Video reference, with soundtrack |
| H3 Audio | `Nynxz/H3` | Audio reference |
| H3 Encode | `Nynxz/H3` | Conditioning and AV latent |
| H3 Extras | `Nynxz/H3` | Canvas values from the wire |
| H3 Rewrite Prompt | `Nynxz/H3/Prompt` | Build the prompt the rewriter LoRA was trained on |
| H3 Rewrite Clean | `Nynxz/H3/Prompt` | Trim a rewriter response to the production prompt |
| H3 CLIP LoRA | `Nynxz/H3/Prompt` | Apply a LoRA to a text encoder, no MODEL input |
| H3 Block Cache | `Nynxz/H3/Sampling` | Skip the transformer stack on low-change steps |
| H3 Depth Skip | `Nynxz/H3/Sampling` | Skip named blocks |
| H3 Detail Schedule | `Nynxz/H3/Sampling` | Sigmas with a separate refinement phase |
| H3 Row Chunk | `Nynxz/H3/Sampling` | Keeps projections under CUDA's int32 limit |
| H3 Sliding Window | `Nynxz/H3/Sampling` | Banded attention over the video rows |
| H3 Reference Isolate | `Nynxz/H3/Sampling` | Stops the reference prefix attending to the target |
| H3 Decode Frames | `Nynxz/H3/Latent` | Decode selected frames |
| H3 Latent Slice | `Nynxz/H3/Latent` | Slice a latent on the token axis |

Assets and the canvas chain on one `h3_inputs` wire into H3 Encode, in any order. Unwired nodes
fall back to H3's defaults.

The reasoning and measurements behind the sampling nodes are in
[`docs/sampling-notes.md`](docs/sampling-notes.md).

## Conditioning

### H3 Canvas

`h3_inputs?, width, height, seconds` → `h3_inputs, report`

Sets the canvas. Both axes snap to 32px, and the duration snaps up to H3's frame grid
(`n % 17 == 5`), so 5s becomes 124 frames. Resolution picking is left to a dedicated resolution
node.

### H3 Inputs

`first_frame?, last_frame?, pictures, audios, size, h3_inputs?` → `h3_inputs, report`

Keyframes and several references on one node. `pictures` (×9) and `audios` (×4) grow as you fill
them, and a slot names the tag it answers to — `picture_2` is `<Picture 2>`. The `report` gives
the real tags, since anything wired upstream shifts them.

**Reference video goes on H3 Video, not here** — core pairs `ref_video_audio_N` with `ref_video_N`
by slot number, so a silent clip in an early slot sends every later soundtrack to the wrong video
([why](docs/sampling-notes.md#why-h3-video-exists-instead-of-more-autogrow-slots)).

### H3 Image

`image, role, size, h3_inputs?` → `h3_inputs`

One asset per node, for when a single reference is all you need or the role varies. `role` is
`reference`, `first_frame` or `last_frame`, which selects the task on H3 Encode. Only images can
be keyframes.

### H3 Video

`frames, fps, audio?, detail, latent?, h3_inputs?` → `h3_inputs`

**`fps` must match the source.** H3 presents reference video at 24 fps with timestamps derived
from it, so a wrong value plays the reference at the wrong speed and mislabels its timestamps.
Frames are resampled nearest-neighbour.

`detail` (`full`/`half`/`quarter`) reduces the resolution the reference is fed in at. Reference
rows are processed every step, so `half` cuts roughly a quarter off the run and off peak VRAM;
alignment is unaffected. `latent` accepts this clip's existing H3 latent, skipping the VAE encode.

### H3 Audio

`audio, h3_inputs?` → `h3_inputs`

Audio reference. Requires `audio_vae` on H3 Encode.

### H3 Encode

`clip, vae, audio_vae?, prompt, mode, keyframe_instruction, h3_inputs?` → `positive, LATENT, report`

Replaces *MiniMax H3 Image to Video* and *MiniMax H3 Reference to Video*. The task follows from
what is wired — nothing → `t2va`, first and/or last frame → `fl2va`, references → `ref2va` — and
`mode` forces one of those names instead of a second vocabulary.

Forcing matters because **fl2va and ref2va cannot be combined**; that is a ComfyUI constraint, not
this pack's. With both wired, fl2va wins, reference images still reach Qwen3-VL as `<Picture i>`
blocks, and anything set aside is named in `report`.

Forcing `fl2va` with no frame roles marked uses the **first two pictures** as the anchors, which is
what H3's own prompt form calls them. An explicit role always wins. `keyframe_instruction` writes
the alignment line an fl2va prompt should open with, using the snapped duration.

> **H3's trained range is ~124–362 frames (5–15s).** Longer is untested and degrades badly — sung
> and spoken content becomes unintelligible well before a minute. For longer pieces, chain 10–15s
> segments with `video continuation` + `audio reference`.

### H3 Extras

`h3_inputs, mode` → `width, height, length, frame_count, latent_t, audio_t, seconds, task,
is_keyframes, is_references, summary`

Reads the canvas back off the wire, including the frame count it snapped up to.

## Prompt

Turn a one-line idea into a full H3 prompt in-graph, using
[lightx2v's rewriter LoRA](https://huggingface.co/lightx2v/MiniMax-H3-Prompt-Rewriter-LoRA-8B) on a
Qwen3-VL-8B text encoder. ComfyUI-format LoRAs:
[nynxz/Qwen3-VL-8B-ComfyUI](https://huggingface.co/nynxz/Qwen3-VL-8B-ComfyUI).

```
CLIPLoader (qwen3vl_8b, type: stable_diffusion)
  -> H3 CLIP LoRA        the rewriter LoRA, strength 1.0
  -> Generate Text       sampling_mode: off (greedy), max_length 2048-4096
       prompt <- H3 Rewrite Prompt.prompt
       image  <- H3 Rewrite Prompt.reference_images
  -> H3 Rewrite Clean    -> prompt for H3 Encode
```

### H3 Rewrite Prompt

`prompt, task, resolution, duration, first_frame?, last_frame?, system_prompt?` →
`prompt, reference_images`

Renders the system prompt, task header and reference-frame placeholders exactly as the adapter was
trained, and batches the reference images in placeholder order — images bind to `<|image_pad|>`
**by position**, so that ordering is what keeps them aligned.

| task | frames | placeholders |
|---|---|---|
| `t2va` | none | — |
| `i2va` | `first_frame` | Picture 1 = first frame |
| `l2va` | `last_frame` | Picture 1 = final frame |
| `fl2va` | both | Picture 1 = first, Picture 2 = last |

Duration is 4–15s. Two frames travel as one IMAGE batch, so `fl2va` scales `last_frame` onto
`first_frame` when they differ. **`ref2va` is not supported by the adapter** — H3 Encode will
condition on references the rewriter cannot write for.

### H3 Rewrite Clean

`generated_text` → `prompt, integrated_multimodal_description, overall_soundscape,
non_diegetic_music`

Strips chat tokens, code fences and any preamble, then splits the three fields. Text it does not
recognise passes through unchanged.

### H3 CLIP LoRA

`clip, lora_name, strength` → `clip`

The core Load LoRA node demands a MODEL input that a rewrite-only graph does not have. Chain two to
stack — an abliteration LoRA under the rewriter, say. Keep the rewriter off any encoder that also
builds conditioning: it changes how the model *writes*.

## Sampling

### H3 Block Cache

`model, threshold, max_consecutive, start_percent, end_percent, verbose` → `MODEL`

Reuses the transformer stack's output on steps where it barely changes. Measured **80s → 30s** on a
5s clip at aggressive settings. `threshold` is an accumulated relative-L1 budget, so it means the
same at any resolution or duration; `0` disables it. 0.05–0.1 is usually free, past 0.2 motion
smears.

### H3 Depth Skip

`model, blocks, start_percent, end_percent, mode` → `MODEL, report`

Skips named blocks: `"3-17"`, `"3-17, 22"`, ranges inclusive. Empty changes nothing. `mode`
defaults to `attention_only`, which keeps the MLP and still captures most of the saving.
Blocks 3–17 are the quietest band on the released checkpoints — confirm against your own output.

### H3 Detail Schedule

`structure_steps, detail_steps, split, shift, detail_spacing` → `SIGMAS, report`

Wire into `SamplerCustomAdvanced` in place of a scheduler. Budgets structure and refinement
separately without changing the shift curve — every sigma still lies on it. A 15/8 split reads out
**a nat and a half deeper into high SNR** than plain shift-12 at the same step count
([why](docs/sampling-notes.md#h3-detail-schedule--why-a-split-schedule-reads-out-deeper)).

### H3 Row Chunk

`model, chunk_rows` → `MODEL, report`

Splits the qkv projection and MLP into row chunks so their intermediates stay under CUDA's int32
limit. **Needed past roughly 10.5s at 1344×768** — beyond that you get `CUDA error: an illegal
memory access was encountered`, usually surfacing at some later unrelated allocation. Not an
approximation: these projections are row-wise, so it computes the same function.

### H3 Sliding Window

`model, window, follow_taps, jitter, isolate_references, start_percent, end_percent` →
`MODEL, report`

Restricts each latent frame's attention to a band of nearby frames, plus rotating long-range taps
so distant frames still reach each other. Text and references stay fully attended. Measured
**1.7× at 5s, 3.2× at 10s**. Needs a Triton-capable GPU; falls back to dense attention otherwise.

### H3 Reference Isolate

`model, start_percent, end_percent` → `MODEL, report`

Stops the reference prefix attending to the denoising target — one square attention becomes two
rectangular ones. One-directional: the generation still sees its references. Saves in proportion to
how much of the sequence is references, **25% with a full-res video reference**, and costs no
memory.

## Latent

### H3 Decode Frames

`samples, vae, index, count, stride` → `IMAGE, total_frames`

Decodes selected frames instead of the whole clip. The VAE works in overlapping 17-frame chunks, so
one frame costs at most two chunk decodes. `index` is negative from the end. `count=8 stride=1`
gives eight consecutive frames; `count=6 stride=20` samples six points across a clip.

### H3 Latent Slice

`samples, start, count, audio` → `LATENT, latent_frames`

Slice a latent on the token axis.

## Development

Pure Python, no build step — edit a file and restart ComfyUI.

```
__init__.py       the NODES list
nodes/_base.py    namespace and menu category
nodes/<group>/    the nodes; `_name.py` holds the logic each is thin over
docs/             reasoning and measurements that would bloat this file
```

```bash
uvx ruff check . && uvx ruff format .
```

## License

MIT
