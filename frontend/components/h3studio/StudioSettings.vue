<template>
  <ZenModal
    :open="open"
    title="H3 Studio settings"
    width="520px"
    height="auto"
    @update:open="(v: boolean) => emit('update:open', v)"
  >
    <div class="sets">
      <h4>Rendering <span>saved with this workflow</span></h4>
      <div class="set">
        <div class="what">
          <b>LoRA step shapes</b>
          <p>
            Changing a LoRA's strength over the steps needs ComfyUI's hooks, and hooks sample on a
            separate, non-dynamic copy of the model. With dynamic VRAM on (ComfyUI's default) that
            is a second copy of H3, which runs a 32 GB card out of memory. <b>Auto</b> uses hooks
            only when dynamic VRAM is off — launch ComfyUI with
            <code>--disable-dynamic-vram</code> — and otherwise applies each shape at its average
            strength. <b>Fast</b> and <b>Low VRAM</b>
            always use hooks, caching the patched weights on the GPU or keeping them off it.
          </p>
        </div>
        <ZenToggleGroup
          :model-value="settings.hooks ?? 'auto'"
          :options="[
            { value: 'auto', label: 'Auto' },
            { value: 'fast', label: 'Fast' },
            { value: 'low_vram', label: 'Low VRAM' },
          ]"
          @update:model-value="(v: string) => set({ hooks: v as 'auto' | 'fast' | 'low_vram' })"
        />
      </div>
      <div class="set">
        <div class="what">
          <b>Step shape detail</b>
          <p>
            The most points a shape is split into. Each change re-patches the LoRA, so fewer is
            faster; only real changes count.
          </p>
        </div>
        <ZenNumber
          :model-value="settings.step_detail ?? 8"
          :min="2"
          :max="24"
          :step="1"
          :precision="0"
          @update:model-value="(v: number) => set({ step_detail: v })"
        />
      </div>
      <div class="set">
        <div class="what">
          <b>Verbose logging</b>
          <p>
            Write each scene's full prompt and its LoRA plan (strengths, hook changes) to the
            ComfyUI console.
          </p>
        </div>
        <ZenSwitch
          :model-value="settings.verbose ?? false"
          @update:model-value="(v: boolean) => set({ verbose: v })"
        />
      </div>

      <h4>Shot writer <span>this browser</span></h4>
      <div class="set">
        <div class="what">
          <b>Writer model</b>
          <p>A text encoder that can generate, used by Rewrite on each shot.</p>
        </div>
        <ZenSelect
          v-model="writerSettings.model"
          class="wide"
          :options="models.length ? models : [writerSettings.model].filter(Boolean)"
          placeholder="pick a model"
        />
      </div>
      <div class="set">
        <div class="what">
          <b>Temperature</b>
          <p>Higher writes more freely.</p>
        </div>
        <ZenNumber
          v-model="writerSettings.temperature"
          :min="0.05"
          :max="1.5"
          :step="0.05"
          :precision="2"
        />
      </div>

      <h4 class="danger">Start over</h4>
      <div class="set danger">
        <div class="what">
          <b>Clear everything</b>
          <p>Back to one empty scene. The canvas size, these settings and the layout stay.</p>
        </div>
        <ZenButton
          v-if="!confirming"
          sm
          variant="danger"
          icon="mdi mdi-delete-sweep-outline"
          @click="confirming = true"
        >
          Clear everything…
        </ZenButton>
      </div>
      <div
        v-if="confirming"
        class="confirm"
        role="alertdialog"
        aria-label="Clear the whole project?"
      >
        <b>Clear the whole project?</b>
        <p>This removes {{ removing }}. Undo (Ctrl+Z, or the undo button) brings it all back.</p>
        <div class="row">
          <ZenButton sm variant="ghost" @click="confirming = false">Cancel</ZenButton>
          <ZenButton sm variant="danger" icon="mdi mdi-delete-sweep-outline" @click="clearAll"
            >Clear everything</ZenButton
          >
        </div>
      </div>
    </div>
  </ZenModal>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import {
  ZenButton,
  ZenModal,
  ZenNumber,
  ZenSelect,
  ZenSwitch,
  ZenToggleGroup,
} from "@nynxz/zenkit-ui";
import type { Project, StudioSettings } from "@/lib/h3studio";
import { clearProject, projectContents } from "@/lib/h3edits";
import { writerModels, writerSettings } from "@/lib/h3writer";

const props = defineProps<{ project: Project; open: boolean }>();
const emit = defineEmits<{ "update:open": [open: boolean] }>();

/** The project document, shared by every view of the studio and edited in place. */
const doc = computed(() => props.project);
const settings = computed<StudioSettings>(() => props.project.settings ?? {});
const set = (change: Partial<StudioSettings>) =>
  (doc.value.settings = { ...settings.value, ...change });

// --- start over: a second, explicit click, and it can be undone ---------------------------------
const confirming = ref(false);
const removing = computed(() => {
  const c = projectContents(props.project);
  const part = (n: number, one: string, many = `${one}s`) =>
    n ? `${n} ${n === 1 ? one : many}` : "";
  const parts = [
    part(c.scenes, "scene"),
    part(c.shots, "shot"),
    part(c.lines, "line of dialogue", "lines of dialogue"),
    part(c.keyframes, "keyframe"),
    part(c.refs, "reference"),
    part(c.voices, "voice"),
    part(c.loras, "LoRA lane"),
  ].filter(Boolean);
  return parts.length > 1
    ? `${parts.slice(0, -1).join(", ")} and ${parts.at(-1)}`
    : (parts[0] ?? "nothing but an empty scene");
});
function clearAll() {
  clearProject(doc.value);
  confirming.value = false;
  emit("update:open", false);
}
watch(
  () => props.open,
  (open) => {
    if (!open) confirming.value = false;
  },
);

const models = ref<string[]>([]);
watch(
  () => props.open,
  async (open) => {
    if (!open || models.value.length) return;
    try {
      models.value = (await writerModels()).models;
    } catch {
      // the list fills in once ComfyUI answers
    }
  },
);
</script>

<style scoped>
.sets {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 2px 8px;
}
h4 {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin: 8px 0 0;
  font-size: 12px;
}
h4 span {
  color: var(--zen-muted, #9aa0aa);
  font-size: 10.5px;
  font-weight: 400;
}
.set {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 8px 10px;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: var(--zen-radius, 8px);
}
.what {
  flex: 1;
  min-width: 0;
}
.what b {
  font-size: 12px;
}
.what p {
  margin: 3px 0 0;
  color: var(--zen-muted, #9aa0aa);
  font-size: 11px;
  line-height: 1.45;
}
.set > :last-child {
  flex: none;
}
h4.danger {
  color: #e5807d;
}
.set.danger {
  border-color: color-mix(in srgb, #c4524f 55%, var(--zen-border, #34343c));
}
.confirm {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  border: 1px solid #c4524f;
  border-radius: var(--zen-radius, 8px);
  background: color-mix(in srgb, #c4524f 12%, transparent);
}
.confirm p {
  margin: 0;
  color: var(--zen-text, #e5e5ea);
  font-size: 11.5px;
  line-height: 1.45;
}
/* The one button that actually clears is red before it is hovered, not only after. */
.confirm :deep(.zen-btn.danger) {
  border-color: #b91c1c;
  background: #b91c1c;
  color: #fff;
}
.confirm .row {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}
.what code {
  white-space: nowrap;
}
.wide {
  width: 210px;
}
</style>
