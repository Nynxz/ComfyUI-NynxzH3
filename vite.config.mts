import { zenPluginConfig } from "@nynxz/zenkit-nodekit/vite";

// The whole build comes from the shared preset: @comfy/* externalised and rewritten,
// CSS folded into the single main.js ComfyUI loads, and NODE_ENV defined for Vue.
const config = zenPluginConfig({
  name: "comfyui-nynxzh3",
  configUrl: import.meta.url,
  srcDir: "./frontend",
  outDir: "web", // matches WEB_DIRECTORY in __init__.py
});

// Code loaded on demand (the Grey Box editor and three.js) goes in chunks named .mjs: ComfyUI
// loads every .js under WEB_DIRECTORY at startup, which would load them up front.
const output = config.build?.rollupOptions?.output;
if (output && !Array.isArray(output)) output.chunkFileNames = "chunks/[name]-[hash].mjs";

export default config;
