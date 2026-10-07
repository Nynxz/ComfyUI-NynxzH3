// The pack's one crossing into @nynxz/zenkit-nodekit. Identity is bound here from pack.json;
// everything else imports from this file.

import {
  createNodekit,
  defineNode,
  hasMediaDrop,
  hasZenPanels,
  highlightNode,
  mediaKind,
  mediaRefUrl,
  openZenPanel,
  readMediaDrop,
  registerZenCapability,
  registerZenPanel,
  revealNode,
  uploadMediaFile,
  useDragSurface,
  viewUrl,
  type DOMWidget,
  type NodeDef,
  type NodeHeaderButtonHandle,
  type NodeHeaderButtonOptions,
  type NodeWidgetDef,
  type WidgetFileExports,
  type WidgetOptions,
  type ZenPanelHandle,
} from "@nynxz/zenkit-nodekit";

import manifest from "../pack.json";

export const {
  NAMESPACE,
  DISPLAY_NAME,
  CATEGORY,
  nodeId,
  route,
  settingId,
  typeId,
  registerNodes,
  discoverNodes,
  discoverWidgets,
  widgetTypes,
  mountWidget,
  addNodeHeaderButton,
  mediaLibrary,
  thumbUrl,
  uploadOrReuse,
} = createNodekit(manifest);

// Identity-free helpers pass straight through.
export {
  defineNode,
  hasMediaDrop,
  hasZenPanels,
  highlightNode,
  mediaKind,
  mediaRefUrl,
  openZenPanel,
  readMediaDrop,
  registerZenCapability,
  registerZenPanel,
  revealNode,
  uploadMediaFile,
  useDragSurface,
  viewUrl,
};
export type {
  DOMWidget,
  NodeDef,
  NodeHeaderButtonHandle,
  NodeHeaderButtonOptions,
  NodeWidgetDef,
  WidgetFileExports,
  WidgetOptions,
  ZenPanelHandle,
};
