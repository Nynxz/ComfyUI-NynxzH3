<template>
  <ZenPopover placement="bottom-end">
    <template #trigger="{ toggle }">
      <ZenButton
        sm
        icon="mdi mdi-book-open-page-variant-outline"
        :title="
          link
            ? `${link.label} — in the Codex${dirty ? ' (changed since saved)' : ''}`
            : 'Save this to the Codex, or open a film from it'
        "
        @click="openMenu(toggle)"
      >
        <span class="chip">{{ link ? shortLabel : "Codex" }}</span>
        <span v-if="dirty" class="dot" aria-label="Unsaved changes" />
      </ZenButton>
    </template>
    <div class="codexpop">
      <section v-if="link" class="current">
        <div class="row">
          <i class="mdi mdi-filmstrip" />
          <b class="grow ellipsis">{{ link.label }}</b>
          <span class="state" :class="{ dirty }">{{ dirty ? "Changed" : "Saved" }}</span>
        </div>
        <div class="row">
          <ZenButton
            sm
            variant="primary"
            icon="mdi mdi-content-save-outline"
            :disabled="busy"
            @click="saveOver"
          >
            Save
          </ZenButton>
          <ZenButton
            sm
            icon="mdi mdi-link-variant-off"
            title="Keep the studio as it is, no longer tied to this film"
            @click="detach"
          >
            Detach
          </ZenButton>
        </div>
      </section>

      <section>
        <h4>{{ link ? "Save as a new film" : "Save to the Codex" }}</h4>
        <p v-if="!shows.length && !loading" class="soft">Make a show in the Codex first.</p>
        <template v-else>
          <ZenSelect
            v-model="form.show"
            size="sm"
            :options="shows.map((s) => ({ value: s.id, label: s.name }))"
          />
          <ZenSelect v-model="form.episode" size="sm" :options="episodeOptions" />
          <ZenInput
            v-model="form.name"
            sm
            placeholder="Name — e.g. Cold open, or Act 1"
            @keydown.enter="saveNew"
          />
          <ZenButton
            sm
            icon="mdi mdi-content-save-plus-outline"
            :disabled="busy || !form.show || !form.name.trim()"
            @click="saveNew"
          >
            Save as new
          </ZenButton>
        </template>
      </section>

      <section>
        <h4>Open a film</h4>
        <p v-if="loading" class="soft">Looking…</p>
        <p v-else-if="!films.length" class="soft">No films saved yet.</p>
        <div v-else class="films zen-scroll">
          <button
            v-for="f in films"
            :key="f.show + f.film.id"
            type="button"
            class="film"
            :class="{ on: link?.film === f.film.id }"
            @click="choose(f)"
          >
            <span class="ellipsis"
              ><b>{{ f.label }}</b></span
            >
            <small class="soft ellipsis"
              >{{ f.showName }} · {{ filmSummary(f.film) }} · {{ ago(f.film.updated) }}</small
            >
          </button>
        </div>
        <div v-if="confirm" class="confirm">
          <span
            >This studio has changes that aren't in the Codex. Open
            {{ confirm.label }} anyway?</span
          >
          <div class="row">
            <ZenButton sm variant="primary" @click="openNow(confirm)">Open it</ZenButton>
            <ZenButton sm @click="confirm = null">Cancel</ZenButton>
          </div>
        </div>
      </section>
      <p v-if="message" class="message">{{ message }}</p>
    </div>
  </ZenPopover>
</template>

<script setup lang="ts">
// The studio's link to the Codex: save what's in the studio into a show as a film, filed under
// an episode; save over the film it came from; or open another film into the studio. The button
// says which film the studio holds, with a dot when it has changed since it was saved.
import { computed, reactive, ref, watch } from "vue";
import { ZenButton, ZenInput, ZenPopover, ZenSelect } from "@nynxz/zenkit-ui";
import { episodeName, filmSummary } from "@/lib/codex";
import { listShows, liveShows, loadShow, type ShowSummary } from "@/lib/codexStore";
import {
  fingerprint,
  linkOf,
  listFilms,
  openFilm,
  saveFilm,
  unlink,
  type FilmChoice,
} from "@/lib/codexFilms";
import type { Project } from "@/lib/h3studio";

const props = defineProps<{ project: Project }>();

const link = computed(() => linkOf(props.project));
/** "E01 · Pilot — Cold open" as "E01 · Cold open": the toolbar is tight. */
const shortLabel = computed(() => link.value?.label.replace(/^(E\d+) · .*? — /, "$1 · ") ?? "");
// The fingerprint is a whole-project hash: worked out after edits settle, not on every keystroke.
const current = ref(fingerprint(props.project));
let timer = 0;
watch(
  () => props.project,
  () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => (current.value = fingerprint(props.project)), 400);
  },
  { deep: true },
);
const dirty = computed(() => !!link.value && link.value.saved !== current.value);

const shows = ref<ShowSummary[]>([]);
const films = ref<FilmChoice[]>([]);
const episodes = ref<{ value: string; label: string }[]>([]);
const loading = ref(false);
const busy = ref(false);
const message = ref("");
const confirm = ref<FilmChoice | null>(null);
const form = reactive({ show: "", episode: "", name: "" });

const episodeOptions = computed(() => [{ value: "", label: "No episode" }, ...episodes.value]);

async function loadEpisodes() {
  const show = liveShows.get(form.show)?.show ?? (await loadShow(form.show))?.show;
  episodes.value = (show?.episodes ?? []).map((e) => ({ value: e.id, label: episodeName(e) }));
  if (!episodes.value.some((e) => e.value === form.episode)) form.episode = "";
}
watch(
  () => form.show,
  () => void loadEpisodes(),
);

function openMenu(toggle: () => void) {
  toggle();
  void load();
}
async function load() {
  loading.value = true;
  message.value = "";
  confirm.value = null;
  try {
    shows.value = await listShows();
    if (!shows.value.some((s) => s.id === form.show))
      form.show = link.value?.show ?? shows.value[0]?.id ?? "";
    await loadEpisodes();
    films.value = await listFilms();
  } finally {
    loading.value = false;
  }
}

async function saveNew() {
  if (!form.show || !form.name.trim()) return;
  busy.value = true;
  try {
    const saved = await saveFilm(props.project, { ...form });
    current.value = saved.saved;
    message.value = `Saved as ${saved.label}.`;
    form.name = "";
    films.value = await listFilms();
  } catch (e) {
    message.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}
async function saveOver() {
  const l = link.value;
  if (!l) return;
  busy.value = true;
  try {
    const film = films.value.find((f) => f.film.id === l.film && f.show === l.show)?.film;
    const saved = await saveFilm(props.project, {
      show: l.show,
      film: l.film,
      episode: film?.episode ?? "",
      name: film?.name ?? l.label,
    });
    current.value = saved.saved;
    message.value = `Saved ${saved.label}.`;
    films.value = await listFilms();
  } catch (e) {
    message.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}
function detach() {
  unlink(props.project);
  message.value = "Detached — this studio is a plain project again.";
}
function choose(f: FilmChoice) {
  if (
    dirty.value ||
    (!link.value && props.project.scenes.some((s) => s.shots.some((sh) => sh.text.trim())))
  )
    confirm.value = f;
  else openNow(f);
}
function openNow(f: FilmChoice) {
  openFilm(props.project, f);
  current.value = fingerprint(props.project);
  confirm.value = null;
  message.value = `Opened ${f.label}.`;
}

function ago(t: number) {
  const s = (Date.now() - t) / 1000;
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return new Date(t).toLocaleDateString();
}
</script>

<style scoped>
.chip {
  display: inline-block;
  max-width: 140px;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  vertical-align: bottom;
}
.dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  margin-left: 6px;
  border-radius: 50%;
  background: var(--zen-warning, #f5b14c);
}
.codexpop {
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-sizing: border-box;
  width: 320px;
  padding: 12px;
  color: var(--zen-text, #e5e5ea);
  font-size: 12px;
}
section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.current {
  padding: 10px;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: var(--zen-radius, 8px);
  background: var(--zen-surface, #202026);
}
h4 {
  margin: 0;
  color: var(--zen-muted, #9aa0aa);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.grow {
  flex: 1;
}
.ellipsis {
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.state {
  color: var(--zen-success, #4ade80);
  font-size: 11px;
}
.state.dirty {
  color: var(--zen-warning, #f5b14c);
}
.soft {
  margin: 0;
  color: var(--zen-muted, #9aa0aa);
}
.films {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 220px;
  overflow-y: auto;
}
.film {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  padding: 6px 8px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--zen-text, #e5e5ea);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.film:hover {
  background: color-mix(in srgb, var(--zen-text, #e5e5ea) 6%, transparent);
}
.film.on {
  border-color: var(--zen-accent, #6366f1);
}
.confirm {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  border: 1px solid var(--zen-warning, #f5b14c);
  border-radius: 6px;
}
.message {
  margin: 0;
  color: var(--zen-muted, #9aa0aa);
}
</style>
