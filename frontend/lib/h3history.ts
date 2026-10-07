// Undo and redo for an H3 Studio project. The history is snapshots of the whole document, one per
// burst of changes: everything that happens within a moment of the last change (typing a line,
// dragging a curve point) is one step. Shared by every view of the project, like the project.
//
// Two things are not edits and are left alone by undo: which scene is current (`active`, which
// follows the playhead), a scene's finished `render` (which arrives from a run) and the layout.
import { effectScope, reactive, watch } from "vue";
import type { Project } from "./h3studio";

const BURST_MS = 600;
const LIMIT = 200;
const VOLATILE = new Set(["active", "render", "layout"]);

const snapshot = (project: Project) => JSON.stringify(project, (key, value) => (VOLATILE.has(key) ? undefined : value));

export interface ProjectHistory {
  readonly canUndo: boolean;
  readonly canRedo: boolean;
  undo(): void;
  redo(): void;
}

const histories = new WeakMap<Project, ProjectHistory>();

export function useProjectHistory(project: Project): ProjectHistory {
  const known = histories.get(project);
  if (known) return known;

  const past: string[] = [];
  const future: string[] = [];
  let current = snapshot(project);
  let burst = 0;
  const state = reactive({ canUndo: false, canRedo: false });
  const sync = () => {
    state.canUndo = past.length > 0 || burst !== 0;
    state.canRedo = future.length > 0;
  };

  /** Close the burst in progress: the document as it is now becomes the current step. */
  function settle() {
    if (!burst) return;
    window.clearTimeout(burst);
    burst = 0;
    current = snapshot(project);
    sync();
  }
  // Detached: the history must outlive whichever view (node or panel) happened to create it.
  effectScope(true).run(() =>
    watch(
    project,
    () => {
      const now = snapshot(project);
      if (now === current && !burst) return;
      if (!burst) {
        past.push(current);
        if (past.length > LIMIT) past.shift();
        future.length = 0;
      }
      window.clearTimeout(burst);
      burst = window.setTimeout(settle, BURST_MS);
      sync();
    },
    { deep: true },
    ),
  );

  /** Put the document back to a snapshot, keeping what undo leaves alone. */
  function restore(json: string) {
    const renders = new Map(project.scenes.map((s) => [s.id, s.render]));
    const next = JSON.parse(json) as Project & Record<string, unknown>;
    const doc = project as Project & Record<string, unknown>;
    for (const key of Object.keys(doc)) if (!(key in next) && !VOLATILE.has(key)) delete doc[key];
    for (const [key, value] of Object.entries(next)) doc[key] = value;
    for (const s of project.scenes) {
      const render = renders.get(s.id);
      if (render) s.render = render;
    }
    project.active = Math.min(project.active, project.scenes.length - 1);
    current = snapshot(project);
  }

  const history: ProjectHistory = {
    get canUndo() {
      return state.canUndo;
    },
    get canRedo() {
      return state.canRedo;
    },
    undo() {
      settle();
      const to = past.pop();
      if (to === undefined) return;
      future.push(current);
      restore(to);
      sync();
    },
    redo() {
      settle();
      const to = future.pop();
      if (to === undefined) return;
      past.push(current);
      restore(to);
      sync();
    },
  };
  histories.set(project, history);
  return history;
}
