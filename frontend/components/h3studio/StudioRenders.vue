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
      <section>
        <h4>Now</h4>
        <div v-if="now" class="now">
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
        <p v-else class="soft small">Nothing rendering.</p>
      </section>

      <section>
        <h4>Up next</h4>
        <p v-if="!queued.length" class="soft small">Nothing queued for this studio.</p>
        <div v-for="(q, i) in queued" :key="q.id" class="qrow" :class="{ running: q.running }">
          <i class="mdi" :class="q.running ? 'mdi-play-circle-outline' : 'mdi-timer-sand'" />
          <span class="ellipsis"
            >{{ q.running ? "Running" : `Queued ${i + (queued[0]?.running ? 0 : 1)}` }} ·
            {{ q.what }}</span
          >
        </div>
      </section>

      <section>
        <h4>History</h4>
        <p v-if="loading && !groups.length" class="soft small">Looking…</p>
        <p v-else-if="!groups.length" class="soft small">
          No renders yet. Every clip a scene renders is kept here.
        </p>
        <div v-for="g in groups" :key="g.id" class="group">
          <button type="button" class="ghead" @click="toggle(g.id)">
            <i class="mdi" :class="open.has(g.id) ? 'mdi-chevron-down' : 'mdi-chevron-right'" />
            <b>S{{ g.index + 1 }}</b>
            <span class="ellipsis soft">{{ g.title }}</span>
            <span class="count">{{ g.takes.length }}</span>
          </button>
          <template v-if="open.has(g.id)">
            <div
              v-for="t in g.takes"
              :key="t.ref"
              class="take"
              :class="{ current: t.ref === g.current }"
            >
              <span class="tthumb"><MediaThumb :media="t.ref" :badge="false" /></span>
              <span class="ttext">
                <span>{{ ago(t.time) }}</span>
                <small class="soft ellipsis" :title="t.prompt">
                  {{ t.seconds ? `${t.seconds.toFixed(1)}s` : ""
                  }}<template v-if="t.seed !== undefined"> · seed {{ t.seed }}</template>
                </small>
              </span>
              <span
                v-if="t.fits === false"
                class="stale"
                title="Made from an earlier version of this scene: using it leaves the scene out of date"
                >edited since</span
              >
              <span v-if="t.ref === g.current" class="badge">Current</span>
              <ZenButton
                v-else
                size="sm"
                title="Make this the scene's clip"
                :disabled="!!using"
                @click="use(g, t)"
                >{{ using === t.ref ? "…" : "Use" }}</ZenButton
              >
            </div>
          </template>
        </div>
      </section>
      <p v-if="note" class="note" :class="{ bad: note.bad }">{{ note.text }}</p>
      <p class="soft small hint">Hold Shift over a take to see it large.</p>
    </div>
  </aside>
</template>

<script setup lang="ts">
// The studio's Renders sidebar: what's rendering now (with its latest step), what's queued for
// this studio, and every take each scene has rendered — any of which can be made the scene's clip
// again. Takes are kept by the server (nodes/h3studio/_reuse.py, takes.json).
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { api } from "@comfy/api";
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

function refresh() {
  void fetchTakes();
  void pollQueue();
}
refresh();
const timer = window.setInterval(() => void pollQueue(), 2500);
const target = api as unknown as EventTarget;
const onDone = () => refresh();
target.addEventListener("nynxz.h3studio.clip", onDone);
target.addEventListener("execution_success", onDone);
watch(
  () => doc.value.scenes.map((s) => s.id).join(),
  () => void fetchTakes(),
);
onBeforeUnmount(() => {
  window.clearInterval(timer);
  target.removeEventListener("nynxz.h3studio.clip", onDone);
  target.removeEventListener("execution_success", onDone);
});

function ago(t: number) {
  const s = Date.now() / 1000 - t;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(t * 1000).toLocaleString();
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
  border-radius: 6px;
  background: var(--zen-media-bg, #0b0b0e);
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
  background: var(--zen-accent, #6366f1);
}
.qrow {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  padding: 5px 6px;
  border-radius: 6px;
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
.take {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 4px;
  border: 1px solid transparent;
  border-radius: 6px;
}
.take.current {
  border-color: color-mix(in srgb, var(--zen-accent, #6366f1) 60%, transparent);
  background: color-mix(in srgb, var(--zen-accent, #6366f1) 10%, transparent);
}
.tthumb {
  flex: none;
  width: 64px;
  height: 36px;
  overflow: hidden;
  border-radius: 4px;
}
.tthumb :deep(.mt) {
  width: 100%;
  height: 100%;
}
.ttext {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}
.stale {
  flex: none;
  color: var(--zen-warning, #f5b14c);
  font-size: 10.5px;
}
.badge {
  padding: 1px 7px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--zen-accent, #6366f1) 25%, transparent);
  font-size: 10.5px;
}
.hint {
  margin-top: auto;
}
.note {
  margin: 0;
  padding: 6px 8px;
  border-radius: 6px;
  background: color-mix(in srgb, var(--zen-success, #4ade80) 14%, transparent);
  font-size: 11.5px;
}
.note.bad {
  background: color-mix(in srgb, var(--zen-danger, #ef4444) 16%, transparent);
}
</style>
