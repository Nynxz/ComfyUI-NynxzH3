// Every change to a grey box scene, its set or the cast is an action: a name and its arguments.
// The editor's buttons, drags and fields call them; undo records them; agents get the same list
// as a tool (lib/greyboxAgent.ts). Each returns a line saying what it did.
import {
  emptySet,
  isVec,
  type CastData,
  type KeyData,
  type Props,
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
  /** The project's props, by name (each its own file). */
  props: Props;
  /** The prop being edited: shape actions then change its shapes instead of the set's. */
  focus?: string;
}
export type Args = Record<string, unknown>;
export interface ActionInfo {
  name: string;
  /** What it does and its arguments, for whoever calls it (an agent reads exactly this). */
  help: string;
  /** Which file it changes. */
  touches: "scene" | "set" | "cast" | "props";
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

/** The shapes being edited: the open prop's, else the set's. */
export function shapesOf(doc: Doc): ShapeData[] {
  return doc.focus && doc.props[doc.focus] ? doc.props[doc.focus]!.shapes : doc.set.shapes;
}
function setShapes(doc: Doc, shapes: ShapeData[]) {
  if (doc.focus && doc.props[doc.focus]) doc.props[doc.focus]!.shapes = shapes;
  else doc.set.shapes = shapes;
}
const where = (doc: Doc) => (doc.focus ? `the prop ${doc.focus}` : "the set");
function shape(doc: Doc, id: unknown): ShapeData {
  const s = shapesOf(doc).find((x) => x.id === id);
  if (!s)
    throw new ActionError(
      `No shape ${String(id)} in ${where(doc)} (shapes: ${shapesOf(doc)
        .map((x) => x.id)
        .join(", ")}).`,
    );
  return s;
}
const PROP_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$/;
function propName(v: unknown): string {
  const name = str(v, "The prop's name");
  if (!PROP_NAME.test(name))
    throw new ActionError(`${name} can't be a prop's name: use letters, numbers, - and _.`);
  return name;
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
/** Editing a key a script's move made (or adding one inside a move's span) turns that move's keys
 *  into ordinary ones: otherwise the script would write the move back and drop the edit. */
function unbake(keys: KeyData[], t: number) {
  const runs = new Set<number>();
  for (const k of keys) {
    if (k.run !== undefined && near(k.t, t)) runs.add(k.run);
    if (k.move && k.run !== undefined && k.move.from - 1e-6 <= t && t <= k.move.to + 1e-6)
      runs.add(k.run);
  }
  for (const k of keys)
    if (k.run !== undefined && runs.has(k.run)) {
      delete k.run;
      delete k.move;
    }
}

function upsertKey(keys: KeyData[], t: number, patch: Partial<KeyData>): KeyData {
  unbake(keys, t);
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
  if ("at" in a) {
    p.at = a.at === null ? undefined : ref(a.at, "`at`");
    // Placed somewhere new by hand: no longer whatever surface a script stood it on (null
    // clears a field; undefined would leave it).
    if (!camera) (p as Args).on = null;
  }
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
  if (!camera && "pose" in a) p.pose = a.pose === "sit" || a.pose === "crouch" ? a.pose : "stand";
  if ("ease" in a)
    p.ease = ["linear", "smooth", "in", "out"].includes(String(a.ease))
      ? (a.ease as KeyData["ease"])
      : undefined;
  return p;
}

const SHAPE_FIELDS = [
  "at",
  "size",
  "radius",
  "height",
  "a",
  "b",
  "yaw",
  "tilt",
  "tone",
  "scale",
] as const;
function applyShape(s: ShapeData, a: Args) {
  for (const f of SHAPE_FIELDS) {
    if (!(f in a)) continue;
    const v = a[f];
    if (f === "at" || f === "size" || f === "a" || f === "b")
      (s as Args)[f] = roundVec(vec(v, `\`${f}\``));
    else if (f === "tone") s.tone = Math.min(Math.max(num(v, "`tone`"), 0), 1);
    else if (f === "scale") s.scale = round(Math.min(Math.max(num(v, "`scale`"), 0.01), 100));
    else if (f === "tilt") s.tilt = round(Math.min(Math.max(num(v, "`tilt`"), -89), 89));
    else (s as Args)[f] = round(num(v, `\`${f}\``));
  }
}
/** Roughly where a shape sits on the floor, for finding the middle of several. */
function footprint(s: ShapeData): [number, number] {
  const p =
    s.at ?? (s.a && s.b ? ([(s.a[0] + s.b[0]) / 2, 0, (s.a[2] + s.b[2]) / 2] as Vec) : null);
  return p ? [p[0], p[2]] : [0, 0];
}

export const ACTIONS: ActionInfo[] = [
  // --- the set -------------------------------------------------------------------------------
  {
    name: "shape.add",
    touches: "set",
    help: "Add a shape to the set (or to the prop being edited). {kind: box|cylinder|sphere|capsule|prop, id?, at?: [x,y,z], size?: [w,h,d] (box), radius?, height? (cylinder), a?, b? (capsule or lying cylinder ends), yaw?, tilt? (box: degrees it leans forward, front edge down), tone? (0-1), prop? and scale? (kind prop)}. A box's `at` is its centre; a cylinder stands on `at`, or lies from `a` to `b` when they're given; a prop is placed with its origin at `at`.",
    run: (doc, a) => {
      const kind = (
        ["box", "cylinder", "sphere", "capsule", "prop"].includes(String(a.kind)) ? a.kind : "box"
      ) as ShapeKind;
      if (kind === "prop") {
        const name = str(a.prop, "Which prop (`prop`)");
        if (!doc.props[name])
          throw new ActionError(
            `No prop ${name} (props: ${Object.keys(doc.props).join(", ") || "none yet"}).`,
          );
        if (doc.focus === name) throw new ActionError(`A prop can't be placed inside itself.`);
      }
      const id = freeId(
        new Set(shapesOf(doc).map((x) => x.id ?? "")),
        typeof a.id === "string" && a.id ? a.id : kind === "prop" ? String(a.prop) : kind,
      );
      const s: ShapeData = { id, type: kind, tone: 0.7 };
      if (kind === "prop") {
        Object.assign(s, { prop: String(a.prop), at: [0, 0, 0], yaw: 0, scale: 1 });
        delete s.tone;
      }
      if (kind === "box") Object.assign(s, { at: [0, 0.5, 0], size: [1, 1, 1], yaw: 0 });
      if (kind === "cylinder") Object.assign(s, { at: [0, 0, 0], radius: 0.3, height: 1 });
      if (kind === "sphere") Object.assign(s, { at: [0, 0.5, 0], radius: 0.5 });
      if (kind === "capsule") Object.assign(s, { a: [0, 0.3, 0], b: [0, 1.5, 0], radius: 0.3 });
      if (kind === "cylinder" && ("a" in a || "b" in a)) {
        Object.assign(s, { a: [0, 0.3, -0.5], b: [0, 0.3, 0.5] });
        delete s.at;
        delete s.height;
      }
      applyShape(s, a);
      shapesOf(doc).push(s);
      return `Added ${kind} ${id}.`;
    },
  },
  {
    name: "shape.update",
    touches: "set",
    help: "Change a shape. {id, at?, size?, radius?, height?, a?, b?, yaw?, tilt? (box: degrees it leans forward, front edge down — a roof slope or ramp), tone?, rename?}.",
    run: (doc, a) => {
      const s = shape(doc, a.id);
      applyShape(s, a);
      if (typeof a.rename === "string" && a.rename.trim() && a.rename !== s.id)
        s.id = freeId(new Set(shapesOf(doc).map((x) => x.id ?? "")), a.rename.trim());
      return `Changed ${s.id}.`;
    },
  },
  {
    name: "shape.remove",
    touches: "set",
    help: "Remove a shape from the set (or the prop being edited). {id}.",
    run: (doc, a) => {
      const s = shape(doc, a.id);
      setShapes(
        doc,
        shapesOf(doc).filter((x) => x !== s),
      );
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
      copy.id = freeId(new Set(shapesOf(doc).map((x) => x.id ?? "")), s.id ?? "shape");
      const shift = (p?: Vec) => (p ? roundVec([p[0] + off[0], p[1] + off[1], p[2] + off[2]]) : p);
      copy.at = shift(copy.at);
      copy.a = shift(copy.a);
      copy.b = shift(copy.b);
      shapesOf(doc).push(copy);
      return `Copied ${s.id} as ${copy.id}.`;
    },
  },
  {
    name: "prop.new",
    touches: "props",
    help: "Start a new prop (a reusable object built from shapes, placed in sets with shape.add {kind: prop}) with one box, and open it for editing. Its origin is on the floor under the middle; +z is its front. {name}.",
    run: (doc, a) => {
      const name = propName(a.name);
      if (doc.props[name]) throw new ActionError(`There's already a prop called ${name}.`);
      doc.props[name] = {
        name,
        shapes: [{ id: "body", type: "box", at: [0, 0.5, 0], size: [1, 1, 1], yaw: 0, tone: 0.7 }],
      };
      doc.focus = name;
      return `Started the prop ${name}: shape actions now build it (prop.done to go back to the set).`;
    },
  },
  {
    name: "prop.make",
    touches: "props",
    help: "Make a prop from shapes already in the set: they move into the prop, and the set gets the prop placed where they were. {name, ids: [shape ids]}.",
    run: (doc, a) => {
      if (doc.focus) throw new ActionError("Finish editing the prop first (prop.done).");
      const name = propName(a.name);
      if (doc.props[name]) throw new ActionError(`There's already a prop called ${name}.`);
      const ids = Array.isArray(a.ids) ? a.ids.map(String) : [];
      const picked = ids.map((id) => shape(doc, id));
      if (!picked.length) throw new ActionError("Which shapes (`ids`)?");
      const feet = picked.map(footprint);
      const xs = feet.map((f) => f[0]);
      const zs = feet.map((f) => f[1]);
      const origin: Vec = roundVec([
        (Math.min(...xs) + Math.max(...xs)) / 2,
        0,
        (Math.min(...zs) + Math.max(...zs)) / 2,
      ]);
      const back = (p?: Vec) => (p ? roundVec([p[0] - origin[0], p[1], p[2] - origin[2]]) : p);
      doc.props[name] = {
        name,
        shapes: picked.map((s) => {
          const local: ShapeData = JSON.parse(JSON.stringify(s));
          local.at = back(local.at);
          local.a = back(local.a);
          local.b = back(local.b);
          return local;
        }),
      };
      doc.set.shapes = doc.set.shapes.filter((x) => !picked.includes(x));
      const id = freeId(new Set(doc.set.shapes.map((x) => x.id ?? "")), name);
      doc.set.shapes.push({ id, type: "prop", prop: name, at: origin, yaw: 0, scale: 1 });
      return `Made the prop ${name} from ${picked.length} shape${picked.length === 1 ? "" : "s"}, placed as ${id}.`;
    },
  },
  {
    name: "prop.edit",
    touches: "props",
    help: "Open a prop for editing: shape actions then change its shapes, in its own frame. {name}.",
    run: (doc, a) => {
      const name = str(a.name, "Which prop");
      if (!doc.props[name])
        throw new ActionError(
          `No prop ${name} (props: ${Object.keys(doc.props).join(", ") || "none yet"}).`,
        );
      doc.focus = name;
      return `Editing the prop ${name}.`;
    },
  },
  {
    name: "prop.update",
    touches: "props",
    help: "Change the open prop's notes (what it is, which way it faces). {notes}.",
    run: (doc, a) => {
      const prop = doc.focus ? doc.props[doc.focus] : undefined;
      if (!prop) throw new ActionError("Open a prop first (prop.edit).");
      prop.notes = typeof a.notes === "string" ? a.notes.trim() : "";
      return `Changed the notes of ${doc.focus}.`;
    },
  },
  {
    name: "prop.done",
    touches: "props",
    help: "Stop editing a prop and go back to the set. {}.",
    run: (doc) => {
      const was = doc.focus;
      doc.focus = undefined;
      return was ? `Back to the set (the prop ${was} is saved).` : "Already on the set.";
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
    help: 'Set a character\'s figure for every scene. {id: "@ren", height?: metres, build?: width scale, tone?: grey 0-1, prop?: a prop\'s name to be drawn as instead (a vehicle that moves with keys; "" for a person again)}.',
    run: (doc, a) => {
      const id = mention(a.id);
      const m = (doc.cast[id] ??= {});
      if ("height" in a) m.height = Math.min(Math.max(num(a.height, "`height`"), 0.3), 3);
      if ("build" in a) m.build = Math.min(Math.max(num(a.build, "`build`"), 0.4), 2.5);
      if ("tone" in a) m.tone = Math.min(Math.max(num(a.tone, "`tone`"), 0), 1);
      if ("prop" in a) {
        const prop = typeof a.prop === "string" ? a.prop.trim() : "";
        if (prop && !doc.props[prop])
          throw new ActionError(
            `No prop ${prop} (props: ${Object.keys(doc.props).join(", ") || "none yet"}).`,
          );
        if (prop) m.prop = prop;
        else delete m.prop;
      }
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
      unbake(x.keys, num(a.t, "`t`"));
      unbake(x.keys, num(a.to, "`to`"));
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
      unbake(x.keys, t);
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
      unbake(s.camera, num(a.t, "`t`"));
      unbake(s.camera, num(a.to, "`to`"));
      const k = s.camera.find((y) => near(y.t, num(a.t, "`t`")));
      if (!k) throw new ActionError(`Shot ${s.name} has no camera key at ${String(a.t)}s.`);
      k.t = round(num(a.to, "`to`"));
      s.camera.sort((p, q) => p.t - q.t);
      return `Camera key moved to ${k.t}s.`;
    },
  },
  {
    name: "scene.replace",
    touches: "scene",
    help: "Replace the whole scene with new scene JSON — what a Grey Box script reads into (the /nynxz/greybox/script/import route). {scene}.",
    run: (doc, a) => {
      const sc = a.scene as SceneData | undefined;
      if (!sc || typeof sc !== "object" || !Array.isArray(sc.shots) || !sc.shots.length)
        throw new ActionError("`scene` should be a scene with at least one shot.");
      doc.scene = JSON.parse(JSON.stringify(sc)) as SceneData;
      return `Replaced the scene${sc.name ? ` with ${sc.name}` : ""}.`;
    },
  },
  {
    name: "set.replace",
    touches: "set",
    help: "Replace the whole set with new set JSON (shapes, marks, cameras), as a set script reads into. {set}.",
    run: (doc, a) => {
      const st = a.set as SetData | undefined;
      if (!st || typeof st !== "object" || !Array.isArray(st.shapes))
        throw new ActionError("`set` should be a set with shapes.");
      doc.set = JSON.parse(JSON.stringify(st)) as SetData;
      return "Replaced the set.";
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
      unbake(s.camera, num(a.t, "`t`"));
      s.camera = s.camera.filter((k) => !near(k.t, num(a.t, "`t`")));
      return "Camera key removed.";
    },
  },
  {
    name: "scene.update",
    touches: "scene",
    help: "Change the scene's name, frame rate, drawing (on: 1 ones, 2 twos, 3 threes), notes or set. {name?, fps?, on?, notes?, set?}.",
    run: (doc, a) => {
      if (typeof a.name === "string") doc.scene.name = a.name;
      if (typeof a.notes === "string") doc.scene.notes = a.notes;
      if (typeof a.fps === "number") doc.scene.fps = Math.min(Math.max(a.fps, 1), 120);
      if (typeof a.on === "number") doc.scene.on = Math.min(Math.max(Math.round(a.on), 1), 4);
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
