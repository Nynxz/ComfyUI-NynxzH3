"""H3 Reference — one or more images that share a role."""

from __future__ import annotations

from comfy_api.latest import io

from ._base import H3Node
from ._refs import REFERENCE, ROLES, H3Refs


class NynxzH3Reference(H3Node):
    @classmethod
    def define_schema(cls):
        return cls.make_schema(
            node_id="H3.Reference",
            display_name="H3 Reference",
            description="One or more reference images for MiniMax H3 and what they contribute. "
            "'reference' gives each one a VAE latent in the DiT, the way core's node treats "
            "every image. 'semantic' passes only its vision tokens through the text encoder — no "
            "latent, so it costs nothing in the DiT sequence. Core has no such split: one VAE "
            "check decides it for every reference at once.",
            inputs=[
                io.Autogrow.Input(
                    "images",
                    template=io.Autogrow.TemplateNames(
                        io.Image.Input("image"),
                        names=[f"image_{i}" for i in range(1, 10)],
                        min=1,
                    ),
                    tooltip="Reference images. Each becomes its own <Picture i>.",
                ),
                io.Combo.Input(
                    "role",
                    options=ROLES,
                    default=REFERENCE,
                    tooltip="'reference' = pixels and meaning: a VAE latent is packed into the "
                    "DiT, so identity and structure carry. Needs a VAE on the encode node. "
                    "'semantic' = meaning only, through the vision tokens the text encoder keeps "
                    "— use it for style or mood you do not want reproduced literally.",
                ),
                io.Int.Input(
                    "vision_size",
                    default=0,
                    min=0,
                    max=2048,
                    step=32,
                    tooltip="Caps the resolution these images reach the TEXT ENCODER at, which "
                    "is what decides how literally they transfer. Qwen3-VL spends one token per "
                    "32x32 pixels and never downscales what it is given, so a full-size "
                    "reference is ~1000 tokens and reproduces closely even with no latent. 512 "
                    "is ~256 tokens, 256 is ~64. 0 leaves it to the encode node. Never upscales, "
                    "and never touches the VAE latent — a 'reference' can keep full-resolution "
                    "pixels while its vision tokens stay coarse.",
                ),
                io.String.Input(
                    "label",
                    default="",
                    tooltip="A name for these references, used in error messages. H3 addresses "
                    "them positionally as <Picture 1>, <Picture 2>, … and the encode node prints "
                    "the mapping it assigned, because latent references are emitted first.",
                ),
                H3Refs.Input(
                    "references",
                    optional=True,
                    tooltip="Chain another H3 Reference in here. Use BYPASS (Ctrl+B) to disable "
                    "one; muting breaks the chain.",
                ),
            ],
            outputs=[H3Refs.Output(display_name="references")],
        )

    @classmethod
    def execute(
        cls,
        images: io.Autogrow.Type = None,
        role=REFERENCE,
        vision_size=0,
        label="",
        references=None,
    ):
        images = images or {}
        collected = [
            images[name]
            for name in sorted(images, key=lambda n: int(n.rsplit("_", 1)[-1]))
            if images[name] is not None
        ]
        if not collected:
            raise ValueError("H3 Reference needs at least one image.")

        # Copy rather than append in place: the upstream list is the upstream node's cached
        # output, and two nodes chaining off one source must not see each other's additions.
        chained = list(references or [])
        base = label.strip() or f"reference {len(chained) + 1}"
        for index, image in enumerate(collected):
            chained.append(
                {
                    "image": image,
                    "role": role,
                    "vision_size": int(vision_size),
                    "label": base if len(collected) == 1 else f"{base}{index + 1}",
                }
            )
        return io.NodeOutput(chained)
