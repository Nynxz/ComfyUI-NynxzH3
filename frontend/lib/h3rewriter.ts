// A whole scene rewritten by the MiniMax-H3 prompt-rewriter LoRA, in the format it was trained on:
// the request (`task / resolution / duration / original_prompt`) and system prompt come from the
// pack's rewrite nodes (/nynxz/h3studio/rewriter-prompt), the scene's first and last keyframes are
// its trained first and last frames, and its three-field answer is read back
// (/nynxz/h3studio/rewriter-clean) into the scene's script: [Shot N] At 00:03.500 → a shot at
// 0:03.5, overall_soundscape → ambience, non_diegetic_music → music. Dialogue stays the studio's own
// lines, kept with the shot they were said in; the rewriter's quoted copy of it is left out.
//
// The job is the writer model wired into H3 Studio Setup's `rewrite_clip` → Generate Text → Preview
// as Text, queued like the shot writer's (lib/h3writer.ts).
import { api } from "@comfy/api";
import type { Project, Scene, Shot } from "./h3studio";
import { speakerNames } from "./h3dialogue";
import { sceneToScript } from "./h3script";
import { pictureNodes, queueText, rewriteClipChain, sampling, type ApiNode } from "./h3writer";

interface ComfyApi {
  fetchApi(path: string, init?: RequestInit): Promise<Response>;
}
const comfy = api as unknown as ComfyApi;

const FRAME = 1 / 24;
/** 3.5 → "00:03.500", the rewriter's own timestamps. */
const stamp = (t: number) =>
  `${String(Math.floor(t / 60)).padStart(2, "0")}:${(t % 60).toFixed(3).padStart(6, "0")}`;
const ASPECTS: [string, number][] = [
  ["21:9", 21 / 9],
  ["16:9", 16 / 9],
  ["4:3", 4 / 3],
  ["1:1", 1],
  ["3:4", 3 / 4],
  ["9:16", 9 / 16],
];

/** The trained aspect closest to the canvas. */
function resolutionOf(project: Project): string {
  const ratio = project.canvas.width / project.canvas.height;
  return ASPECTS.reduce((best, a) =>
    Math.abs(Math.log(a[1] / ratio)) < Math.abs(Math.log(best[1] / ratio)) ? a : best,
  )[0];
}

/** The scene's keyframes the rewriter can take: its first frame and its last. */
function framesOf(scene: Scene) {
  const first = scene.keyframes.find((k) => k.media && k.at <= FRAME);
  const last = scene.keyframes.find((k) => k.media && k !== first && k.at >= scene.seconds - FRAME);
  const task = first && last ? "fl2va" : first ? "i2va" : last ? "l2va" : "t2va";
  return { task, frames: [first, last].filter((k) => k !== undefined) };
}

function spoken(project: Project, shot: Shot): string[] {
  return (shot.lines ?? [])
    .filter((l) => l.words.trim())
    .map((l) => {
      const how =
        l.mode === "voiceover"
          ? "says in an off-screen voiceover"
          : l.mode === "sing"
            ? "sings"
            : l.delivery
              ? `says (${l.delivery})`
              : "says";
      return `${speakerNames(project, l)} ${how}: "${l.words.trim()}"`;
    });
}

/** What the rewriter is asked to rewrite: the scene's shots at their times, what is said in each,
 *  its references described, and its style and sound. */
export function sceneRequest(project: Project, index: number): string {
  const scene = project.scenes[index]!;
  const shots = scene.shots.map((shot, j) => {
    const when = j === 0 ? "" : `At ${stamp(shot.at)}, `;
    const body = [shot.text.trim(), ...spoken(project, shot)].filter(Boolean).join(" ");
    return `[Shot ${j + 1}] ${when}${body || "(continues)"}`;
  });
  const refs = project.refs
    .filter((r) => r.note.trim() && scene.shots.some((s) => s.text.includes(`@${r.name}`)))
    .map((r) => `@${r.name} is ${r.note.trim()}`);
  const style = [project.style, scene.direction || project.direction].map((s) => s.trim());
  const soundscape = (scene.soundscape || project.soundscape).trim();
  const music = (scene.music || project.music).trim();
  return [
    ...shots,
    refs.length ? `References: ${refs.join("; ")}.` : "",
    style.some(Boolean) ? `Style: ${style.filter(Boolean).join(" ")}` : "",
    soundscape ? `Ambience: ${soundscape}` : "",
    music ? `Music: ${music}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

const DIALOGUE = /<d>[\s\S]*?<\/d>/g;
/** A rewritten shot as studio shot text: no quoted dialogue (the studio says its own lines), no
 *  speaker ids or speech markers. */
function shotText(text: string): string {
  const sentences = text
    .replace(DIALOGUE, "\u0000")
    .split(/(?<=[.!?])\s+/)
    .filter((s) => !s.includes("\u0000"));
  const clean = sentences
    .join(" ")
    .replace(/\s*\(S\d+\)/g, "")
    .replace(/<\/?(scenetrans|cutoff)>/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
  return clean.charAt(0).toUpperCase() + clean.slice(1);
}

/** `[Shot N] At 00:03.500, …` paragraphs as shots, in order and inside the scene. */
function shotsOf(description: string, seconds: number): { at: number; text: string }[] {
  const out: { at: number; text: string }[] = [];
  for (const part of description.split(/\[Shot \d+\]\s*/).slice(1)) {
    const m = /^At (\d+):(\d+(?:\.\d+)?),?\s*/i.exec(part);
    const at = out.length === 0 ? 0 : m ? Number(m[1]) * 60 + Number(m[2]) : NaN;
    if (!Number.isFinite(at) || at >= seconds || (out.length && at <= out.at(-1)!.at)) continue;
    out.push({
      at: Math.round(at * 1000) / 1000,
      text: shotText(m ? part.slice(m[0].length) : part),
    });
  }
  return out;
}

/** The scene's script with the rewriter's shots and sound in it, its dialogue kept with the new
 *  shot that covers when each line was said. */
function rewrittenScript(project: Project, index: number, fields: Record<string, string>): string {
  const scene = project.scenes[index]!;
  const found = shotsOf(fields.integrated_multimodal_description ?? "", scene.seconds);
  if (!found.length) throw new Error("The rewriter's answer had no [Shot 1] — try again.");
  const shots: Shot[] = found.map((s, j) => ({
    id: scene.shots[j]?.id ?? `rw${j}`,
    at: s.at,
    text: s.text,
    transition: "cut",
    lines: [],
  }));
  for (const old of scene.shots) {
    const into = [...shots].reverse().find((s) => s.at <= old.at + 0.01) ?? shots[0]!;
    into.lines!.push(...(old.lines ?? []));
  }
  const rewritten: Scene = {
    ...scene,
    shots,
    soundscape: fields.overall_soundscape?.trim() || scene.soundscape,
    music: fields.non_diegetic_music?.trim() || scene.music,
  };
  const scenes = project.scenes.map((s, i) => (i === index ? rewritten : s));
  return sceneToScript({ ...project, scenes }, index);
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await comfy.fetchApi(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const out = (await res.json()) as T & { error?: string };
  if (!res.ok) throw new Error(out.error ?? `${path} failed.`);
  return out;
}

/** Rewrite scene `index` with the writer model wired into Setup's `rewrite_clip`, and give back the
 *  scene's new script, to review and apply like a pasted one. */
export async function rewriteScene(project: Project, index: number, seed: number): Promise<string> {
  const scene = project.scenes[index];
  if (!scene) throw new Error("No such scene.");
  const chain = await rewriteClipChain();
  if (!chain)
    throw new Error(
      "Wire the rewriter (Qwen3-VL-8B + its LoRA) into H3 Studio Setup's rewrite_clip.",
    );
  const { task, frames } = framesOf(scene);
  const { text } = await post<{ text: string }>("/nynxz/h3studio/rewriter-prompt", {
    prompt: sceneRequest(project, index),
    task,
    resolution: frames.length ? "adaptive" : resolutionOf(project),
    duration: scene.seconds,
  });
  const scale = Math.min(1, 768 / Math.max(project.canvas.width, project.canvas.height));
  const side = (n: number) => Math.max(64, Math.round((n * scale) / 16) * 16);
  const prompt: Record<string, ApiNode> = {
    ...chain.nodes,
    ...(frames.length
      ? pictureNodes(
          frames.map((k) => ({ media: k.media, kind: "image" as const })),
          side(project.canvas.width),
          side(project.canvas.height),
        )
      : {}),
    write: {
      class_type: "TextGenerate",
      inputs: {
        clip: chain.clip,
        ...(frames.length ? { image: ["pictures", 0] } : {}),
        prompt: text,
        max_length: 2048,
        ...sampling(seed),
        use_default_template: false,
      },
    },
    show: { class_type: "PreviewAny", inputs: { source: ["write", 0] } },
  };
  const reply = await queueText(prompt);
  const { fields } = await post<{ fields: Record<string, string> }>(
    "/nynxz/h3studio/rewriter-clean",
    { text: reply },
  );
  return rewrittenScript(project, index, fields);
}
