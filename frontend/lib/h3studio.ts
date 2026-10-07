// H3 Studio's project document on the frontend: its shape (mirrors nodes/h3studio/_project.py,
// which normalizes and compiles it), one shared reactive copy per node so the on-node editor and
// its pop-out panel edit the same project live, and the preview route.
import { effectScope, reactive, watch } from "vue";
import { api } from "@comfy/api";
import { mediaKind, mediaRefUrl, route } from "@/framework";

export const FPS = 24;
export const CONTEXT_FRAMES = [5, 22, 39] as const;

export type Transition = "cut" | "dissolve" | "fade" | "wipe" | "continue" | "continue_timed";
/** How a shot follows the one before (nodes/h3studio/_project.py `TRANSITIONS`). */
/** How a scene follows the one before (see CONTINUATIONS in nodes/h3studio/_project.py). */
export type Continuation = "cut" | "guide" | "first_frame" | "reference" | "sound";
export const CONTINUATIONS: {
  value: Continuation;
  label: string;
  icon: string;
  title: string;
  script: string;
}[] = [
  {
    value: "cut",
    label: "Cut",
    icon: "mdi-content-cut",
    title: "Starts fresh: only shared references carry over",
    script: "cut",
  },
  {
    value: "guide",
    label: "Continue",
    icon: "mdi-link-variant",
    title: "Its last frames lead into this scene: the motion and the camera carry on",
    script: "continues",
  },
  {
    value: "first_frame",
    label: "Open on its last frame",
    icon: "mdi-image-move",
    title:
      "Its last frame is this scene's first frame: it picks up exactly where it ended, then moves on its own",
    script: "from last frame",
  },
  {
    value: "sound",
    label: "Cut, sound carries",
    icon: "mdi-music-note-outline",
    title:
      "A new shot, but its sound picks up where the previous scene's left off: music and ambience carry across the cut",
    script: "sound carries",
  },
  {
    value: "reference",
    label: "Same place",
    icon: "mdi-map-marker-outline",
    title:
      "Its last frame is a reference picture (@setting): the same place and light, in a new shot",
    script: "same place",
  },
];
export const continuationOf = (mode: Continuation) =>
  CONTINUATIONS.find((c) => c.value === mode) ?? CONTINUATIONS[0]!;

export const TRANSITIONS: { value: Transition; label: string; icon: string; title: string }[] = [
  { value: "cut", label: "Cut", icon: "mdi-content-cut", title: "A new shot: H3 cuts here" },
  {
    value: "dissolve",
    label: "Cross-dissolve",
    icon: "mdi-blur",
    title: "A new shot, cross-dissolving from the one before",
  },
  {
    value: "fade",
    label: "Fade",
    icon: "mdi-brightness-6",
    title: "A new shot, fading out and back in",
  },
  {
    value: "wipe",
    label: "Wipe",
    icon: "mdi-arrow-right-bold-box-outline",
    title: "A new shot, wiping in",
  },
  {
    value: "continue",
    label: "No cut",
    icon: "mdi-link-variant",
    title: 'Carries on the shot before, joined with "Then," — no cut',
  },
  {
    value: "continue_timed",
    label: "No cut, timed",
    icon: "mdi-timer-outline",
    title: 'Carries on the shot before at its own time ("At 00:03.000, …") — no cut',
  },
];
export const continues = (shot: Shot | undefined) =>
  shot?.transition === "continue" || shot?.transition === "continue_timed";
/** Each shot's colour in a scene: a shot that carries on the one before (no cut) is part of the
 *  same H3 shot, so it shares that shot's colour. */
export function shotColors(scene: Scene): string[] {
  let shown = -1;
  return scene.shots.map((sh, i) => shotColor(i === 0 || !continues(sh) ? ++shown : shown));
}

export interface Shot {
  id: string;
  at: number;
  text: string;
  /** How it follows the shot before (the first shot always starts the scene). Default: a cut. */
  transition?: Transition;
  /** What is spoken in the shot, in order (see `h3dialogue.ts`). */
  lines?: Line[];
}
/** A voice in the film. Linked to a reference (`ref`), it is that `<Subject N>` in the prompt;
 *  `timbre` is an audio reference its voice follows. */
export interface Voice {
  id: string;
  name: string;
  ref: string;
  timbre: string;
  /** How it sounds, e.g. "a quiet, breathy young female voice". */
  voice: string;
  language: string;
}
export type LineMode = "say" | "voiceover" | "sing";
export interface Line {
  id: string;
  /** Voice ids; more than one speak together. */
  speakers: string[];
  mode: LineMode;
  /** How it is said: "softly", "with a laugh"… */
  delivery: string;
  /** The exact words, in their own language. */
  words: string;
  /** The rest of the line, spoken over the cut into the next shot. */
  next: string;
  /** Cut short by the end of the clip. */
  cutoff: boolean;
  /** Overrides the voice's language. */
  language: string;
  /** When it starts, seconds into the scene (set by dragging it on the timeline). Unset, or
   *  earlier than the line before it ends, it follows straight on. */
  at?: number;
}
export interface Keyframe {
  id: string;
  at: number;
  media: string;
  /** A picture of another shape than the canvas: cropped to fill it (default) or stretched onto it. */
  fit?: "crop" | "stretch";
}
export type RefSize = 1 | 0.75 | 0.5;
export const REF_SIZES: { value: RefSize; label: string }[] = [
  { value: 1, label: "Full" },
  { value: 0.75, label: "¾" },
  { value: 0.5, label: "½" },
];
export type MediaKind = "image" | "video" | "audio";
/** H3's reference limits per scene. */
export const LIMITS: Record<MediaKind, number> = { image: 9, video: 3, audio: 3 };

export interface Ref {
  id: string;
  /** Empty for a proxy: a name and a description standing in until a picture is added. */
  media: string;
  kind: MediaKind;
  /** A video brings its own sound (as an extra <Audio n>) unless this is false. */
  soundtrack?: boolean;
  /** Shown to H3 at this fraction of the canvas size (pictures and videos); 1 when unset. */
  size?: RefSize;
  name: string;
  note: string;
  /** A picture: its look ("reference") or only its meaning ("semantic"). A video: its look and
   *  motion ("reference"), or only as blocking — staging, timing and camera, none of its look. */
  role: "reference" | "semantic" | "blocking";
  retain: string;
  /** Scenes that show it without using it — a scene that @mentions it (or where its voice speaks)
   *  always does. A list of scene ids, or "all". */
  scenes: "all" | string[];
}
export interface Scene {
  id: string;
  title: string;
  /** Its noise seed, given to the sampler through H3 Studio Outputs' `seed`. */
  seed: number;
  seconds: number;
  shots: Shot[];
  keyframes: Keyframe[];
  /** This scene's own direction, in place of the film's; empty to use the film's. */
  direction: string;
  soundscape: string;
  music: string;
  continuation: { mode: Continuation; frames: number };
  /** The scene's finished clip (`output/h3studio/…`), saved by H3 Studio Clip on its last run. */
  render?: string;
}
/** A LoRA lane. A scene renders all its frames with one set of weights, so the lane has one
 *  strength per scene: its own in `scenes` (by scene id), else the lane's `strength`. Within a scene
 *  it can follow `sampling`, a multiplier over the denoising steps (high noise → low noise). */
export interface LoraLane {
  id: string;
  name: string;
  enabled: boolean;
  strength: number;
  scenes?: Record<string, number>;
  /** A scene's own shape over the sampling steps; scenes without one follow `sampling`. */
  steps?: Record<string, { p: number; v: number }[]>;
  /** Older projects: a curve over the film's clock, read at each scene's middle. Turned into
   *  `scenes` when the project loads. */
  film: { t: number; v: number }[];
  sampling: { p: number; v: number }[];
}
export interface StudioSettings {
  /** LoRA step shapes: "auto" (default) uses hooks unless dynamic VRAM is on (then each shape's
   *  average); "fast" / "low_vram" always use hooks, caching on the GPU or re-patching from RAM. */
  hooks?: "auto" | "fast" | "low_vram";
  /** The most changes a step shape is split into. */
  step_detail?: number;
  /** Log each scene's prompt and LoRA plan to the ComfyUI console. */
  verbose?: boolean;
}
export interface Project {
  /** 2: references are in a scene only when used there or marked for it (see `refInScene`). */
  v: 2;
  canvas: { width: number; height: number };
  style: string;
  /** How the film is made, said after the style in every scene: "animated on twos, held poses". */
  direction: string;
  soundscape: string;
  music: string;
  refs: Ref[];
  scenes: Scene[];
  loras?: LoraLane[];
  cast?: Voice[];
  /** How scenes render (nodes/h3studio/_project.py `normalize_settings`). */
  settings?: StudioSettings;
  active: number;
  /** Editor layout: inspector beside the monitor, under it, or whichever shows the picture bigger. */
  layout?: "auto" | "side" | "stacked";
  /** Set only while a partial render is queued (lib/h3render.ts): the scenes that run renders; the
   *  others play their latest clip. */
  renderOnly?: string[];
}
export interface Compiled {
  task: string;
  prompt: string;
  frames: number;
  seconds: number;
  /** `alias`: the same file as an earlier reference, which H3 is shown instead. */
  refs: {
    id: string;
    name: string;
    media: string;
    kind: MediaKind;
    role: string;
    tag: string;
    soundtrack_tag: string | null;
    alias?: boolean;
  }[];
  keyframes: { frame: number; media: string }[];
  warnings: string[];
}

/** H3's own canvas for a shape (core `adapt_canvas`): 768 on the short edge, capped at 768×1344. */
export function nativeCanvas(ratio: number): { width: number; height: number } {
  const [w, h] = ratio >= 1 ? [768 * ratio, 768] : [768, 768 / ratio];
  const s = Math.min(1, Math.sqrt((768 * 1344) / (w * h)));
  const snap = (v: number) => Math.max(32, Math.round((v * s) / 32) * 32);
  return { width: snap(w), height: snap(h) };
}

export const uid = (prefix: string) => `${prefix}${Math.random().toString(36).slice(2, 8)}`;

/** H3's frame grid: 17k + 5 frames at 24 fps. */
export function framesFor(seconds: number): number {
  let n = Math.max(5, Math.round(seconds * FPS));
  while (n % 17 !== 5) n++;
  return n;
}
export const snapSeconds = (seconds: number) =>
  Math.round((framesFor(seconds) / FPS) * 1000) / 1000;

/** A scene's seed when it has none of its own: FNV-1a of its id, as nodes/h3studio/_project.py's
 *  `seed_of` computes it, so both sides agree on a project saved before seeds. */
export function seedOf(id: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < id.length; i++) h = Math.imul(h ^ id.charCodeAt(i), 0x01000193) >>> 0;
  return h;
}
export const randomSeed = () => Math.floor(Math.random() * 2 ** 32);

export function newScene(seconds = 5): Scene {
  return {
    id: uid("s"),
    seed: randomSeed(),
    title: "",
    seconds: snapSeconds(seconds),
    shots: [{ id: uid("sh"), at: 0, text: "" }],
    keyframes: [],
    direction: "",
    soundscape: "",
    music: "",
    continuation: { mode: "guide", frames: 22 },
  };
}

export function defaultProject(): Project {
  const first = newScene();
  first.continuation.mode = "cut";
  return {
    v: 2,
    canvas: { width: 1344, height: 768 },
    style: "",
    direction: "",
    soundscape: "",
    music: "",
    refs: [],
    scenes: [first],
    active: 0,
  };
}

/** Fill whatever a saved widget holds out to a full project; the server normalizes properly. */
export function toProject(raw: unknown): Project {
  const base = defaultProject();
  if (!raw || typeof raw !== "object") return base;
  const p = raw as Partial<Project>;
  const scenes =
    Array.isArray(p.scenes) && p.scenes.length
      ? p.scenes.map((s) => ({ ...newScene(), ...s, seed: s.seed ?? seedOf(s.id) }))
      : base.scenes;
  const project: Project = {
    ...base,
    ...p,
    canvas: { ...base.canvas, ...(p.canvas ?? {}) },
    // Before version 2 every reference was in every scene by default: now it's only where used.
    refs: Array.isArray(p.refs)
      ? p.refs.map((r) => ({
          ...r,
          kind: r.kind ?? mediaKind(r.media),
          scenes: Array.isArray(r.scenes)
            ? r.scenes
            : r.scenes === "all" && p.v === 2
              ? ("all" as const)
              : [],
        }))
      : [],
    scenes,
    cast: Array.isArray(p.cast) ? p.cast : [],
    loras: Array.isArray(p.loras)
      ? p.loras.map((l) => ({ ...newLoraLane(l.name ?? ""), ...l }))
      : [],
    active: Math.min(Math.max(p.active ?? 0, 0), scenes.length - 1),
    v: 2,
  };
  // A lane drawn as a curve over the film becomes the per-scene strengths it rendered with.
  for (const lane of project.loras ?? [])
    if (lane.film.length) {
      lane.scenes = Object.fromEntries(
        project.scenes.map((sc, i) => [sc.id, sceneLoraStrength(project, lane, i)]),
      );
      lane.film = [];
    }
  return project;
}

interface Host {
  value: unknown;
  callback?: (v: unknown) => void;
}

const shared = new WeakMap<object, Project>();

/** The project behind a node's widget: one reactive copy shared by every view of that node,
 *  written back to the widget (and so the saved workflow) on every change. */
export function useProject(widget: Host | undefined): Project {
  const key = widget ?? {};
  const existing = shared.get(key);
  if (existing) return existing;
  const project = reactive(toProject(widget?.value)) as Project;
  shared.set(key, project);
  // Detached: the save-back must outlive whichever view (node or panel) happened to create it.
  if (widget)
    effectScope(true).run(() =>
      watch(
        project,
        () => {
          const value = JSON.parse(JSON.stringify(project)) as Project;
          widget.value = value;
          try {
            widget.callback?.(value);
          } catch {
            /* no callback */
          }
        },
        { deep: true },
      ),
    );
  return project;
}

export async function compileScene(project: Project, scene: number): Promise<Compiled | null> {
  try {
    const res = await fetch("/nynxz/h3studio/compile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project, scene }),
    });
    return res.ok ? ((await res.json()) as Compiled) : null;
  } catch {
    return null;
  }
}

export function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  return m ? `${m}:${s.toFixed(1).padStart(4, "0")}` : `${s.toFixed(1)}s`;
}

const panelOpen = reactive(new Set<string>());
/** Whether a node's studio is open in a pop-out panel (its node then shows a summary). */
export const isPanelOpen = (nodeId: string) => panelOpen.has(nodeId);
export function setPanelOpen(nodeId: string, open: boolean) {
  if (open) panelOpen.add(nodeId);
  else panelOpen.delete(nodeId);
}

export const SHOT_COLORS = ["#6d8cff", "#3fbf9b", "#e0a54a", "#d96aa7", "#8f7cf0", "#4fb0d9"];
export const shotColor = (i: number) => SHOT_COLORS[i % SHOT_COLORS.length]!;

// --- the film clock: every scene laid end to end -------------------------------------------------

/** Where each scene starts on the film's clock. */
export function sceneStarts(project: Project): number[] {
  const starts: number[] = [];
  let t = 0;
  for (const s of project.scenes) {
    starts.push(t);
    t += s.seconds;
  }
  return starts;
}

export const filmLength = (project: Project) =>
  project.scenes.reduce((sum, s) => sum + s.seconds, 0);

export interface Place {
  scene: number;
  shot: number;
  /** Seconds into the scene. */
  local: number;
  sceneStart: number;
}

/** The scene and shot under a film time. */
export function placeAt(project: Project, t: number): Place {
  const starts = sceneStarts(project);
  let scene = 0;
  for (let i = 0; i < starts.length; i++) if (t >= starts[i]! - 1e-6) scene = i;
  const local = Math.max(0, t - starts[scene]!);
  const shots = project.scenes[scene]!.shots;
  let shot = 0;
  for (let i = 0; i < shots.length; i++) if (local >= shots[i]!.at - 1e-6) shot = i;
  return { scene, shot, local, sceneStart: starts[scene]! };
}

/** What the monitor shows at a film time: the latest keyframe at or before it in its scene, else
 *  the scene's first picture (or video) reference — the storyboard frame for that moment. */
export function pictureAt(
  project: Project,
  place: Place,
): { media: string; kind: "keyframe" | "reference" } | null {
  const scene = project.scenes[place.scene]!;
  const keyframe = [...scene.keyframes]
    .sort((a, b) => b.at - a.at)
    .find((k) => k.at <= place.local + 1e-6);
  if (keyframe) return { media: keyframe.media, kind: "keyframe" };
  const seen = shotRefs(project, place).find((r) => r.kind !== "audio" && r.media);
  if (seen) return { media: seen.media, kind: "reference" };
  const inScene = project.refs.filter((r) => refInScene(project, r, scene));
  const ref =
    inScene.find((r) => r.kind === "image" && r.media) ??
    inScene.find((r) => r.kind === "video" && r.media);
  return ref ? { media: ref.media, kind: "reference" } : null;
}
/** Whether a scene uses a reference: a shot @mentions it, or a voice it gives a face or a timbre to
 *  speaks there (as nodes/h3studio/_project.py's `mentions_ref`). */
export function refUsedIn(project: Project, ref: Ref, scene: Scene): boolean {
  const mention = new RegExp(`@${ref.name.replace(/[-]/g, "\\-")}(?![\\w-])`, "i");
  if (scene.shots.some((s) => mention.test(s.text))) return true;
  const voices = new Set(
    (project.cast ?? []).filter((v) => v.ref === ref.id || v.timbre === ref.id).map((v) => v.id),
  );
  return (
    voices.size > 0 &&
    scene.shots.some((s) => (s.lines ?? []).some((l) => l.speakers.some((v) => voices.has(v))))
  );
}
/** Whether a scene shows H3 a reference: it uses it, or it's marked for that scene (or every scene). */
export function refInScene(project: Project, ref: Ref, scene: Scene): boolean {
  return refUsedIn(project, ref, scene) || ref.scenes === "all" || ref.scenes.includes(scene.id);
}
/** The references a shot @mentions, in the order it mentions them. */
export function shotRefs(project: Project, place: Place): Ref[] {
  const text = project.scenes[place.scene]?.shots[place.shot]?.text ?? "";
  const names = [...new Set((text.match(/@[\w-]+/g) ?? []).map((m) => m.slice(1).toLowerCase()))];
  return names.flatMap((n) => project.refs.filter((r) => r.name.toLowerCase() === n));
}

const urls = new Map<string, string>();
/** A media ref's URL that stays the same for the page's life. `mediaRefUrl` adds a fresh
 *  cache-buster on every call, so calling it while rendering reloads the file each time. */
export function stableUrl(ref: string): string {
  let url = urls.get(ref);
  if (!url) urls.set(ref, (url = mediaRefUrl(ref)));
  return url;
}

const thumbs = new Map<string, string>();
/** A small cached JPEG of a picture or a video's first frame (the pack's `media/thumb` route), so a
 *  grid of references doesn't download and decode every full-size file. Empty for audio. */
export function thumbUrl(ref: string, size = 256): string {
  const key = `${size}|${ref}`;
  let url = thumbs.get(key);
  if (url === undefined) {
    const [type, ...rest] = ref.split("/");
    const ok =
      ["input", "output", "temp"].includes(type ?? "") && rest.length && mediaKind(ref) !== "audio";
    const query = new URLSearchParams({
      type: type ?? "",
      name: rest.join("/"),
      size: String(size),
    });
    url = ok
      ? (api as { apiURL: (p: string) => string }).apiURL(`${route("media")}/thumb?${query}`)
      : "";
    thumbs.set(key, url);
  }
  return url;
}

/** How the editor was left: restored when the workflow loads. Not part of the project (changing
 *  the view mustn't recompile the prompt), so it lives in the node's properties. */
export interface StudioView {
  mode?: string;
  loop?: string;
  tab?: string;
  zoom?: number;
  /** Playhead, seconds — saved when playback stops, not as it runs. */
  time?: number;
  /** Timeline height, px. */
  timeline?: number;
  /** Reference sections folded or opened by hand (by default an empty one is folded). */
  refsFold?: Record<string, "open" | "folded">;
  /** The inspector's height under the monitor (stacked) and its width beside it (side), px. */
  stackH?: number;
  sideW?: number;
  /** Track groups hidden by the timeline filters ("keyframes", "loras", "refs"). */
  hide?: string[];
  /** LoRA lanes (by id) showing their shapes over the sampling steps instead of strengths. */
  loraSteps?: string[];
}
interface ViewNode {
  properties?: Record<string, unknown>;
  graph?: { change?: () => void } | null;
}
const VIEW_KEY = "nynxzH3View";
const views = new WeakMap<object, StudioView>();
/** The node's view state, shared by every mount of its editor (node and panel). */
export function useStudioView(node: ViewNode | undefined): StudioView {
  if (!node) return reactive({});
  const known = views.get(node);
  if (known) return known;
  const saved = node.properties?.[VIEW_KEY];
  const view = reactive<StudioView>(
    saved && typeof saved === "object" ? { ...(saved as StudioView) } : {},
  );
  views.set(node, view);
  let timer = 0;
  effectScope(true).run(() =>
    watch(view, () => {
      clearTimeout(timer);
      timer = window.setTimeout(() => {
        node.properties ??= {};
        node.properties[VIEW_KEY] = { ...view };
        node.graph?.change?.();
      }, 300);
    }),
  );
  return view;
}

export function newLoraLane(name: string): LoraLane {
  return { id: uid("l"), name, enabled: true, strength: 1, scenes: {}, film: [], sampling: [] };
}

/** A curve's value at `x`: linear between points, flat past the ends (as the Python side). */
export function curveAt<K extends string>(
  points: ({ v: number } & Record<K, number>)[],
  key: K,
  x: number,
  fallback: number,
): number {
  if (!points.length) return fallback;
  if (x <= points[0]![key]) return points[0]!.v;
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1]!;
    const b = points[i]!;
    if (x <= b[key]) {
      const span = b[key] - a[key];
      return a.v + (b.v - a.v) * (span > 0 ? (x - a[key]) / span : 1);
    }
  }
  return points[points.length - 1]!.v;
}

/** The strength a lane renders scene `i` with: the scene's own, else the lane's (an old film curve
 *  is read at the scene's middle). */
export function sceneLoraStrength(project: Project, lane: LoraLane, i: number): number {
  const own = lane.scenes?.[project.scenes[i]?.id ?? ""];
  if (own !== undefined) return own;
  const start = sceneStarts(project)[i] ?? 0;
  const mid = start + (project.scenes[i]?.seconds ?? 0) / 2;
  return Math.round(curveAt(lane.film, "t", mid, lane.strength) * 1000) / 1000;
}

// --- what this ComfyUI can do -------------------------------------------------------------------
/** Asked once per page: with dynamic VRAM running, LoRA step shapes on Auto are only averages. */
export const capabilities = reactive<{ dynamicVram: boolean | null }>({ dynamicVram: null });
let asked = false;
export function loadCapabilities() {
  if (asked) return;
  asked = true;
  void fetch("/nynxz/h3studio/capabilities")
    .then((r) => (r.ok ? r.json() : null))
    .then((d: { dynamic_vram?: boolean } | null) => {
      if (d) capabilities.dynamicVram = !!d.dynamic_vram;
    })
    .catch(() => {});
}
/** Whether a LoRA's strength can really change over the sampling steps here. Unknown counts as yes. */
export const stepShapesWork = (project: Project) =>
  (project.settings?.hooks ?? "auto") !== "auto" || capabilities.dynamicVram !== true;
/** A shape's average multiplier, what it amounts to when it can't change over the steps. */
export function shapeMean(points: { p: number; v: number }[]): number {
  const n = 24;
  let sum = 0;
  for (let i = 0; i < n; i++) sum += curveAt(points, "p", (i + 0.5) / n, 1);
  return sum / n;
}
