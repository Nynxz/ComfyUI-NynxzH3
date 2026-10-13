// H3 Studio's shot writer: redrafts a shot's description with a text model, using ComfyUI's own
// nodes and nothing else. A draft is a tiny job of its own on the normal queue —
//
//   CLIPLoader (the writer model) → Generate Text (TextGenerate) → Preview as Text (PreviewAny)
//
// When H3 Studio Setup's `rewrite_clip` is wired, the writer model is that chain instead (a
// CLIPLoader through H3 CLIP LoRA, say), copied out of the workflow as it would queue.
//
// with the guide (nodes/h3studio/writer_guide.md) as the system prompt. Preview as Text sends the
// result back on ComfyUI's `executed` event, so models load, cache and unload like any other job,
// and the user's workflow is never touched.
import { reactive, watch } from "vue";
import { api } from "@comfy/api";
import { app } from "@comfy/app";
import { formatTime, refInScene, sceneStarts, shotRefs, type Project, type Ref } from "./h3studio";
import { speakerNames } from "./h3dialogue";

interface ComfyApi extends EventTarget {
  clientId?: string;
  fetchApi(path: string, init?: RequestInit): Promise<Response>;
}
const comfy = api as unknown as ComfyApi;

export type WriterMode = "polish" | "expand" | "tighten";
export const WRITER_MODES: { value: WriterMode; label: string; icon: string; title: string }[] = [
  {
    value: "polish",
    label: "Polish",
    icon: "mdi mdi-auto-fix",
    title: "Same content and length, written the way H3 reads best",
  },
  {
    value: "expand",
    label: "Expand",
    icon: "mdi mdi-text-box-plus-outline",
    title: "More concrete visual detail, motion and camera",
  },
  {
    value: "tighten",
    label: "Tighten",
    icon: "mdi mdi-content-cut",
    title: "Shorter, only what is seen, sized to the shot",
  },
];
const MODE_ASK: Record<WriterMode, string> = {
  polish: "Keep the same content and about the same length; make it clear, concrete and visual.",
  expand:
    "Keep what it says and add concrete visual detail: composition, light, how things move, and the camera. Three to five sentences.",
  tighten:
    "Make it shorter: keep only what is seen and what happens, sized to the shot's length. One or two sentences.",
};

/** A shot's redraft in progress or waiting to be used, by shot id — shared by the ✨ button in the
 *  shot card's header and the draft box under its text. */
export interface ShotDraft {
  state: "idle" | "writing" | "ready" | "error";
  mode: WriterMode;
  text: string;
  error: string;
}
export const shotDrafts = reactive(new Map<string, ShotDraft>());

// --- settings: which model writes, kept per browser ------------------------------------------------
const SETTINGS_KEY = "nynxz.h3studio.writer";
export interface WriterSettings {
  /** A text encoder file that can generate (Qwen, Gemma, …), from CLIPLoader's list. */
  model: string;
  /** CLIPLoader's type; most generating models are recognised whatever it says. */
  type: string;
  temperature: number;
  /** Let the writer look at the shot's references (needs a model with vision, e.g. Qwen3-VL). */
  pictures: boolean;
}
function loadSettings(): WriterSettings {
  const base = { model: "", type: "stable_diffusion", temperature: 0.7, pictures: true };
  try {
    return {
      ...base,
      ...(JSON.parse(localStorage.getItem(SETTINGS_KEY) ?? "{}") as Partial<WriterSettings>),
    };
  } catch {
    return base;
  }
}
export const writerSettings = reactive<WriterSettings>(loadSettings());
watch(writerSettings, () => {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(writerSettings));
  } catch {
    // remembered settings are a convenience
  }
});

/** Text encoders that look like they can write — the H3 encoder itself can't (no output head). */
const WRITERS = /gemma|qwen|llama|mistral|phi/i;
const CANT_WRITE = /minimax|t5gemma/i;
export async function writerModels(): Promise<{ models: string[]; types: string[] }> {
  const res = await comfy.fetchApi("/object_info/CLIPLoader");
  const info = (await res.json()) as {
    CLIPLoader?: { input: { required: Record<string, [unknown]> } };
  };
  const req = info.CLIPLoader?.input.required ?? {};
  const all = (req.clip_name?.[0] as string[] | undefined) ?? [];
  return {
    models: all.filter((m) => WRITERS.test(m) && !CANT_WRITE.test(m)),
    types: (req.type?.[0] as string[] | undefined) ?? [],
  };
}

// --- the writer model wired into H3 Studio Setup's rewrite_clip -------------------------------------
const SETUP = "nynxz.H3.StudioSetup";
export type ApiNode = { class_type: string; inputs: Record<string, unknown> };
export type ApiLink = [string, number];
const isLink = (v: unknown): v is ApiLink =>
  Array.isArray(v) && v.length === 2 && typeof v[1] === "number";

interface LiveNode {
  type: string;
  mode?: number;
  inputs?: { name: string; link: number | null }[];
}
/** Whether a Setup in the workflow (inside subgraphs too) has `rewrite_clip` wired. */
export function rewriteClipWired(): boolean {
  const root = (
    app as unknown as {
      graph?: { nodes?: LiveNode[]; subgraphs?: Map<string, { nodes?: LiveNode[] }> };
    }
  ).graph;
  const nodes = [
    ...(root?.nodes ?? []),
    ...[...(root?.subgraphs?.values() ?? [])].flatMap((g) => g.nodes ?? []),
  ];
  return nodes.some(
    (n) => n.type === SETUP && n.inputs?.some((i) => i.name === "rewrite_clip" && i.link != null),
  );
}

/** The nodes behind Setup's `rewrite_clip`, as the workflow would queue them, and the link to
 *  their CLIP — or null when it isn't wired. */
export async function rewriteClipChain(): Promise<{
  nodes: Record<string, ApiNode>;
  clip: ApiLink;
} | null> {
  const { output } = await (
    app as unknown as { graphToPrompt(): Promise<{ output: Record<string, ApiNode> }> }
  ).graphToPrompt();
  const setup = Object.values(output).find(
    (n) => n.class_type === SETUP && isLink(n.inputs.rewrite_clip),
  );
  if (!setup) return null;
  const clip = setup.inputs.rewrite_clip as ApiLink;
  const nodes: Record<string, ApiNode> = {};
  const stack = [String(clip[0])];
  while (stack.length) {
    const id = stack.pop()!;
    if (id in nodes || !output[id]) continue;
    nodes[id] = output[id];
    for (const v of Object.values(output[id].inputs)) if (isLink(v)) stack.push(String(v[0]));
  }
  return { nodes, clip: [String(clip[0]), clip[1]] };
}

/** Read each time: the guide is a file in the pack, meant to be tuned between drafts. */
const writerGuide = () => comfy.fetchApi("/nynxz/h3studio/writer-guide").then((r) => r.text());

const MAX_PICTURES = 6;
const PICTURE_SIDE = 448;
/** The references the writer looks at for a shot: the ones it @mentions, then the others its scene
 *  shows H3 — pictures and videos with a file, not control videos. */
export function writerPictures(project: Project, sceneIndex: number, shotIndex: number): Ref[] {
  const scene = project.scenes[sceneIndex];
  if (!writerSettings.pictures || !scene) return [];
  const seen = (r: Ref) =>
    (r.kind === "image" || r.kind === "video") && !!r.media && r.role !== "control";
  const ordered = [
    ...shotRefs(project, { scene: sceneIndex, shot: shotIndex, local: 0, sceneStart: 0 }),
    ...project.refs.filter((r) => refInScene(project, r, scene)),
  ];
  return [...new Set(ordered)].filter(seen).slice(0, MAX_PICTURES);
}

/** The job's nodes that read each file (a video by its first frame), letterbox them to one size and
 *  batch them in order, ending at node `pictures`. */
export function pictureNodes(
  pictures: Pick<Ref, "media" | "kind">[],
  width = PICTURE_SIDE,
  height = PICTURE_SIDE,
): Record<string, ApiNode> {
  const nodes: Record<string, ApiNode> = {};
  const batch: Record<string, ApiLink> = {};
  pictures.forEach((ref, i) => {
    const [folder, ...rest] = ref.media.split("/");
    const file = `${rest.join("/")} [${folder}]`;
    const image: ApiLink = [`picture${i}`, 0];
    if (ref.kind === "video") {
      nodes[`video${i}`] = { class_type: "LoadVideo", inputs: { file } };
      nodes[`frames${i}`] = {
        class_type: "GetVideoComponents",
        inputs: { video: [`video${i}`, 0] },
      };
      nodes[`picture${i}`] = {
        class_type: "ImageFromBatch",
        inputs: { image: [`frames${i}`, 0], batch_index: 0, length: 1 },
      };
    } else {
      nodes[`picture${i}`] = { class_type: "LoadImage", inputs: { image: file } };
    }
    nodes[`fit${i}`] = {
      class_type: "ResizeAndPadImage",
      inputs: {
        image,
        target_width: width,
        target_height: height,
        padding_color: "black",
        interpolation: "area",
      },
    };
    batch[`images.image${i}`] = [`fit${i}`, 0];
  });
  nodes.pictures = { class_type: "BatchImagesNode", inputs: batch };
  return nodes;
}

/** What the model is asked: the shot and what's around it, and how to redraft it. */
export function writerAsk(
  project: Project,
  sceneIndex: number,
  shotIndex: number,
  mode: WriterMode,
  pictures: Ref[] = [],
): string {
  const scene = project.scenes[sceneIndex]!;
  const shot = scene.shots[shotIndex]!;
  const end = scene.shots[shotIndex + 1]?.at ?? scene.seconds;
  const { width, height } = project.canvas;
  const shape = width > height ? "landscape" : width < height ? "portrait" : "square";
  const refs = project.refs.map((r) => {
    const picture = pictures.indexOf(r);
    const shown = picture >= 0 ? `, picture ${picture + 1}` : "";
    return `- @${r.name} (${r.kind ?? "image"}${shown})${r.note.trim() ? `: ${r.note.trim()}` : ""}`;
  });
  const prev =
    scene.shots[shotIndex - 1]?.text.trim() ??
    project.scenes[sceneIndex - 1]?.shots.at(-1)?.text.trim();
  const next =
    scene.shots[shotIndex + 1]?.text.trim() ??
    project.scenes[sceneIndex + 1]?.shots[0]?.text.trim();
  const lines = (shot.lines ?? [])
    .filter((l) => l.words.trim())
    .map((l) => `- ${speakerNames(project, l)}: "${l.words.trim()}"`);
  const start = (sceneStarts(project)[sceneIndex] ?? 0) + shot.at;
  return [
    `Rewrite the description of shot ${shotIndex + 1} of scene ${sceneIndex + 1}: ${(end - shot.at).toFixed(1)} seconds long, starting ${formatTime(start)} into the film, ${shape} (${width}×${height}).`,
    MODE_ASK[mode],
    refs.length
      ? `References you may use, keep each @name exactly:\n${refs.join("\n")}`
      : "There are no references.",
    pictures.length
      ? `The ${pictures.length === 1 ? "picture" : `${pictures.length} pictures`} attached ${pictures.length === 1 ? "is" : "are"} ${pictures.map((r, i) => `picture ${i + 1} = @${r.name}`).join(", ")}${pictures.some((r) => r.kind === "video") ? " (a video by its first frame)" : ""}. Describe what you see in them where the shot shows them, and still call each by its @name.`
      : "",
    project.style.trim()
      ? `The film's style (the studio adds it; don't repeat it): ${project.style.trim()}`
      : "",
    prev ? `The shot before: ${prev}` : "",
    next ? `The shot after: ${next}` : "",
    lines.length
      ? `Spoken during this shot (the studio adds the words; describe the speakers, not the speech):\n${lines.join("\n")}`
      : "",
    `The current description:\n"""\n${shot.text.trim() || "(empty — write one from the context)"}\n"""`,
    "Reply with the new description only.",
  ]
    .filter(Boolean)
    .join("\n\n");
}

/** The model's reply as a description: no thinking, quotes, labels or preamble. */
export function cleanDraft(reply: string): string {
  return reply
    .replace(/<think>[\s\S]*?<\/think>/gi, "")
    .replace(/^\s*(here(?:'s| is)[^:\n]*:|new description:|description:)\s*/i, "")
    .trim()
    .replace(/^"""\s*|\s*"""$/g, "")
    .replace(/^["“](.*)["”]$/s, "$1")
    .trim();
}

/** @names in the original the draft lost. */
export function droppedMentions(before: string, after: string): string[] {
  const have = new Set((after.match(/@[\p{L}\p{N}_-]+/gu) ?? []).map((m) => m.toLowerCase()));
  return [
    ...new Set((before.match(/@[\p{L}\p{N}_-]+/gu) ?? []).map((m) => m.toLowerCase())),
  ].filter((m) => !have.has(m));
}

/** Queue the writer job and wait for its text. Rejects with ComfyUI's message if it fails. */
export async function runWriter(ask: string, seed: number, pictures: Ref[] = []): Promise<string> {
  const chain = await rewriteClipChain();
  if (!chain && !writerSettings.model)
    throw new Error("Pick a writer model first, or wire H3 Studio Setup's rewrite_clip.");
  const prompt: Record<string, ApiNode> = {
    ...chain?.nodes,
    ...(pictures.length ? pictureNodes(pictures) : {}),
    guide: { class_type: "PrimitiveStringMultiline", inputs: { value: await writerGuide() } },
    ...(chain
      ? {}
      : {
          load: {
            class_type: "CLIPLoader",
            inputs: {
              clip_name: writerSettings.model,
              type: writerSettings.type,
              device: "default",
            },
          },
        }),
    write: {
      class_type: "TextGenerate",
      inputs: {
        clip: chain?.clip ?? ["load", 0],
        ...(pictures.length ? { image: ["pictures", 0] } : {}),
        prompt: ask,
        max_length: 400,
        ...sampling(seed),
        use_default_template: true,
        system_prompt: ["guide", 0],
      },
    },
    show: { class_type: "PreviewAny", inputs: { source: ["write", 0] } },
  };
  return queueText(prompt);
}

/** Generate Text's sampling inputs, at the writer's temperature. */
export function sampling(seed: number): Record<string, unknown> {
  return {
    sampling_mode: "on",
    "sampling_mode.temperature": writerSettings.temperature,
    "sampling_mode.top_k": 64,
    "sampling_mode.top_p": 0.95,
    "sampling_mode.min_p": 0.05,
    "sampling_mode.repetition_penalty": 1.05,
    "sampling_mode.seed": seed,
    thinking: false,
  };
}

/** Queue a text job whose answer is node `show` (Preview as Text), and wait for that text. Rejects
 *  with ComfyUI's message if it fails. */
export async function queueText(prompt: Record<string, ApiNode>): Promise<string> {
  const res = await comfy.fetchApi("/prompt", {
    method: "POST",
    body: JSON.stringify({ prompt, client_id: comfy.clientId }),
  });
  const body = (await res.json()) as {
    prompt_id?: string;
    error?: { message?: string };
    node_errors?: Record<string, { errors?: { message: string; details?: string }[] }>;
  };
  if (!res.ok || !body.prompt_id) {
    const nodeError = Object.values(body.node_errors ?? {})[0]?.errors?.[0];
    throw new Error(
      nodeError
        ? `${nodeError.message}${nodeError.details ? ` (${nodeError.details})` : ""}`
        : (body.error?.message ?? "ComfyUI refused the writer job."),
    );
  }
  const id = body.prompt_id;
  return new Promise((resolve, reject) => {
    const done = () => {
      comfy.removeEventListener("executed", onExecuted);
      comfy.removeEventListener("execution_error", onError);
      comfy.removeEventListener("execution_interrupted", onStopped);
    };
    const onExecuted = (e: Event) => {
      const d = (
        e as CustomEvent<{ prompt_id: string; node: string; output?: { text?: string[] } }>
      ).detail;
      if (d?.prompt_id !== id || d.node !== "show") return;
      done();
      resolve(d.output?.text?.[0] ?? "");
    };
    const onError = (e: Event) => {
      const d = (e as CustomEvent<{ prompt_id: string; exception_message?: string }>).detail;
      if (d?.prompt_id !== id) return;
      done();
      reject(new Error(d.exception_message?.trim() || "The writer job failed."));
    };
    const onStopped = (e: Event) => {
      if ((e as CustomEvent<{ prompt_id: string }>).detail?.prompt_id !== id) return;
      done();
      reject(new Error("Stopped."));
    };
    comfy.addEventListener("executed", onExecuted);
    comfy.addEventListener("execution_error", onError);
    comfy.addEventListener("execution_interrupted", onStopped);
  });
}
