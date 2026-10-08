// Component styles plus the bridge that maps ComfyUI's CSS vars onto --zen-* tokens, so the
// components theme correctly without the ZenKit runtime.
import "@nynxz/zenkit-ui/style.css";
import "@nynxz/zenkit-ui/comfy-bridge.css";

// zenkit-ui's LoRA picker (H3 Studio's LoRA lanes) reads NynxzNodes' LoRA routes.
import { setLoraDetailOpener, setLoraSource } from "@nynxz/zenkit-ui";

import { loraSource, openLoraDetailPanel } from "@/lib/loraApi";

import { DISPLAY_NAME, discoverWidgets, registerNodes, widgetTypes } from "@/framework";

// Every .vue in frontend/widgets/ is a node widget; the filename determines its io type.
const widgets = import.meta.glob("./widgets/*.vue", { eager: true });

setLoraSource(loraSource);
setLoraDetailOpener(openLoraDetailPanel);

registerNodes(discoverWidgets(widgets));

// Old workflows rewired to H3 Studio's current sockets, by name, before they load.
import { registerSocketMigrations } from "@/lib/socketMigrations";
registerSocketMigrations();

// The Codex: a show's characters, places, props and looks (ZenKit's Start menu, else the sidebar).
import { registerCodex } from "@/lib/codexOpen";
void registerCodex();
// Grey box: the tools agents use to read, change and look at grey box scenes.
import { registerGreyBoxCapabilities } from "@/lib/greyboxAgent";
registerGreyBoxCapabilities();

console.log(`[${DISPLAY_NAME}] widgets: ${widgetTypes(widgets).join(", ") || "(none)"}`);
