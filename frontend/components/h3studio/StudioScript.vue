<template>
  <ZenModal
    :open="open"
    title="Script"
    width="640px"
    height="min(620px, 86vh)"
    @update:open="(v: boolean) => emit('update:open', v)"
  >
    <div class="script">
      <ZenToggleGroup
        v-model="tab"
        :options="[
          { value: 'paste', label: 'Paste', icon: 'mdi mdi-clipboard-arrow-down-outline' },
          { value: 'copy', label: 'Copy', icon: 'mdi mdi-clipboard-arrow-up-outline' },
          { value: 'llm', label: 'Write with an LLM', icon: 'mdi mdi-robot-outline' },
        ]"
      />

      <template v-if="tab === 'paste'">
        <p class="hint">
          Paste a script — scenes, shots, timings and dialogue as text (the
          <b>Write with an LLM</b> tab has the format). @names the studio doesn't have yet become
          placeholders.
        </p>
        <textarea
          v-model="pasted"
          class="text"
          spellcheck="false"
          placeholder="## Scene 1 (5s)&#10;&#10;### 0:00&#10;@anna walks down the platform.&#10;ANNA: I get off at the next station."
        />
        <div v-if="parsed" class="summary">
          <span
            ><b>{{ parsed.scenes.length }}</b> scene{{
              parsed.scenes.length === 1 ? "" : "s"
            }}</span
          >
          <span
            ><b>{{ shotCount }}</b> shot{{ shotCount === 1 ? "" : "s" }}</span
          >
          <span
            ><b>{{ lineCount }}</b> line{{ lineCount === 1 ? "" : "s" }} of dialogue</span
          >
          <span v-if="newVoices"
            ><b>{{ newVoices }}</b> new voice{{ newVoices === 1 ? "" : "s" }}</span
          >
          <span v-if="parsed.placeholders.length"
            ><b>{{ parsed.placeholders.length }}</b> new placeholder{{
              parsed.placeholders.length === 1 ? "" : "s"
            }}</span
          >
        </div>
        <p v-if="parsed?.placeholders.length" class="note">
          <i class="mdi mdi-account-question-outline" /> New placeholders:
          {{ parsed.placeholders.map((p) => `@${p.name}`).join(", ") }} — described in words until
          you give them pictures (References tab).
        </p>
        <template v-if="drops && (drops.refs.length || drops.voices.length)">
          <p class="note">
            <i class="mdi mdi-broom" /> Replacing removes what the script doesn't use:
            {{
              [
                ...drops.refs.map((r) => `@${r.name}`),
                ...drops.voices.map((v) => `${v.name || "an unnamed voice"} (voice)`),
              ].join(", ")
            }}.
          </p>
          <ZenCheckbox v-model="keepUnused" label="Keep them anyway" />
        </template>
        <p v-for="(w, i) in parsed?.warnings ?? []" :key="i" class="warn">
          <i class="mdi mdi-alert-outline" /> {{ w }}
        </p>
        <div class="row">
          <span class="grow" />
          <ZenButton
            sm
            variant="ghost"
            icon="mdi mdi-table-row-plus-after"
            :disabled="!parsed?.scenes.length"
            @click="apply('append')"
          >
            Add after the scenes
          </ZenButton>
          <ZenButton
            sm
            variant="primary"
            icon="mdi mdi-file-replace-outline"
            :disabled="!parsed?.scenes.length"
            @click="apply('replace')"
          >
            Replace the project
          </ZenButton>
        </div>
        <p class="hint">
          Either is one undo step. Replacing makes the script the film: its scenes, style, sound and
          voices, and the references it uses (they keep their pictures). LoRA lanes, render settings
          and the canvas stay. Adding keeps everything and puts the new scenes at the end.
        </p>
      </template>

      <template v-else-if="tab === 'copy'">
        <p class="hint">
          This project as a script — to keep, to edit, or to hand to an LLM to revise and paste
          back.
        </p>
        <textarea class="text" readonly :value="written" />
        <div class="row">
          <ZenButton sm icon="mdi mdi-content-copy" @click="copy(written, 'script')">{{
            copied === "script" ? "Copied" : "Copy script"
          }}</ZenButton>
          <ZenButton
            sm
            variant="ghost"
            icon="mdi mdi-download"
            @click="download(written, 'h3-script.txt', 'text/plain')"
            >Download</ZenButton
          >
          <span class="grow" />
          <ZenButton
            sm
            variant="ghost"
            icon="mdi mdi-code-json"
            title="Everything, exactly: ids, LoRA lanes, step shapes, settings"
            @click="download(exportJson(project), 'h3-project.json', 'application/json')"
          >
            Export JSON
          </ZenButton>
          <ZenButton
            sm
            variant="ghost"
            icon="mdi mdi-file-upload-outline"
            title="Replace this project with an exported one"
            @click="pickJson"
            >Import JSON…</ZenButton
          >
          <input
            ref="fileEl"
            type="file"
            accept=".json,application/json"
            hidden
            @change="readJson"
          />
        </div>
        <div v-if="jsonError" class="warn"><i class="mdi mdi-alert-outline" /> {{ jsonError }}</div>
        <div
          v-if="pendingJson"
          class="confirm"
          role="alertdialog"
          aria-label="Replace this project?"
        >
          <b>Replace this project with the imported one?</b>
          <p>{{ pendingSummary }} — everything here is replaced. Undo brings it back.</p>
          <div class="row">
            <span class="grow" />
            <ZenButton sm variant="ghost" @click="pendingJson = null">Cancel</ZenButton>
            <ZenButton sm variant="danger" icon="mdi mdi-file-replace-outline" @click="confirmJson"
              >Replace</ZenButton
            >
          </div>
        </div>
      </template>

      <template v-else>
        <p class="hint">
          Paste this into a chat with any LLM, then describe the film you want. It explains the
          format and how H3 reads a prompt, and lists this project's references and voices — so what
          it writes pastes straight back in on the <b>Paste</b> tab.
        </p>
        <textarea class="text" readonly :value="instructions" />
        <div class="row">
          <span class="grow" />
          <ZenButton sm icon="mdi mdi-content-copy" @click="copy(instructions, 'llm')">{{
            copied === "llm" ? "Copied" : "Copy instructions"
          }}</ZenButton>
        </div>
      </template>
    </div>
  </ZenModal>
</template>

<script setup lang="ts">
// The Script dialog: paste a project as text (from an LLM, or by hand), copy it out, export or
// import it exactly as JSON, and the instructions that teach an LLM the format (lib/h3script.ts).
import { computed, ref, watch } from "vue";
import { ZenButton, ZenCheckbox, ZenModal, ZenToggleGroup } from "@nynxz/zenkit-ui";
import type { Project } from "@/lib/h3studio";
import {
  applyScript,
  exportJson,
  importJson,
  llmInstructions,
  parseProjectScript,
  replaceDrops,
  toScript,
} from "@/lib/h3script";

const props = defineProps<{ project: Project; open: boolean }>();
const emit = defineEmits<{ "update:open": [open: boolean] }>();

/** The project document, shared by every view of the studio and edited in place. */
const doc = computed(() => props.project);
const tab = ref<"paste" | "copy" | "llm">("paste");

// --- paste ---------------------------------------------------------------------------------------
const pasted = ref("");
const parsed = computed(() =>
  pasted.value.trim() ? parseProjectScript(props.project, pasted.value) : null,
);
const shotCount = computed(() => parsed.value?.scenes.reduce((n, s) => n + s.shots.length, 0) ?? 0);
const lineCount = computed(
  () =>
    parsed.value?.scenes.reduce(
      (n, s) => n + s.shots.reduce((m, sh) => m + (sh.lines?.length ?? 0), 0),
      0,
    ) ?? 0,
);
const keepUnused = ref(false);
const drops = computed(() => (parsed.value ? replaceDrops(props.project, parsed.value) : null));
const newVoices = computed(
  () =>
    parsed.value?.cast.filter((v) => !props.project.cast?.some((c) => c.id === v.id)).length ?? 0,
);
function apply(how: "replace" | "append") {
  if (!parsed.value) return;
  applyScript(doc.value, parsed.value, how, keepUnused.value);
  pasted.value = "";
  keepUnused.value = false;
  emit("update:open", false);
}

// --- copy ----------------------------------------------------------------------------------------
const written = computed(() => toScript(props.project));
const instructions = computed(() => llmInstructions(props.project));
const copied = ref<string | null>(null);
async function copy(text: string, what: string) {
  try {
    await navigator.clipboard.writeText(text);
    copied.value = what;
    setTimeout(() => (copied.value = null), 1500);
  } catch {
    copied.value = null;
  }
}
function download(text: string, name: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// --- JSON: replace the whole project, after a second click -------------------------------------
const fileEl = ref<HTMLInputElement | null>(null);
const pendingJson = ref<Project | null>(null);
const jsonError = ref("");
const pendingSummary = computed(() => {
  const p = pendingJson.value;
  if (!p) return "";
  return `${p.scenes.length} scene${p.scenes.length === 1 ? "" : "s"}, ${p.refs.length} reference${p.refs.length === 1 ? "" : "s"}, ${p.cast?.length ?? 0} voice${p.cast?.length === 1 ? "" : "s"}`;
});
function pickJson() {
  jsonError.value = "";
  fileEl.value?.click();
}
async function readJson(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  try {
    pendingJson.value = importJson(await file.text());
  } catch {
    jsonError.value = `${file.name} isn't an H3 Studio project.`;
  }
}
function confirmJson() {
  const next = pendingJson.value;
  if (!next) return;
  const target = doc.value as Project & Record<string, unknown>;
  for (const key of Object.keys(target)) if (!(key in next)) delete target[key];
  Object.assign(target, next);
  pendingJson.value = null;
  emit("update:open", false);
}

watch(
  () => props.open,
  (open) => {
    if (!open) {
      pendingJson.value = null;
      jsonError.value = "";
    }
  },
);
</script>

<style scoped>
/* One height for every tab, so switching tabs never moves the dialog: the text box takes up
   whatever the tab's other parts leave. */
.script {
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
.note {
  margin: 0;
  color: var(--zen-muted, #9aa0aa);
  font-size: 11px;
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
  font-size: 11.5px;
}
.confirm :deep(.zen-btn.danger) {
  border-color: #b91c1c;
  background: #b91c1c;
  color: #fff;
}
</style>
