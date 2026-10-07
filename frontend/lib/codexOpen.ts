// Where the Codex opens: a panel in ZenKit's Start menu (the taskbar) when ZenKit is installed,
// else a tab in ComfyUI's own sidebar. Either way it is the same CodexApp.
import { createApp, type App } from "vue";
import { app } from "@comfy/app";
import { openZenPanel, registerZenPanel } from "@/framework";
import CodexApp from "@/components/codex/CodexApp.vue";
import { registerCodexCapabilities } from "./codexAgent";

const PANEL = {
  id: "nynxz.codex",
  title: "Codex",
  icon: "mdi mdi-book-open-page-variant-outline",
  width: 1100,
  height: 720,
  minWidth: 640,
  minHeight: 420,
};

/** Open the Codex: its ZenKit panel, or ComfyUI's sidebar tab without ZenKit. */
export function openCodex() {
  if (openZenPanel(PANEL, CodexApp)) return;
  (
    app as { extensionManager?: { sidebarTab?: { toggleSidebarTab?(id: string): void } } }
  ).extensionManager?.sidebarTab?.toggleSidebarTab?.(PANEL.id);
}

export async function registerCodex() {
  registerCodexCapabilities();
  if (await registerZenPanel({ ...PANEL, plugin: "NynxzH3" }, CodexApp)) return;
  let mounted: App | null = null;
  (
    app as { extensionManager?: { registerSidebarTab?(tab: unknown): void } }
  ).extensionManager?.registerSidebarTab?.({
    id: PANEL.id,
    title: PANEL.title,
    tooltip: "Codex — a show's characters, places, props and looks",
    icon: PANEL.icon,
    type: "custom",
    render(el: HTMLElement) {
      el.style.height = "100%";
      mounted?.unmount();
      mounted = createApp(CodexApp);
      mounted.mount(el);
    },
    destroy() {
      mounted?.unmount();
      mounted = null;
    },
  });
}
