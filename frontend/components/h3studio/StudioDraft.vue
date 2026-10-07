<template>
  <!-- The ✨ button and its menu (in the shot card's header) -->
  <ZenPopover v-if="part === 'button'" placement="bottom-end">
    <template #trigger="{ toggle }">
      <button
        type="button"
        class="spark"
        :class="{ busy: draft.state === 'writing' }"
        :disabled="draft.state === 'writing'"
        :title="
          draft.state === 'writing' ? 'Writing a new draft…' : 'Rewrite this shot with a text model'
        "
        @click.stop="open(toggle)"
      >
        <i
          class="mdi"
          :class="draft.state === 'writing' ? 'mdi-loading mdi-spin' : 'mdi-creation'"
        />
      </button>
    </template>
    <template #default="{ close }">
      <div class="menu">
        <b class="head">Rewrite this shot</b>
        <button
          v-for="m in WRITER_MODES"
          :key="m.value"
          type="button"
          class="item"
          :disabled="!writerSettings.model"
          @click="run(m.value, close)"
        >
          <i :class="m.icon" />
          <span>
            <b>{{ m.label }}</b>
            <small>{{ m.title }}</small>
          </span>
        </button>
        <div class="sep" />
        <label class="col">
          <span class="lbl">writer model</span>
          <ZenSelect
            v-model="writerSettings.model"
            :options="models.length ? models : [writerSettings.model].filter(Boolean)"
            placeholder="pick a model"
          />
        </label>
        <label class="col">
          <span class="lbl">temperature — higher is freer</span>
          <ZenNumber
            v-model="writerSettings.temperature"
            :min="0.05"
            :max="1.5"
            :step="0.05"
            :precision="2"
          />
        </label>
        <p class="hint">
          A small job of its own on the queue, following
          <code>nodes/h3studio/writer_guide.md</code>.
        </p>
      </div>
    </template>
  </ZenPopover>

  <!-- The draft (under the shot's text) -->
  <div v-else-if="draft.state === 'ready'" class="box">
    <p class="text">
      <template v-for="(p, i) in parts" :key="i">
        <b v-if="p.mention">{{ p.text }}</b>
        <template v-else>{{ p.text }}</template>
      </template>
    </p>
    <p v-if="dropped.length" class="warn">
      <i class="mdi mdi-alert-outline" /> Lost {{ dropped.join(", ") }} — try again, or add it back
      after.
    </p>
    <div class="row">
      <ZenButton sm icon="mdi mdi-check" @click="use">Use it</ZenButton>
      <ZenButton sm variant="ghost" icon="mdi mdi-refresh" @click="run(draft.mode)"
        >Try again</ZenButton
      >
      <span class="grow" />
      <ZenButton sm variant="ghost" icon="mdi mdi-close" @click="discard">Discard</ZenButton>
    </div>
  </div>
  <p v-else-if="draft.state === 'writing'" class="box busy">
    <i class="mdi mdi-loading mdi-spin" /> Writing a new draft ({{ draft.mode }})…
  </p>
  <p v-else-if="draft.state === 'error'" class="box err">
    <i class="mdi mdi-alert-circle-outline" /> {{ draft.error }}
    <button type="button" class="linkbtn" @click="discard">Dismiss</button>
  </p>
</template>

<script setup lang="ts">
// A shot's redraft (see lib/h3writer.ts), in two parts that share one draft per shot: `button`, the
// ✨ in the shot card's header whose menu runs Polish / Expand / Tighten and picks the model, and
// `box`, the draft under the text — used (Ctrl+Z puts the old text back), tried again, or discarded.
import { computed, ref } from "vue";
import { ZenButton, ZenNumber, ZenPopover, ZenSelect } from "@nynxz/zenkit-ui";
import type { Project } from "@/lib/h3studio";
import {
  WRITER_MODES,
  cleanDraft,
  droppedMentions,
  runWriter,
  shotDrafts as drafts,
  writerAsk,
  writerModels,
  writerSettings,
  type ShotDraft,
  type WriterMode,
} from "@/lib/h3writer";

const props = defineProps<{
  project: Project;
  sceneIndex: number;
  shotIndex: number;
  part: "button" | "box";
}>();

const idle: ShotDraft = { state: "idle", mode: "polish", text: "", error: "" };

const shot = computed(() => props.project.scenes[props.sceneIndex]?.shots[props.shotIndex]);
const draft = computed<ShotDraft>(() => (shot.value && drafts.get(shot.value.id)) || idle);
function put(id: string, change: Partial<ShotDraft>) {
  drafts.set(id, { ...(drafts.get(id) ?? idle), ...change });
}

const models = ref<string[]>([]);
function open(toggle: () => void) {
  if (!models.value.length)
    void writerModels().then(
      (r) => (models.value = r.models),
      () => {},
    );
  toggle();
}

const parts = computed(() =>
  draft.value.text.split(/(@[\w-]+)/).map((text) => ({ text, mention: text.startsWith("@") })),
);
const dropped = computed(() => droppedMentions(shot.value?.text ?? "", draft.value.text));

async function run(mode: WriterMode, close?: () => void) {
  close?.();
  const id = shot.value?.id;
  if (!id) return;
  put(id, { state: "writing", mode, error: "" });
  try {
    const reply = await runWriter(
      writerAsk(props.project, props.sceneIndex, props.shotIndex, mode),
      Math.floor(Math.random() * 2 ** 31),
    );
    const text = cleanDraft(reply);
    put(
      id,
      text
        ? { state: "ready", text }
        : { state: "error", error: "The model gave back nothing — try again, or another model." },
    );
  } catch (e) {
    put(id, { state: "error", error: e instanceof Error ? e.message : String(e) });
  }
}
function use() {
  if (shot.value) shot.value.text = draft.value.text;
  discard();
}
function discard() {
  if (shot.value) drafts.delete(shot.value.id);
}
</script>

<style scoped>
.spark {
  display: grid;
  flex: none;
  place-items: center;
  width: 22px;
  height: 22px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 6px;
  background: none;
  color: var(--h3-muted);
  cursor: pointer;
}
.spark:hover:not(:disabled),
.spark.busy {
  border-color: color-mix(in srgb, var(--h3-accent) 55%, transparent);
  color: var(--h3-accent);
}
.spark:disabled {
  cursor: progress;
}
.menu {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 260px;
  padding: 8px;
}
.head {
  padding: 0 4px 2px;
  font-size: 12px;
}
.item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px;
  border: 0;
  border-radius: 6px;
  background: none;
  color: var(--zen-text, #e5e5ea);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.item:hover:not(:disabled) {
  background: color-mix(in srgb, var(--zen-accent, #6366f1) 18%, transparent);
}
.item:disabled {
  cursor: default;
  opacity: 0.45;
}
.item .mdi {
  margin-top: 1px;
  font-size: 15px;
}
.item span {
  display: flex;
  flex-direction: column;
}
.item b {
  font-size: 12px;
}
.item small {
  color: var(--zen-muted, #9aa0aa);
  font-size: 10.5px;
}
.sep {
  height: 1px;
  margin: 4px 0;
  background: var(--zen-border, #34343c);
}
.col {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 0 4px;
}
.lbl {
  color: var(--zen-muted, #9aa0aa);
  font-size: 10.5px;
}
.hint {
  margin: 2px 4px 0;
  color: var(--zen-muted, #9aa0aa);
  font-size: 10px;
}
.box {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 7px 8px;
  border: 1px dashed color-mix(in srgb, var(--h3-accent) 55%, var(--h3-line));
  border-radius: var(--h3-radius);
  background: color-mix(in srgb, var(--h3-accent) 6%, transparent);
}
.box.busy,
.box.err {
  display: block;
  color: var(--h3-muted);
  font-size: 11px;
}
.box.err {
  border-color: #c4524f;
  background: color-mix(in srgb, #c4524f 10%, transparent);
  color: var(--h3-text);
}
.text {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
}
.text b {
  color: #9db7ff;
  font-weight: 500;
}
.warn {
  margin: 0;
  color: #f1a76b;
  font-size: 10.5px;
}
.row {
  display: flex;
  align-items: center;
  gap: 4px;
}
.linkbtn {
  margin-left: 6px;
  padding: 0;
  border: 0;
  background: none;
  color: var(--h3-accent);
  font: inherit;
  text-decoration: underline;
  cursor: pointer;
}
.grow {
  flex: 1;
}
</style>
