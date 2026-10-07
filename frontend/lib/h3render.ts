// Rendering part of a film: which scenes are up to date, and running just the ones you pick.
//
// Each scene's latest clip is recorded by the studio's Python side (nodes/h3studio/_reuse.py), with
// the fingerprint of what made it. `/nynxz/h3studio/status` compares that with the scene as it stands
// now: "current" (nothing that shapes it changed), "stale" (it, or the scene it continues from, did),
// or "none" (never rendered). Sampler settings aren't part of that check — they're only known in a run.
//
// A partial render works with either workflow:
// - a scene loop (Start Loop's iteration into H3 Studio Setup's `scene`): one run, with the project's
//   `renderOnly` set to the scenes to render — the others play their latest clip without sampling;
// - no loop (the studio renders its active scene): one run per scene, in order. A scene that
//   continues from the previous one picks up that scene's latest clip, so they chain.
import { nextTick, reactive, watch } from "vue";
import { api } from "@comfy/api";
import { app } from "@comfy/app";
import type { Project } from "./h3studio";

export type SceneState = "current" | "stale" | "none";
export interface SceneStatus {
  id: string;
  state: SceneState;
  /** Its latest clip (a media ref), if any. */
  ref: string | null;
  /** When that clip was made (seconds since the epoch). */
  time: number | null;
}

/** Each scene's status by id, kept fresh: after edits settle, and whenever a clip lands. */
export function useRenderStatus(project: Project) {
  const status = reactive(new Map<string, SceneStatus>());
  let timer = 0;
  let asked = 0;
  async function refresh() {
    const ask = ++asked;
    try {
      const res = await fetch("/nynxz/h3studio/status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project }),
      });
      if (!res.ok || ask !== asked) return;
      const { scenes } = (await res.json()) as { scenes: SceneStatus[] };
      status.clear();
      for (const s of scenes) status.set(s.id, s);
    } catch {
      /* the server is away: keep what we had */
    }
  }
  const soon = () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => void refresh(), 500);
  };
  // Anything in a scene can change its fingerprint; what's on screen (zoom, selection) doesn't.
  watch(() => JSON.stringify({ ...project, active: 0 }), soon, { immediate: true });
  const target = api as unknown as EventTarget;
  const onDone = () => soon();
  target.addEventListener("nynxz.h3studio.clip", onDone);
  target.addEventListener("execution_success", onDone);
  const stop = () => {
    window.clearTimeout(timer);
    target.removeEventListener("nynxz.h3studio.clip", onDone);
    target.removeEventListener("execution_success", onDone);
  };
  return { status, refresh, stop };
}

interface GraphNode {
  id: number | string;
  type: string;
  inputs?: { name: string; link: number | null }[];
}
interface Graph {
  getNodeById(id: number | string): GraphNode | null;
  links:
    Record<number, { origin_id: number | string }> | Map<number, { origin_id: number | string }>;
}
const linkOf = (graph: Graph, id: number) => {
  const links = graph.links;
  return links instanceof Map ? links.get(id) : links[id];
};

/** Whether this studio renders in a scene loop: its Setup's `scene` input is wired. */
export function rendersInALoop(studioNodeId: string): boolean {
  const graph = (app as unknown as { graph: Graph }).graph;
  const studio = graph.getNodeById(studioNodeId);
  const setupLink = studio?.inputs?.find((i) => i.name === "setup")?.link;
  const setup =
    setupLink != null ? graph.getNodeById(linkOf(graph, setupLink)?.origin_id ?? -1) : null;
  return setup?.inputs?.find((i) => i.name === "scene")?.link != null;
}

const queue = () =>
  (app as unknown as { queuePrompt(n: number, count: number): Promise<unknown> }).queuePrompt(0, 1);

/** Render `ids` (in film order), or every scene when null. Resolves once the runs are queued. */
export async function renderScenes(project: Project, studioNodeId: string, ids: string[] | null) {
  const order = project.scenes.map((s) => s.id);
  const chosen = ids ? order.filter((id) => ids.includes(id)) : order;
  if (!chosen.length) return;
  if (rendersInALoop(studioNodeId)) {
    project.renderOnly = ids ? chosen : undefined;
    await nextTick();
    try {
      await queue();
    } finally {
      project.renderOnly = undefined;
    }
    return;
  }
  const active = project.active;
  try {
    for (const id of chosen) {
      project.active = order.indexOf(id);
      await nextTick();
      await queue();
    }
  } finally {
    project.active = active;
  }
}
