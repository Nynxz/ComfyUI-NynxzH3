// The pack's one crossing into @nynxz/zenkit-nodekit: everything identity-free, plus what
// createNodekit binds to the identity in pack.json. Everything else imports from this file.

import { createNodekit } from "@nynxz/zenkit-nodekit";

import manifest from "../pack.json";

export * from "@nynxz/zenkit-nodekit";
export const {
  NAMESPACE,
  DISPLAY_NAME,
  CATEGORY,
  nodeId,
  route,
  routeUrl,
  settingId,
  typeId,
  registerNodes,
  discoverNodes,
  discoverWidgets,
  widgetTypes,
  mountWidget,
  addNodeHeaderButton,
  mediaLibrary,
  mediaInfo,
  thumbUrl,
  uploadOrReuse,
} = createNodekit(manifest);
