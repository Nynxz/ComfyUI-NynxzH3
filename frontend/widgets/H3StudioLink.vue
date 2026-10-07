<template>
  <div class="link">
    <div class="row">
      <ZenSelect
        class="pick"
        size="sm"
        :model-value="value.studio"
        :options="options"
        :placeholder="studios.length ? 'Pick an H3 Studio…' : 'No H3 Studio in this workflow'"
        :disabled="!studios.length"
        @update:model-value="pick"
        @active="point"
      />
      <ZenIconButton
        icon="mdi mdi-crosshairs-gps"
        size="sm"
        :disabled="!linked"
        title="Show the studio on the canvas"
        @click="reveal"
        @pointerenter="linked && point(value.studio)"
        @pointerleave="point(null)"
      />
    </div>
    <p class="count" :class="{ missing: value.studio && !linked }">
      <template v-if="linked">
        <b>{{ value.count }}</b> scene{{ value.count === 1 ? "" : "s" }} · one loop pass each
      </template>
      <template v-else-if="value.studio"
        >Studio #{{ value.studio }} isn't in this workflow</template
      >
      <template v-else>Pick the studio whose scenes the loop renders</template>
    </p>
  </div>
</template>

<script lang="ts">
// Read by nodekit's `discoverWidgets`: H3StudioLink.vue -> NYNXZ_H3_STUDIO_LINK
// (nodes/h3studio/io_types.py).
import type { NodeDef, WidgetOptions } from "@/framework";

export const widgetOptions: WidgetOptions = {
  name: "link",
  minHeight: 56,
  default: { studio: "", count: 1 },
};

export const nodeDef: Omit<NodeDef, "widgets"> = {
  is: "nynxz.H3.StudioScenes",
};
</script>

<script setup lang="ts">
// The H3 Studio Scenes node's body: which studio it follows, picked from the workflow's studios —
// hovering one outlines it on the canvas — and that studio's scene count, kept in step here so the
// node's value (and with it ComfyUI's cache) changes whenever scenes are added or removed.
import { computed, onBeforeUnmount, ref } from "vue";
import { ZenIconButton, ZenSelect } from "@nynxz/zenkit-ui";
import { highlightNode, revealNode } from "@/framework";
import { app } from "@comfy/app";

interface Link {
  studio: string;
  count: number;
}
interface GraphNode {
  id: number | string;
  type: string;
  title?: string;
  widgets?: { name: string; value: unknown }[];
}
const props = defineProps<{
  widget?: { value: unknown; callback?: (v: unknown) => void };
}>();

const toLink = (v: unknown): Link => {
  const o = (v && typeof v === "object" ? v : {}) as Partial<Link>;
  return { studio: String(o.studio ?? ""), count: Math.max(1, Number(o.count) || 1) };
};
const value = ref(toLink(props.widget?.value));
function write(next: Link) {
  if (next.studio === value.value.studio && next.count === value.value.count) return;
  value.value = next;
  const widget = props.widget;
  if (!widget) return;
  widget.value = { ...next };
  widget.callback?.(widget.value);
  (app as { graph?: { setDirtyCanvas?(a: boolean, b: boolean): void } }).graph?.setDirtyCanvas?.(
    true,
    true,
  );
}

interface Studio {
  id: string;
  title: string;
  scenes: number;
}
const studios = ref<Studio[]>([]);
function scan() {
  const graph = (app as { graph?: { nodes?: GraphNode[] } }).graph;
  studios.value = (graph?.nodes ?? [])
    .filter((n) => n.type === "nynxz.H3.Studio")
    .map((n) => {
      const project = n.widgets?.find((w) => w.name === "project")?.value as
        { scenes?: unknown[] } | undefined;
      return {
        id: String(n.id),
        title: n.title || "H3 Studio",
        scenes: Array.isArray(project?.scenes) ? project.scenes.length : 1,
      };
    });
  const current = studios.value.find((s) => s.id === value.value.studio);
  if (current) write({ studio: current.id, count: current.scenes });
  else if (!value.value.studio && studios.value.length === 1)
    write({ studio: studios.value[0]!.id, count: studios.value[0]!.scenes });
}
scan();
// Studios come and go, and their scenes change, with no event this node hears.
const timer = window.setInterval(scan, 750);

const linked = computed(() => studios.value.some((s) => s.id === value.value.studio));
const options = computed(() =>
  studios.value.map((s) => ({
    value: s.id,
    label: `#${s.id} · ${s.title} — ${s.scenes} scene${s.scenes === 1 ? "" : "s"}`,
    icon: "mdi mdi-movie-open-star-outline",
  })),
);

function pick(id: string) {
  const s = studios.value.find((x) => x.id === id);
  if (s) write({ studio: s.id, count: s.scenes });
}

let unpoint: (() => void) | null = null;
function point(id: string | null) {
  unpoint?.();
  unpoint = null;
  if (id) unpoint = highlightNode(id, `#${id}`);
}
function reveal() {
  if (linked.value) revealNode(value.value.studio);
}

onBeforeUnmount(() => {
  window.clearInterval(timer);
  point(null);
});
</script>

<style scoped>
.link {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 2px;
  color: var(--zen-text, #e5e5ea);
  font-size: 11.5px;
}
.row {
  display: flex;
  gap: 4px;
  min-width: 0;
}
.pick {
  flex: 1;
  min-width: 0;
}
.count {
  margin: 0;
  padding: 0 2px;
  color: var(--zen-muted, #9aa0aa);
}
.count b {
  color: var(--zen-text, #e5e5ea);
}
.count.missing {
  color: var(--zen-danger, #f87171);
}
</style>
