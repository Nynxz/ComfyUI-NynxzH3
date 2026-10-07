<template>
  <div
    ref="viewport"
    class="map"
    :class="{ panning: !!pan }"
    @pointerdown="startPan"
    @wheel.prevent="onWheel"
  >
    <div
      class="world"
      :style="{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})` }"
    >
      <svg class="edges" width="1" height="1" aria-hidden="true">
        <g v-for="e in drawnEdges" :key="e.key" :class="{ dim: e.dim, episode: e.episode }">
          <line :x1="e.a.x" :y1="e.a.y" :x2="e.b.x" :y2="e.b.y" />
          <text v-if="e.label" :x="(e.a.x + e.b.x) / 2" :y="(e.a.y + e.b.y) / 2 - 6">
            {{ e.label }}
          </text>
        </g>
      </svg>
      <button
        v-for="n in drawnNodes"
        :key="n.id"
        type="button"
        class="node"
        :class="{ episode: n.episode, on: n.id === selected, dim: n.dim }"
        :style="{ left: `${n.x}px`, top: `${n.y}px`, '--c': n.color }"
        :title="n.title"
        @pointerdown.stop="startDrag(n.id, $event)"
      >
        <span v-if="!n.episode" class="disc">
          <MediaThumb :media="n.cover" :badge="false" :label="n.name" />
        </span>
        <span class="label">{{ n.name }}</span>
      </button>
    </div>

    <div class="tools">
      <button
        v-for="k in legend"
        :key="k.id"
        type="button"
        class="chip"
        :class="{ off: hidden.has(k.id) }"
        :style="{ '--c': k.color }"
        :title="
          hidden.has(k.id) ? `Show ${k.label.toLowerCase()}` : `Hide ${k.label.toLowerCase()}`
        "
        @pointerdown.stop
        @click="toggle(k.id)"
      >
        <span class="dot" />{{ k.label }}
      </button>
      <span class="grow" />
      <ZenIconButton
        icon="mdi mdi-fit-to-screen-outline"
        size="sm"
        title="Fit everything in view"
        @pointerdown.stop
        @click="fit"
      />
      <ZenIconButton
        icon="mdi mdi-auto-fix"
        size="sm"
        title="Lay it all out again"
        @pointerdown.stop
        @click="tidy"
      />
    </div>

    <ZenEmpty
      v-if="!nodes.length"
      class="empty"
      title="Nothing to map yet"
      icon="mdi mdi-graph-outline"
    >
      Add characters, places and the rest, then link them — who lives where, whose voice is whose.
    </ZenEmpty>
  </div>
</template>

<script setup lang="ts">
// The show as a map: every entry and episode, with lines for how they relate (an entry's links,
// labelled) and which episodes use what (dashed). Drag nodes to arrange them — where they are is
// saved with the show — drag the background to pan, scroll to zoom. Clicking selects.
import { computed, nextTick, onMounted, reactive, ref, watch } from "vue";
import { ZenEmpty, ZenIconButton } from "@nynxz/zenkit-ui";
import {
  EPISODE_COLOR,
  KIND_ORDER,
  KINDS,
  coverOf,
  episodeName,
  type EntryKind,
  type Show,
} from "@/lib/codex";
import { layout, type MapEdge, type MapNode, type Point } from "@/lib/codexMap";
import MediaThumb from "@/components/h3studio/MediaThumb.vue";

const props = defineProps<{ show: Show }>();
const selected = defineModel<string>("selected", { default: "" });
/** The show, edited in place: dragging writes node positions into it. */
const doc = computed(() => props.show);

type Group = EntryKind | "episode";
const hidden = reactive(new Set<Group>());
const toggle = (g: Group) => (hidden.has(g) ? hidden.delete(g) : hidden.add(g));
const legend = computed(() => [
  ...KIND_ORDER.filter((k) => doc.value.entries.some((e) => e.kind === k)).map((k) => ({
    id: k as Group,
    label: KINDS[k].plural,
    color: KINDS[k].color,
  })),
  ...(doc.value.episodes.length
    ? [{ id: "episode" as Group, label: "Episodes", color: EPISODE_COLOR }]
    : []),
]);

const nodes = computed(() => [
  ...doc.value.entries.map((e) => ({
    id: e.id,
    group: e.kind as Group,
    name: e.name,
    cover: coverOf(e),
    color: KINDS[e.kind].color,
    episode: false,
    title: `${KINDS[e.kind].label}: ${e.name}`,
  })),
  ...doc.value.episodes.map((ep) => ({
    id: ep.id,
    group: "episode" as Group,
    name: episodeName(ep),
    cover: "",
    color: EPISODE_COLOR,
    episode: true,
    title: ep.logline || episodeName(ep),
  })),
]);
const edges = computed(() => [
  ...doc.value.entries.flatMap((e) =>
    e.links.map((l) => ({ from: e.id, to: l.to, label: l.label, episode: false })),
  ),
  ...doc.value.episodes.flatMap((ep) =>
    ep.uses.map((u) => ({ from: ep.id, to: u, label: "", episode: true })),
  ),
]);

/** Places any node that has no position yet (and keeps the rest where they are). */
function place(all = false) {
  const groups: Group[] = [...KIND_ORDER, "episode"];
  const mapNodes: MapNode[] = nodes.value.map((n) => ({
    id: n.id,
    group: groups.indexOf(n.group),
  }));
  const mapEdges: MapEdge[] = edges.value.map((e) => ({ from: e.from, to: e.to }));
  const placed = all ? {} : doc.value.map;
  const next = layout(mapNodes, mapEdges, placed);
  for (const [id, p] of Object.entries(next)) if (all || !doc.value.map[id]) doc.value.map[id] = p;
}
watch(
  () => nodes.value.map((n) => n.id).join(),
  () => place(),
  { immediate: true },
);

const posOf = (id: string): Point => doc.value.map[id] ?? { x: 0, y: 0 };

/** The selection and what it touches; everything else fades. */
const neighbours = computed(() => {
  if (!selected.value) return null;
  const near = new Set([selected.value]);
  for (const e of edges.value) {
    if (e.from === selected.value) near.add(e.to);
    if (e.to === selected.value) near.add(e.from);
  }
  return near;
});
const shown = (id: string) => {
  const n = nodes.value.find((x) => x.id === id);
  return !!n && !hidden.has(n.group);
};
const drawnNodes = computed(() =>
  nodes.value
    .filter((n) => !hidden.has(n.group))
    .map((n) => ({ ...n, ...posOf(n.id), dim: !!neighbours.value && !neighbours.value.has(n.id) })),
);
const drawnEdges = computed(() =>
  edges.value
    .filter((e) => shown(e.from) && shown(e.to))
    .map((e, i) => ({
      key: `${e.from}-${e.to}-${i}`,
      a: posOf(e.from),
      b: posOf(e.to),
      label: e.label,
      episode: e.episode,
      dim: !!neighbours.value && !(e.from === selected.value || e.to === selected.value),
    })),
);

// --- view: pan, zoom, fit --------------------------------------------------------------------
const viewport = ref<HTMLElement | null>(null);
const view = reactive({ x: 0, y: 0, k: 1 });
function fit() {
  const el = viewport.value;
  const pts = drawnNodes.value;
  if (!el || !pts.length) return;
  const xs = pts.map((p) => p.x);
  const ys = pts.map((p) => p.y);
  const pad = 90;
  const w = Math.max(...xs) - Math.min(...xs) + pad * 2;
  const h = Math.max(...ys) - Math.min(...ys) + pad * 2;
  view.k = Math.min(1.4, Math.max(0.2, Math.min(el.clientWidth / w, el.clientHeight / h)));
  view.x = el.clientWidth / 2 - ((Math.max(...xs) + Math.min(...xs)) / 2) * view.k;
  view.y = el.clientHeight / 2 - ((Math.max(...ys) + Math.min(...ys)) / 2) * view.k;
}
onMounted(() => nextTick(fit));
function tidy() {
  place(true);
  void nextTick(fit);
}
function onWheel(e: WheelEvent) {
  const el = viewport.value;
  if (!el) return;
  const r = el.getBoundingClientRect();
  const mx = e.clientX - r.left;
  const my = e.clientY - r.top;
  const k = Math.min(2.5, Math.max(0.15, view.k * Math.exp(-e.deltaY * 0.0015)));
  view.x = mx - ((mx - view.x) * k) / view.k;
  view.y = my - ((my - view.y) * k) / view.k;
  view.k = k;
}
const pan = ref<{ x: number; y: number; vx: number; vy: number; moved: boolean } | null>(null);
function startPan(e: PointerEvent) {
  if (e.button !== 0) return;
  pan.value = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false };
  const move = (ev: PointerEvent) => {
    const p = pan.value;
    if (!p) return;
    if (Math.hypot(ev.clientX - p.x, ev.clientY - p.y) > 3) p.moved = true;
    view.x = p.vx + ev.clientX - p.x;
    view.y = p.vy + ev.clientY - p.y;
  };
  const up = () => {
    if (pan.value && !pan.value.moved) selected.value = "";
    pan.value = null;
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}
function startDrag(id: string, e: PointerEvent) {
  if (e.button !== 0) return;
  const start = { ...posOf(id) };
  const sx = e.clientX;
  const sy = e.clientY;
  let moved = false;
  const move = (ev: PointerEvent) => {
    const dx = (ev.clientX - sx) / view.k;
    const dy = (ev.clientY - sy) / view.k;
    if (!moved && Math.hypot(dx, dy) * view.k < 3) return;
    moved = true;
    doc.value.map[id] = { x: Math.round(start.x + dx), y: Math.round(start.y + dy) };
  };
  const up = () => {
    if (!moved) selected.value = id;
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}
</script>

<style scoped>
.map {
  position: relative;
  overflow: hidden;
  height: 100%;
  min-height: 0;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: var(--zen-radius, 8px);
  background-color: var(--zen-surface, #202026);
  background-image: radial-gradient(
    color-mix(in srgb, var(--zen-text, #e5e5ea) 9%, transparent) 1px,
    transparent 1px
  );
  background-size: 22px 22px;
  cursor: grab;
  user-select: none;
  touch-action: none;
}
.map.panning {
  cursor: grabbing;
}
.world {
  position: absolute;
  top: 0;
  left: 0;
  transform-origin: 0 0;
}
.edges {
  position: absolute;
  overflow: visible;
}
.edges line {
  stroke: color-mix(in srgb, var(--zen-text, #e5e5ea) 35%, transparent);
  stroke-width: 1.5;
}
.edges .episode line {
  stroke-dasharray: 4 5;
  stroke: color-mix(in srgb, var(--zen-text, #e5e5ea) 22%, transparent);
}
.edges text {
  fill: var(--zen-muted, #9aa0aa);
  font-size: 11px;
  text-anchor: middle;
  paint-order: stroke;
  stroke: var(--zen-surface, #202026);
  stroke-width: 4px;
}
.edges .dim {
  opacity: 0.15;
}
.node {
  position: absolute;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 0;
  border: 0;
  background: none;
  color: var(--zen-text, #e5e5ea);
  font: inherit;
  transform: translate(-50%, -50%);
  cursor: pointer;
  transition: opacity var(--zen-dur, 160ms);
}
.disc {
  overflow: hidden;
  width: 58px;
  height: 58px;
  border: 3px solid var(--c);
  border-radius: 50%;
  background: var(--zen-media-bg, #111);
}
.disc :deep(.mt) {
  width: 100%;
  height: 100%;
}
.label {
  max-width: 130px;
  padding: 1px 7px;
  overflow: hidden;
  border-radius: 999px;
  background: color-mix(in srgb, var(--zen-surface, #202026) 85%, transparent);
  font-size: 11.5px;
  font-weight: 600;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.node.episode .label {
  padding: 6px 12px;
  border: 1.5px solid var(--c);
  border-radius: 8px;
  background: var(--zen-surface, #202026);
}
.node.on .disc,
.node.on.episode .label {
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--zen-accent, #6366f1) 45%, transparent);
}
.node.dim {
  opacity: 0.25;
}
.tools {
  position: absolute;
  top: 8px;
  right: 8px;
  left: 8px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  pointer-events: none;
}
.tools > * {
  pointer-events: auto;
}
.grow {
  flex: 1;
  pointer-events: none;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 24px;
  padding: 0 9px;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: 999px;
  background: var(--zen-surface, #202026);
  color: var(--zen-text, #e5e5ea);
  font: inherit;
  font-size: 11.5px;
  cursor: pointer;
}
.chip.off {
  opacity: 0.45;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--c);
}
.empty {
  position: absolute;
  inset: 0;
  margin: auto;
  height: fit-content;
}
</style>
