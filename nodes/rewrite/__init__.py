"""Prompt rewriting — turning a short request into an H3 prompt before anything is sampled.

    _prompt.py   the trained system prompt and chat template, vendored verbatim
    _rewrite.py  reference-frame ordering and response cleanup, the logic the nodes are thin over
    node.py      H3 Rewrite Prompt / H3 Rewrite Clean / H3 CLIP LoRA

This group runs *before* the rest of the pack: it drives a Qwen3-VL-8B text encoder carrying the
MiniMax-H3 prompt-rewriter LoRA, and hands the rewritten prompt to whatever conditions the video
model. Nothing here touches H3 itself, so it needs no `_core` seam.

**The LoRA loader lives here rather than in a group of its own** because it is what makes the
rewriter run: the stock Load LoRA node demands a MODEL input, and a rewrite graph has no
diffusion model in it at all.
"""
