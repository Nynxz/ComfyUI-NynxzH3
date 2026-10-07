// Grey box for agents: ZenKit capabilities (ZenAgent sees them as tools) to read a scene, change it
// with the same actions the editor uses, and look at it — an exact still of a shot, or the contact
// sheet with the plan — so an agent can build and block scenes without working blind. Changes go
// through an open Grey Box Studio when it shows that scene (live, undoable), else to the files.
import { registerZenCapability } from "@/framework";
import { toScene, toSet, emptyScene, emptySet, type CastData } from "./greybox";
import { ACTIONS, act, ActionError, type Doc } from "./greyboxActions";
import { liveSessions, type GreyBoxSession } from "./greyboxDoc";

interface Project {
  id: string;
  name: string;
  scenes: string[];
  sets: string[];
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
async function projects(): Promise<Project[]> {
  const res = await fetch("/nynxz/greybox/projects");
  return ((await res.json()) as { projects?: Project[] }).projects ?? [];
}

/** The project and scene meant: as named, else what's open in an editor, else the only one. */
async function where(
  args: Record<string, unknown>,
  needScene = true,
): Promise<{ project: string; scene: string }> {
  const live = [...liveSessions][0];
  const list = await projects();
  let project =
    typeof args.project === "string" && args.project ? args.project : (live?.state.project ?? "");
  if (!project && list.length === 1) project = list[0]!.id;
  const p = list.find((x) => x.id === project || x.name.toLowerCase() === project.toLowerCase());
  if (!p)
    throw new Error(
      `Which project? Projects (Codex shows): ${list.map((x) => `${x.name} (${x.id})`).join(", ") || "none — make a show in the Codex"}.`,
    );
  let scene = typeof args.scene === "string" && args.scene ? args.scene : "";
  if (!scene && live?.state.project === p.id) scene = live.state.sceneName;
  if (!scene && p.scenes.length === 1) scene = p.scenes[0]!;
  if (needScene && !p.scenes.includes(scene))
    throw new Error(
      `Which scene? ${p.name}'s scenes: ${p.scenes.join(", ") || "none yet (greybox.new_scene)"}.`,
    );
  return { project: p.id, scene };
}
const liveFor = (project: string, scene: string): GreyBoxSession | undefined =>
  [...liveSessions].find(
    (s) => s.state.project === project && s.state.sceneName === scene && s.state.loaded,
  );

interface Opened {
  scene: unknown;
  set: unknown;
  setName: string | null;
  cast: CastData;
}
async function load(project: string, scene: string): Promise<{ doc: Doc; setName: string }> {
  const o = await post<Opened>("/nynxz/greybox/open", { project, scene });
  return {
    doc: {
      scene: toScene(o.scene),
      set: toSet(o.set ?? emptySet(o.setName ?? "set")),
      cast: o.cast ?? {},
    },
    setName: o.setName ?? "",
  };
}

const ACTION_LIST = ACTIONS.map((a) => `- ${a.name}: ${a.help}`).join("\n");

export function registerGreyBoxCapabilities() {
  void registerZenCapability({
    id: "greybox.projects",
    effect: "read",
    description: "List grey box projects (Codex shows) with their scenes and sets.",
    run: async () =>
      (await projects()).map((p) => ({
        project: p.id,
        name: p.name,
        scenes: p.scenes,
        sets: p.sets,
      })),
  });

  void registerZenCapability({
    id: "greybox.read",
    effect: "read",
    description:
      "Read a grey box scene as JSON: the scene (actors with their keys, shots with camera keys), its set " +
      "(shapes, marks, set cameras) and the cast (heights). Units are metres, Y up, floor y=0; yaw 0 faces +Z, " +
      "90 faces +X. Read before changing anything.",
    params: {
      type: "object",
      properties: { project: { type: "string" }, scene: { type: "string" } },
    },
    run: async (args) => {
      const w = await where(args);
      const live = liveFor(w.project, w.scene);
      const doc = live ? live.doc : (await load(w.project, w.scene)).doc;
      return {
        project: w.project,
        scene_name: w.scene,
        scene: doc.scene,
        set: doc.set,
        cast: doc.cast,
      };
    },
  });

  void registerZenCapability({
    id: "greybox.act",
    effect: "write",
    description:
      "Change a grey box scene, its set or the cast with a list of actions, run in order (stops at the first " +
      "that fails and says why). Each item: {action, ...its arguments}. Points are [x, y, z] in metres; " +
      'anywhere a point goes, a mark\'s name or "@actor" works too. Look at the result with greybox.look.\n' +
      "Actions:\n" +
      ACTION_LIST,
    params: {
      type: "object",
      properties: {
        project: { type: "string" },
        scene: { type: "string" },
        actions: {
          type: "array",
          items: {
            type: "object",
            properties: { action: { type: "string" } },
            required: ["action"],
          },
        },
      },
      required: ["actions"],
    },
    run: async (args) => {
      const w = await where(args);
      const steps = Array.isArray(args.actions) ? (args.actions as Record<string, unknown>[]) : [];
      const live = liveFor(w.project, w.scene);
      const done: string[] = [];
      if (live) {
        for (const step of steps) {
          const { action, ...rest } = step;
          if (!live.run(String(action), rest))
            return { done, failed: { action, error: live.state.message } };
          done.push(live.state.message);
        }
        await live.flush();
        return { done, live: true };
      }
      const { doc, setName } = await load(w.project, w.scene);
      const touched = new Set<string>();
      for (const step of steps) {
        const { action, ...rest } = step;
        try {
          const r = act(doc, String(action), rest);
          touched.add(r.touches);
          done.push(r.message);
        } catch (e) {
          if (!(e instanceof ActionError)) throw e;
          await save(w.project, w.scene, setName, doc, touched);
          return { done, failed: { action, error: e.message } };
        }
      }
      await save(w.project, w.scene, setName, doc, touched);
      return { done };
    },
  });

  void registerZenCapability({
    id: "greybox.look",
    effect: "read",
    description:
      'See a grey box scene rendered. what: "sheet" (default) — every shot\'s frames plus a plan from above ' +
      "with the marks, everyone's path and each shot's camera; \"still\" — one exact frame of a shot at time t " +
      "(scene seconds). Returns an image. Look after every few changes.",
    params: {
      type: "object",
      properties: {
        project: { type: "string" },
        scene: { type: "string" },
        what: { type: "string", enum: ["sheet", "still"] },
        shot: { type: "string" },
        t: { type: "number" },
      },
    },
    run: async (args) => {
      const w = await where(args);
      const live = liveFor(w.project, w.scene);
      if (live) await live.flush();
      const base = { project: w.project, name: w.scene };
      if (args.what === "still") {
        const r = await post<{ ref: string }>("/nynxz/greybox/still", {
          ...base,
          shot: typeof args.shot === "string" ? args.shot : "",
          t: typeof args.t === "number" ? args.t : undefined,
          width: 960,
          height: 540,
          save: true,
        });
        return { image: r.ref };
      }
      const r = await post<{ ref: string }>("/nynxz/greybox/sheet", base);
      return { image: r.ref };
    },
  });

  void registerZenCapability({
    id: "greybox.new_scene",
    effect: "write",
    description:
      "Start a grey box scene in a project, on an existing set or a new one (a floor to build on). " +
      "{project?, name (lowercase-with-dashes), set (a set's name; new if it doesn't exist)}.",
    params: {
      type: "object",
      properties: {
        project: { type: "string" },
        name: { type: "string" },
        set: { type: "string" },
      },
      required: ["name", "set"],
    },
    run: async (args) => {
      const w = await where(args, false);
      const slug = (v: unknown) =>
        String(v ?? "")
          .trim()
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, "-")
          .replace(/^-|-$/g, "");
      const name = slug(args.name);
      const set = slug(args.set);
      if (!name || !set) throw new Error("A scene needs a name and a set.");
      const list = await projects();
      const p = list.find((x) => x.id === w.project)!;
      if (p.scenes.includes(name)) throw new Error(`There's already a scene ${name}.`);
      if (!p.sets.includes(set))
        await post("/nynxz/greybox/save", {
          project: w.project,
          kind: "set",
          name: set,
          data: emptySet(set),
        });
      const scene = emptyScene(set);
      scene.name = name;
      await post("/nynxz/greybox/save", { project: w.project, kind: "scene", name, data: scene });
      return { project: w.project, scene: name, set, new_set: !p.sets.includes(set) };
    },
  });
}

async function save(
  project: string,
  scene: string,
  setName: string,
  doc: Doc,
  touched: Set<string>,
) {
  if (touched.has("scene"))
    await post("/nynxz/greybox/save", { project, kind: "scene", name: scene, data: doc.scene });
  if (touched.has("set") && setName)
    await post("/nynxz/greybox/save", { project, kind: "set", name: setName, data: doc.set });
  if (touched.has("cast"))
    await post("/nynxz/greybox/save", { project, kind: "cast", name: "cast", data: doc.cast });
}
