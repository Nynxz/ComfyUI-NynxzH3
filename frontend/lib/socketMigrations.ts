// Saved workflows keep each node's sockets as they were, and links point at sockets by position.
// When a node's sockets are reordered or removed, an old workflow would wire the wrong ones — so
// before a workflow loads, its H3 Studio nodes are rewired by socket name to the current order,
// and links to removed sockets are dropped.
import { app } from "@comfy/app";

interface Spec {
  inputs: string[];
  outputs: string[];
}
// Inputs as the frontend lays them out: required first, then optional, widgets last.
const SPECS: Record<string, Spec> = {
  "nynxz.H3.StudioSetup": {
    inputs: ["model", "clip", "vae", "audio_vae", "previous", "scene", "controlnet"],
    outputs: ["setup"],
  },
  "nynxz.H3.StudioOutputs": {
    inputs: ["render"],
    outputs: ["model", "positive", "noise", "latent", "frames", "prompt"],
  },
};
/** Output types, for a socket an old workflow never had: the frontend matches outputs to the
 *  node's by position, so every one must be there. */
const OUTPUT_TYPES: Record<string, string> = {
  setup: "NYNXZ_H3_STUDIO_SETUP",
  model: "MODEL",
  positive: "CONDITIONING",
  noise: "NOISE",
  latent: "LATENT",
  frames: "INT",
  prompt: "STRING",
};

type LinkId = number | string;
interface SlotIn {
  name: string;
  link?: LinkId | null;
  slot_index?: number;
  [k: string]: unknown;
}
interface SlotOut {
  name: string;
  links?: LinkId[] | null;
  slot_index?: number;
  [k: string]: unknown;
}
interface NodeData {
  id: LinkId;
  type: string;
  inputs?: SlotIn[];
  outputs?: SlotOut[];
}
/** A link as saved: a tuple at the top level, an object in newer files and subgraphs. */
type LinkData =
  | [LinkId, LinkId, number, LinkId, number, unknown]
  | { id: LinkId; origin_id: LinkId; origin_slot: number; target_id: LinkId; target_slot: number };
interface GraphData {
  nodes?: NodeData[];
  links?: LinkData[];
  inputs?: { linkIds?: LinkId[] }[];
  outputs?: { linkIds?: LinkId[] }[];
  definitions?: { subgraphs?: GraphData[] };
}

const linkId = (l: LinkData) => (Array.isArray(l) ? l[0] : l.id);
const ends = (l: LinkData) =>
  Array.isArray(l) ? { origin: l[1], target: l[3] } : { origin: l.origin_id, target: l.target_id };
function setSlot(l: LinkData, end: "origin" | "target", slot: number) {
  if (Array.isArray(l)) l[end === "origin" ? 2 : 4] = slot;
  else if (end === "origin") l.origin_slot = slot;
  else l.target_slot = slot;
}

/** `names` in the spec's order, anything the spec doesn't know kept after them as it was. */
function ordered<T extends { name: string }>(slots: T[], spec: string[]): T[] {
  const known = spec.flatMap((n) => slots.filter((s) => s.name === n));
  return [...known, ...slots.filter((s) => !spec.includes(s.name))];
}

export function migrateGraph(graph: GraphData, removed: Record<string, Spec>): void {
  const links = graph.links ?? [];
  const byId = new Map(links.map((l) => [String(linkId(l)), l]));
  const nodes = new Map((graph.nodes ?? []).map((n) => [String(n.id), n]));
  const dropped = new Set<string>();
  const drop = (id: LinkId) => {
    const l = byId.get(String(id));
    if (!l) return;
    dropped.add(String(id));
    const { origin, target } = ends(l);
    const from = nodes.get(String(origin));
    for (const o of from?.outputs ?? []) o.links = o.links?.filter((x) => String(x) !== String(id));
    const to = nodes.get(String(target));
    for (const i of to?.inputs ?? []) if (String(i.link) === String(id)) i.link = null;
  };

  for (const node of graph.nodes ?? []) {
    const spec = SPECS[node.type];
    if (!spec) continue;
    const gone = removed[node.type];
    for (const i of node.inputs ?? [])
      if (gone?.inputs.includes(i.name) && i.link != null) drop(i.link);
    for (const o of node.outputs ?? [])
      if (gone?.outputs.includes(o.name)) for (const id of o.links ?? []) drop(id);
    if (node.inputs) {
      node.inputs = ordered(
        node.inputs.filter((i) => !gone?.inputs.includes(i.name)),
        spec.inputs,
      );
      node.inputs.forEach((i, at) => {
        const l = i.link != null ? byId.get(String(i.link)) : undefined;
        if (l) setSlot(l, "target", at);
      });
    }
    if (node.outputs) {
      const old = node.outputs;
      node.outputs = spec.outputs.map(
        (name) => old.find((o) => o.name === name) ?? { name, type: OUTPUT_TYPES[name], links: [] },
      );
      node.outputs.forEach((o, at) => {
        if (o.slot_index !== undefined) o.slot_index = at;
        for (const id of o.links ?? []) {
          const l = byId.get(String(id));
          if (l) setSlot(l, "origin", at);
        }
      });
    }
  }
  if (dropped.size) {
    graph.links = links.filter((l) => !dropped.has(String(linkId(l))));
    for (const io of [...(graph.inputs ?? []), ...(graph.outputs ?? [])])
      io.linkIds = io.linkIds?.filter((x) => !dropped.has(String(x)));
  }
  for (const sub of graph.definitions?.subgraphs ?? []) migrateGraph(sub, removed);
}

/** Sockets these nodes no longer have. */
const REMOVED: Record<string, Spec> = {
  "nynxz.H3.StudioSetup": { inputs: ["previous_frames", "previous_audio"], outputs: [] },
  "nynxz.H3.StudioOutputs": { inputs: [], outputs: ["trim_frames", "width", "height", "seed"] },
};

export function registerSocketMigrations(): void {
  app.registerExtension({
    name: "nynxz.H3Studio.socketMigrations",
    beforeConfigureGraph(graphData: unknown) {
      if (graphData && typeof graphData === "object") migrateGraph(graphData as GraphData, REMOVED);
    },
  });
}
