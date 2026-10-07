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
| H3 Edit | `Nynxz/H3/Prompt` | Edit or restyle a still: instruction + `@named` references → prompt and assets (experimental) |
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

## Per-reference roles (H3 Reference, H3 Mood Board, H3 Reference to Video)

> Experimental. The nodes work and the plumbing is verified against core, but the *result* is
> untested on a GPU — see the honest limit at the end.

H3 conditions on a reference image through two independent channels: its **vision tokens**, which
enter the Qwen3-VL-32B conditioning behind a `<Picture i>` label, and its **pixels**, as a VAE
latent packed into the DiT sequence. Core's `MiniMax H3 Reference to Video` couples them with one
check — wire a VAE and *every* reference becomes a latent, leave it out and *none* does.

These two nodes decouple it per reference:

- **H3 Reference** — takes up to 9 images and tags them `reference` (both channels) or `semantic`
  (vision tokens only). Chain several nodes to mix roles in one run.
- **H3 Reference to Video** — core's ref2va node, honouring those roles. Outputs the usual
  `positive` + `latent`, plus a `picture_map` string telling you which `<Picture i>` each
  reference became.

- **H3 Mood Board** — several images that share a *look* but not a subject, collapsed into
  **one** `<Picture>`. Each is encoded by the vision tower separately, then their token spans are
  blended position by position and the spare brackets are cut out. Chains like an H3 Reference.

So a hero shot can carry its identity as pixels while a board of style images steers the look:

```
H3 Mood Board [3 refs, average, 384] ─┐
H3 Reference  [hero.png, reference]  ─┴→ H3 Reference to Video → positive, latent
```

This is the same technique as the mood board in
[ComfyUI-QI21Remix](https://github.com/nynxz/ComfyUI-QI21Remix), ported — the blend engine is
shared, only the span-finding differs. It ports *better* here: 2.1's encoder deletes vision
tokens so the surgery needs `image_slots`, while H3 keeps them and hands over a map
(`minimax_token_tags`), so a run of vision tags simply *is* a picture.

- `average` — a weighted mean at every grid position. Where the images agree the vectors
  reinforce; where they differ they partly cancel, and the residual is the shared look.
- `mosaic` — each cell taken whole from one source, checkerboard-style, with `block_size`,
  `feather` and `jitter`. Keeps each image's local coherence instead of averaging it away.

`weights` (e.g. `1, 0.5, 2`) biases both, but means different things: under `average` it is how
much of the mix a source carries; under `mosaic`, which never mixes, how many *cells* it claims.
They are normalised, so raising all of them changes nothing.

### `semantic` does not mean "abstract" — resolution does

This is the part worth understanding, and it is the one thing that will surprise you: a
`semantic` reference can still transfer almost exactly.

Qwen3-VL patches at 16px and merges 2×2 — **one vision token per 32×32 pixels** — and it never
downscales what it is handed (its cap is 12.8M pixels, far above any reference). DeepStack then
injects multi-level ViT features at those same positions. So a generation-sized reference is
**1008 tokens** of dense, spatially-resolved encoding: enough to reproduce the image closely with
no latent at all. Dropping the VAE latent removes one transfer channel; it does not abstract the
other.

What buys abstraction is the token budget, and it falls with the square of resolution:

| reference size | vision tokens |
|---|---|
| 1344×768 (a full `match`-sized reference) | 1008 |
| 512×512 | 256 |
| 384×384 | 144 |
| 256×256 | 64 |

Two ways to spend less:

- **`vision_size`** on H3 Reference caps what the *text encoder* sees, independently of the VAE
  latent — so a `reference` can keep full-detail pixels while its vision tokens stay coarse.
- **H3 Mood Board**'s `resolution` sets the grid every board image is fitted to, which is both
  what makes them blendable and the board's whole cost. 384 is 144 tokens for the lot.

The encode node reports what each picture cost in its `picture_map`, so you can see what you are
spending rather than guess.

> Collapsing a board leaves **gaps** in the picture numbering — the surviving `<Picture i>` label
> was written by the tokenizer's counter before the cut. The `picture_map` is the authoritative
> list of what to prompt with; do not assume pictures run 1..N.

**Read the `picture_map` before you write the prompt.** Nothing tells H3 which `<Picture i>` a
latent belongs to except order — the tokenizer labels from a plain counter and the DiT reads
`refs[k]` as the k-th picture. Latent-bearing references are therefore emitted first, so
`<Picture 1>` is always a `reference`, and the numbering is *not* chain order.

A `semantic` reference costs no latent slot: core's `PackedLayout` gives reference image k the
time position `text_len + k`, packed as a run after the whole text rather than spliced at its tag,
so dropping one simply closes the gap.

Images only. Reference videos and audio carry their own timeline spans and soundtrack pairing —
chain core's node for those.

**Honest limit:** a `<Picture N>` that has vision tokens but no latent is a shape H3 was probably
never trained on, so `semantic` is an extrapolation, not a documented mode. Both endpoints of it
are supported by core (all-latent, and no-VAE-at-all), and the equivalent split demonstrably does
something on Qwen Image 2.1 — but whether the middle is *useful* here is exactly what this group
exists to find out.

## Editing a still

### H3 Edit (experimental)

`source, instruction, references, pictures, style, keep, mode, size, vae?` → `prompt, h3_inputs, report, latent`

H3's shortest clip is 5 frames, and its last frame decodes to a clean still — so H3 is an image
editor that understands references. H3 Edit writes the prompt for that the way H3's own
reference guide lays it out, and the assets on a 5-frame canvas sized to the source:

```
source + pictures ─► H3 Edit ─┬─► prompt    ─► H3 Encode (mode auto) ─► positive ─► sampler
         vae ──────►          ├─► h3_inputs ─┘                                       ▲   │
                              └─► latent ────────────────────────────────────────────┘   │
                                             H3 Decode Frames (index -1) ◄────────────────┘
```

**Sample H3 Edit's `latent`, not H3 Encode's, with denoise below 1.** H3 Encode's LATENT is an
empty canvas: from it the sampler invents a new picture, and in `reference` mode the source is
only one reference among several, so a style picture's *content* can win. H3 Edit's latent (with
`vae` wired) is the source held for 5 frames, so a partial denoise edits *your* picture — lower
keeps more of it; around 0.6–0.85 is a place to start for a restyle.

- **instruction** — what changes, in plain words. `@source` is the picture being edited; each
  reference is `@name`. Names become the right `<Subject N>` / `<Picture N>` whatever the slot
  order, and anything unknown or unmentioned is in `report`.
- **references** — one line per wired picture, in slot order: `@name (role): what it is`.

  | role | retention marker | use |
  |---|---|---|
  | `look` | `fully_preserved` | a character, prop or place that appears as shown |
  | `style` | `attribute_transfer` | its rendering moves onto the source; none of its content |
  | `loose` | `weak_reference` | a broad likeness only |

- **keep** — how much of the source survives: `closely`, `changes` (composition and poses stay),
  `loosely`.
- **mode** — `reference` makes the source a subject H3 redraws (the strongest restyle);
  `first_frame` pins it as the opening keyframe and changes it across the clip (closest to the
  source, and references only reach the text encoder).

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
