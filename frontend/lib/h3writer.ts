// H3 Studio's shot writer: redrafts a shot's description with a text model, using ComfyUI's own
// nodes and nothing else. A draft is a tiny job of its own on the normal queue —
//
//   CLIPLoader (the writer model) → Generate Text (TextGenerate) → Preview as Text (PreviewAny)
//
// with the guide (nodes/h3studio/writer_guide.md) as the system prompt. Preview as Text sends the
// result back on ComfyUI's `executed` event, so models load, cache and unload like any other job,
// and the user's workflow is never touched.
import { reactive, watch } from "vue";
import { api } from "@comfy/api";
import { formatTime, sceneStarts, type Project } from "./h3studio";
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
}
function loadSettings(): WriterSettings {
  const base = { model: "", type: "stable_diffusion", temperature: 0.7 };
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

/** Read each time: the guide is a file in the pack, meant to be tuned between drafts. */
const writerGuide = () => comfy.fetchApi("/nynxz/h3studio/writer-guide").then((r) => r.text());

/** What the model is asked: the shot and what's around it, and how to redraft it. */
export function writerAsk(
  project: Project,
  sceneIndex: number,
  shotIndex: number,
  mode: WriterMode,
): string {
  const scene = project.scenes[sceneIndex]!;
  const shot = scene.shots[shotIndex]!;
  const end = scene.shots[shotIndex + 1]?.at ?? scene.seconds;
  const { width, height } = project.canvas;
  const shape = width > height ? "landscape" : width < height ? "portrait" : "square";
  const refs = project.refs
    .map((r) => `- @${r.name} (${r.kind ?? "image"})${r.note.trim() ? `: ${r.note.trim()}` : ""}`);
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
  const have = new Set((after.match(/@[\w-]+/g) ?? []).map((m) => m.toLowerCase()));
  return [...new Set((before.match(/@[\w-]+/g) ?? []).map((m) => m.toLowerCase()))].filter(
    (m) => !have.has(m),
  );
}

/** Queue the writer job and wait for its text. Rejects with ComfyUI's message if it fails. */
export async function runWriter(ask: string, seed: number): Promise<string> {
  if (!writerSettings.model) throw new Error("Pick a writer model first.");
  const prompt = {
    guide: { class_type: "PrimitiveStringMultiline", inputs: { value: await writerGuide() } },
    load: {
      class_type: "CLIPLoader",
      inputs: { clip_name: writerSettings.model, type: writerSettings.type, device: "default" },
    },
    write: {
      class_type: "TextGenerate",
      inputs: {
        clip: ["load", 0],
        prompt: ask,
        max_length: 400,
        sampling_mode: "on",
        "sampling_mode.temperature": writerSettings.temperature,
        "sampling_mode.top_k": 64,
        "sampling_mode.top_p": 0.95,
        "sampling_mode.min_p": 0.05,
        "sampling_mode.repetition_penalty": 1.05,
        "sampling_mode.seed": seed,
        thinking: false,
        use_default_template: true,
        system_prompt: ["guide", 0],
      },
    },
    show: { class_type: "PreviewAny", inputs: { source: ["write", 0] } },
  };
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
