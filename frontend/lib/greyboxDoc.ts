// A Grey Box Studio session: a project (a Codex show's greybox/ folder), one scene in it with its
// set and the cast. Every change goes through an action (lib/greyboxActions.ts); each settles into
// one undo step and is saved to its file shortly after. Files changed by someone else (an agent
// working on them) are picked up and reloaded, unless an edit here is waiting to be saved.
import { reactive } from "vue";
import { toScene, toSet, emptyScene, emptySet, type CastData } from "./greybox";
import { act, ActionError, type Args, type Doc } from "./greyboxActions";

type Kind = "scene" | "set" | "cast";
export interface ProjectInfo {
  id: string;
  name: string;
  scenes: string[];
  sets: string[];
  hasCast: boolean;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = (await res.json().catch(() => ({}))) as T & { error?: string };
  if (!res.ok) throw new Error(data.error ?? `${path}: ${res.status}`);
  return data;
}

export function useGreyBox() {
  const state = reactive({
    projects: [] as ProjectInfo[],
    project: "",
    sceneName: "",
    setName: "",
    scenes: [] as string[],
    sets: [] as string[],
    loaded: false,
    saving: false,
    error: "",
    /** The last action's message, or why it couldn't be done. */
    message: "",
    canUndo: false,
    canRedo: false,
    /** Bumped when files are reloaded from disk. */
    reloads: 0,
  });
  const doc = reactive<Doc>({ scene: toScene({}), set: toSet({}), cast: {} });

  const saved: Record<Kind, string> = { scene: "", set: "", cast: "" };
  let stamps: Record<string, number> = {};
  const json = (k: Kind) => JSON.stringify(doc[k]);

  // --- history -----------------------------------------------------------------------------------
  const past: string[] = [];
  const future: string[] = [];
  let base = "";
  const snap = () => JSON.stringify(doc);
  function checkpoint() {
    const now = snap();
    if (now === base) return;
    past.push(base);
    if (past.length > 200) past.shift();
    future.length = 0;
    base = now;
    syncHistory();
  }
  function syncHistory() {
    state.canUndo = past.length > 0 || snap() !== base;
    state.canRedo = future.length > 0;
  }
  function restore(to: string) {
    const d = JSON.parse(to) as Doc;
    doc.scene = d.scene;
    doc.set = d.set;
    doc.cast = d.cast;
    base = to;
  }
  function undo() {
    checkpoint();
    const to = past.pop();
    if (to === undefined) return;
    future.push(base);
    restore(to);
    syncHistory();
    state.message = "Undone.";
    schedule();
  }
  function redo() {
    checkpoint();
    const to = future.pop();
    if (to === undefined) return;
    past.push(base);
    restore(to);
    syncHistory();
    state.message = "Redone.";
    schedule();
  }

  // --- saving ------------------------------------------------------------------------------------
  let timer = 0;
  const dirty = (): Kind[] =>
    (["scene", "set", "cast"] as Kind[]).filter((k) => json(k) !== saved[k]);
  function schedule() {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => void flush(), 500);
  }
  async function flush() {
    window.clearTimeout(timer);
    if (!state.project || !state.sceneName) return;
    const kinds = dirty();
    if (!kinds.length) return;
    state.saving = true;
    try {
      for (const kind of kinds) {
        const name = kind === "scene" ? state.sceneName : kind === "set" ? state.setName : "cast";
        if (kind === "set" && !name) continue;
        const body = json(kind);
        const res = await post<{ stamps: Record<string, number> }>("/nynxz/greybox/save", {
          project: state.project,
          kind,
          name,
          data: JSON.parse(body),
        });
        saved[kind] = body;
        stamps = res.stamps;
      }
      state.error = "";
    } catch (e) {
      state.error = e instanceof Error ? e.message : String(e);
    } finally {
      state.saving = false;
    }
  }

  // --- actions -----------------------------------------------------------------------------------
  /** Run an action. `settle: false` for the steps of a drag: the drag's start was the checkpoint. */
  function run(name: string, args: Args = {}, opts: { settle?: boolean } = {}): boolean {
    if (opts.settle !== false) checkpoint();
    try {
      state.message = act(doc, name, args).message;
      if (opts.settle !== false) checkpoint();
      schedule();
      syncHistory();
      return true;
    } catch (e) {
      state.message = e instanceof ActionError ? e.message : String(e);
      return false;
    }
  }
  /** Before a drag: one undo step for the whole drag. */
  const beginChange = () => checkpoint();
  const endChange = () => {
    checkpoint();
    schedule();
  };

  // --- loading -----------------------------------------------------------------------------------
  async function listProjects() {
    const res = await fetch("/nynxz/greybox/projects");
    const data = (await res.json()) as { projects?: ProjectInfo[] };
    state.projects = data.projects ?? [];
  }

  interface Opened {
    scene: unknown;
    set: unknown;
    setName: string | null;
    cast: CastData;
    scenes: string[];
    sets: string[];
    stamps: Record<string, number>;
  }
  async function open(project: string, sceneName: string) {
    await flush();
    const o = await post<Opened>("/nynxz/greybox/open", { project, scene: sceneName });
    state.project = project;
    state.sceneName = sceneName;
    state.scenes = o.scenes;
    state.sets = o.sets;
    state.setName = o.setName ?? "";
    doc.scene = toScene(o.scene ?? emptyScene(state.setName));
    doc.set = toSet(o.set ?? emptySet(state.setName || "set"));
    doc.cast = o.cast ?? {};
    saved.scene = o.scene ? json("scene") : "";
    saved.set = o.set ? json("set") : "";
    saved.cast = json("cast");
    stamps = o.stamps;
    past.length = 0;
    future.length = 0;
    base = snap();
    syncHistory();
    state.loaded = true;
    state.error = "";
  }

  async function newScene(name: string, set: string) {
    await flush();
    state.sceneName = name;
    state.setName = set;
    const exists = state.sets.includes(set);
    doc.scene = emptyScene(set);
    doc.scene.name = name;
    if (!exists) doc.set = emptySet(set);
    else {
      const o = await post<Opened>("/nynxz/greybox/open", { project: state.project, set });
      doc.set = toSet(o.set);
      saved.set = json("set");
    }
    saved.scene = "";
    if (!exists) saved.set = "";
    await flush();
    await open(state.project, name);
  }

  /** Copy the worked example in; `replace` overwrites its scenes and set with the current ones. */
  async function addExample(replace = false) {
    await flush();
    const res = await post<{ scenes: string[]; sets: string[] }>("/nynxz/greybox/example", {
      project: state.project,
      replace,
    });
    state.scenes = res.scenes;
    state.sets = res.sets;
  }

  /** Delete a scene or a set (not one a scene uses). Deleting the open scene closes it. */
  async function remove(kind: "scene" | "set", name: string) {
    await flush();
    const res = await post<{ scenes: string[]; sets: string[]; stamps: Record<string, number> }>(
      "/nynxz/greybox/delete",
      { project: state.project, kind, name },
    );
    state.scenes = res.scenes;
    state.sets = res.sets;
    stamps = res.stamps;
    if (kind === "scene" && name === state.sceneName) {
      state.loaded = false;
      state.sceneName = "";
      state.setName = "";
      past.length = 0;
      future.length = 0;
      syncHistory();
    }
  }

  /** Reload files that changed on disk, if nothing here is waiting to be saved. */
  async function poll() {
    if (!state.project || !state.sceneName || state.saving || dirty().length) return;
    const res = await post<{ stamps: Record<string, number>; scenes: string[]; sets: string[] }>(
      "/nynxz/greybox/stamps",
      { project: state.project },
    ).catch(() => null);
    if (!res) return;
    state.scenes = res.scenes;
    state.sets = res.sets;
    const mine = [`scenes/${state.sceneName}.json`, `sets/${state.setName}.json`, "cast.json"];
    const changed = mine.some((f) => res.stamps[f] !== undefined && res.stamps[f] !== stamps[f]);
    stamps = res.stamps;
    if (!changed || dirty().length) return;
    const keepUndo = { past: [...past], future: [...future] };
    await open(state.project, state.sceneName);
    past.push(...keepUndo.past);
    syncHistory();
    state.reloads++;
    state.message = "Reloaded: the files changed on disk.";
  }
  const pollTimer = window.setInterval(() => void poll(), 2500);

  return {
    state,
    doc,
    run,
    beginChange,
    endChange,
    undo,
    redo,
    flush,
    listProjects,
    open,
    newScene,
    addExample,
    remove,
    stop: () => {
      window.clearInterval(pollTimer);
      void flush();
    },
  };
}
export type GreyBoxSession = ReturnType<typeof useGreyBox>;
/** Editors open right now: an agent's actions go through the one showing the scene they change. */
export const liveSessions = new Set<GreyBoxSession>();

export async function renderStill(
  s: GreyBoxSession,
  shot: string,
  t: number,
  width: number,
  height: number,
): Promise<string> {
  const res = await post<{ png: string }>("/nynxz/greybox/still", {
    project: s.state.project,
    name: s.state.sceneName,
    scene: s.doc.scene,
    set: s.doc.set,
    cast: s.doc.cast,
    shot,
    t,
    width,
    height,
  });
  return `data:image/png;base64,${res.png}`;
}

export async function renderShot(
  s: GreyBoxSession,
  shot: string,
  width: number,
  height: number,
  depth = false,
): Promise<string> {
  const res = await post<{ ref: string }>("/nynxz/greybox/render", {
    project: s.state.project,
    name: s.state.sceneName,
    scene: s.doc.scene,
    set: s.doc.set,
    cast: s.doc.cast,
    shot,
    width,
    height,
    depth,
  });
  return res.ref;
}

const held = new Map<string, { session: GreyBoxSession; users: number; timer?: number }>();
/** The session for a key, shared by every editor showing it — so a node's editor and its popped-out
 *  panel hand over one session (its undo history, unsaved edits) instead of starting afresh. */
export function holdGreyBox(key: string): GreyBoxSession {
  const h = held.get(key);
  if (h) {
    window.clearTimeout(h.timer);
    h.users++;
    return h.session;
  }
  const session = useGreyBox();
  held.set(key, { session, users: 1 });
  liveSessions.add(session);
  return session;
}
export function releaseGreyBox(key: string) {
  const h = held.get(key);
  if (!h || --h.users > 0) return;
  h.timer = window.setTimeout(() => {
    held.delete(key);
    liveSessions.delete(h.session);
    h.session.stop();
  }, 2000);
}
