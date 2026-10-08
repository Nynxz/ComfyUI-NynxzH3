<template>
  <aside class="renders">
    <header class="head">
      <i class="mdi mdi-history" />
      <b>Renders</b>
      <span class="grow" />
      <ZenIconButton icon="mdi mdi-refresh" size="sm" title="Refresh" @click="refresh" />
      <ZenIconButton icon="mdi mdi-close" size="sm" title="Close" @click="emit('close')" />
    </header>

    <div class="scroll zen-scroll">
      <section v-if="now">
        <h4>Now</h4>
        <div class="now">
          <div class="nowthumb">
            <video v-if="now.frame?.video" :src="now.frame.url" autoplay muted loop playsinline />
            <img v-else-if="now.frame?.url" :src="now.frame.url" alt="" />
            <i v-else class="mdi mdi-progress-clock" />
          </div>
          <div class="nowtext">
            <span class="live"
              ><span class="dot" /> S{{ now.scene + 1
              }}<template v-if="now.title"> · {{ now.title }}</template></span
            >
            <small class="soft">{{
              now.steps ? `step ${now.step} of ${now.steps}` : "starting…"
            }}</small>
            <div v-if="now.steps" class="bar">
              <span :style="{ width: `${(now.step / now.steps) * 100}%` }" />
            </div>
          </div>
        </div>
      </section>

      <section v-if="queued.length">
        <h4>Up next</h4>
        <div v-for="(q, i) in queued" :key="q.id" class="qrow" :class="{ running: q.running }">
          <i class="mdi" :class="q.running ? 'mdi-play-circle-outline' : 'mdi-timer-sand'" />
          <span class="ellipsis"
            >{{ q.running ? "Running" : `Queued ${i + (queued[0]?.running ? 0 : 1)}` }} ·
            {{ q.what }}</span
          >
        </div>
      </section>

      <section>
        <h4 class="filmhead">
          Film
          <span class="grow" />
          <ZenButton
            size="sm"
            variant="ghost"
            icon="mdi mdi-movie-export-outline"
            :disabled="exporting"
            title="Join every scene's current take into the film and save it, now"
            @click="exportFilm"
            >{{ exporting ? "Saving…" : "Export film" }}</ZenButton
          >
        </h4>
        <div v-if="film" class="take film" :title="filmDetails(film)">
          <span class="tthumb"><MediaThumb :media="film.ref" :badge="false" /></span>
          <span class="when">{{ ago(film.time) }}</span>
          <span
            v-if="film.missing.length"
            class="gap"
            :title="`Scene ${film.missing.join(', ')} had no render yet: black`"
            ><i class="mdi mdi-alert-outline" />{{ film.missing.length }}</span
          >
          <span class="soft small">{{ clock(film.seconds) }}</span>
        </div>
        <p v-else class="soft small">
          A full render saves the film here when its last scene lands; Export film saves it from the
          current takes any time.
        </p>
        <button
          v-if="films.length > 1"
          type="button"
          class="ghead older"
          @click="olderOpen = !olderOpen"
        >
          <i class="mdi" :class="olderOpen ? 'mdi-chevron-down' : 'mdi-chevron-right'" />
          <span class="soft">Earlier films</span>
          <span class="count">{{ films.length - 1 }}</span>
        </button>
        <template v-if="olderOpen">
          <div v-for="f in films.slice(1)" :key="f.ref" class="take film" :title="filmDetails(f)">
            <span class="tthumb"><MediaThumb :media="f.ref" :badge="false" /></span>
            <span class="when">{{ ago(f.time) }}</span>
            <span class="soft small">{{ clock(f.seconds) }}</span>
          </div>
        </template>
      </section>

      <section>
        <h4>History</h4>
        <p v-if="loading && !groups.length" class="soft small">Looking…</p>
        <p v-else-if="!groups.length" class="soft small">
          No renders yet. Each clip a scene renders is kept here, so you can go back to it.
        </p>
        <div v-for="g in groups" :key="g.id" class="group">
          <button type="button" class="ghead" @click="toggle(g.id)">
            <i class="mdi" :class="open.has(g.id) ? 'mdi-chevron-down' : 'mdi-chevron-right'" />
            <b>S{{ g.index + 1 }}</b>
            <span class="ellipsis soft">{{ g.title }}</span>
            <span class="count">{{ g.takes.length }}</span>
          </button>
          <template v-if="open.has(g.id)">
            <template v-for="part in parts(g.takes)" :key="part.label">
              <h5
                v-if="part.label"
                class="sub"
                :title="
                  part.stale
                    ? 'Made before the scene was last edited: using one puts the scene back out of date'
                    : undefined
                "
              >
                {{ part.label }}
              </h5>
              <div
                v-for="t in part.takes"
                :key="t.ref"
                class="take"
                :class="{ current: t.ref === g.current, stale: part.stale }"
                :title="details(t)"
              >
                <span class="tthumb"><MediaThumb :media="t.ref" :badge="false" /></span>
                <span class="when">{{ ago(t.time) }}</span>
                <span v-if="t.ref === g.current" class="badge">Current</span>
                <ZenButton
                  v-else
                  size="sm"
                  variant="ghost"
                  class="use"
                  title="Make this the scene's clip"
                  :disabled="!!using"
                  @click="use(g, t)"
                  >{{ using === t.ref ? "…" : "Use" }}</ZenButton
                >
              </div>
            </template>
          </template>
        </div>
      </section>
      <p v-if="note" class="note" :class="{ bad: note.bad }">{{ note.text }}</p>
      <p v-if="groups.length" class="soft small hint">Hold Shift over a take to see it large.</p>
    </div>
  </aside>
</template>

<script setup lang="ts">
// The studio's Renders sidebar: what's rendering now (with its latest step), what's queued for
// this studio, and every take each scene has rendered — any of which can be made the scene's clip
// again. Takes are kept by the server (nodes/h3studio/_reuse.py, takes.json).
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { api } from "@comfy/api";
import { app } from "@comfy/app";
import { ZenButton, ZenIconButton } from "@nynxz/zenkit-ui";
import type { StudioLive } from "@/lib/h3live";
import type { Project } from "@/lib/h3studio";
import MediaThumb from "./MediaThumb.vue";

interface Take {
  ref: string;
  time: number;
  seed?: number;
  seconds?: number;
  prompt?: string;
  /** False when it was made from an earlier version of the scene (not just another seed). */
  fits?: boolean;
}

const props = defineProps<{ project: Project; nodeId: string; live: StudioLive }>();
const emit = defineEmits<{ close: []; changed: [] }>();
/** The project, edited in place when a take is made a scene's clip. */
const doc = computed(() => props.project);

// --- now -----------------------------------------------------------------------------------------
const now = computed(() => {
  const scene = props.live.rendering;
  if (scene === null) return null;
  const run = props.live.runs[scene];
  const frame = run?.steps.at(-1);
  return {
    scene,
    title: doc.value.scenes[scene]?.title ?? "",
    frame,
    step: frame?.step ?? 0,
    steps: Math.max(0, (run?.total ?? 0) - 1),
  };
});

// --- up next: ComfyUI's queue, the runs that hold this studio ------------------------------------
interface Queued {
  id: string;
  running: boolean;
  what: string;
}
const queued = ref<Queued[]>([]);
type QueueRow = [
  number,
  string,
  Record<string, { class_type?: string; inputs?: Record<string, unknown> }>,
];
function describe(prompt: QueueRow[2]): string | null {
  const entry = Object.entries(prompt).find(
    ([id, n]) =>
      n.class_type === "nynxz.H3.Studio" &&
      (id === props.nodeId || id.endsWith(`:${props.nodeId}`)),
  );
  if (!entry) return null;
  const proj = (entry[1].inputs?.project ?? {}) as { renderOnly?: string[]; active?: number };
  const scenes = doc.value.scenes;
  const label = (id: string) => {
    const i = scenes.findIndex((s) => s.id === id);
    return i >= 0 ? `S${i + 1}` : "a removed scene";
  };
  if (proj.renderOnly?.length) return proj.renderOnly.map(label).join(", ");
  const loop = Object.values(prompt).some((n) => n.class_type === "StartLoop");
  return loop ? "every scene" : `S${(proj.active ?? 0) + 1}`;
}
async function pollQueue() {
  try {
    const res = await (api as { fetchApi(p: string): Promise<Response> }).fetchApi("/queue");
    if (!res.ok) return;
    const q = (await res.json()) as { queue_running?: QueueRow[]; queue_pending?: QueueRow[] };
    const rows: Queued[] = [];
    for (const [running, list] of [
      [true, q.queue_running ?? []],
      [false, [...(q.queue_pending ?? [])].sort((a, b) => a[0] - b[0])],
    ] as const)
      for (const row of list) {
        const what = describe(row[2]);
        if (what) rows.push({ id: row[1], running, what });
      }
    queued.value = rows;
  } catch {
    /* the server is away */
  }
}

// --- history ---------------------------------------------------------------------------------------
const takes = ref<Record<string, Take[]>>({});
const loading = ref(false);
async function fetchTakes() {
  loading.value = true;
  try {
    const res = await fetch("/nynxz/h3studio/takes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenes: doc.value.scenes.map((s) => s.id), project: doc.value }),
    });
    if (res.ok) takes.value = ((await res.json()) as { takes: Record<string, Take[]> }).takes;
  } finally {
    loading.value = false;
  }
}
const groups = computed(() =>
  doc.value.scenes
    .map((s, index) => ({
      id: s.id,
      index,
      title: s.title,
      current: s.render ?? "",
      takes: takes.value[s.id] ?? [],
    }))
    .filter((g) => g.takes.length),
);
const open = reactive(new Set<string>());
const toggle = (id: string) => (open.has(id) ? open.delete(id) : open.add(id));
watch(
  groups,
  (gs) => {
    // The scene rendering now, or else the first with takes, starts open.
    const live = props.live.rendering !== null ? doc.value.scenes[props.live.rendering]?.id : null;
    if (live && gs.some((g) => g.id === live)) open.add(live);
    else if (!open.size && gs[0]) open.add(gs[0].id);
  },
  { immediate: true },
);

const using = ref("");
const note = ref<{ text: string; bad: boolean } | null>(null);
async function use(g: { id: string; index: number }, t: Take) {
  using.value = t.ref;
  note.value = null;
  try {
    const res = await fetch("/nynxz/h3studio/take/use", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scene: g.id, ref: t.ref }),
    });
    if (!res.ok) {
      // The route answers a take it doesn't know with {"ok": false}; a ComfyUI that hasn't
      // been restarted since this was added has no route at all.
      const known = (await res.text()).includes('"ok"');
      note.value = {
        bad: true,
        text: known
          ? "That take isn't one of this scene's any more."
          : "Couldn't switch takes — restart ComfyUI so it has the new Renders routes.",
      };
      return;
    }
    const scene = doc.value.scenes[g.index];
    if (scene) {
      scene.render = t.ref;
      // Its own seed back too: the scene then matches the take, instead of reading as changed.
      if (typeof t.seed === "number") scene.seed = t.seed;
    }
    note.value = {
      bad: false,
      text:
        t.fits === false
          ? `S${g.index + 1} now uses the take from ${ago(t.time)} — made before the scene was last edited, so it still shows as out of date.`
          : `S${g.index + 1} now uses the take from ${ago(t.time)}${typeof t.seed === "number" ? ` (seed ${t.seed})` : ""}.`,
    };
    emit("changed");
    void fetchTakes();
  } catch {
    note.value = { bad: true, text: "Couldn't reach ComfyUI." };
  } finally {
    using.value = "";
  }
}

// --- film: the finished film, saved by a full render or by Export film -----------------------------
interface Film {
  ref: string;
  time: number;
  seconds: number;
  missing: number[];
}
const films = ref<Film[]>([]);
const film = computed(() => films.value[0] ?? null);
const olderOpen = ref(false);
const exporting = ref(false);
async function fetchFilms() {
  const res = await fetch("/nynxz/h3studio/films", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenes: doc.value.scenes.map((s) => s.id) }),
  });
  if (res.ok) films.value = ((await res.json()) as { films: Film[] }).films;
}
async function exportFilm() {
  exporting.value = true;
  note.value = null;
  try {
    let workflow: unknown = null;
    try {
      workflow = app.graph?.serialize();
    } catch {
      workflow = null;
    }
    const res = await fetch("/nynxz/h3studio/film/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project: doc.value, workflow }),
    });
    const body = (await res.json()) as Film & { error?: string };
    if (!res.ok) throw new Error(body.error ?? res.statusText);
    note.value = {
      bad: false,
      text: body.missing.length
        ? `Film saved — scene ${body.missing.join(", ")} black, never rendered.`
        : "Film saved.",
    };
    await fetchFilms();
  } catch (e) {
    note.value = {
      bad: true,
      text: `Couldn't save the film: ${e instanceof Error ? e.message : e}`,
    };
  } finally {
    exporting.value = false;
  }
}
function filmDetails(f: Film) {
  return [new Date(f.time * 1000).toLocaleString(), clock(f.seconds), f.ref]
    .filter(Boolean)
    .join(" · ");
}
function clock(s: number) {
  return `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
}

function refresh() {
  void fetchTakes();
  void fetchFilms();
  void pollQueue();
}
refresh();
const timer = window.setInterval(() => void pollQueue(), 2500);
const target = api as unknown as EventTarget;
const onDone = () => refresh();
target.addEventListener("nynxz.h3studio.clip", onDone);
target.addEventListener("nynxz.h3studio.film", onDone);
target.addEventListener("execution_success", onDone);
watch(
  () => doc.value.scenes.map((s) => s.id).join(),
  () => void fetchTakes(),
);
onBeforeUnmount(() => {
  window.clearInterval(timer);
  target.removeEventListener("nynxz.h3studio.clip", onDone);
  target.removeEventListener("nynxz.h3studio.film", onDone);
  target.removeEventListener("execution_success", onDone);
});

/** A scene's takes, the ones from its current version first; split under labels only when some
 *  were made from an earlier version. */
function parts(takes: Take[]) {
  const stale = takes.filter((t) => t.fits === false);
  if (!stale.length) return [{ label: "", stale: false, takes }];
  const fresh = takes.filter((t) => t.fits !== false);
  return [
    ...(fresh.length ? [{ label: "This version", stale: false, takes: fresh }] : []),
    { label: "Earlier versions", stale: true, takes: stale },
  ];
}
function details(t: Take) {
  return [
    new Date(t.time * 1000).toLocaleString(),
    t.seconds ? `${t.seconds.toFixed(1)}s` : "",
    t.seed !== undefined ? `seed ${t.seed}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}
function ago(t: number) {
  const s = Date.now() / 1000 - t;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  const d = new Date(t * 1000);
  return s < 7 * 86400
    ? d.toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}
</script>

<style scoped>
.renders {
  display: flex;
  flex: none;
  flex-direction: column;
  box-sizing: border-box;
  width: 250px;
  min-height: 0;
  border: 1px solid var(--h3-line);
  border-radius: var(--h3-radius);
  background: var(--h3-panel);
  color: var(--h3-text);
  font-size: 12px;
}
.head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 6px 6px 10px;
  border-bottom: 1px solid var(--h3-line);
}
.grow {
  flex: 1;
}
.scroll {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
  padding: 10px;
  overflow-y: auto;
}
section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
h4 {
  margin: 0;
  color: var(--h3-muted);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.soft {
  color: var(--h3-muted);
}
.small {
  margin: 0;
  font-size: 11.5px;
}
.ellipsis {
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.now {
  display: flex;
  gap: 8px;
  align-items: center;
}
.nowthumb {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 84px;
  height: 48px;
  overflow: hidden;
  border-radius: var(--h3-radius, var(--zen-radius, 8px));
  background: var(--zen-media-bg, var(--h3-field));
  color: var(--h3-muted);
}
.nowthumb img,
.nowthumb video {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.nowtext {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.live {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--zen-danger, #ef4444);
  animation: pulse 1.2s ease-in-out infinite;
}
@keyframes pulse {
  50% {
    opacity: 0.35;
  }
}
.bar {
  height: 3px;
  overflow: hidden;
  border-radius: 2px;
  background: var(--h3-field);
}
.bar span {
  display: block;
  height: 100%;
  background: var(--h3-accent);
}
.qrow {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  padding: 5px 6px;
  border-radius: var(--h3-radius, var(--zen-radius, 8px));
  background: var(--h3-field);
}
.qrow.running {
  color: var(--h3-text);
  font-weight: 600;
}
.group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.ghead {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  padding: 4px 2px;
  border: 0;
  background: none;
  color: var(--h3-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.count {
  margin-left: auto;
  color: var(--h3-muted);
  font-size: 11px;
}
/* A take is a card like the studio's others: its field colour, line and radius. */
.take {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 5px 6px 5px 5px;
  border: 1px solid var(--h3-line);
  border-radius: var(--h3-radius);
  background: var(--h3-field);
}
.take.current {
  border-color: color-mix(in srgb, var(--h3-accent) 60%, transparent);
  background: color-mix(in srgb, var(--h3-accent) 10%, transparent);
}
.tthumb {
  flex: none;
  width: 72px;
  height: 40px;
  overflow: hidden;
  border-radius: calc(var(--h3-radius) - 3px);
  background: var(--zen-media-bg, var(--h3-panel));
}
.tthumb :deep(.mt) {
  width: 100%;
  height: 100%;
}
.when {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.take.stale .tthumb {
  opacity: 0.7;
}
.take.stale .when {
  color: var(--h3-muted);
}
.filmhead {
  display: flex;
  align-items: center;
}
.filmhead :deep(.zen-btn) {
  letter-spacing: normal;
  text-transform: none;
}
.take.film .when {
  flex: 1;
}
.gap {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: var(--zen-warning, #f5b14c);
  font-size: 11px;
}
.older {
  padding-left: 0;
}
.sub {
  margin: 4px 2px 0;
  color: var(--h3-muted);
  font-size: 10.5px;
  font-weight: 600;
}
.badge {
  padding: 0 6px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--h3-accent) 25%, transparent);
  font-size: 10px;
  line-height: 16px;
}
/* Use waits until a take is pointed at, so the list reads as takes rather than buttons. */
.take .use {
  flex: none;
  opacity: 0;
}
.take:hover .use,
.take:focus-within .use {
  opacity: 1;
}
@media (hover: none) {
  .take .use {
    opacity: 1;
  }
}
.hint {
  margin-top: auto;
}
.note {
  margin: 0;
  padding: 6px 8px;
  border-radius: var(--h3-radius, var(--zen-radius, 8px));
  background: color-mix(in srgb, var(--zen-success, #4ade80) 14%, transparent);
  font-size: 11.5px;
}
.note.bad {
  background: color-mix(in srgb, var(--zen-danger, #ef4444) 16%, transparent);
}
</style>
