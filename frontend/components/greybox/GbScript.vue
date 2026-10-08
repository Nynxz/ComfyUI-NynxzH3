<template>
  <div class="gbs">
    <div class="bar">
      <ZenToggleGroup
        :model-value="tab"
        size="sm"
        :options="[
          { value: 'scene', label: 'Scene', icon: 'mdi mdi-movie-open-outline' },
          { value: 'set', label: 'Set', icon: 'mdi mdi-cube-outline' },
        ]"
        @update:model-value="(v: string) => open(v as Kind)"
      />
      <span class="grow" />
      <ZenButton
        size="sm"
        variant="ghost"
        icon="mdi mdi-refresh"
        title="Write the script again from the scene as it is now (drops edits here)"
        :disabled="busy"
        @click="load(tab)"
        >Reload</ZenButton
      >
      <ZenButton size="sm" variant="ghost" icon="mdi mdi-content-copy" @click="copy"
        >Copy</ZenButton
      >
      <ZenButton
        size="sm"
        variant="primary"
        icon="mdi mdi-check"
        :title="`Read the script and replace the ${tab} with it (undo puts it back)`"
        :disabled="busy || !text[tab].trim()"
        @click="apply"
        >Apply</ZenButton
      >
    </div>
    <textarea
      v-model="text[tab]"
      class="text"
      spellcheck="false"
      :placeholder="busy ? 'Writing the script…' : ''"
      @keydown.stop
    />
    <div v-if="errors.length" class="errors">
      <b>Not applied — {{ errors.length }} to fix:</b>
      <div v-for="e in errors" :key="e">{{ e }}</div>
    </div>
    <p v-else class="hint">
      {{ note }}
    </p>
  </div>
</template>

<script setup lang="ts">
// Grey Box Studio's Script panel: the open scene (or its set) as a Grey Box script, to read, copy,
// edit or replace by pasting. Applying checks it against the set first (marks, shapes, surfaces);
// with any error nothing changes, and a clean script replaces the scene or set as one undo step.
import { onMounted, reactive, ref } from "vue";
import { ZenButton, ZenToggleGroup } from "@nynxz/zenkit-ui";
import { exportScript, importScript, type GreyBoxSession } from "@/lib/greyboxDoc";

type Kind = "scene" | "set";
const props = defineProps<{ session: GreyBoxSession }>();
const s = props.session;

const tab = ref<Kind>("scene");
const text = reactive<Record<Kind, string>>({ scene: "", set: "" });
const loaded = reactive<Record<Kind, boolean>>({ scene: false, set: false });
const errors = ref<string[]>([]);
const busy = ref(false);
const note = ref("Edit the script, or paste one in, then Apply. Undo puts the old one back.");

async function load(kind: Kind) {
  busy.value = true;
  errors.value = [];
  try {
    text[kind] = await exportScript(s, kind, kind === "scene" ? s.doc.scene : s.doc.set);
    loaded[kind] = true;
  } catch (e) {
    errors.value = [e instanceof Error ? e.message : String(e)];
  } finally {
    busy.value = false;
  }
}
function open(kind: Kind) {
  tab.value = kind;
  errors.value = [];
  if (!loaded[kind]) void load(kind);
}
async function apply() {
  busy.value = true;
  errors.value = [];
  try {
    const kind = tab.value;
    const res = await importScript(s, kind, text[kind]);
    if (res.errors.length) {
      errors.value = res.errors;
      return;
    }
    if (s.run(`${kind}.replace`, { [kind]: res.data })) {
      note.value = `Applied: ${s.state.message}`;
      // The script as the scene now reads back, so what's shown is what's there.
      await load(kind);
    } else errors.value = [s.state.message];
  } catch (e) {
    errors.value = [e instanceof Error ? e.message : String(e)];
  } finally {
    busy.value = false;
  }
}
async function copy() {
  try {
    await navigator.clipboard.writeText(text[tab.value]);
    note.value = "Copied.";
  } catch {
    note.value = "Couldn't copy: select the text and copy it.";
  }
}
onMounted(() => load("scene"));
</script>

<style scoped>
.gbs {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: min(720px, 80vw);
  height: min(640px, 72vh);
  padding: 8px;
  border-radius: var(--zen-radius, 8px);
  background: var(--zen-bg, var(--comfy-menu-bg, #1a1a1f));
}
.bar {
  display: flex;
  align-items: center;
  gap: 6px;
}
.grow {
  flex: 1;
}
.text {
  flex: 1;
  min-height: 0;
  padding: 8px 10px;
  border: 1px solid var(--zen-border, #3a3a44);
  border-radius: var(--zen-radius, 6px);
  background: var(--zen-input, #15151a);
  color: var(--zen-text, #e5e5ea);
  font: 12px/1.5 var(--zen-mono, ui-monospace, "SFMono-Regular", Menlo, monospace);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  overflow: auto;
  resize: none;
  tab-size: 2;
}
.errors {
  max-height: 30%;
  overflow: auto;
  padding: 6px 8px;
  border-radius: var(--zen-radius, 6px);
  background: color-mix(in srgb, var(--zen-danger, #e5484d) 14%, transparent);
  color: var(--zen-text, #e5e5ea);
  font-size: 12px;
  line-height: 1.5;
}
.hint {
  margin: 0;
  color: var(--zen-muted, #9aa0aa);
  font-size: 11.5px;
}
</style>
