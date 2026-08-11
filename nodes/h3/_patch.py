"""Installing block patches that compose, instead of overwriting each other.

`set_model_patch_replace` files one callable per `(block_name, index)` key. Two nodes that both
want to wrap block 12 do not stack — the second silently wins, and the first appears to be doing
nothing. That is a real conflict in this group: profiling a run *with* the block cache on is the
only way to see what the cache bought, so the two nodes have to coexist.

The fix is small: read whatever patch is already at the key and hand it to the new one as its
"run the rest of the chain" callable. `extra["original_block"]` is only used when the chain is
empty, so the innermost patch still reaches the real block.
"""

from __future__ import annotations


def block_patch(model_options: dict, index: int, wrap):
    """Build a patch for block `index` that composes with any already installed there.

    `wrap(args, run)` is the caller's logic: `args` is the block's argument dict, and calling
    `run(args)` executes the rest of the chain (ending at the real block) and returns its
    `{"img": ...}` result. Not calling `run` skips the block entirely, which is what makes
    step caching possible.
    """
    previous = (
        model_options.get("transformer_options", {})
        .get("patches_replace", {})
        .get("dit", {})
        .get(("double_block", index))
    )

    def patch(args, extra):
        if previous is not None:
            return wrap(args, lambda inner: previous(inner, extra))
        return wrap(args, extra["original_block"])

    return patch
