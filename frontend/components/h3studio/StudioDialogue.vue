<template>
  <div class="dlg" @paste="onPaste" @keydown.alt.enter.prevent="add()">
    <div class="dhead">
      <i class="mdi mdi-comment-quote-outline" />
      <span class="lbl">dialogue</span>
      <span
        v-if="talk"
        class="soft"
        :class="{ over: talk > seconds }"
        :title="
          talk > seconds ? 'Probably longer than the shot' : 'Roughly how long it takes to say'
        "
      >
        ~{{ talk.toFixed(1) }}s of {{ seconds.toFixed(1) }}s
      </span>
      <span class="grow" />
      <ZenIconButton
        icon="mdi mdi-script-text-outline"
        title="Paste a script: one NAME: words per line"
        @click="scriptOpen = !scriptOpen"
      />
      <ZenIconButton icon="mdi mdi-plus" title="Add a line (Alt+Enter)" @click="add()" />
    </div>

    <div v-if="scriptOpen" class="script">
      <textarea
        v-model="script"
        rows="4"
        spellcheck="false"
        placeholder="ANNA: I get off at the next station.&#10;BEN (whispering): Wait.&#10;ANNA (V.O.): I still remember that road.&#10;ANNA & BEN: Wait for us!"
        @keydown.ctrl.enter.prevent="applyScript"
      />
      <div class="row">
        <span class="hintline"
          >A name is a voice, a reference's @name, or a new voice. (V.O.) is a voice-over, (sings)
          sung, anything else in brackets is how it's said.</span
        >
        <ZenButton sm icon="mdi mdi-check" :disabled="!script.trim()" @click="applyScript"
          >Add lines</ZenButton
        >
      </div>
    </div>

    <div
      v-for="(line, i) in lines"
      :key="line.id"
      class="line"
      :class="{ over: times.get(line.id)?.over }"
      :style="{ '--vc': voiceColor(project, line.speakers[0]) }"
    >
      <div class="lhead">
        <span class="whos">
          <button
            v-for="v in cast"
            :key="v.id"
            type="button"
            class="who"
            :class="{ on: line.speakers.includes(v.id) }"
            :style="{ '--vc': voiceColor(project, v.id) }"
            :title="`${v.name}${refName(v.ref)} — click to speak, Shift+click to speak together`"
            @click="pick(line, v.id, $event.shiftKey)"
          >
            <img v-if="voiceThumb(project, v)" class="face" :src="voiceThumb(project, v)" alt="" />
            <span v-else class="dot" />
            {{ v.name }}
          </button>
          <button type="button" class="who add" title="A new voice" @click="addVoice(line)">
            <i class="mdi mdi-account-plus-outline" />
          </button>
        </span>
        <button
          v-for="m in MODES"
          :key="m.value"
          type="button"
          class="mode"
          :class="{ on: line.mode === m.value }"
          :title="m.title"
          @click="line.mode = m.value"
        >
          <i :class="m.icon" />
        </button>
        <ZenIconButton icon="mdi mdi-close" title="Remove this line" @click="remove(i)" />
      </div>
      <textarea
        :ref="(el) => (areas[i] = el as HTMLTextAreaElement | null)"
        v-model="line.words"
        class="words"
        rows="1"
        spellcheck="false"
        :placeholder="`What ${speakerNames(project, line)} ${line.mode === 'sing' ? 'sings' : 'says'}, word for word`"
        @keydown="onWordsKey($event, i)"
      />
      <div class="row how">
        <span
          v-if="times.get(line.id)"
          class="when"
          :title="
            line.at === undefined
              ? 'Follows straight on — drag it on the timeline to place it'
              : 'Placed on the timeline'
          "
        >
          <i class="mdi mdi-clock-outline" />{{ times.get(line.id)!.start.toFixed(1) }}s
          <template v-if="times.get(line.id)!.gap > PAUSE">· pause</template>
          <button
            v-if="line.at !== undefined"
            type="button"
            class="unpin"
            title="Follow straight on again"
            @click="line.at = undefined"
          >
            <i class="mdi mdi-close" />
          </button>
        </span>
        <input
          v-model="line.delivery"
          class="delivery"
          placeholder="how — softly, with a laugh…"
          :list="`dlv-${uidBase}`"
        />
        <button
          type="button"
          class="flag"
          :class="{ on: crosses.has(line.id) || !!line.next }"
          :disabled="last"
          :title="
            last
              ? 'The last shot has no cut to cross'
              : 'The line carries on over the cut into the next shot'
          "
          @click="toggleCross(line)"
        >
          <i class="mdi mdi-arrow-right-bold-box-outline" /> over the cut
        </button>
        <button
          type="button"
          class="flag"
          :class="{ on: line.cutoff }"
          :disabled="!last"
          :title="
            last
              ? 'Cut short by the end of the clip'
              : 'Only the last shot can be cut off by the end'
          "
          @click="line.cutoff = !line.cutoff"
        >
          <i class="mdi mdi-content-cut" /> cut off
        </button>
      </div>
      <textarea
        v-if="crosses.has(line.id) || line.next"
        v-model="line.next"
        class="words next"
        rows="1"
        spellcheck="false"
        placeholder="…and the rest, heard over the next shot"
      />
    </div>
    <datalist :id="`dlv-${uidBase}`">
      <option v-for="d in DELIVERIES" :key="d" :value="d" />
    </datalist>
    <p v-if="!lines.length && !scriptOpen" class="hintline">
      No one speaks. <b>+</b> adds a line; Enter in a line starts the reply. Or paste a script —
      <code>NAME: words</code>.
    </p>
  </div>
</template>

<script setup lang="ts">
// A shot's lines: who speaks (Shift+click for several at once), how, and the exact words. Enter
// in the words starts the next line for whoever spoke before (a back-and-forth), Backspace on an
// empty line removes it, Alt+Enter adds one. Pasting `NAME: words` lines reads them as a script.
import { computed, nextTick, ref } from "vue";
import { ZenButton, ZenIconButton } from "@nynxz/zenkit-ui";
import { uid, type Line, type Project, type Scene, type Shot } from "@/lib/h3studio";
import {
  DELIVERIES,
  MODES,
  newLine,
  newVoice,
  parseScript,
  PAUSE,
  lineTimes,
  speakerNames,
  voiceColor,
  voiceThumb,
} from "@/lib/h3dialogue";

const props = defineProps<{
  project: Project;
  scene: Scene;
  shot: Shot;
  index: number;
  seconds: number;
  last: boolean;
}>();
const emit = defineEmits<{ voice: [id: string] }>();

const uidBase = uid("");
/** The project document and this shot in it, shared by every view and edited in place. */
const doc = computed(() => props.project);
const shotDoc = computed(() => props.shot);
const cast = computed(() => props.project.cast ?? []);
const lines = computed(() => props.shot.lines ?? []);
const areas: (HTMLTextAreaElement | null)[] = [];
const crosses = ref(new Set<string>());
const scriptOpen = ref(false);
const script = ref("");

/** When this shot's lines are said, by line id. */
const times = computed(
  () =>
    new Map(
      lineTimes(props.scene)
        .filter((x) => x.shot === props.index)
        .map((x) => [x.line.id, x]),
    ),
);
/** How far into the shot the talking runs. */
const talk = computed(() =>
  Math.max(0, ...[...times.value.values()].map((x) => x.end - props.shot.at)),
);
const refName = (id: string) => {
  const ref = props.project.refs.find((r) => r.id === id);
  return ref ? ` (@${ref.name})` : "";
};

function setLines(next: Line[]) {
  shotDoc.value.lines = next;
}
function focusLine(i: number) {
  void nextTick(() => areas[i]?.focus());
}
/** A new line, for whoever spoke the line before last (the reply), else the last speaker. */
function add(at = lines.value.length) {
  const prev = lines.value[at - 1];
  const before = lines.value[at - 2];
  const speakers =
    before && prev && before.speakers.join() !== prev.speakers.join()
      ? before.speakers
      : (prev?.speakers ?? (cast.value[0] ? [cast.value[0].id] : []));
  const next = [...lines.value];
  next.splice(at, 0, newLine([...speakers]));
  setLines(next);
  focusLine(at);
}
function remove(i: number) {
  setLines(lines.value.filter((_, j) => j !== i));
}
function pick(line: Line, id: string, together: boolean) {
  if (!together) line.speakers = [id];
  else
    line.speakers = line.speakers.includes(id)
      ? line.speakers.filter((s) => s !== id)
      : [...line.speakers, id];
}
function addVoice(line: Line) {
  const voice = newVoice(`Voice ${cast.value.length + 1}`);
  doc.value.cast = [...cast.value, voice];
  line.speakers = [voice.id];
  emit("voice", voice.id);
}
function toggleCross(line: Line) {
  const next = new Set(crosses.value);
  if (next.has(line.id) || line.next) {
    next.delete(line.id);
    line.next = "";
  } else next.add(line.id);
  crosses.value = next;
}
function onWordsKey(e: KeyboardEvent, i: number) {
  if (e.key === "Enter" && !e.shiftKey && !e.altKey) {
    e.preventDefault();
    add(i + 1);
  } else if (e.key === "Backspace" && !lines.value[i]!.words) {
    e.preventDefault();
    remove(i);
    focusLine(Math.max(0, i - 1));
  }
}
function applyScript() {
  const { lines: parsed, voices } = parseScript(props.project, script.value);
  if (!parsed.length) return;
  if (voices.length) doc.value.cast = [...cast.value, ...voices];
  setLines([...lines.value, ...parsed]);
  script.value = "";
  scriptOpen.value = false;
}
/** A pasted script (two or more `NAME: words` lines) outside a text field becomes lines. */
function onPaste(e: ClipboardEvent) {
  const target = e.target as HTMLElement;
  if (target.tagName === "TEXTAREA" || target.tagName === "INPUT") return;
  const text = e.clipboardData?.getData("text") ?? "";
  if (text.split(/\n/).filter((l) => /^[^:]{1,40}:\s*\S/.test(l.trim())).length < 2) return;
  e.preventDefault();
  script.value = text;
  applyScript();
}
defineExpose({ add });
</script>

<style scoped>
.dlg {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.lhead {
  display: flex;
  align-items: flex-start;
  gap: 3px;
}
.whos {
  display: flex;
  flex: 1;
  flex-wrap: wrap;
  gap: 3px;
  min-width: 0;
}
.dhead,
.row {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}
.row {
  flex-wrap: wrap;
}
.dhead .mdi {
  color: var(--h3-muted);
}
.dhead .soft {
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
}
.soft.over,
.line.over .words {
  color: #f1a76b;
}
.line {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 5px 6px;
  border-left: 2px solid var(--vc, var(--h3-accent));
  border-radius: 0 var(--h3-radius) var(--h3-radius) 0;
  background: color-mix(in srgb, var(--h3-text) 3%, transparent);
}
.line.over {
  border-left-color: #f1a76b;
}
.who .face,
.who .dot {
  flex: none;
  width: 14px;
  height: 14px;
  margin-left: -4px;
  border-radius: 50%;
  object-fit: cover;
  box-shadow: 0 0 0 1.5px var(--vc);
}
.who .dot {
  width: 8px;
  height: 8px;
  margin: 0 1px 0 -2px;
  background: var(--vc);
  box-shadow: none;
}
.when {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: var(--h3-muted);
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
}
.unpin {
  display: grid;
  place-items: center;
  width: 14px;
  height: 14px;
  padding: 0;
  border: 0;
  border-radius: 3px;
  background: none;
  color: inherit;
  cursor: pointer;
}
.unpin:hover {
  background: color-mix(in srgb, var(--h3-text) 12%, transparent);
}
.who,
.mode,
.flag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 7px;
  border: 1px solid var(--h3-line);
  border-radius: 999px;
  background: none;
  color: var(--h3-muted);
  font: inherit;
  font-size: 10.5px;
  cursor: pointer;
}
.mode {
  padding: 1px 5px;
  border-radius: 5px;
}
.who:hover,
.mode:hover,
.flag:hover:not(:disabled) {
  border-color: var(--h3-accent);
  color: var(--h3-text);
}
.who.on {
  border-color: var(--vc);
  background: color-mix(in srgb, var(--vc) 28%, transparent);
  color: var(--h3-text);
}
.mode.on,
.flag.on {
  border-color: var(--h3-accent);
  background: color-mix(in srgb, var(--h3-accent) 25%, transparent);
  color: var(--h3-text);
}
.flag:disabled {
  opacity: 0.4;
  cursor: default;
}
.words,
.delivery,
.script textarea {
  box-sizing: border-box;
  width: 100%;
  padding: 4px 7px;
  border: 1px solid var(--h3-line);
  border-radius: var(--h3-radius);
  background: var(--h3-field);
  color: var(--h3-text);
  font: inherit;
  font-size: 12px;
  outline: none;
  resize: none;
  field-sizing: content;
}
.words.next {
  border-style: dashed;
}
.delivery {
  flex: 1 1 120px;
  width: auto;
  min-width: 0;
  font-size: 11px;
}
.words:focus,
.delivery:focus,
.script textarea:focus {
  border-color: var(--h3-accent);
}
.script {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.script textarea {
  font-family: ui-monospace, monospace;
  font-size: 11px;
}
.hintline {
  flex: 1 1 140px;
  margin: 0;
  color: var(--h3-muted);
  font-size: 10.5px;
}
code {
  font-size: 10px;
}
.grow {
  flex: 1;
}
</style>
