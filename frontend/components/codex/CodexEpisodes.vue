<template>
  <ZenSplit
    class="episodes"
    gutter="gap"
    :panes="[{ size: 280, min: 220, max: 420 }, { min: 320 }]"
  >
    <template #pane-0>
      <div class="list panel zen-scroll">
        <button
          v-for="ep in sorted"
          :key="ep.id"
          type="button"
          class="row"
          :class="{ on: ep.id === selected }"
          @click="selected = ep.id"
        >
          <span class="num">E{{ String(ep.number).padStart(2, "0") }}</span>
          <span class="text">
            <b>{{ ep.title || "Untitled" }}</b>
            <small>{{ ep.logline || "No logline yet" }}</small>
          </span>
          <i class="mdi status" :class="statusOf(ep).icon" :title="statusOf(ep).label" />
        </button>
        <button type="button" class="row new" @click="add">
          <i class="mdi mdi-plus" /> New episode
        </button>
      </div>
    </template>
    <template #pane-1>
      <div v-if="episode" class="detail panel zen-scroll">
        <div class="head">
          <span class="num">E</span>
          <ZenNumber
            v-model="episode.number"
            size="sm"
            :min="1"
            :max="999"
            :step="1"
            :precision="0"
            class="numin"
          />
          <input
            v-model="episode.title"
            class="title"
            placeholder="Episode title"
            aria-label="Episode title"
          />
        </div>
        <ZenToggleGroup v-model="episode.status" :options="EPISODE_STATUS" />
        <section>
          <h4>Logline</h4>
          <ZenInput
            v-model="episode.logline"
            type="textarea"
            :rows="2"
            placeholder="What happens, in a sentence or two."
          />
        </section>
        <section>
          <h4>Uses</h4>
          <div class="uses">
            <span v-for="e in used" :key="e.id" class="use" :style="{ '--c': KINDS[e.kind].color }">
              <i class="mdi" :class="KINDS[e.kind].icon" />
              {{ e.name }}
              <button
                type="button"
                :aria-label="`Remove ${e.name}`"
                title="Remove"
                @click="unuse(e.id)"
              >
                <i class="mdi mdi-close" />
              </button>
            </span>
            <ZenSelect
              v-if="unused.length"
              size="sm"
              class="adduse"
              model-value=""
              placeholder="Add a character, place…"
              :options="unused"
              @update:model-value="use"
            />
          </div>
        </section>
        <section>
          <h4>Films</h4>
          <p v-if="!epFilms.length" class="soft small">
            Save an H3 Studio into this episode from the studio's Codex button to come back to it.
          </p>
          <div v-for="f in epFilms" :key="f.id" class="film">
            <i class="mdi mdi-filmstrip" />
            <span class="ftext">
              <b>{{ f.name }}</b>
              <small class="soft"
                >{{ filmSummary(f) }} · saved {{ new Date(f.updated).toLocaleString() }}</small
              >
            </span>
            <ZenSelect
              v-if="studios.length > 1"
              size="sm"
              class="studiopick"
              :model-value="studioId"
              :options="studios.map((s) => ({ value: s.id, label: s.label }))"
              @update:model-value="studioId = $event"
            />
            <ZenButton
              size="sm"
              icon="mdi mdi-movie-open-play-outline"
              :disabled="!studios.length"
              :title="
                studios.length
                  ? 'Load this into the H3 Studio in the workflow'
                  : 'Add an H3 Studio to the workflow to open it'
              "
              @click="openIn(f)"
            >
              Open in H3 Studio
            </ZenButton>
            <ZenIconButton
              icon="mdi mdi-delete-outline"
              size="sm"
              title="Delete this film (Ctrl+Z brings it back)"
              @click="removeFilm(f.id)"
            />
          </div>
          <p v-if="opened" class="ok small"><i class="mdi mdi-check" /> {{ opened }}</p>
        </section>
        <section class="grow">
          <h4>Outline</h4>
          <ZenInput
            v-model="episode.outline"
            type="textarea"
            :rows="12"
            placeholder="The beats, in order. Each one should happen because of the one before."
          />
        </section>
        <section>
          <h4>Notes</h4>
          <ZenInput
            v-model="episode.notes"
            type="textarea"
            :rows="3"
            placeholder="Anything else."
          />
        </section>
        <div class="foot">
          <ZenButton size="sm" icon="mdi mdi-delete-outline" @click="remove"
            >Delete episode</ZenButton
          >
        </div>
      </div>
      <div v-else class="detail panel">
        <ZenEmpty title="No episodes yet" icon="mdi mdi-filmstrip-box-multiple">
          Each episode gets a logline, an outline, and the characters and places it uses.
          <template #actions>
            <ZenButton variant="primary" icon="mdi mdi-plus" @click="add">New episode</ZenButton>
          </template>
        </ZenEmpty>
      </div>
    </template>
  </ZenSplit>
</template>

<script setup lang="ts">
// A show's episodes: a list, and the one picked — its number, title and status, a logline, the
// entries it uses (which the map draws), an outline and notes.
import { computed, onBeforeUnmount, ref } from "vue";
import {
  ZenButton,
  ZenEmpty,
  ZenIconButton,
  ZenInput,
  ZenNumber,
  ZenSelect,
  ZenSplit,
  ZenToggleGroup,
} from "@nynxz/zenkit-ui";
import {
  EPISODE_STATUS,
  KIND_ORDER,
  episodeName,
  KINDS,
  newEpisode,
  type Episode,
  type Show,
  filmSummary,
  type Film,
} from "@/lib/codex";
import { openFilm } from "@/lib/codexFilms";
import { studiosInGraph, type StudioTarget } from "@/lib/codexStudio";

const props = defineProps<{ show: Show }>();
const selected = defineModel<string>("selected", { default: "" });
/** The show, edited in place. */
const doc = computed(() => props.show);

const sorted = computed(() => [...doc.value.episodes].sort((a, b) => a.number - b.number));
const episode = computed(
  () => doc.value.episodes.find((e) => e.id === selected.value) ?? sorted.value[0],
);
const statusOf = (ep: Episode) =>
  EPISODE_STATUS.find((s) => s.value === ep.status) ?? EPISODE_STATUS[0]!;

// --- films: H3 Studio projects saved into this episode ----------------------------------------------
const epFilms = computed(() => doc.value.films.filter((f) => f.episode === episode.value?.id));
const studios = ref<StudioTarget[]>(studiosInGraph());
const studioId = ref(studios.value[0]?.id ?? "");
const scan = () => {
  studios.value = studiosInGraph();
  if (!studios.value.some((s) => s.id === studioId.value))
    studioId.value = studios.value[0]?.id ?? "";
};
const timer = window.setInterval(scan, 1500);
onBeforeUnmount(() => window.clearInterval(timer));
const opened = ref("");
function openIn(f: Film) {
  const target = studios.value.find((s) => s.id === studioId.value);
  if (!target || !episode.value) return;
  openFilm(target.project, {
    show: doc.value.id,
    showName: doc.value.name,
    film: f,
    label: `${episodeName(episode.value)} — ${f.name}`,
  });
  opened.value = `Opened in ${target.label.split(" — ")[0]}.`;
}
function removeFilm(id: string) {
  doc.value.films = doc.value.films.filter((f) => f.id !== id);
}

const used = computed(() =>
  (episode.value?.uses ?? []).flatMap((id) => doc.value.entries.filter((e) => e.id === id)),
);
const unused = computed(() =>
  KIND_ORDER.flatMap((k) =>
    doc.value.entries
      .filter((e) => e.kind === k && !episode.value?.uses.includes(e.id))
      .map((e) => ({ value: e.id, label: e.name, icon: KINDS[k].icon })),
  ),
);
function use(id: string) {
  if (episode.value && id && !episode.value.uses.includes(id)) episode.value.uses.push(id);
}
function unuse(id: string) {
  if (episode.value) episode.value.uses = episode.value.uses.filter((u) => u !== id);
}

function add() {
  const ep = newEpisode(doc.value);
  doc.value.episodes.push(ep);
  selected.value = ep.id;
}
function remove() {
  const ep = episode.value;
  if (!ep) return;
  doc.value.episodes = doc.value.episodes.filter((e) => e.id !== ep.id);
  delete doc.value.map[ep.id];
  selected.value = sorted.value[0]?.id ?? "";
}
</script>

<style scoped>
.episodes {
  height: 100%;
  min-height: 0;
}
.panel {
  box-sizing: border-box;
  height: 100%;
  overflow-y: auto;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: var(--zen-radius, 8px);
  background: var(--zen-surface, #202026);
}
.list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px;
}
.row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--zen-text, #e5e5ea);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.row:hover {
  background: color-mix(in srgb, var(--zen-text, #e5e5ea) 6%, transparent);
}
.row.on {
  background: color-mix(in srgb, var(--zen-accent, #6366f1) 20%, transparent);
}
.num {
  color: var(--zen-muted, #9aa0aa);
  font-family: ui-monospace, monospace;
  font-weight: 600;
}
.text {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}
.text small {
  overflow: hidden;
  color: var(--zen-muted, #9aa0aa);
  white-space: nowrap;
  text-overflow: ellipsis;
}
.status {
  color: var(--zen-muted, #9aa0aa);
}
.row.new {
  justify-content: center;
  margin-top: 4px;
  border: 1px dashed var(--zen-border, #34343c);
  color: var(--zen-muted, #9aa0aa);
}
.detail {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px 18px;
}
.head {
  display: flex;
  align-items: center;
  gap: 6px;
}
.numin {
  width: 64px;
}
.title {
  flex: 1;
  min-width: 0;
  padding: 0 4px;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--zen-text, #e5e5ea);
  font: inherit;
  font-size: 20px;
  font-weight: 700;
}
h4 {
  margin: 0 0 6px;
  color: var(--zen-muted, #9aa0aa);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.uses {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.use {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 26px;
  padding: 0 4px 0 9px;
  border: 1px solid var(--c);
  border-radius: 999px;
  font-size: 12px;
}
.use .mdi {
  color: var(--c);
}
.use button {
  display: flex;
  padding: 2px;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--zen-muted, #9aa0aa);
  cursor: pointer;
}
.adduse {
  min-width: 200px;
}
.film {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: var(--zen-radius, 8px);
}
.ftext {
  display: flex;
  flex: 1 1 160px;
  flex-direction: column;
  min-width: 0;
}
.ftext b,
.ftext small {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.studiopick {
  min-width: 140px;
}
.soft {
  color: var(--zen-muted, #9aa0aa);
}
.small {
  margin: 0;
  font-size: 11.5px;
}
.ok {
  color: var(--zen-success, #4ade80);
}
.foot {
  display: flex;
  justify-content: flex-end;
}
</style>
