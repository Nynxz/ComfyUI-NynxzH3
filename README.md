# ComfyUI-NynxzH3

MiniMax H3 nodes for ComfyUI: conditioning, sampling and latent handling.

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

## Conditioning

### H3 Canvas

`h3_inputs?, width, height, seconds` → `h3_inputs, report`

Sets the canvas. Both axes snap to 32px, and the duration snaps up to H3's frame grid
(`n % 17 == 5`), so 5s becomes 124 frames. The report gives the resulting canvas, latent lengths,
and how far past H3's base resolution cap it lands.

Resolution picking — aspect ratios, megapixels — is left to a dedicated resolution node.

### H3 Inputs

`first_frame?, last_frame?, pictures, audios, size, h3_inputs?` → `h3_inputs, report`

Keyframes and several references on one node. `pictures` (×9) and `audios` (×4) grow as you fill
them, and a slot names the tag it answers to — `picture_2` is `<Picture 2>`. The `report` gives the
real tags, since anything wired upstream shifts them.

**Reference video goes on H3 Video, not here.** A video is four correlated settings — frames, fps,
soundtrack, detail — and an autogrow slot holds one value, so it can only be carried by splitting
those across parallel groups. That is what makes core's `ref_video_audio_N` pair with
`ref_video_N` by slot number: put a silent clip in an early slot and every later soundtrack lands
on the wrong video, with nothing on screen saying so. H3 Video binds all four together on one node
and chains.

### H3 Image

`image, role, size, h3_inputs?` → `h3_inputs`

One asset per node, for when a single reference is all you need or the role varies.

`role` is `reference`, `first_frame` or `last_frame`, which selects the task on H3 Encode. Only
images can be keyframes.

### H3 Video

`frames, fps, audio?, detail, latent?, h3_inputs?` → `h3_inputs`

`fps` must match the source. H3 presents reference video at 24 fps with timestamps derived from
it, so a wrong value plays the reference at the wrong speed and mislabels its timestamps. Frames
are resampled nearest-neighbour.

`detail` (`full`/`half`/`quarter`) reduces the resolution the reference is fed in at. Reference
rows are processed on every sampling step, so `half` cuts roughly a quarter off the run and off
peak VRAM. Alignment is unaffected.

`latent` accepts this clip's existing H3 latent, skipping the VAE encode — useful for a second
pass over an earlier result.

### H3 Audio

`audio, h3_inputs?` → `h3_inputs`

Audio reference. Requires `audio_vae` on H3 Encode.

### H3 Encode

`clip, vae, audio_vae?, prompt, mode, keyframe_instruction, h3_inputs?`
→ `positive, LATENT, report`

Replaces *MiniMax H3 Image to Video* and *MiniMax H3 Reference to Video*. The task follows from
what is wired:

| wired | task |
|---|---|
| nothing | `t2va` |
| first and/or last frame | `fl2va` |
| references | `ref2va` |

`mode` is `auto`, `t2va`, `fl2va` or `ref2va` — the task names, not a second vocabulary. Forcing
one matters because **fl2va and ref2va cannot be combined**; that is a ComfyUI constraint, not this
pack's. With both wired, fl2va wins; reference images still reach Qwen3-VL as `<Picture i>` blocks,
and anything set aside is named in `report`.

Forcing `fl2va` with nothing marked as a first or last frame uses the **first two pictures** as
those anchors, which is what H3's own prompt form calls them (`Picture 1`, `Picture 2`). An
explicit role always wins over that.

`keyframe_instruction` writes the alignment line H3 expects an fl2va prompt to open with, using
the snapped duration.

> **H3's trained range is ~124–362 frames (5–15s).** Longer is untested and degrades badly —
> sung and spoken content becomes unintelligible well before a minute. For longer pieces, chain
> 10–15s segments with `video continuation` + `audio reference`.

### H3 Extras

`h3_inputs, mode` → `width, height, length, frame_count, latent_t, audio_t, seconds, task,
is_keyframes, is_references, summary`

Reads the canvas back off the wire, including the frame count it snapped up to.

## Sampling

### H3 Block Cache

`model, threshold, max_consecutive, start_percent, end_percent, verbose` → `MODEL`

Reuses the transformer stack's output on steps where it barely changes, skipping 49 of 50 blocks.
Measured 80s → 30s on a 5s clip at aggressive settings.

`threshold` is an accumulated relative-L1 budget, so it means the same at any resolution or
duration. `0` disables it entirely. 0.05–0.1 is usually free; past 0.2 motion smears.

### H3 Depth Skip

`model, blocks, start_percent, end_percent, mode` → `MODEL, report`

Skips named blocks: `"3-17"`, `"3-17, 22"`, ranges inclusive. Empty changes nothing.

`mode` defaults to `attention_only`, which keeps the MLP and still captures most of the saving —
attention is ~83% of block time at these sequence lengths. `whole_block` skips everything.

Blocks 3–17 measure as the quietest band on the released checkpoints, but confirm against your
own output before relying on it.

### H3 Detail Schedule

`structure_steps, detail_steps, split, shift` → `SIGMAS, report`

Wire into `SamplerCustomAdvanced` in place of a scheduler. At H3's default shift of 12, a 20-step
schedule spends one step below sigma 0.5 and ends on a 0.387 → 0 jump. This budgets structure and
refinement separately without changing the shift curve — every sigma still lies on it.

### H3 Row Chunk

`model, chunk_rows` → `MODEL, report`

Splits the qkv projection and MLP into row chunks so their intermediates stay under CUDA's int32
limit. Needed past roughly **10.5s at 1344×768** — beyond that you get `CUDA error: an illegal
memory access was encountered`, usually surfacing at some later unrelated allocation. Not an
approximation: these projections are row-wise, so it computes the same function. Also lowers peak
activation memory.

### H3 Sliding Window

`model, window, follow_taps, jitter, isolate_references, start_percent, end_percent`
→ `MODEL, report`

Restricts each latent frame's attention to a band of nearby frames, plus rotating long-range taps
so distant frames still reach each other. Text and references stay fully attended. Measured at
window 8 with 2 taps: attention **1.7× at 5s, 3.2× at 10s**, peak memory unchanged.

Needs a Triton-capable GPU; falls back to dense attention otherwise.

### H3 Reference Isolate

`model, start_percent, end_percent` → `MODEL, report`

Stops the reference prefix attending to the denoising target — one square attention becomes two
rectangular ones. One-directional: the generation still sees its references.

Saves in proportion to how much of the sequence is references: **25% with a full-res video
reference, 1.3% with none**. Costs no memory. `start_percent` lets references watch composition
get decided before freezing them.

## Latent

### H3 Decode Frames

`samples, vae, index, count, stride` → `IMAGE, total_frames`

Decodes selected frames instead of the whole clip. The VAE works in overlapping 17-frame chunks,
so one frame costs at most two chunk decodes. `index` is negative from the end. `count=8 stride=1`
gives eight consecutive frames; `count=6 stride=20` samples six points across a clip.

### H3 Latent Slice

`samples, start, count, audio` → `LATENT, latent_frames`

Slices on the latent token axis. `count=0` keeps everything from `start`. `audio` is `drop` (video
only, for *VAE Decode*) or `trim` (proportionally cut, staying a playable AV latent).

## Prompts

H3 expects a specific prompt format — named fields, `[Shot N]` markers with timestamps, `(S1)`
speaker IDs, `<d>[Language] …</d>` dialogue. See `VIDEO_PROMPT_WRITING_GUIDE_base_en.md` and
`VIDEO_PROMPT_WRITING_GUIDE_ref_en.md`.

`SYSTEM_PROMPT_image_to_h3.md` is that format as a system prompt for a vision model: give it an
image and an idea, get a finished prompt back.

## Development

Pure Python, no build step — edit a file and restart ComfyUI.

```
__init__.py       the NODES list
nodes/_base.py    namespace and menu category
nodes/<group>/    the nodes; `_name.py` holds the logic each is thin over
tests/            not shipped
```

```bash
uvx ruff check . && uvx ruff format .
for t in tests/test_*.py; do COMFY_ROOT=/path/to/ComfyUI python "$t"; done
```

Several suites compare this pack's arithmetic against ComfyUI's own functions rather than against
our copy of it — the flow curve against `comfy.model_sampling.time_snr_shift`, partial decode
against a full `vae.decode`, conditioning against core's packing. That is what catches a core
release moving something underneath us.

## Related

**ComfyUI-NynxzVideo** — experimental H3 work: sliding-window and block-sparse attention,
profiling, masked and regional editing, frame holding, and the Qwen3-VL generation tail.

## License

MIT
