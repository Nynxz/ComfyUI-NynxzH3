<template>
  <div
    ref="rootEl"
    class="refs"
    :class="{ dropping: fileOver, dragging: !!dragId || fileOver }"
    :style="cardPx ? { '--card': cardPx } : undefined"
    @dragover="onRootDragOver"
    @dragleave="onRootDragLeave"
    @drop="onRootDrop"
  >
    <div v-if="fileOver" class="dropmask">
      <i class="mdi mdi-tray-arrow-down" /><span>Drop to add references</span>
    </div>

    <div class="strip">
    <section
      v-for="sec in sections"
      :key="sec.id"
      class="sec"
      :class="{ vacant: !sec.refs.length, slim: isFolded(sec) }"
      :style="{ '--n': Math.max(1, sec.refs.length) }"
      :title="isFolded(sec) ? `${sec.label}${sec.hint ? ` (${sec.hint})` : ''}: ${sec.empty}` : undefined"
      @dragover="onSectionDragOver(sec.id, $event)"
      @drop="onSectionDrop(sec.id, $event)"
    >
      <header class="sechead">
        <button
          type="button"
          class="secname"
          :title="isFolded(sec) ? 'Show this section' : 'Fold this section away'"
          @click="toggleFold(sec)"
        >
          <i class="mdi" :class="sec.icon" />
          <span>{{ cardPx ? sec.short : sec.label }}</span>
        </button>
        <span v-if="sec.hint && !cardPx" class="sechint">{{ sec.hint }}</span>
        <span class="grow" />
        <span class="count">{{ sec.count }}</span>
        <ZenIconButton
          v-if="sec.kind"
          icon="mdi mdi-text-box-plus-outline"
          :title="`Add a placeholder ${PLACEHOLDER[sec.kind].noun} — described in words until you drop one in`"
          @click="emit('addProxy', sec.kind)"
        />
        <ZenIconButton
          v-if="sec.accept"
          icon="mdi mdi-plus"
          :title="`Add ${sec.noun}`"
          :disabled="sec.full"
          @click="emit('add', sec.accept)"
        />
      </header>

      <div v-show="!isFolded(sec)" class="grid">
        <div
          v-for="r in sec.refs"
          :key="r.id"
          class="card"
          :class="{
            on: selected === r.id,
            off: !inScene(r),
            proxy: !r.media,
            dragging: dragId === r.id,
            over: overId === r.id && dragId !== r.id,
            filling: fileCardId === r.id,
          }"
          @click="emit('select', r.id)"
          @contextmenu.prevent.stop="emit('menu', r.id, $event)"
          @dragover="onCardDragOver(r.id, sec.id, $event)"
          @dragleave="onCardDragLeave(r.id, $event)"
          @drop="onCardDrop(r.id, sec.id, $event)"
          @dragend="endDrag"
        >
          <div
            class="thumb"
            draggable="true"
            title="Drag to reorder · hold Shift to see it large"
            @dragstart="startDrag(r.id, $event)"
          >
            <MediaThumb :media="r.media" :badge="false" :label="r.name" />
            <span class="num" :title="tagOf(r.id)">{{ numberOf(r.id) }}</span>
            <span
              v-if="r.kind === 'image'"
              class="role"
              :class="r.role"
              :title="
                r.role === 'reference'
                  ? 'Look + meaning: H3 sees the pixels'
                  : 'Meaning only: just the text encoder'
              "
            >
              <i class="mdi" :class="r.role === 'reference' ? 'mdi-eye' : 'mdi-text-box-outline'" />
            </span>
            <span v-else class="role kind" :title="r.kind">
              <i class="mdi" :class="r.kind === 'video' ? 'mdi-video' : 'mdi-music-note'" />
            </span>
            <span
              v-if="soundtrackOf(r.id)"
              class="sound"
              :title="`Its own sound is ${soundtrackOf(r.id)}`"
            >
              <i class="mdi mdi-volume-high" />
            </span>
            <span v-if="!inScene(r)" class="outmark" title="Not used in this scene"
              ><i class="mdi mdi-eye-off"
            /></span>
            <div class="meta">
              <span class="name">@{{ r.name }}</span>
            </div>
            <div v-if="fileCardId === r.id" class="replacing">
              <i class="mdi" :class="r.media ? 'mdi-swap-horizontal' : 'mdi-image-plus-outline'" />
              <span>{{ r.media ? "Replace" : "Fill" }}</span>
            </div>
          </div>
        </div>
        <div v-if="!sec.refs.length" class="empty" @click="sec.accept && emit('add', sec.accept)">
          {{ sec.empty }}
        </div>
      </div>
    </section>
    <!-- The wide strip hides empty sections, so adding goes through one tile at its end. -->
    <ZenPopover v-if="cardPx" placement="bottom-start">
      <template #trigger="{ toggle }">
        <button type="button" class="addtile" title="Add a reference" @click="toggle">
          <i class="mdi mdi-plus" /><span>Add</span>
        </button>
      </template>
      <template #default="{ close }">
        <div class="addmenu">
          <button
            v-for="item in addItems"
            :key="item.label"
            type="button"
            :disabled="item.disabled"
            @click="item.run(); close()"
          >
            <i class="mdi" :class="item.icon" /> {{ item.label }}
          </button>
        </div>
      </template>
    </ZenPopover>
    </div>

    <!-- the selected reference -->
    <div
      v-if="current"
      class="editor"
      :class="{ filling: fileEditor }"
      @dragover="onEditorDragOver"
      @dragleave="onEditorDragLeave"
      @drop="onEditorDrop"
    >
      <div v-if="!current.media" class="proxynote">
        <i class="mdi" :class="PLACEHOLDER[current.kind].icon" />
        <div class="proxytext">
          <b>Placeholder {{ PLACEHOLDER[current.kind].noun }}</b>
          <span
            >H3 reads the description below until you drop a {{ PLACEHOLDER[current.kind].noun }}
            here or on its card.</span
          >
        </div>
        <ZenButton sm variant="primary" icon="mdi mdi-plus" @click="emit('pick', current.id)"
          >Choose…</ZenButton
        >
      </div>
      <div class="erow">
        <span class="lbl">name</span>
        <input
          v-model="current.name"
          class="field"
          spellcheck="false"
          @input="current.name = current.name.replace(/[^\w-]/g, '')"
        />
      </div>
      <div class="erow">
        <span class="lbl">is</span>
        <textarea
          v-model="current.note"
          class="field note"
          rows="2"
          placeholder="who or what — e.g. a baker in a white apron"
        />
      </div>
      <ZenToggleGroup
        v-if="current.kind === 'image'"
        v-model="current.role"
        class="wide"
        :options="[
          {
            value: 'reference',
            label: 'Look + meaning',
            icon: 'mdi mdi-eye',
            title: 'H3 sees the pixels — strongest likeness',
          },
          {
            value: 'semantic',
            label: 'Meaning only',
            icon: 'mdi mdi-text-box-outline',
            title: 'Only the text encoder sees it — a looser hint',
          },
        ]"
      />
      <ZenToggleGroup
        v-if="current.kind === 'video'"
        v-model="current.role"
        class="wide"
        :options="[
          {
            value: 'reference',
            label: 'Look + motion',
            icon: 'mdi mdi-eye',
            title: 'H3 takes the people, place and movement from the video',
          },
          {
            value: 'blocking',
            label: 'Blocking only',
            icon: 'mdi mdi-cube-scan',
            title:
              'Only the staging, timing and camera — none of its look. For grey-box renders and rough animatics',
          },
        ]"
      />
      <ZenCheckbox
        v-if="current.kind === 'video' && current.media && current.role !== 'blocking'"
        :model-value="current.soundtrack !== false"
        :label="`Use the video's own sound${soundtrackOf(current.id) ? ` (${soundtrackOf(current.id)})` : ''}`"
        @update:model-value="(v: boolean) => (current!.soundtrack = v)"
      />
      <div v-if="current.kind !== 'audio'" class="erow">
        <span class="lbl">size</span>
        <ZenToggleGroup
          :model-value="String(current.size ?? 1)"
          :options="REF_SIZES.map((s) => ({ value: String(s.value), label: s.label }))"
          @update:model-value="(v: string) => setSize(Number(v))"
        />
        <span class="soft" :title="SIZE_HINT">H3 sees it at up to {{ shownAt }}</span>
      </div>
      <div class="erow">
        <span class="lbl">scenes</span>
        <button
          v-for="(s, i) in project.scenes"
          :key="s.id"
          type="button"
          class="chip"
          :class="{ on: refInScene(project, current, s), used: refUsedIn(project, current, s) }"
          :disabled="refUsedIn(project, current, s)"
          :title="
            refUsedIn(project, current, s)
              ? `Scene ${i + 1} uses @${current.name}, so H3 is always shown it there`
              : refInScene(project, current, s)
                ? `Shown in scene ${i + 1} without being mentioned — click to leave it out`
                : `Not used in scene ${i + 1} — click to show it there anyway`
          "
          @click="emit('toggleScene', current.id, s.id)"
        >
          {{ i + 1 }}
        </button>
        <button
          type="button"
          class="chip every"
          :class="{ on: current.scenes === 'all' }"
          :title="current.scenes === 'all' ? 'Shown in every scene — click for only where used or marked' : 'Show it in every scene, used or not (a style picture, a soundtrack)'"
          @click="current.scenes = current.scenes === 'all' ? [] : 'all'"
        >
          all
        </button>
        <span class="grow" />
        <ZenButton
          v-if="current.media"
          sm
          variant="ghost"
          icon="mdi mdi-image-edit-outline"
          title="Swap the picture, keeping the name — every shot that mentions it follows"
          @click="emit('pick', current.id)"
        >
          Replace…
        </ZenButton>
        <ZenButton
          sm
          variant="ghost"
          icon="mdi mdi-trash-can-outline"
          @click="emit('remove', current.id)"
          >Remove</ZenButton
        >
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// The references panel: the scene's references in the sections H3 numbers them by — pictures it
// sees (look + meaning) first, then pictures it only reads about, then videos, then audio — as
// cards you drag to reorder. Dragging a picture between the two picture sections changes its role,
// which is the same thing as changing where H3 numbers it.
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import {
  ZenButton,
  ZenCheckbox,
  ZenIconButton,
  ZenPopover,
  ZenToggleGroup,
} from "@nynxz/zenkit-ui";
import { hasMediaDrop } from "@/framework";
import {
  LIMITS,
  REF_SIZES,
  refInScene,
  refUsedIn,
  type Compiled,
  type Project,
  type Ref,
  type StudioView,
} from "@/lib/h3studio";
import MediaThumb from "./MediaThumb.vue";

const props = defineProps<{
  project: Project;
  sceneIndex: number;
  compiled: Compiled | null;
  selected: string | null;
  /** How the studio was left: which sections are folded is kept on it. */
  view?: StudioView;
  /** In the strip under the monitor (the stacked layout), where wide means a filmstrip. */
  strip?: boolean;
}>();
const emit = defineEmits<{
  select: [id: string];
  menu: [id: string, event: MouseEvent];
  add: [accept: string];
  drop: [event: DragEvent];
  remove: [id: string];
  toggleScene: [refId: string, sceneId: string];
  pick: [id: string];
  replace: [id: string, event: DragEvent];
  addProxy: [kind: Ref["kind"]];
}>();

type SectionId = "look" | "meaning" | "video" | "audio";
const PLACEHOLDER = {
  image: { noun: "picture", icon: "mdi-image-outline" },
  video: { noun: "video", icon: "mdi-video-outline" },
  audio: { noun: "sound", icon: "mdi-music-note-outline" },
} as const;
const scene = computed(() => props.project.scenes[props.sceneIndex]);
const inScene = (r: Ref) =>
  scene.value ? refInScene(props.project, r, scene.value) : false;
const sectionOf = (r: Ref): SectionId =>
  r.kind === "image" ? (r.role === "semantic" ? "meaning" : "look") : r.kind;

const sections = computed(() => {
  const of = (id: SectionId) => props.project.refs.filter((r) => sectionOf(r) === id);
  // Against H3's limits only what it is shown counts: placeholders have no media to show, and one
  // file under several names is shown once.
  const shown = (refs: Ref[]) => new Set(refs.filter((r) => r.media && inScene(r)).map((r) => `${r.media}|${r.role}`)).size;
  const pictures = shown(props.project.refs.filter((r) => r.kind === "image"));
  const count = (id: SectionId, kind: "image" | "video" | "audio") =>
    `${shown(props.project.refs.filter((r) => sectionOf(r) === id))}${kind === "image" ? "" : `/${LIMITS[kind]}`}`;
  return [
    {
      id: "look" as const,
      short: "Pictures",
      kind: "image" as const,
      label: "Pictures",
      hint: "look + meaning",
      icon: "mdi-eye",
      noun: "pictures",
      accept: "image/*",
      refs: of("look"),
      count: `${pictures}/${LIMITS.image}`,
      full: pictures >= LIMITS.image,
      empty: "Drop pictures H3 should match closely",
    },
    {
      id: "meaning" as const,
      short: "Meaning only",
      kind: null,
      label: "Pictures",
      hint: "meaning only",
      icon: "mdi-text-box-outline",
      noun: "",
      accept: "",
      refs: of("meaning"),
      count: "",
      full: true,
      empty: "Drag a picture here for a looser hint",
    },
    {
      id: "video" as const,
      short: "Videos",
      kind: "video" as const,
      label: "Videos",
      hint: "",
      icon: "mdi-video-outline",
      noun: "a video",
      accept: "video/*",
      refs: of("video"),
      count: count("video", "video"),
      full: shown(of("video")) >= LIMITS.video,
      empty: "Drop a clip to follow its look and motion",
    },
    {
      id: "audio" as const,
      short: "Audio",
      kind: "audio" as const,
      label: "Audio",
      hint: "",
      icon: "mdi-music-note-outline",
      noun: "audio",
      accept: "audio/*",
      refs: of("audio"),
      count: count("audio", "audio"),
      full: shown(of("audio")) >= LIMITS.audio,
      empty: "Drop a voice, song or sound",
    },
  ];
});

// --- size: in the wide strip (the stacked layout) cards are as tall as the strip allows -----------
const rootEl = ref<HTMLElement | null>(null);
const box = ref({ w: 0, h: 0 });
let resizes: ResizeObserver | null = null;
onMounted(() => {
  if (!rootEl.value) return;
  resizes = new ResizeObserver(([entry]) => {
    if (entry) box.value = { w: entry.contentRect.width, h: entry.contentRect.height };
  });
  resizes.observe(rootEl.value);
});
onBeforeUnmount(() => resizes?.disconnect());
const cardPx = computed(() =>
  props.strip && box.value.w >= 600 ? `${Math.round(Math.min(200, Math.max(64, box.value.h - 48)))}px` : null,
);
const addItems = computed(() => {
  const full = (id: SectionId) => sections.value.find((s) => s.id === id)?.full ?? false;
  return [
    { label: "Pictures…", icon: "mdi-image-plus-outline", disabled: full("look"), run: () => emit("add", "image/*") },
    { label: "Video…", icon: "mdi-video-plus-outline", disabled: full("video"), run: () => emit("add", "video/*") },
    { label: "Audio…", icon: "mdi-music-note-plus", disabled: full("audio"), run: () => emit("add", "audio/*") },
    { label: "Placeholder picture", icon: "mdi-image-outline", disabled: false, run: () => emit("addProxy", "image") },
    { label: "Placeholder video", icon: "mdi-video-outline", disabled: false, run: () => emit("addProxy", "video") },
    { label: "Placeholder sound", icon: "mdi-music-note-outline", disabled: false, run: () => emit("addProxy", "audio") },
  ];
});

// --- folding: an empty section starts folded; any can be folded or opened by its name -------------
type Section = (typeof sections.value)[number];
const viewDoc = computed(() => props.view);
const folds = ref<Record<string, "open" | "folded">>({ ...(props.view?.refsFold ?? {}) });
const isFolded = (sec: Section) => (folds.value[sec.id] ?? (sec.refs.length ? "open" : "folded")) === "folded";
function toggleFold(sec: Section) {
  folds.value = { ...folds.value, [sec.id]: isFolded(sec) ? "open" : "folded" };
  if (viewDoc.value) viewDoc.value.refsFold = folds.value;
}

const compiledRef = (id: string) => props.compiled?.refs.find((r) => r.id === id);
const tagOf = (id: string) => {
  const c = compiledRef(id);
  if (!c) return "not in this scene";
  const twin = c.alias && props.compiled?.refs.find((r) => r.tag === c.tag && !r.alias);
  return twin ? `${c.tag} — the same file as @${twin.name}, so H3 is shown it once` : c.tag;
};
const numberOf = (id: string) => compiledRef(id)?.tag.replace(/\D/g, "") || "–";
const soundtrackOf = (id: string) => compiledRef(id)?.soundtrack_tag ?? null;
const current = computed(() => props.project.refs.find((r) => r.id === props.selected) ?? null);

const SIZE_HINT =
  "How big H3 is shown this reference, against the canvas. A full-size picture costs about as much as one of a 5-second scene's 37 latent frames; ½ costs a quarter of that, at some cost to likeness — fine for a setting or a loose hint, less so for a face.";
function setSize(v: number) {
  const size = REF_SIZES.find((s) => s.value === v)?.value;
  if (current.value && size) current.value.size = size;
}
/** The largest size H3 is shown the reference at: the canvas's area, scaled by its size. */
const shownAt = computed(() => {
  const s = current.value?.size ?? 1;
  const snap = (n: number) => Math.max(32, Math.round((n * s) / 32) * 32);
  return `${snap(props.project.canvas.width)}×${snap(props.project.canvas.height)} px`;
});

// --- reorder: drag a card's thumbnail onto another card (or into a section) ----------------------
const dragId = ref<string | null>(null);
const overId = ref<string | null>(null);
const fileOver = ref(false);
/** The card (or the selected reference's editor) new media is being dragged over, to replace. */
const fileCardId = ref<string | null>(null);
const fileEditor = ref(false);

function startDrag(id: string, e: DragEvent) {
  dragId.value = id;
  if (e.dataTransfer) {
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", id);
  }
}
function endDrag() {
  dragId.value = null;
  overId.value = null;
}
/** Whether the dragged card may land in a section: only within its own kind. */
function accepts(section: SectionId): boolean {
  const dragged = props.project.refs.find((r) => r.id === dragId.value);
  if (!dragged) return false;
  return dragged.kind === "image"
    ? section === "look" || section === "meaning"
    : sectionOf(dragged) === section;
}
function moveTo(section: SectionId, beforeId: string | null) {
  const refs = props.project.refs;
  const from = refs.findIndex((r) => r.id === dragId.value);
  if (from < 0) return;
  const [moved] = refs.splice(from, 1);
  if (moved!.kind === "image") moved!.role = section === "meaning" ? "semantic" : "reference";
  let to = beforeId ? refs.findIndex((r) => r.id === beforeId) : -1;
  if (to < 0) {
    // After the last card of the section, or at the end.
    const last = refs
      .map((r, i) => (sectionOf(r) === section ? i : -1))
      .filter((i) => i >= 0)
      .pop();
    to = last === undefined ? refs.length : last + 1;
  }
  refs.splice(to, 0, moved!);
}
/** Whether a dragover is new media from outside (a file, the Media Viewer…), not a card. */
const isFileDrag = (e: DragEvent) => !dragId.value && hasMediaDrop(e);

function onCardDragOver(id: string, section: SectionId, e: DragEvent) {
  if (isFileDrag(e)) {
    e.preventDefault();
    e.stopPropagation();
    fileOver.value = false;
    fileCardId.value = id;
    return;
  }
  if (!dragId.value || !accepts(section)) return;
  e.preventDefault();
  e.stopPropagation();
  overId.value = id;
}
function onCardDragLeave(id: string, e: DragEvent) {
  const to = e.relatedTarget as Node | null;
  if (fileCardId.value === id && !(e.currentTarget as HTMLElement).contains(to)) fileCardId.value = null;
}
function onCardDrop(id: string, section: SectionId, e: DragEvent) {
  if (isFileDrag(e)) {
    e.preventDefault();
    e.stopPropagation();
    fileCardId.value = null;
    emit("replace", id, e);
    return;
  }
  if (!dragId.value || !accepts(section)) return;
  e.preventDefault();
  e.stopPropagation();
  if (id !== dragId.value) moveTo(section, id);
  endDrag();
}
function onSectionDragOver(section: SectionId, e: DragEvent) {
  if (!dragId.value || !accepts(section)) return;
  e.preventDefault();
  e.stopPropagation();
  overId.value = null;
}
function onSectionDrop(section: SectionId, e: DragEvent) {
  if (!dragId.value || !accepts(section)) return;
  e.preventDefault();
  e.stopPropagation();
  moveTo(section, null);
  endDrag();
}

// --- new media dropped anywhere on the panel -------------------------------------------------------
function onRootDragOver(e: DragEvent) {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  fileOver.value = true;
  fileCardId.value = null;
}
function onRootDragLeave(e: DragEvent) {
  const to = e.relatedTarget as Node | null;
  if (!to || !(e.currentTarget as HTMLElement).contains(to)) {
    fileOver.value = false;
    fileCardId.value = null;
    fileEditor.value = false;
  }
}
function onRootDrop(e: DragEvent) {
  fileOver.value = false;
  fileCardId.value = null;
  if (dragId.value) return;
  emit("drop", e);
}

// --- new media dropped on the selected reference's editor replaces its media ---------------------
function onEditorDragOver(e: DragEvent) {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  e.stopPropagation();
  fileOver.value = false;
  fileEditor.value = true;
}
function onEditorDragLeave(e: DragEvent) {
  const to = e.relatedTarget as Node | null;
  if (!(e.currentTarget as HTMLElement).contains(to)) fileEditor.value = false;
}
function onEditorDrop(e: DragEvent) {
  fileEditor.value = false;
  if (!isFileDrag(e) || !current.value) return;
  e.preventDefault();
  e.stopPropagation();
  emit("replace", current.value.id, e);
}
</script>

<style scoped>
.refs {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
}
.dropmask {
  position: absolute;
  inset: 0;
  z-index: 5;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: 2px dashed var(--zen-accent, #6366f1);
  border-radius: var(--zen-radius, 8px);
  background: color-mix(in srgb, var(--zen-accent, #6366f1) 14%, var(--zen-surface, #202026));
  color: var(--zen-text, #e5e5ea);
  font-weight: 600;
  pointer-events: none;
}
.dropmask .mdi {
  font-size: 26px;
}
.sec {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sechead {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--zen-muted, #9aa0aa);
  font-size: 11px;
}
.sechead .mdi {
  font-size: 14px;
}
.secname {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0;
  border: 0;
  background: none;
  color: var(--zen-text, #e5e5ea);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}
.secname:hover {
  color: var(--zen-accent, #6366f1);
}
.sec.slim .secname {
  color: var(--zen-muted, #9aa0aa);
}
.sechint {
  font-size: 10.5px;
}
.count {
  font-variant-numeric: tabular-nums;
}
.grow {
  flex: 1;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(72px, 1fr));
  gap: 6px;
  min-height: 34px;
}
.card {
  padding: 3px;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: var(--zen-radius, 8px);
  background: var(--zen-input, #1b1b20);
  cursor: pointer;
  transition:
    border-color 0.12s ease,
    opacity 0.12s ease;
}
.card:hover {
  border-color: color-mix(in srgb, var(--zen-accent, #6366f1) 50%, var(--zen-border, #34343c));
}
.card.on {
  border-color: var(--zen-accent, #6366f1);
  box-shadow: 0 0 0 1px var(--zen-accent, #6366f1) inset;
}
.card.off {
  opacity: 0.5;
}
.card.dragging {
  opacity: 0.3;
}
.card.over {
  border-color: var(--zen-accent, #6366f1);
  box-shadow: -3px 0 0 var(--zen-accent, #6366f1);
}
.card.filling {
  border-color: var(--zen-accent, #6366f1);
  box-shadow: 0 0 0 2px var(--zen-accent, #6366f1);
}
.replacing {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  background: color-mix(in srgb, var(--zen-accent, #6366f1) 55%, rgb(0 0 0 / 60%));
  color: #fff;
  font-size: 10.5px;
  font-weight: 700;
  pointer-events: none;
}
.replacing .mdi {
  font-size: 20px;
}
.editor.filling {
  outline: 2px dashed var(--zen-accent, #6366f1);
  outline-offset: 2px;
  border-radius: var(--zen-radius, 8px);
}
.thumb {
  position: relative;
  aspect-ratio: 1;
  overflow: hidden;
  border-radius: calc(var(--zen-radius, 8px) * 0.75);
  background: #000;
  cursor: grab;
}
.thumb:active {
  cursor: grabbing;
}
.num,
.role,
.sound {
  position: absolute;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: calc(var(--zen-radius, 8px) * 0.6);
  background: rgb(0 0 0 / 65%);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
}
.num {
  top: 3px;
  left: 3px;
}
.role {
  top: 3px;
  right: 3px;
  padding: 0 3px;
  font-size: 11px;
}
.role.reference {
  background: var(--zen-accent, #6366f1);
}
.role.semantic {
  background: rgb(0 0 0 / 70%);
  color: #cfd3dc;
}
.sound {
  right: 3px;
  bottom: 18px;
  padding: 0 3px;
  font-size: 10px;
}
.outmark {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  background: rgb(0 0 0 / 45%);
  color: #fff;
  font-size: 18px;
}
.meta {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  padding: 10px 4px 2px;
  background: linear-gradient(transparent, rgb(0 0 0 / 80%));
  pointer-events: none;
}
.name {
  display: block;
  overflow: hidden;
  color: #fff;
  font-size: 10px;
  font-weight: 600;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.empty {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 34px;
  padding: 0 8px;
  border: 1px dashed var(--zen-border, #34343c);
  border-radius: var(--zen-radius, 8px);
  color: var(--zen-muted, #9aa0aa);
  font-size: 10.5px;
  text-align: center;
  cursor: pointer;
}
.card.proxy .name {
  font-style: italic;
}
.proxynote {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px dashed color-mix(in srgb, var(--zen-accent, #6366f1) 55%, var(--zen-border, #34343c));
  border-radius: var(--zen-radius, 8px);
  background: color-mix(in srgb, var(--zen-accent, #6366f1) 7%, transparent);
}
.proxynote > .mdi {
  flex: none;
  color: var(--zen-accent, #6366f1);
  font-size: 20px;
}
.proxytext {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  color: var(--zen-muted, #9aa0aa);
  font-size: 10.5px;
  line-height: 1.35;
}
.proxytext b {
  color: var(--zen-text, #e5e5ea);
  font-size: 11.5px;
  font-weight: 600;
}
.editor {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding-top: 10px;
  border-top: 1px solid var(--zen-border, #34343c);
}
.soft {
  color: var(--zen-muted, #9aa0aa);
  font-size: 10.5px;
}
.field.note {
  min-height: calc(2lh + 10px);
  max-height: calc(6lh + 10px);
  line-height: 1.4;
  resize: none;
  field-sizing: content;
}
.erow {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.lbl {
  min-width: 40px;
  color: var(--zen-muted, #9aa0aa);
  font-size: 10.5px;
  font-weight: 600;
}
.field {
  flex: 1;
  min-width: 0;
  padding: 5px 8px;
  border: 1px solid var(--zen-control-border, var(--zen-border, #34343c));
  border-radius: var(--zen-radius, 7px);
  outline: none;
  background: var(--zen-field-bg, var(--zen-input, #1b1b20));
  color: var(--zen-text, #e5e5ea);
  font: inherit;
  font-size: 12px;
}
.field:focus {
  border-color: var(--zen-accent, #6366f1);
}
.wide :deep(.zen-tg) {
  display: flex;
  width: 100%;
}
.wide :deep(.zen-tg-b) {
  flex: 1;
}
.chip {
  min-width: 24px;
  height: 22px;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: calc(var(--zen-radius, 8px) * 0.75);
  background: none;
  color: var(--zen-muted, #9aa0aa);
  font: inherit;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
}
/* Solid: the scene uses it. Dashed: marked to show there anyway. */
.chip.used {
  cursor: default;
  opacity: 1;
}
.chip.on:not(.used) {
  border-style: dashed;
}
.chip.every {
  min-width: 30px;
  font-weight: 600;
}
.chip.on {
  border-color: var(--zen-accent, #6366f1);
  background: color-mix(in srgb, var(--zen-accent, #6366f1) 25%, transparent);
  color: var(--zen-text, #e5e5ea);
}
.strip {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.addtile {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  width: calc(var(--card, 72px) * 0.6);
  height: var(--card, 72px);
  margin: 28px 0 0 10px;
  border: 1px dashed var(--zen-border, #34343c);
  border-radius: var(--zen-radius, 8px);
  background: none;
  color: var(--zen-muted, #9aa0aa);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}
.addtile:hover {
  border-color: var(--zen-accent, #6366f1);
  color: var(--zen-text, #e5e5ea);
}
.addtile .mdi {
  font-size: 20px;
}
.addmenu {
  display: flex;
  flex-direction: column;
  min-width: 190px;
  padding: 4px;
}
.addmenu button {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: 0;
  border-radius: calc(var(--zen-radius, 8px) * 0.75);
  background: none;
  color: var(--zen-text, #e5e5ea);
  font: inherit;
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}
.addmenu button:hover:not(:disabled) {
  background: color-mix(in srgb, var(--zen-accent, #6366f1) 18%, transparent);
}
.addmenu button:disabled {
  opacity: 0.45;
  cursor: default;
}
/* A wide, short panel (the stacked layout): the sections side by side, each scrolling on its own,
   with the selected reference's editor as a column on the right — not one long scroll. */
@container h3strip (min-width: 620px) {
  .refs {
    flex-direction: row;
    gap: 0;
    height: 100%;
  }
  /* A filmstrip: each section exactly as wide as its cards, packed from the left; empty sections
     hidden (shown slim while something is dragged, to drop on); cards as tall as the strip. */
  .strip {
    flex: 1;
    flex-direction: row;
    gap: 0;
    min-width: 0;
    overflow-x: auto;
    overflow-y: hidden;
  }
  .sec {
    flex: none;
    min-height: 0;
    overflow: hidden;
    padding: 0 10px;
    border-right: 1px solid var(--zen-border, #34343c);
  }
  .sec:first-of-type {
    padding-left: 0;
  }
  .grid {
    grid-template-columns: repeat(var(--n), var(--card, 72px));
  }
  .name {
    font-size: clamp(10px, calc(var(--card, 72px) / 9), 12.5px);
  }
  .refs:not(.dragging) .sec.vacant {
    display: none;
  }
  .sec.slim,
  .refs.dragging .sec.vacant {
    flex: 0 0 30px;
    min-width: 0;
    padding: 0 4px;
  }
  .sec.slim .sechead,
  .refs.dragging .sec.vacant .sechead {
    flex-direction: column;
    align-items: center;
    height: 100%;
  }
  .sec.slim .secname,
  .refs.dragging .sec.vacant .secname {
    writing-mode: vertical-rl;
    transform: rotate(180deg);
  }
  .sec.slim .grow,
  .refs.dragging .sec.vacant .grow,
  .refs.dragging .sec.vacant .grid {
    display: none;
  }
  .proxytext span {
    display: none;
  }
  .editor {
    flex: 0 0 320px;
    min-height: 0;
    overflow-y: auto;
    padding: 0 0 0 10px;
    border-top: 0;
  }
}
</style>
