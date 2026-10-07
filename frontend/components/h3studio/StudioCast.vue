<template>
  <div ref="root" class="cast">
    <p class="hintline">
      The voices that speak. A voice linked to a reference is that subject in the prompt; its
      description is written the first time it is heard in a scene, and it keeps one speaker ID (S1,
      S2…) through the scene.
    </p>
    <div
      v-for="v in cast"
      :key="v.id"
      class="voice"
      :class="{ on: v.id === focus, lifted: dragging === v.id }"
      :style="{ '--vc': voiceColor(project, v.id) }"
    >
      <div class="row">
        <span
          v-if="cast.length > 1"
          class="grip"
          title="Drag to reorder — the timeline's voice lanes follow this order"
          @pointerdown.stop="startDrag($event, v.id)"
        >
          <i class="mdi mdi-drag-vertical" />
        </span>
        <img v-if="voiceThumb(project, v)" class="face" :src="voiceThumb(project, v, 128)" alt="" />
        <span v-else class="face none"><i class="mdi mdi-account-voice" /></span>
        <input v-model="v.name" class="name" placeholder="name — e.g. Anna, the old man" />
        <span class="soft" :title="'Lines spoken across the film'"
          >{{ spoken(v.id) }} {{ spoken(v.id) === 1 ? "line" : "lines" }}</span
        >
        <ZenIconButton
          icon="mdi mdi-trash-can-outline"
          title="Remove this voice (and its part in lines)"
          @click="remove(v.id)"
        />
      </div>
      <input
        v-model="v.voice"
        class="field"
        placeholder="sounds like — a quiet, breathy young female voice"
      />
      <div class="row">
        <label
          class="pick"
          title="The reference this voice belongs to: it becomes that <Subject N>"
        >
          <i class="mdi mdi-account-box-outline" />
          <ZenSelect v-model="v.ref" :options="refOptions" />
        </label>
        <label class="pick" title="The language the words are in">
          <i class="mdi mdi-translate" />
          <ZenSelect v-model="v.language" :options="LANGUAGES" />
        </label>
        <label
          v-if="audioOptions.length > 1"
          class="pick"
          title="An audio reference whose voice timbre this voice follows"
        >
          <i class="mdi mdi-waveform" />
          <ZenSelect v-model="v.timbre" :options="audioOptions" />
        </label>
      </div>
    </div>
    <div class="row">
      <ZenButton sm variant="ghost" icon="mdi mdi-account-plus-outline" @click="add()"
        >Voice</ZenButton
      >
      <ZenButton
        v-for="r in unvoiced"
        :key="r.id"
        sm
        variant="ghost"
        icon="mdi mdi-plus"
        :title="`A voice for @${r.name}`"
        @click="add(r.name, r.id)"
      >
        @{{ r.name }}
      </ZenButton>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { ZenButton, ZenIconButton, ZenSelect } from "@nynxz/zenkit-ui";
import type { Project } from "@/lib/h3studio";
import { LANGUAGES, newVoice, voiceColor, voiceThumb } from "@/lib/h3dialogue";

const props = defineProps<{ project: Project; focus?: string | null }>();

/** The project document, shared by every view of the studio and edited in place. */
const doc = computed(() => props.project);
const cast = computed(() => props.project.cast ?? []);
const refOptions = computed(() => [
  { value: "", label: "no reference" },
  ...props.project.refs
    .filter((r) => r.kind !== "audio")
    .map((r) => ({ value: r.id, label: `@${r.name}` })),
]);
const audioOptions = computed(() => [
  { value: "", label: "own timbre" },
  ...props.project.refs
    .filter((r) => r.kind === "audio")
    .map((r) => ({ value: r.id, label: `@${r.name}` })),
]);
/** Picture and video references with no voice yet — one click gives them one. */
const unvoiced = computed(() =>
  props.project.refs
    .filter((r) => r.kind !== "audio" && !cast.value.some((v) => v.ref === r.id))
    .slice(0, 4),
);

const spoken = (id: string) =>
  props.project.scenes.reduce(
    (n, s) =>
      n +
      s.shots.reduce(
        (m, sh) =>
          m + (sh.lines ?? []).filter((l) => l.speakers.includes(id) && l.words.trim()).length,
        0,
      ),
    0,
  );

// --- reordering: drag a card by its grip; it swaps with a neighbour once past that one's middle ---
const root = ref<HTMLElement | null>(null);
const dragging = ref<string | null>(null);
function startDrag(e: PointerEvent, id: string) {
  if (e.button !== 0) return;
  e.preventDefault();
  // Captured by the list, which stays put: a card moves in the page as it is reordered, and that
  // would drop a capture held by its grip.
  const list = root.value;
  if (!list) return;
  list.setPointerCapture(e.pointerId);
  dragging.value = id;
  const move = (m: PointerEvent) => {
    const voices = cast.value;
    const at = voices.findIndex((v) => v.id === id);
    const mid = (el: HTMLElement | undefined) => {
      const r = el?.getBoundingClientRect();
      return r ? r.top + r.height / 2 : null;
    };
    const cards = [...(root.value?.querySelectorAll<HTMLElement>(":scope > .voice") ?? [])];
    const above = mid(cards[at - 1]);
    const below = mid(cards[at + 1]);
    const to = above !== null && m.clientY < above ? at - 1 : below !== null && m.clientY > below ? at + 1 : at;
    if (to === at) return;
    const next = [...voices];
    const [moved] = next.splice(at, 1);
    next.splice(to, 0, moved!);
    doc.value.cast = next;
  };
  const up = () => {
    dragging.value = null;
    list.removeEventListener("pointermove", move);
    list.removeEventListener("pointerup", up);
  };
  list.addEventListener("pointermove", move);
  list.addEventListener("pointerup", up);
}

function add(name = `Voice ${cast.value.length + 1}`, ref = "") {
  doc.value.cast = [...cast.value, newVoice(name, ref)];
}
function remove(id: string) {
  doc.value.cast = cast.value.filter((v) => v.id !== id);
  for (const s of doc.value.scenes)
    for (const sh of s.shots)
      for (const l of sh.lines ?? []) l.speakers = l.speakers.filter((x) => x !== id);
}
</script>

<style scoped>
.cast {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 2px;
}
.voice {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 7px;
  border: 1px solid var(--h3-line);
  border-radius: var(--h3-radius);
  background: color-mix(in srgb, var(--h3-text) 2%, transparent);
}
.voice {
  border-left: 3px solid var(--vc);
}
.voice.lifted {
  box-shadow: 0 6px 18px rgb(0 0 0 / 40%);
}
.grip {
  display: grid;
  flex: none;
  place-items: center;
  width: 14px;
  margin: 0 -4px 0 -4px;
  color: var(--h3-muted);
  cursor: grab;
  touch-action: none;
}
.grip:hover {
  color: var(--h3-text);
}
.voice.on {
  border-color: var(--vc);
}
.face {
  flex: none;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  object-fit: cover;
  box-shadow: 0 0 0 2px var(--vc);
}
.face.none {
  display: grid;
  place-items: center;
  background: color-mix(in srgb, var(--vc) 25%, transparent);
  color: var(--h3-text);
}
.row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
  min-width: 0;
}
.name,
.field {
  box-sizing: border-box;
  min-width: 0;
  padding: 4px 7px;
  border: 1px solid var(--h3-line);
  border-radius: var(--h3-radius);
  background: var(--h3-field);
  color: var(--h3-text);
  font: inherit;
  font-size: 12px;
  outline: none;
}
.name {
  flex: 1;
  font-weight: 600;
}
.name:focus,
.field:focus {
  border-color: var(--h3-accent);
}
.pick {
  display: flex;
  flex: 1 1 110px;
  align-items: center;
  gap: 4px;
  min-width: 0;
  color: var(--h3-muted);
}
.pick > :deep(*:last-child) {
  flex: 1;
  min-width: 0;
}
.soft {
  color: var(--h3-muted);
  font-size: 10.5px;
}
.hintline {
  margin: 0;
  color: var(--h3-muted);
  font-size: 10.5px;
}
/* A wide, short panel (the stacked layout): each voice on one line — name, how it sounds, then its
   reference, language and timbre — so the whole cast fits the strip. */
@container h3strip (min-width: 620px) {
  .voice {
    display: grid;
    grid-template-columns: minmax(200px, 1fr) minmax(180px, 1.3fr) minmax(280px, 1.7fr);
    align-items: center;
    gap: 8px;
    padding: 5px 7px;
  }
  .voice > .row {
    flex-wrap: nowrap;
  }
  .pick {
    flex: 1 1 0;
  }
}
</style>
