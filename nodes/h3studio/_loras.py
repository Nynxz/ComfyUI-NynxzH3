"""H3 Studio's LoRA lanes, applied to one scene.

A LoRA patches the model's weights, and a scene renders all its frames in one pass through one set
of weights per step — so a lane's strength is per scene (its film curve, sampled at the scene), and
the only way it can change *within* a scene is over the sampling steps (high noise → low noise).

- In a scene with no step shapes, each LoRA is patched straight into the model (like LoRA Loader
  Model Only): no per-step overhead.
- In a scene with one, every LoRA becomes a hook on the positive conditioning — the shaped ones with
  keyframes from their shape, the rest at a constant strength — what core's Create Hook LoRA +
  Create Hook Keyframes do. The model itself is passed on untouched: with dynamic VRAM, sampling with
  hooks makes a non-dynamic copy of the model and keeps it on that model object, so the same object
  scene after scene (and run after run) reuses one copy. A clone per scene would load the whole
  model again each time, which runs a model like H3 out of memory.
"""

from __future__ import annotations

import logging
import os
from typing import Any

LOG = logging.getLogger(__name__)

#: Loaded LoRA files, by path, kept while their file is unchanged (a loop renders scene after scene).
_cache: dict[str, tuple[float, dict]] = {}
_CACHE_MAX = 6


def _load(name: str) -> dict | None:
    import comfy.utils
    import folder_paths

    path = folder_paths.get_full_path("loras", name)
    if not path:
        return None
    mtime = os.path.getmtime(path)
    hit = _cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    lora = comfy.utils.load_torch_file(path, safe_load=True)
    if len(_cache) >= _CACHE_MAX:
        _cache.pop(next(iter(_cache)))
    _cache[path] = (mtime, lora)
    return lora


def _keyframes(points: list[dict[str, float]], detail: int):
    """A shape over sampling progress (0 = first step, high noise) as hook keyframes: read at
    `detail` evenly spaced points, keeping only those where the strength changes — each keyframe
    re-patches every layer the LoRA touches, so "early only" is two, not a dozen."""
    import comfy.hooks

    from ._project import curve_at

    group = comfy.hooks.HookKeyframeGroup()
    last = None
    for i in range(detail):
        p = i / detail
        v = round(curve_at(points, "p", p, 1.0), 2)
        if last is None or abs(v - last) >= 0.01:
            group.add(comfy.hooks.HookKeyframe(strength=v, start_percent=p))
            last = v
    return group


def _hooks_fail_on(model) -> bool:
    """Whether hook LoRAs would fail on this model: its weights are quantized (scaled fp8 and the
    like) and ComfyUI's hook patcher can't handle those yet. That patcher walks every state-dict
    key, and quantized layers list scale tensors that are not attributes of the layer
    (`'Linear' object has no attribute 'weight_scale'`). A ComfyUI with the fix has
    `model_patcher.put_hook_weight`."""
    import comfy.model_patcher

    if hasattr(comfy.model_patcher, "put_hook_weight"):
        return False
    return any(k.endswith(("weight_scale", "comfy_quant")) for k in model.model_state_dict())


def _is_dynamic(model) -> bool:
    """Whether the model runs with ComfyUI's dynamic VRAM, where hooks need a second copy of it."""
    is_dynamic = getattr(model, "is_dynamic", None)
    return bool(is_dynamic and is_dynamic())


def _mean(points: list[dict[str, float]]) -> float:
    from ._project import curve_at

    n = 24
    return sum(curve_at(points, "p", (i + 0.5) / n, 1.0) for i in range(n)) / n


def apply(
    model,
    positive,
    loras: list[dict[str, Any]],
    warnings: list[str],
    settings: dict[str, Any] | None = None,
):
    """The model with the scene's constant LoRAs patched in, and the positive conditioning with
    its scheduled ones hooked on. Either is returned as given when nothing applies to it."""
    if not loras:
        return model, positive
    if model is None:
        warnings.append("LoRA lanes need the model wired into H3 Studio Setup — they were skipped.")
        return model, positive

    import comfy.hooks
    import comfy.sd

    settings = settings or {}
    verbose = settings.get("verbose", False)
    shaped = any(lane["sampling"] for lane in loras)
    dynamic = shaped and settings.get("hooks", "auto") == "auto" and _is_dynamic(model)
    quantized = shaped and not dynamic and _hooks_fail_on(model)
    hooked = shaped and not dynamic and not quantized
    hooks = None
    for lane in loras:
        lora = _load(lane["name"])
        if lora is None:
            warnings.append(f"LoRA {lane['name']} was not found — skipped.")
            continue
        if hooked:
            hook = comfy.hooks.create_hook_lora(
                lora=lora, strength_model=lane["strength"], strength_clip=0
            )
            if lane["sampling"]:
                keyframes = _keyframes(lane["sampling"], settings.get("step_detail", 8))
                hook.set_keyframes_on_hooks(hook_kf=keyframes)
                if verbose:
                    LOG.info(
                        "H3 Studio LoRA %s hooked at %s: %s",
                        lane["name"],
                        lane["strength"],
                        ", ".join(
                            f"{k.start_percent:.0%}→{k.strength}" for k in keyframes.keyframes
                        ),
                    )
            elif verbose:
                LOG.info("H3 Studio LoRA %s hooked at %s", lane["name"], lane["strength"])
            hooks = hook if hooks is None else hooks.clone_and_combine(hook)
            continue
        strength = lane["strength"]
        if lane["sampling"]:
            warnings.append(
                f"{lane['name']}: dynamic VRAM is on, and hooks would load a second copy of the "
                "model — its step shape is applied at its average. Launch ComfyUI with "
                "--disable-dynamic-vram to use step shapes (or choose Fast in Studio settings)."
                if dynamic
                else f"{lane['name']}: this model is quantized, which this ComfyUI's per-step LoRA "
                "hooks can't patch yet — it is applied at the average of its step shape instead."
            )
            strength *= _mean(lane["sampling"])
        model, _ = comfy.sd.load_lora_for_models(model, None, lora, strength, 0)
    if hooks is not None:
        positive = comfy.hooks.set_hooks_for_conditioning(positive, hooks)
        # MaxSpeed (ComfyUI's default) caches patched weights on the GPU; MinVram re-patches from
        # system RAM at each change. Set on the model itself, which is passed on as it came.
        model.set_hook_mode(
            comfy.hooks.EnumHookMode.MinVram
            if settings.get("hooks") == "low_vram"
            else comfy.hooks.EnumHookMode.MaxSpeed
        )
    LOG.info(
        "H3 Studio LoRAs: %s", ", ".join(f"{lane['name']}@{lane['strength']}" for lane in loras)
    )
    return model, positive
