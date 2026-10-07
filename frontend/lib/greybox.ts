// Grey box scenes in the editor: their JSON (the same files nodes/greybox reads — docs/GREYBOX.md)
// and where everything is at a moment, worked out by the same rules as nodes/greybox/core/scene.py
// so the editor moves things exactly as the render will.

export type Vec = [number, number, number];
export type ShapeKind = "box" | "cylinder" | "sphere" | "capsule";

export interface ShapeData {
  id?: string;
  type?: ShapeKind;
  at?: Vec;
  size?: Vec;
  radius?: number;
  height?: number;
  a?: Vec;
  b?: Vec;
  yaw?: number;
  tone?: number;
}
export interface SetCam {
  at: Vec;
  look: Ref;
  lens?: number;
}
export interface SetData {
  name?: string;
  notes?: string;
  shapes: ShapeData[];
  marks: Record<string, Vec>;
  cameras: Record<string, SetCam>;
}
export interface MemberData {
  height?: number;
  build?: number;
  tone?: number;
}
export type CastData = Record<string, MemberData>;

/** A point, a mark's name, an actor ("@ren"), or (for a camera's `at`) a set camera's name. */
export type Ref = Vec | string;
export type Ease = "linear" | "smooth" | "in" | "out";
export interface KeyData {
  t: number;
  at?: Ref;
  look?: Ref;
  face?: number | string;
  pose?: "stand" | "sit";
  lens?: number;
  ease?: Ease;
}
export interface ActorData {
  id: string;
  keys: KeyData[];
}
export interface ShotData {
  name: string;
  start: number;
  end: number;
  camera: KeyData[];
}
export interface SceneData {
  name?: string;
  set?: string;
  fps?: number;
  notes?: string;
  actors: ActorData[];
  shots: ShotData[];
  shapes?: ShapeData[];
}

export const DEFAULT_HEIGHT = 1.7;
export const DEFAULT_LENS = 35;
const LOOK_DROP = 0.12;

export interface Member {
  height: number;
  build: number;
  tone: number;
}
export const member = (cast: CastData, id: string): Member => {
  const m = cast[id] ?? cast[id.replace(/^@/, "")] ?? {};
  return {
    height: clamp(m.height ?? DEFAULT_HEIGHT, 0.3, 3),
    build: clamp(m.build ?? 1, 0.4, 2.5),
    tone: clamp(m.tone ?? 0.88, 0, 1),
  };
};

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);
const isVec = (v: unknown): v is Vec =>
  Array.isArray(v) && v.length === 3 && v.every((x) => typeof x === "number");

export function emptySet(name = "New set"): SetData {
  return {
    name,
    shapes: [{ id: "floor", type: "box", at: [0, -0.05, 0], size: [8, 0.1, 8], tone: 0.42 }],
    marks: {},
    cameras: {},
  };
}
export function emptyScene(set: string): SceneData {
  return {
    name: "New scene",
    set,
    fps: 24,
    actors: [],
    shots: [
      {
        name: "1A",
        start: 0,
        end: 3,
        camera: [{ t: 0, at: [0, 1.6, 5], look: [0, 1.2, 0], lens: 35 }],
      },
    ],
  };
}
export const toSet = (raw: unknown): SetData => {
  const o = (raw && typeof raw === "object" ? raw : {}) as Partial<SetData>;
  return {
    ...o,
    shapes: Array.isArray(o.shapes) ? o.shapes : [],
    marks: o.marks && typeof o.marks === "object" ? o.marks : {},
    cameras: o.cameras && typeof o.cameras === "object" ? o.cameras : {},
  };
};
export const toScene = (raw: unknown): SceneData => {
  const o = (raw && typeof raw === "object" ? raw : {}) as Partial<SceneData>;
  return {
    ...o,
    actors: Array.isArray(o.actors) ? o.actors.filter((a) => a && Array.isArray(a.keys)) : [],
    shots: Array.isArray(o.shots) ? o.shots.filter((s) => s && Array.isArray(s.camera)) : [],
  };
};

// --- motion ----------------------------------------------------------------------------------------

function ease(u: number, kind?: string): number {
  if (kind === "smooth") return u * u * (3 - 2 * u);
  if (kind === "in") return u * u;
  if (kind === "out") return 1 - (1 - u) * (1 - u);
  return u;
}
function catmull(p0: Vec, p1: Vec, p2: Vec, p3: Vec, u: number): Vec {
  const u2 = u * u;
  const u3 = u2 * u;
  return [0, 1, 2].map(
    (i) =>
      0.5 *
      (2 * p1[i]! +
        (-p0[i]! + p2[i]!) * u +
        (2 * p0[i]! - 5 * p1[i]! + 4 * p2[i]! - p3[i]!) * u2 +
        (-p0[i]! + 3 * p1[i]! - 3 * p2[i]! + p3[i]!) * u3),
  ) as Vec;
}
/** A smooth path through `points` at `times`, each segment eased by its starting key. */
export function pathAt(
  times: number[],
  points: Vec[],
  eases: (string | undefined)[],
  t: number,
): Vec {
  const n = times.length;
  if (t <= times[0]!) return points[0]!;
  if (t >= times[n - 1]!) return points[n - 1]!;
  let i = 0;
  for (let j = 0; j < n - 1; j++) if (times[j]! <= t) i = j;
  const span = Math.max(times[i + 1]! - times[i]!, 1e-9);
  const u = ease((t - times[i]!) / span, eases[i]);
  return catmull(
    points[Math.max(i - 1, 0)]!,
    points[i]!,
    points[i + 1]!,
    points[Math.min(i + 2, n - 1)]!,
    u,
  );
}
const angleLerp = (a: number, b: number, u: number) =>
  a + (((((b - a + 180) % 360) + 360) % 360) - 180) * u;

export interface ActorState {
  id: string;
  at: Vec;
  yaw: number;
  pose: "stand" | "sit";
  member: Member;
}
export const eyeOf = (s: ActorState): Vec => {
  const h = s.member.height * (s.pose === "sit" ? 0.72 : 1);
  return [s.at[0], s.at[1] + h - LOOK_DROP, s.at[2]];
};

export interface Camera {
  at: Vec;
  look: Vec;
  lens: number;
}
/** Vertical field of view in degrees for a 35 mm-equivalent lens. */
export const fovOf = (lens: number) => (2 * Math.atan(12 / lens) * 180) / Math.PI;

/** Everything about a scene that moves: built once per edit, asked many times per frame. */
export class Evaluator {
  constructor(
    readonly scene: SceneData,
    readonly set: SetData,
    readonly cast: CastData,
  ) {}

  private sorted(keys: KeyData[]) {
    return [...keys].sort((a, b) => a.t - b.t);
  }

  point(ref: Ref | undefined, t: number, depth = 0): Vec {
    if (isVec(ref)) return ref;
    if (typeof ref === "string") {
      const name = ref.replace(/^mark:/, "");
      if (this.set.marks[name]) return this.set.marks[name]!;
      if (ref.startsWith("@")) return this.actor(ref, t, depth + 1)?.at ?? [0, 0, 0];
    }
    return [0, 0, 0];
  }
  target(ref: Ref | undefined, t: number): Vec {
    if (typeof ref === "string" && ref.startsWith("@")) {
      const a = this.actor(ref, t);
      return a ? eyeOf(a) : [0, 1.2, 0];
    }
    const p = this.point(ref, t);
    return isVec(ref) ? p : [p[0], 1.2, p[2]];
  }

  actor(id: string, t: number, depth = 0): ActorState | null {
    const a = this.scene.actors.find((x) => x.id === id);
    if (!a || !a.keys.length || depth > 4) return null;
    const keys = this.sorted(a.keys);
    const times = keys.map((k) => k.t);
    const points = keys.map((k) => this.point(k.at, k.t, depth));
    const eases = keys.map((k) => k.ease);
    const at = pathAt(times, points, eases, t);
    const before = keys.filter((k) => k.t <= t);
    const prev = before.length ? before : keys.slice(0, 1);
    const pose = [...prev].reverse().find((k) => k.pose)?.pose ?? "stand";
    return {
      id,
      at,
      yaw: this.yaw(keys, times, points, eases, t, depth),
      pose,
      member: member(this.cast, id),
    };
  }

  private yaw(
    keys: KeyData[],
    times: number[],
    points: Vec[],
    eases: (string | undefined)[],
    t: number,
    depth: number,
  ): number {
    const before = keys.filter((k) => k.t <= t);
    let face = [...before].reverse().find((k) => k.face !== undefined)?.face;
    if (face === undefined) face = keys.find((k) => k.face !== undefined)?.face ?? "path";
    if (typeof face === "number") {
      const after = keys.filter((k) => k.t > t && typeof k.face === "number");
      const last = [...(before.length ? before : keys.slice(0, 1))]
        .reverse()
        .find((k) => k.face !== undefined);
      if (after.length && last && typeof last.face === "number") {
        const next = after[0]!;
        const u = clamp((t - last.t) / Math.max(next.t - last.t, 1e-9), 0, 1);
        return angleLerp(last.face, next.face as number, u);
      }
      return face;
    }
    const here = pathAt(times, points, eases, t);
    if (face === "path") {
      for (const dt of [0.05, -0.05]) {
        const there = pathAt(times, points, eases, t + dt);
        const s = Math.sign(dt);
        const dx = (there[0] - here[0]) * s;
        const dz = (there[2] - here[2]) * s;
        if (dx * dx + dz * dz > 1e-8) return (Math.atan2(dx, dz) * 180) / Math.PI;
      }
      return 0;
    }
    const other = face.startsWith("@")
      ? (this.actor(face, t, depth + 1)?.at ?? here)
      : this.point(face, t);
    return (Math.atan2(other[0] - here[0], other[2] - here[2]) * 180) / Math.PI;
  }

  actors(t: number): ActorState[] {
    return this.scene.actors.flatMap((a) => this.actor(a.id, t) ?? []);
  }

  camera(shot: ShotData, t: number): Camera {
    const keys = this.sorted(shot.camera);
    if (!keys.length) return { at: [0, 1.6, 5], look: [0, 1.2, 0], lens: DEFAULT_LENS };
    const times = keys.map((k) => k.t);
    const eases = keys.map((k) => k.ease ?? "smooth");
    const spots = keys.map((k) => this.cameraKey(k, t));
    const at = pathAt(
      times,
      spots.map((s) => s.at),
      eases,
      t,
    );
    const look = pathAt(
      times,
      spots.map((s) => s.look),
      eases,
      t,
    );
    let lens: number;
    if (t <= times[0]!) lens = spots[0]!.lens;
    else if (t >= times[times.length - 1]!) lens = spots[spots.length - 1]!.lens;
    else {
      let i = 0;
      for (let j = 0; j < times.length - 1; j++) if (times[j]! <= t) i = j;
      const u = ease((t - times[i]!) / Math.max(times[i + 1]! - times[i]!, 1e-9), eases[i]);
      lens = spots[i]!.lens + (spots[i + 1]!.lens - spots[i]!.lens) * u;
    }
    return { at, look, lens };
  }

  cameraKey(k: KeyData, t: number): Camera {
    const base = typeof k.at === "string" ? this.set.cameras[k.at] : undefined;
    if (base) {
      return {
        at: base.at,
        look: this.target(k.look ?? base.look, t),
        lens: k.lens ?? base.lens ?? DEFAULT_LENS,
      };
    }
    let at = this.point(k.at, t);
    if (!isVec(k.at)) at = [at[0], 1.6, at[2]];
    return { at, look: this.target(k.look ?? [0, 1.2, 0], t), lens: k.lens ?? DEFAULT_LENS };
  }

  /** The scene's length: its last shot's end or last key, whichever is later. */
  get length(): number {
    const ends = [
      ...this.scene.shots.map((s) => s.end),
      ...this.scene.actors.flatMap((a) => a.keys.map((k) => k.t)),
    ];
    return Math.max(1, ...ends);
  }

  shotAt(t: number): ShotData | null {
    return (
      this.scene.shots.find((s) => t >= s.start && t < s.end) ?? this.scene.shots.at(-1) ?? null
    );
  }
}

/** An actor as the renderer draws it: body, head and the small block that shows which way it faces. */
export function figure(s: ActorState): (ShapeData & { owner: string })[] {
  const m = s.member;
  const k = m.height / DEFAULT_HEIGHT;
  const h = m.height * (s.pose === "sit" ? 0.72 : 1);
  const r = 0.17 * m.build * k;
  const [x, y, z] = s.at;
  const yaw = (s.yaw * Math.PI) / 180;
  const fx = Math.sin(yaw);
  const fz = Math.cos(yaw);
  const headR = 0.115 * k;
  const headY = y + h - headR;
  const out: (ShapeData & { owner: string })[] = [
    {
      type: "capsule",
      a: [x, y + r, z],
      b: [x, y + h - 2 * headR - r * 0.6, z],
      radius: r,
      tone: m.tone,
      owner: s.id,
    },
    { type: "sphere", at: [x, headY, z], radius: headR, tone: m.tone, owner: s.id },
    {
      type: "box",
      at: [x + fx * headR * 0.95, headY - headR * 0.15, z + fz * headR * 0.95],
      size: [headR * 0.7, headR * 0.45, headR * 0.5],
      yaw: s.yaw,
      tone: Math.min(1, m.tone + 0.1),
      owner: s.id,
    },
  ];
  if (s.pose === "sit")
    out.push({
      type: "capsule",
      a: [x, y + 0.5 * k, z],
      b: [x + fx * 0.42 * k, y + 0.48 * k, z + fz * 0.42 * k],
      radius: r * 0.7,
      tone: m.tone,
      owner: s.id,
    });
  return out;
}

/** A point given as a mark or actor, shown for editing: what it refers to, in words. */
export const describeRef = (ref: Ref | undefined): string =>
  ref === undefined ? "—" : isVec(ref) ? ref.map((v) => v.toFixed(2)).join(", ") : ref;
export { isVec };
