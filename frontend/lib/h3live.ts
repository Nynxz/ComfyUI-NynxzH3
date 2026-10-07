// Live sampling previews and finished clips for H3 Studio, per scene.
//
// The studio's Python side announces each scene it renders (`nynxz.h3studio.render`, once per run
// or loop pass, under the node id on the canvas). Every sampling preview that arrives until the
// run moves on belongs to that scene. Previews come from whichever source is there:
//
//   • Model Preview Override (ComfyUI-NynxzPersonal) — tiny-VAE clips with step numbers. Listened
//     to by event name only, so the studio doesn't depend on that pack.
//   • ComfyUI's own sampler previews (`b_preview_with_metadata`), with steps from `progress` —
//     used for a scene only while no Preview Override frame has arrived for it.
//
// Every step of a scene's latest run is kept (until that scene renders again or the page reloads),
// so the monitor can scrub through them. H3 Studio Clip reports each finished, saved clip
// (`nynxz.h3studio.clip`); the editor stores that in the project, so it outlives the page.
import { api } from "@comfy/api";
import { reactive } from "vue";

const RENDER_EVENT = "nynxz.h3studio.render";
const CLIP_EVENT = "nynxz.h3studio.clip";
const OVERRIDE_EVENT = "nynxz.personal.preview_override";

export interface LiveFrame {
  /** A still or a video clip; absent when the step came as decoded frames. */
  url: string;
  video: boolean;
  /** The clip carries sound (Preview Override with an audio VAE). */
  audio?: boolean;
  /** An animated WebP's frames, decoded so playback can be placed at any moment. */
  frames?: VideoFrame[];
  step: number;
  total: number | null;
}

/** One scene's latest sampling run. */
export interface LiveRun {
  /** One payload per step boundary that arrived, in step order. */
  steps: LiveFrame[];
  /** The schedule, one sigma per boundary (Preview Override sends it with the first message). */
  sigmas: number[] | null;
  /** The change each step made (`deltas[i]` belongs to boundary i + 1). */
  deltas: number[];
  /** Boundaries in the run (steps + 1). */
  total: number;
}

export interface StudioLive {
  /** The scene sampling right now, or null between runs. */
  rendering: number | null;
  /** Each scene's latest run. */
  runs: Record<number, LiveRun>;
  /** Finished clips reported this session, by scene — the editor moves them into the project. */
  clips: Record<number, string>;
}

const studios = reactive(new Map<string, StudioLive>());
let current: { nodeId: string; scene: number; fromOverride: boolean } | null = null;
let progress: { value: number; max: number } | null = null;
let listening = false;

function entry(nodeId: string): StudioLive {
  if (!studios.has(nodeId)) studios.set(nodeId, { rendering: null, runs: {}, clips: {} });
  return studios.get(nodeId)!;
}

function release(f: LiveFrame) {
  if (f.url) URL.revokeObjectURL(f.url);
  for (const vf of f.frames ?? []) vf.close();
}

function put(frame: LiveFrame) {
  if (!current) return;
  const run = entry(current.nodeId).runs[current.scene];
  if (!run) return;
  if (frame.total) run.total = Math.max(run.total, frame.total + 1);
  const same = run.steps.findIndex((f) => f.step === frame.step);
  if (same >= 0) {
    release(run.steps[same]!);
    run.steps[same] = frame;
  } else run.steps.push(frame);
  run.steps.sort((a, b) => a.step - b.step);
}

/** An animated WebP's frames (Chromium's ImageDecoder), or null for a still or elsewhere. */
async function decodeFrames(blob: Blob): Promise<VideoFrame[] | null> {
  if (typeof ImageDecoder === "undefined") return null;
  try {
    const decoder = new ImageDecoder({ data: blob.stream(), type: blob.type });
    await decoder.completed;
    const track = decoder.tracks.selectedTrack;
    if (!track || track.frameCount <= 1) return null;
    const frames: VideoFrame[] = [];
    for (let i = 0; i < track.frameCount; i++) frames.push((await decoder.decode({ frameIndex: i })).image);
    decoder.close();
    return frames;
  } catch {
    return null;
  }
}

function finish() {
  if (current) entry(current.nodeId).rendering = null;
  current = null;
  progress = null;
}

function blobOf(b64: string, mime: string): Blob {
  return new Blob([Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))], { type: mime });
}

type Detail<T> = CustomEvent<T>;

function listen() {
  if (listening) return;
  listening = true;
  const target = api as unknown as EventTarget;

  target.addEventListener(RENDER_EVENT, (e) => {
    const d = (e as Detail<{ node_id?: string; scene?: number }>).detail;
    if (!d?.node_id || typeof d.scene !== "number") return;
    if (current) entry(current.nodeId).rendering = null;
    current = { nodeId: d.node_id, scene: d.scene, fromOverride: false };
    progress = null;
    const e2 = entry(d.node_id);
    for (const f of e2.runs[d.scene]?.steps ?? []) release(f);
    e2.runs[d.scene] = { steps: [], sigmas: null, deltas: [], total: 0 };
    e2.rendering = d.scene;
  });

  target.addEventListener(CLIP_EVENT, (e) => {
    const d = (e as Detail<{ node_id?: string; scene?: number; media?: string }>).detail;
    if (d?.node_id && typeof d.scene === "number" && d.media) entry(d.node_id).clips[d.scene] = d.media;
  });

  target.addEventListener(OVERRIDE_EVENT, (e) => {
    type Message = {
      image?: string;
      mime?: string;
      step?: number;
      total?: number;
      sigmas?: number[] | null;
      delta?: number | null;
      audio?: boolean;
    };
    const d = (e as Detail<Message>).detail;
    if (!current || !d) return;
    current.fromOverride = true;
    const run = entry(current.nodeId).runs[current.scene];
    const step = d.step ?? 0;
    if (run) {
      if (Array.isArray(d.sigmas)) {
        run.sigmas = d.sigmas;
        run.total = Math.max(run.total, d.sigmas.length);
      }
      if (typeof d.delta === "number" && step >= 1) run.deltas[step - 1] = d.delta;
    }
    if (!d.image) return;
    const mime = d.mime ?? "image/jpeg";
    const blob = blobOf(d.image, mime);
    const at = current;
    if (mime === "image/webp") {
      // Possibly animated: decode it, so the monitor can show any moment of it, not just play it.
      void decodeFrames(blob).then((frames) => {
        if (current !== at) return frames?.forEach((f) => f.close());
        put(frames ? { url: "", video: false, frames, step, total: d.total ?? null } : { url: URL.createObjectURL(blob), video: false, step, total: d.total ?? null });
      });
      return;
    }
    put({ url: URL.createObjectURL(blob), video: mime.startsWith("video/"), audio: !!d.audio, step, total: d.total ?? null });
  });

  target.addEventListener("progress", (e) => {
    const d = (e as Detail<{ value?: number; max?: number }>).detail;
    if (typeof d?.value === "number" && typeof d.max === "number") progress = { value: d.value, max: d.max };
  });

  target.addEventListener("b_preview_with_metadata", (e) => {
    const d = (e as Detail<{ blob?: Blob }>).detail;
    if (!current || current.fromOverride || !d?.blob) return;
    put({ url: URL.createObjectURL(d.blob), video: false, step: progress?.value ?? 0, total: progress?.max ?? null });
  });

  for (const ended of ["execution_success", "execution_error", "execution_interrupted"]) target.addEventListener(ended, finish);
}

/** The live state of one studio node (by its id on the canvas). */
export function useStudioLive(nodeId: string): StudioLive {
  listen();
  return entry(nodeId);
}
