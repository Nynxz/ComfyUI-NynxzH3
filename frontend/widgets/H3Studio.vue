<template>
  <div class="h3host">
    <StudioSummary v-if="!panel && poppedOut" :project="project" @focus="popOut" />
    <StudioEditor v-else :project="project" :view="view" :node-id="nodeId" :in-panel="panel" @pop-out="popOut" />
  </div>
</template>

<script lang="ts">
// Read by nodekit's `discoverWidgets`: the io type comes from this file's NAME
// (H3Studio.vue -> NYNXZ_H3_STUDIO, matching nodes/h3studio/io_types.py).
import type { NodeDef, WidgetOptions } from "@/framework";
import { defaultProject } from "@/lib/h3studio";

export const widgetOptions: WidgetOptions = {
  name: "project",
  // Fill: the studio takes whatever size the node is given and scrolls inside, instead of the
  // node jumping around the graph as shots are added.
  fill: true,
  minHeight: 640,
  default: defaultProject(),
};

export const nodeDef: Omit<NodeDef, "widgets"> = {
  is: "nynxz.H3.Studio",
  minSize: [960, 800],
  slotLinks: [
    { input: "setup", spawn: "nynxz.H3.StudioSetup" },
    { output: "render", spawn: "nynxz.H3.StudioOutputs" },
  ],
};
</script>

<script setup lang="ts">
// The node's body: the studio editor — or, while it is popped out into a ZenKit panel, a summary
// of the film. Both views edit one shared project (lib/h3studio.ts), written back to this widget.
import { computed, getCurrentInstance, onBeforeUnmount, onMounted } from "vue";
import { hasZenPanels, openZenPanel, type ZenPanelHandle } from "@/framework";
import { isPanelOpen, setPanelOpen, useProject, useStudioView } from "@/lib/h3studio";
import StudioEditor from "@/components/h3studio/StudioEditor.vue";
import StudioSummary from "@/components/h3studio/StudioSummary.vue";

interface DOMWidget {
  value: unknown;
  callback?: (v: unknown) => void;
}
interface StudioNode {
  id?: number | string;
  graph?: { id?: string; change?: () => void } | null;
  properties?: Record<string, unknown>;
  onRemoved?: (...args: unknown[]) => unknown;
}
const props = defineProps<{ widget?: DOMWidget; node?: StudioNode; panel?: boolean }>();

const project = useProject(props.widget);
const view = useStudioView(props.node);
const nodeId = String(props.node?.id ?? "");
const poppedOut = computed(() => isPanelOpen(nodeId));

// The panel instance marks itself open for as long as it is mounted, so closing the panel any
// way at all brings the editor back to the node.
onMounted(() => props.panel && setPanelOpen(nodeId, true));
onBeforeUnmount(() => props.panel && setPanelOpen(nodeId, false));

// --- popped out survives a reload ------------------------------------------------------------------
// The node remembers it (a property, saved with the workflow) and pops out again when it loads. The
// panel id comes from the graph and node ids, so ZenKit finds the panel's saved size, place and
// workspace tile under it. A node leaving with its workflow closes the panel but keeps its place.
const POPPED = "nynxzH3PoppedOut";
const handles = new WeakMap<object, ZenPanelHandle>();
const quiet = new WeakSet<object>();
const panelId = () => {
  const graph = props.node?.graph?.id;
  return graph ? `nynxz.h3studio:${graph}:${nodeId}` : `nynxz.h3studio.${nodeId}`;
};
function remember(popped: boolean) {
  const node = props.node;
  if (!node) return;
  node.properties ??= {};
  if (Boolean(node.properties[POPPED]) === popped) return;
  node.properties[POPPED] = popped;
  node.graph?.change?.();
}

const self = getCurrentInstance()!.type;
function popOut() {
  const node = props.node;
  const handle = openZenPanel(
    {
      id: panelId(),
      title: "H3 Studio",
      icon: "mdi mdi-movie-open-outline",
      width: 1080,
      height: 760,
      minWidth: 640,
      minHeight: 480,
      persist: true,
      props: { widget: props.widget, node: props.node, panel: true },
      onClose: () => {
        if (node) handles.delete(node);
        if (node && quiet.delete(node)) return;
        remember(false);
      },
    },
    self,
  );
  if (!handle || !node) return;
  handles.set(node, handle);
  remember(true);
  const previous = node.onRemoved;
  node.onRemoved = function (this: unknown, ...args: unknown[]) {
    const h = handles.get(node);
    if (h) {
      quiet.add(node);
      h.close({ keep: true });
    }
    return previous?.apply(this, args);
  };
}

onMounted(() => {
  if (props.panel || !props.node?.properties?.[POPPED]) return;
  // ZenKit can finish installing after this node mounts; give it a moment rather than give up.
  let tries = 0;
  const attempt = () => {
    if (isPanelOpen(nodeId) || (props.node && handles.has(props.node))) return;
    if (hasZenPanels()) popOut();
    else if (++tries < 40) setTimeout(attempt, 250);
  };
  attempt();
});
</script>

<style scoped>
.h3host {
  position: relative;
  box-sizing: border-box;
  width: 100%;
  height: 100%;
  min-height: 0;
}
/* Pinned to the body's exact box, so the editor's flexible rows have a definite height to share
   and the monitor gives way before the timeline is cut off. */
.h3host > * {
  position: absolute;
  inset: 0;
}
</style>
