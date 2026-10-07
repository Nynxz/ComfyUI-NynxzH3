"""Per-reference roles for MiniMax H3 — which references become latents, and which only inform.

H3 conditions on a reference twice, through two independent channels:

  * its **vision tokens**, spliced into the Qwen3-VL-32B conditioning behind a `<Picture i>`
    label and tagged as video modality (`minimax_token_tags`);
  * its **pixels**, as a VAE latent in `minimax_refs`, packed into the DiT sequence after the
    text.

Core's `MiniMaxH3ReferenceToVideo` couples them:

    ref_items.append({"type": "image", "data": resized})
    if vae is not None:
        ref_blocks.append({"kind": "image", ..., "latent": vae.encode(resized)})

One VAE check for every reference, so either all of them are latents or none is — the same
all-or-nothing this pack's `ComfyUI-QI21Remix` sibling unpicks for Qwen Image 2.1. The DiT has no
such limit. `PackedLayout` gives reference image k the time position `text_len + k` — packed as a
run AFTER the whole text, never spliced at its `<Picture i>` tag the way 2.1 splices at an
`image_slot` — so a reference that carries no latent simply takes no slot, and the ones that do
close up behind it. Omitting one is structurally free.

**What is NOT free is the ordinal convention.** The tokenizer labels references from per-type
counters, and nothing carries the label/latent correspondence to the model except ORDER:

    counters[kind] += 1
    add_text("<Picture %d>: " % counters["image"])

So `ref_blocks[k]` is read as `<Picture k+1>`. Latent-bearing references are therefore emitted
FIRST here, taking `<Picture 1..M>`, with semantic-only ones after them — which keeps that
correspondence exact while still letting any subset carry pixels.

    H3 Reference  image_1 [hero]   role: reference  -> <Picture 1>, latent
    H3 Reference  image_1 [style]  role: semantic   -> <Picture 2>, no latent

**`semantic` means "no VAE latent" — it does NOT mean "abstract".** Qwen3-VL patches at 16px and
merges 2x2, one vision token per 32x32 pixels, and `process_qwen2vl_images` caps at 12.8M pixels,
which no reference ever approaches. So nothing downscales a reference on its way into the text
encoder and the encode node's sizing is the only thing setting the budget. A generation-sized
1344x768 reference is **1008 vision tokens**, with DeepStack injecting multi-level ViT features at
those same positions — a dense, spatially-resolved encoding that can reproduce the image closely
with no latent at all. Dropping the latent removes one transfer channel; it does not abstract the
other one.

What buys abstraction is the token budget, and it falls with the square of resolution: 1008 at
1344x768, 256 at 512, 64 at 256, 16 at 128. Two ways to spend less:

  * `vision_size` on H3 Reference caps one reference's text-encoder resolution, independently of
    its VAE latent — so a `reference` can keep full-detail pixels while its tokens stay coarse;
  * **H3 Mood Board** collapses N images into ONE `<Picture>` — each encoded separately, their
    token spans blended position by position, the spare brackets cut out — so the model receives
    what they have in COMMON rather than N competing references. Its `resolution` is both what
    makes the spans blendable (an identical grid) and the board's whole cost.

Honest limit: a `<Picture N>` with vision tokens and no latent is a shape H3 was probably never
trained on. On Qwen Image 2.1 the equivalent demonstrably does something; here it is untested,
which is the whole reason this lives in the experimental pack rather than its own.

Images only for now. Reference videos and audio carry their own timeline spans and soundtrack
pairing, and are better left to core's node until the image case proves itself.
"""
