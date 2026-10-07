<template>
  <div class="gbhost">
    <div v-if="!panel && poppedOut" class="popped">
      <i class="mdi mdi-cube-scan" />
      <div class="text">
        <b>Grey Box Studio is open in a panel</b>
        <span
          >{{ value.project || "No project" }}{{ value.scene ? ` · ${value.scene}` : ""
          }}{{ value.shot ? ` · shot ${value.shot}` : "" }}</span
        >
      </div>
      <ZenButton size="sm" variant="primary" icon="mdi mdi-open-in-new" @click="popOut"
        >Show it</ZenButton
      >
    </div>
    <GreyBoxEditor
      v-else
      :value="value"
      :in-panel="panel"
      :can-pop-out="canPopOut"
      :width="size.width"
      :height="size.height"
      :session-key="panelId()"
      @change="onChange"
      @pop-out="popOut"
    />
  </div>
</template>

<script lang="ts">
// Read by nodekit's `discoverWidgets`: GreyBoxStudio.vue -> NYNXZ_GREY_BOX_STUDIO
// (nodes/greybox/io_types.py).
import { reactive as _reactive } from "vue";
import type { NodeDef, WidgetOptions } from "@/framework";

/** Grey Box Studio nodes whose editor is open in a panel right now. */
const openPanels = _reactive(new Set<string>());

export const widgetOptions: WidgetOptions = {
  name: "studio",
  fill: true,
  minHeight: 640,
  default: { project: "", scene: "", shot: "" },
};

export const nodeDef: Omit<NodeDef, "widgets"> = {
  is: "nynxz.GreyBox.Studio",
  minSize: [1120, 900],
};
</script>

<script setup lang="ts">
// The Grey Box Studio node's body: the editor — or, while it's popped out into a ZenKit panel, a
// card saying so. The node's value is which project, scene and shot it renders.
import {
  computed,
  defineAsyncComponent,
  getCurrentInstance,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
} from "vue";
import { ZenButton } from "@nynxz/zenkit-ui";
import { hasZenPanels, openZenPanel, type ZenPanelHandle } from "@/framework";
import type { StudioValue } from "@/components/greybox/GreyBoxEditor.vue";

// The editor (and three.js with it) loads only when a Grey Box Studio is on the canvas.
const GreyBoxEditor = defineAsyncComponent(() => import("@/components/greybox/GreyBoxEditor.vue"));

interface DOMWidget {
  value: unknown;
  callback?: (v: unknown) => void;
}
interface GbNode {
  id?: number | string;
  graph?: { id?: string; change?: () => void } | null;
  properties?: Record<string, unknown>;
  widgets?: { name: string; value: unknown }[];
  onRemoved?: (...args: unknown[]) => unknown;
}
const props = defineProps<{ widget?: DOMWidget; node?: GbNode; panel?: boolean }>();

const toValue = (v: unknown): StudioValue => {
  const o = (v && typeof v === "object" ? v : {}) as Partial<StudioValue>;
  return {
    project: String(o.project ?? ""),
    scene: String(o.scene ?? ""),
    shot: String(o.shot ?? ""),
  };
};
const value = ref<StudioValue>(toValue(props.widget?.value));
function onChange(next: StudioValue) {
  value.value = next;
  const w = props.widget;
  if (!w) return;
  w.value = { ...next };
  w.callback?.(w.value);
}

// The render's size, from the node's own width and height: the shot view is framed to it.
const size = reactive({ width: 832, height: 480 });
const readSize = () => {
  const n = (name: string) => Number(props.node?.widgets?.find((w) => w.name === name)?.value);
  if (n("width") > 0) size.width = n("width");
  if (n("height") > 0) size.height = n("height");
};
readSize();
const sizeTimer = window.setInterval(readSize, 1000);
onBeforeUnmount(() => window.clearInterval(sizeTimer));

// --- popping out ------------------------------------------------------------------------------------
const nodeId = String(props.node?.id ?? "");
const open = openPanels;
const poppedOut = computed(() => open.has(nodeId));
const canPopOut = hasZenPanels();
onMounted(() => props.panel && open.add(nodeId));
onBeforeUnmount(() => props.panel && open.delete(nodeId));

const POPPED = "nynxzGreyBoxPoppedOut";
const handles = new WeakMap<object, ZenPanelHandle>();
const quiet = new WeakSet<object>();
const panelId = () => {
  const graph = props.node?.graph?.id;
  return graph ? `nynxz.greybox:${graph}:${nodeId}` : `nynxz.greybox.${nodeId}`;
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
      title: "Grey Box Studio",
      icon: "mdi mdi-cube-scan",
      width: 1180,
      height: 780,
      minWidth: 720,
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
  let tries = 0;
  const attempt = () => {
    if (open.has(nodeId) || (props.node && handles.has(props.node))) return;
    if (hasZenPanels()) popOut();
    else if (++tries < 40) setTimeout(attempt, 250);
  };
  attempt();
});
</script>

<style scoped>
.gbhost {
  position: relative;
  box-sizing: border-box;
  width: 100%;
  height: 100%;
  min-height: 0;
}
.popped {
  display: flex;
  align-items: center;
  gap: 12px;
  box-sizing: border-box;
  height: 100%;
  padding: 16px;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: var(--zen-radius, 8px);
  background: var(--zen-surface, #202026);
  color: var(--zen-text, #e5e5ea);
}
.popped > .mdi {
  color: var(--zen-accent, #6366f1);
  font-size: 26px;
}
.text {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.text span {
  color: var(--zen-muted, #9aa0aa);
  font-size: 11.5px;
}
</style>
