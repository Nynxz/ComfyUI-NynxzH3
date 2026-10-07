// Every change to a grey box scene, its set or the cast is an action: a name and its arguments.
// The editor's buttons, drags and fields call them; undo records them; agents get the same list
// as a tool (lib/greyboxAgent.ts). Each returns a line saying what it did.
import {
  emptySet,
  isVec,
  type CastData,
  type KeyData,
  type SceneData,
  type SetData,
  type ShapeData,
  type ShapeKind,
  type Vec,
} from "./greybox";

export interface Doc {
  scene: SceneData;
  set: SetData;
  cast: CastData;
}
export type Args = Record<string, unknown>;
export interface ActionInfo {
  name: string;
  /** What it does and its arguments, for whoever calls it (an agent reads exactly this). */
  help: string;
  /** Which file it changes. */
  touches: "scene" | "set" | "cast";
  run: (doc: Doc, a: Args) => string;
}

export class ActionError extends Error {}

const vec = (v: unknown, what: string): Vec => {
  if (isVec(v)) return [v[0], v[1], v[2]];
  throw new ActionError(`${what} should be [x, y, z] in metres.`);
};
const num = (v: unknown, what: string): number => {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  throw new ActionError(`${what} should be a number.`);
};
const str = (v: unknown, what: string): string => {
  if (typeof v === "string" && v.trim()) return v.trim();
  throw new ActionError(`${what} is needed.`);
};
const mention = (v: unknown) => {
  const s = str(v, "The actor");
  return s.startsWith("@") ? s : `@${s}`;
};
const near = (a: number, b: number) => Math.abs(a - b) < 1e-3;
const round = (v: number) => Math.round(v * 1000) / 1000;
const roundVec = (v: Vec): Vec => [round(v[0]), round(v[1]), round(v[2])];

function shape(doc: Doc, id: unknown): ShapeData {
  const s = doc.set.shapes.find((x) => x.id === id);
  if (!s)
    throw new ActionError(
      `No shape ${String(id)} in the set (shapes: ${doc.set.shapes.map((x) => x.id).join(", ")}).`,
    );
  return s;
}
function actor(doc: Doc, id: unknown) {
  const a = doc.scene.actors.find((x) => x.id === mention(id));
  if (!a) throw new ActionError(`No actor ${String(id)} in the scene.`);
  return a;
}
function shot(doc: Doc, name: unknown) {
  const s = doc.scene.shots.find((x) => x.name === name);
  if (!s)
    throw new ActionError(
      `No shot ${String(name)} (shots: ${doc.scene.shots.map((x) => x.name).join(", ")}).`,
    );
  return s;
}
const freeId = (taken: Set<string>, base: string) => {
  let id = base;
  for (let n = 2; taken.has(id); n++) id = `${base}-${n}`;
  return id;
};
/** Where a ref may point: a point, a mark, an actor, or (camera `at`) a set camera. */
function ref(v: unknown, what: string): Vec | string {
  if (typeof v === "string" && v.trim()) return v.trim();
  return roundVec(vec(v, what));
}
/** Insert or update the key at `t` with the given fields. */
function upsertKey(keys: KeyData[], t: number, patch: Partial<KeyData>): KeyData {
  let k = keys.find((x) => near(x.t, t));
  if (!k) {
    k = { t: round(t) };
    keys.push(k);
    keys.sort((a, b) => a.t - b.t);
  }
  for (const [key, value] of Object.entries(patch)) {
    if (value === undefined) continue;
    if (value === null) delete (k as unknown as Args)[key];
    else (k as unknown as Args)[key] = value;
  }
  return k;
}
function keyPatch(a: Args, camera: boolean): Partial<KeyData> {
  const p: Partial<KeyData> = {};
  if ("at" in a) p.at = a.at === null ? undefined : ref(a.at, "`at`");
  if (camera && "look" in a) p.look = ref(a.look, "`look`");
  if (camera && "lens" in a)
    p.lens = a.lens === null ? undefined : Math.min(Math.max(num(a.lens, "`lens`"), 8), 400);
  if (!camera && "face" in a)
    p.face =
      a.face === null
        ? undefined
        : typeof a.face === "number"
          ? round(a.face)
          : str(a.face, "`face`");
  if (!camera && "pose" in a) p.pose = a.pose === "sit" ? "sit" : "stand";
  if ("ease" in a)
    p.ease = ["linear", "smooth", "in", "out"].includes(String(a.ease))
      ? (a.ease as KeyData["ease"])
      : undefined;
  return p;
}

const SHAPE_FIELDS = ["at", "size", "radius", "height", "a", "b", "yaw", "tone"] as const;
function applyShape(s: ShapeData, a: Args) {
  for (const f of SHAPE_FIELDS) {
    if (!(f in a)) continue;
    const v = a[f];
    if (f === "at" || f === "size" || f === "a" || f === "b")
      (s as Args)[f] = roundVec(vec(v, `\`${f}\``));
    else if (f === "tone") s.tone = Math.min(Math.max(num(v, "`tone`"), 0), 1);
    else (s as Args)[f] = round(num(v, `\`${f}\``));
  }
}

export const ACTIONS: ActionInfo[] = [
  // --- the set -------------------------------------------------------------------------------
  {
    name: "shape.add",
    touches: "set",
    help: "Add a shape to the set. {kind: box|cylinder|sphere|capsule, id?, at?: [x,y,z], size?: [w,h,d] (box), radius?, height? (cylinder), a?, b? (capsule ends), yaw?, tone? (0-1)}. A box's `at` is its centre; a cylinder stands on `at`.",
    run: (doc, a) => {
      const kind = (
        ["box", "cylinder", "sphere", "capsule"].includes(String(a.kind)) ? a.kind : "box"
      ) as ShapeKind;
      const id = freeId(
        new Set(doc.set.shapes.map((x) => x.id ?? "")),
        typeof a.id === "string" && a.id ? a.id : kind,
      );
      const s: ShapeData = { id, type: kind, tone: 0.7 };
      if (kind === "box") Object.assign(s, { at: [0, 0.5, 0], size: [1, 1, 1], yaw: 0 });
      if (kind === "cylinder") Object.assign(s, { at: [0, 0, 0], radius: 0.3, height: 1 });
      if (kind === "sphere") Object.assign(s, { at: [0, 0.5, 0], radius: 0.5 });
      if (kind === "capsule") Object.assign(s, { a: [0, 0.3, 0], b: [0, 1.5, 0], radius: 0.3 });
      applyShape(s, a);
      doc.set.shapes.push(s);
      return `Added ${kind} ${id}.`;
    },
  },
  {
    name: "shape.update",
    touches: "set",
    help: "Change a shape. {id, at?, size?, radius?, height?, a?, b?, yaw?, tone?, rename?}.",
    run: (doc, a) => {
      const s = shape(doc, a.id);
      applyShape(s, a);
      if (typeof a.rename === "string" && a.rename.trim() && a.rename !== s.id)
        s.id = freeId(new Set(doc.set.shapes.map((x) => x.id ?? "")), a.rename.trim());
      return `Changed ${s.id}.`;
    },
  },
  {
    name: "shape.remove",
    touches: "set",
    help: "Remove a shape from the set. {id}.",
    run: (doc, a) => {
      const s = shape(doc, a.id);
      doc.set.shapes = doc.set.shapes.filter((x) => x !== s);
      return `Removed ${s.id}.`;
    },
  },
  {
    name: "shape.duplicate",
    touches: "set",
    help: "Copy a shape, moved by `offset` (default [0.6, 0, 0]). {id, offset?}.",
    run: (doc, a) => {
      const s = shape(doc, a.id);
      const off = "offset" in a ? vec(a.offset, "`offset`") : ([0.6, 0, 0] as Vec);
      const copy: ShapeData = JSON.parse(JSON.stringify(s));
      copy.id = freeId(new Set(doc.set.shapes.map((x) => x.id ?? "")), s.id ?? "shape");
      const shift = (p?: Vec) => (p ? roundVec([p[0] + off[0], p[1] + off[1], p[2] + off[2]]) : p);
      copy.at = shift(copy.at);
      copy.a = shift(copy.a);
      copy.b = shift(copy.b);
      doc.set.shapes.push(copy);
      return `Copied ${s.id} as ${copy.id}.`;
    },
  },
  {
    name: "mark.set",
    touches: "set",
    help: "Add or move a mark: a named spot on the floor actors and cameras can use. {name, at: [x,0,z]}.",
    run: (doc, a) => {
      const name = str(a.name, "The mark's name");
      doc.set.marks[name] = roundVec(vec(a.at, "`at`"));
      return `Mark ${name} at ${doc.set.marks[name]!.join(", ")}.`;
    },
  },
  {
    name: "mark.rename",
    touches: "set",
    help: "Rename a mark, and every key in this scene that uses it. {name, to}.",
    run: (doc, a) => {
      const from = str(a.name, "The mark");
      const to = str(a.to, "The new name");
      if (!doc.set.marks[from]) throw new ActionError(`No mark ${from}.`);
      doc.set.marks[to] = doc.set.marks[from]!;
      delete doc.set.marks[from];
      const swap = (k: KeyData) => {
        if (k.at === from) k.at = to;
        if (k.look === from) k.look = to;
        if (k.face === from) k.face = to;
      };
      doc.scene.actors.forEach((x) => x.keys.forEach(swap));
      doc.scene.shots.forEach((s) => s.camera.forEach(swap));
      return `Renamed mark ${from} to ${to}.`;
    },
  },
  {
    name: "mark.remove",
    touches: "set",
    help: "Remove a mark. {name}.",
    run: (doc, a) => {
      const name = str(a.name, "The mark");
      delete doc.set.marks[name];
      return `Removed mark ${name}.`;
    },
  },
  {
    name: "setcam.set",
    touches: "set",
    help: "Add or change a named camera set-up of the set, for shots to start from. {name, at: [x,y,z], look: point|mark|@actor, lens?: mm}.",
    run: (doc, a) => {
      const name = str(a.name, "The camera's name");
      const prev = doc.set.cameras[name];
      doc.set.cameras[name] = {
        at: "at" in a ? roundVec(vec(a.at, "`at`")) : (prev?.at ?? [0, 1.6, 5]),
        look: "look" in a ? ref(a.look, "`look`") : (prev?.look ?? [0, 1.2, 0]),
        lens: "lens" in a ? num(a.lens, "`lens`") : (prev?.lens ?? 35),
      };
      return `Set camera ${name}.`;
    },
  },
  {
    name: "setcam.remove",
    touches: "set",
    help: "Remove a set camera. {name}.",
    run: (doc, a) => {
      const name = str(a.name, "The camera");
      delete doc.set.cameras[name];
      return `Removed set camera ${name}.`;
    },
  },
  {
    name: "set.update",
    touches: "set",
    help: "Change the set's name or notes. {name?, notes?}.",
    run: (doc, a) => {
      if (typeof a.name === "string") doc.set.name = a.name;
      if (typeof a.notes === "string") doc.set.notes = a.notes;
      return "Changed the set.";
    },
  },
  // --- the cast ------------------------------------------------------------------------------
  {
    name: "cast.set",
    touches: "cast",
    help: 'Set a character\'s figure for every scene. {id: "@ren", height?: metres, build?: width scale, tone?: grey 0-1}.',
    run: (doc, a) => {
      const id = mention(a.id);
      const m = (doc.cast[id] ??= {});
      if ("height" in a) m.height = Math.min(Math.max(num(a.height, "`height`"), 0.3), 3);
      if ("build" in a) m.build = Math.min(Math.max(num(a.build, "`build`"), 0.4), 2.5);
      if ("tone" in a) m.tone = Math.min(Math.max(num(a.tone, "`tone`"), 0), 1);
      return `${id}'s figure set.`;
    },
  },
  // --- the scene's people --------------------------------------------------------------------
  {
    name: "actor.add",
    touches: "scene",
    help: 'Put a character in the scene, standing at `at` (a point or mark) from the start. {id: "@ren", at, face?}.',
    run: (doc, a) => {
      const id = mention(a.id);
      if (doc.scene.actors.some((x) => x.id === id))
        throw new ActionError(`${id} is already in the scene.`);
      const key: KeyData = { t: 0, at: ref(a.at ?? [0, 0, 0], "`at`") };
      if (a.face !== undefined) key.face = typeof a.face === "number" ? a.face : String(a.face);
      doc.scene.actors.push({ id, keys: [key] });
      return `${id} added.`;
    },
  },
  {
    name: "actor.remove",
    touches: "scene",
    help: "Take a character out of the scene. {id}.",
    run: (doc, a) => {
      const x = actor(doc, a.id);
      doc.scene.actors = doc.scene.actors.filter((y) => y !== x);
      return `${x.id} removed.`;
    },
  },
  {
    name: "key.set",
    touches: "scene",
    help: 'Key a character at time t (adds the key, or changes the one there). {actor, t, at?: point|mark|@other, face?: degrees|"path"|@other|mark, pose?: stand|sit, ease?: linear|smooth|in|out}. null clears a field.',
    run: (doc, a) => {
      const x = actor(doc, a.actor);
      const t = num(a.t, "`t`");
      upsertKey(x.keys, t, keyPatch(a, false));
      return `${x.id} keyed at ${round(t)}s.`;
    },
  },
  {
    name: "key.move",
    touches: "scene",
    help: "Move a character's key to another time. {actor, t, to}.",
    run: (doc, a) => {
      const x = actor(doc, a.actor);
      const k = x.keys.find((y) => near(y.t, num(a.t, "`t`")));
      if (!k) throw new ActionError(`${x.id} has no key at ${String(a.t)}s.`);
      k.t = round(Math.max(0, num(a.to, "`to`")));
      x.keys.sort((p, q) => p.t - q.t);
      return `${x.id}'s key moved to ${k.t}s.`;
    },
  },
  {
    name: "key.remove",
    touches: "scene",
    help: "Remove a character's key. {actor, t}.",
    run: (doc, a) => {
      const x = actor(doc, a.actor);
      const t = num(a.t, "`t`");
      if (x.keys.length <= 1)
        throw new ActionError(`${x.id} needs at least one key — remove the actor instead.`);
      x.keys = x.keys.filter((k) => !near(k.t, t));
      return `${x.id}'s key at ${round(t)}s removed.`;
    },
  },
  // --- shots ---------------------------------------------------------------------------------
  {
    name: "shot.add",
    touches: "scene",
    help: "Add a shot. {name?, start?, end?, from?: a set camera's name, at?: [x,y,z], look?: point|mark|@actor, lens?}. Starts where the last shot ends by default.",
    run: (doc, a) => {
      const last = doc.scene.shots.at(-1);
      const start = "start" in a ? num(a.start, "`start`") : (last?.end ?? 0);
      const end = "end" in a ? num(a.end, "`end`") : start + 3;
      const name = freeId(
        new Set(doc.scene.shots.map((s) => s.name)),
        typeof a.name === "string" && a.name ? a.name : `${doc.scene.shots.length + 1}A`,
      );
      const key: KeyData = { t: round(start) };
      if (typeof a.from === "string") key.at = a.from;
      else key.at = "at" in a ? ref(a.at, "`at`") : (last?.camera[0]?.at ?? [0, 1.6, 5]);
      if ("look" in a) key.look = ref(a.look, "`look`");
      else if (typeof a.from !== "string") key.look = last?.camera[0]?.look ?? [0, 1.2, 0];
      if ("lens" in a) key.lens = num(a.lens, "`lens`");
      doc.scene.shots.push({
        name,
        start: round(start),
        end: round(Math.max(end, start + 0.1)),
        camera: [key],
      });
      doc.scene.shots.sort((p, q) => p.start - q.start);
      return `Shot ${name} added (${round(start)}–${round(end)}s).`;
    },
  },
  {
    name: "shot.update",
    touches: "scene",
    help: "Change a shot's span or name. {name, start?, end?, rename?}. Its camera keys move with its start.",
    run: (doc, a) => {
      const s = shot(doc, a.name);
      if ("start" in a) {
        const d = num(a.start, "`start`") - s.start;
        s.start = round(s.start + d);
        s.camera.forEach((k) => (k.t = round(k.t + d)));
        if (!("end" in a)) s.end = round(s.end + d);
      }
      if ("end" in a) s.end = round(Math.max(num(a.end, "`end`"), s.start + 0.1));
      if (typeof a.rename === "string" && a.rename.trim())
        s.name = freeId(
          new Set(doc.scene.shots.filter((x) => x !== s).map((x) => x.name)),
          a.rename.trim(),
        );
      doc.scene.shots.sort((p, q) => p.start - q.start);
      return `Shot ${s.name}: ${s.start}–${s.end}s.`;
    },
  },
  {
    name: "shot.remove",
    touches: "scene",
    help: "Remove a shot. {name}.",
    run: (doc, a) => {
      const s = shot(doc, a.name);
      if (doc.scene.shots.length <= 1) throw new ActionError("A scene needs at least one shot.");
      doc.scene.shots = doc.scene.shots.filter((x) => x !== s);
      return `Shot ${s.name} removed.`;
    },
  },
  {
    name: "camkey.set",
    touches: "scene",
    help: "Key a shot's camera at time t (scene seconds; adds or changes). {shot, t, at?: [x,y,z]|mark|set camera, look?: point|mark|@actor, lens?: mm, ease?}. null clears a field.",
    run: (doc, a) => {
      const s = shot(doc, a.shot);
      const t = num(a.t, "`t`");
      upsertKey(s.camera, t, keyPatch(a, true));
      return `Shot ${s.name}'s camera keyed at ${round(t)}s.`;
    },
  },
  {
    name: "camkey.move",
    touches: "scene",
    help: "Move a camera key to another time. {shot, t, to}.",
    run: (doc, a) => {
      const s = shot(doc, a.shot);
      const k = s.camera.find((y) => near(y.t, num(a.t, "`t`")));
      if (!k) throw new ActionError(`Shot ${s.name} has no camera key at ${String(a.t)}s.`);
      k.t = round(num(a.to, "`to`"));
      s.camera.sort((p, q) => p.t - q.t);
      return `Camera key moved to ${k.t}s.`;
    },
  },
  {
    name: "camkey.remove",
    touches: "scene",
    help: "Remove a camera key. {shot, t}.",
    run: (doc, a) => {
      const s = shot(doc, a.shot);
      if (s.camera.length <= 1)
        throw new ActionError(`Shot ${s.name} needs at least one camera key.`);
      s.camera = s.camera.filter((k) => !near(k.t, num(a.t, "`t`")));
      return "Camera key removed.";
    },
  },
  {
    name: "scene.update",
    touches: "scene",
    help: "Change the scene's name, frame rate, notes or set. {name?, fps?, notes?, set?}.",
    run: (doc, a) => {
      if (typeof a.name === "string") doc.scene.name = a.name;
      if (typeof a.notes === "string") doc.scene.notes = a.notes;
      if (typeof a.fps === "number") doc.scene.fps = Math.min(Math.max(a.fps, 1), 120);
      if (typeof a.set === "string" && a.set) doc.scene.set = a.set;
      return "Changed the scene.";
    },
  },
];

const BY_NAME = new Map(ACTIONS.map((x) => [x.name, x]));
export const actionInfo = (name: string) => BY_NAME.get(name);

/** Run one action on `doc`. Throws ActionError (with a message worth showing) when it can't. */
export function act(
  doc: Doc,
  name: string,
  args: Args = {},
): { message: string; touches: ActionInfo["touches"] } {
  const info = BY_NAME.get(name);
  if (!info)
    throw new ActionError(`No action ${name}. Actions: ${ACTIONS.map((x) => x.name).join(", ")}.`);
  return { message: info.run(doc, args), touches: info.touches };
}

export { emptySet };
