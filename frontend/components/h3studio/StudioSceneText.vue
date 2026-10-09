<template>
  <ZenModal
    :open="scene !== null"
    :title="`Scene ${(scene ?? 0) + 1} as text`"
    width="600px"
    height="min(560px, 86vh)"
    @update:open="(v: boolean) => !v && emit('close')"
  >
    <div class="scenetext">
      <p class="hint">
        This scene in the script format. Edit it here, or copy it out (to an LLM, say) and paste the
        new version over it. Applying replaces the scene's heading, sound and shots; its seed,
        keyframes and renders stay.
      </p>
      <textarea v-model="text" class="text" spellcheck="false" />
      <div v-if="parsed && one" class="summary">
        <span
          ><b>{{ one.shots.length }}</b> shot{{ one.shots.length === 1 ? "" : "s" }}</span
        >
        <span
          ><b>{{ lineCount }}</b> line{{ lineCount === 1 ? "" : "s" }} of dialogue</span
        >
        <span
          ><b>{{ one.seconds }}s</b></span
        >
        <span v-if="newVoices"
          ><b>{{ newVoices }}</b> new voice{{ newVoices === 1 ? "" : "s" }}</span
        >
        <span v-if="parsed.placeholders.length"
          ><b>{{ parsed.placeholders.length }}</b> new placeholder{{
            parsed.placeholders.length === 1 ? "" : "s"
          }}: {{ parsed.placeholders.map((p) => `@${p.name}`).join(", ") }}</span
        >
      </div>
      <p v-if="problem" class="warn"><i class="mdi mdi-alert-outline" /> {{ problem }}</p>
      <p v-for="(w, i) in parsed?.warnings ?? []" :key="i" class="warn">
        <i class="mdi mdi-alert-outline" /> {{ w }}
      </p>
      <div class="row">
        <ZenButton sm icon="mdi mdi-content-copy" @click="copy">{{
          copied ? "Copied" : "Copy"
        }}</ZenButton>
        <span class="grow" />
        <ZenButton sm variant="ghost" @click="emit('close')">Cancel</ZenButton>
        <ZenButton
          sm
          variant="primary"
          icon="mdi mdi-file-replace-outline"
          :disabled="!!problem || !changed"
          @click="apply"
        >
          Replace scene {{ (scene ?? 0) + 1 }}
        </ZenButton>
      </div>
    </div>
  </ZenModal>
</template>

<script setup lang="ts">
// One scene as script text: edit it, or paste a new version of it over the scene (lib/h3script.ts).
import { computed, ref, watch } from "vue";
import { ZenButton, ZenModal } from "@nynxz/zenkit-ui";
import type { Project } from "@/lib/h3studio";
import { applySceneScript, parseProjectScript, sceneToScript } from "@/lib/h3script";

const props = defineProps<{ project: Project; scene: number | null }>();
const emit = defineEmits<{ close: [] }>();

const text = ref("");
const original = ref("");
watch(
  () => props.scene,
  (i) => {
    original.value = i === null ? "" : sceneToScript(props.project, i);
    text.value = original.value;
  },
  { immediate: true },
);
const changed = computed(() => text.value.trim() !== original.value.trim());

const parsed = computed(() =>
  text.value.trim() ? parseProjectScript(props.project, text.value) : null,
);
const one = computed(() => (parsed.value?.scenes.length === 1 ? parsed.value.scenes[0]! : null));
const problem = computed(() => {
  const n = parsed.value?.scenes.length ?? 0;
  if (!text.value.trim()) return "Nothing to apply.";
  if (n === 0) return 'Start the scene with a "## Scene" heading, e.g. "## Scene 3 (6s, cut)".';
  if (n > 1) return `That's ${n} scenes — paste one here, or use Script ▸ Paste for several.`;
  return "";
});
const lineCount = computed(
  () => one.value?.shots.reduce((n, sh) => n + (sh.lines?.length ?? 0), 0) ?? 0,
);
const newVoices = computed(
  () =>
    parsed.value?.cast.filter((v) => !props.project.cast?.some((c) => c.id === v.id)).length ?? 0,
);

function apply() {
  if (props.scene === null || !parsed.value || problem.value) return;
  applySceneScript(props.project, props.scene, parsed.value);
  emit("close");
}

const copied = ref(false);
async function copy() {
  try {
    await navigator.clipboard.writeText(text.value);
    copied.value = true;
    setTimeout(() => (copied.value = false), 1500);
  } catch {
    copied.value = false;
  }
}
</script>

<style scoped>
.scenetext {
  display: flex;
  flex-direction: column;
  gap: 8px;
  height: 100%;
  min-height: 0;
  padding: 2px 2px 6px;
  box-sizing: border-box;
}
.text {
  box-sizing: border-box;
  flex: 1 1 0;
  width: 100%;
  min-height: 120px;
  padding: 8px 10px;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: var(--zen-radius, 8px);
  background: var(--zen-field-bg, var(--zen-input, #1b1b20));
  color: var(--zen-text, #e5e5ea);
  font-family: var(--zen-mono, ui-monospace, monospace);
  font-size: 11.5px;
  line-height: 1.5;
  resize: none;
  outline: none;
}
.text:focus {
  border-color: var(--zen-accent, #6366f1);
}
.hint {
  margin: 0;
  color: var(--zen-muted, #9aa0aa);
  font-size: 11px;
  line-height: 1.45;
}
.summary {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  color: var(--zen-muted, #9aa0aa);
  font-size: 11.5px;
}
.summary b {
  color: var(--zen-text, #e5e5ea);
}
.warn {
  margin: 0;
  color: #e09a2d;
  font-size: 11px;
}
.row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.grow {
  flex: 1;
}
</style>
