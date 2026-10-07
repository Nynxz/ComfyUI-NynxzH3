// H3 Studio's edits: every change the editor makes to a project, as plain functions of it. The
// editor adds what follows from an edit (what gets selected, where the playhead goes); each call
// here is one step of undo.
import { mediaKind } from "@/framework";
import { newScene, placeAt, randomSeed, sceneStarts, snapSeconds, uid, type Keyframe, type Project, type Ref, type Scene, type Shot } from "./h3studio";
import { moveLine } from "./h3dialogue";
import { edgeOf } from "./h3tracks";

// --- the whole project ----------------------------------------------------------------------------
/** What clearing the project would remove. */
export function projectContents(project: Project) {
  return {
    scenes: project.scenes.length,
    shots: project.scenes.reduce((n, s) => n + s.shots.length, 0),
    lines: project.scenes.reduce((n, s) => n + s.shots.reduce((m, sh) => m + (sh.lines?.length ?? 0), 0), 0),
    keyframes: project.scenes.reduce((n, s) => n + s.keyframes.length, 0),
    refs: project.refs.length,
    voices: project.cast?.length ?? 0,
    loras: project.loras?.length ?? 0,
  };
}
/** Start over: one empty scene and nothing else. The canvas, the settings and the layout stay. */
export function clearProject(project: Project) {
  const first = newScene();
  first.continuation.mode = "cut";
  project.scenes = [first];
  project.refs = [];
  project.cast = [];
  project.loras = [];
  project.style = "";
  project.soundscape = "";
  project.music = "";
  project.active = 0;
}

// --- scenes ---------------------------------------------------------------------------------------
export function setSeconds(project: Project, i: number, v: number) {
  const s = project.scenes[i]!;
  s.seconds = snapSeconds(Math.min(Math.max(v, 1), 30));
  for (const shot of s.shots.slice(1)) shot.at = Math.min(shot.at, Math.max(0.25, s.seconds - 0.25));
  for (const k of s.keyframes) k.at = Math.min(k.at, s.seconds);
}
/** The first scene always cuts in: there is nothing before it to continue from. */
function firstCuts(project: Project) {
  project.scenes[0]!.continuation.mode = "cut";
}
export function insertScene(project: Project, at: number): Scene {
  const scene = newScene();
  project.scenes.splice(at, 0, scene);
  firstCuts(project);
  return scene;
}
export function duplicateScene(project: Project, i: number): Scene {
  const copy = JSON.parse(JSON.stringify(project.scenes[i])) as Scene;
  copy.id = uid("s");
  copy.seed = randomSeed();
  for (const sh of copy.shots) {
    sh.id = uid("sh");
    for (const l of sh.lines ?? []) l.id = uid("d");
  }
  for (const k of copy.keyframes) k.id = uid("k");
  project.scenes.splice(i + 1, 0, copy);
  return copy;
}
export function moveScene(project: Project, i: number, by: number) {
  const [moved] = project.scenes.splice(i, 1);
  project.scenes.splice(i + by, 0, moved!);
  firstCuts(project);
}
export function removeScene(project: Project, i: number): boolean {
  if (project.scenes.length < 2) return false;
  project.scenes.splice(i, 1);
  firstCuts(project);
  return true;
}

// --- shots ----------------------------------------------------------------------------------------
export function findShot(project: Project, id: string): { scene: number; shot: number } | null {
  for (let si = 0; si < project.scenes.length; si++) {
    const shot = project.scenes[si]!.shots.findIndex((x) => x.id === id);
    if (shot >= 0) return { scene: si, shot };
  }
  return null;
}
/** A new shot starting at film time `t`, or null when that's too close to a cut or an edge. */
export function splitShotAt(project: Project, t: number): Shot | null {
  const p = placeAt(project, t);
  const s = project.scenes[p.scene]!;
  const at = Math.round(p.local * 100) / 100;
  if (at <= 0.25 || at >= s.seconds - 0.25 || s.shots.some((x) => Math.abs(x.at - at) < 0.25)) return null;
  const shot: Shot = { id: uid("sh"), at, text: "" };
  s.shots.push(shot);
  s.shots.sort((a, b) => a.at - b.at);
  return shot;
}
/** A new shot in scene `i`: the last shot split at its middle. */
export function addShotTo(project: Project, i: number): Shot | null {
  const scene = project.scenes[i];
  if (!scene) return null;
  const last = scene.shots[scene.shots.length - 1]!;
  return splitShotAt(project, (sceneStarts(project)[i] ?? 0) + (last.at + scene.seconds) / 2);
}
export function removeShot(project: Project, id: string): boolean {
  const at = findShot(project, id);
  if (!at) return false;
  const s = project.scenes[at.scene]!;
  if (s.shots.length < 2) return false;
  s.shots.splice(at.shot, 1);
  s.shots[0]!.at = 0;
  return true;
}
/** Move shot `id` to start at film time `t`, kept a little inside its neighbours. */
export function moveShot(project: Project, id: string, t: number) {
  const at = findShot(project, id);
  if (!at || at.shot === 0) return;
  const s = project.scenes[at.scene]!;
  const lo = s.shots[at.shot - 1]!.at + 0.25;
  const hi = (s.shots[at.shot + 1]?.at ?? s.seconds) - 0.25;
  s.shots[at.shot]!.at = Math.round(Math.min(Math.max(t - sceneStarts(project)[at.scene]!, lo), hi) * 100) / 100;
}
/** Move a scene's shot from place `from` to place `to`. Each shot keeps its length, text and lines;
 *  the cuts are worked out again in the new order, and lines placed in time move with their shot. */
export function reorderShot(project: Project, sceneIndex: number, from: number, to: number) {
  const s = project.scenes[sceneIndex];
  if (!s || from === to || !s.shots[from] || !s.shots[to]) return;
  const spans = s.shots.map((sh, i) => ({ shot: sh, length: (s.shots[i + 1]?.at ?? s.seconds) - sh.at }));
  const [moving] = spans.splice(from, 1);
  spans.splice(to, 0, moving!);
  let at = 0;
  for (const { shot, length } of spans) {
    const by = at - shot.at;
    for (const line of shot.lines ?? []) if (line.at !== undefined) line.at = Math.round((line.at + by) * 100) / 100;
    shot.at = Math.round(at * 100) / 100;
    at += length;
  }
  s.shots = spans.map((x) => x.shot);
}
/** A shot dragged along the timeline and dropped with its start at film time `t`. Dragged left, it
 *  goes before every shot whose middle its start passed; dragged right, after every shot whose
 *  middle its end passed. Shots stay in their scene. */
export function dropShot(project: Project, id: string, t: number) {
  const at = findShot(project, id);
  if (!at) return;
  const s = project.scenes[at.scene]!;
  const shot = s.shots[at.shot]!;
  const local = t - sceneStarts(project)[at.scene]!;
  const length = (s.shots[at.shot + 1]?.at ?? s.seconds) - shot.at;
  const edge = local < shot.at ? local : local + length;
  const mids = s.shots
    .map((sh, i) => ({ sh, mid: (sh.at + (s.shots[i + 1]?.at ?? s.seconds)) / 2 }))
    .filter((x) => x.sh !== shot);
  reorderShot(project, at.scene, at.shot, mids.filter((x) => x.mid < edge).length);
}
export function mentionInShot(project: Project, name: string, scene: number, shot: number) {
  const sh = project.scenes[scene]!.shots[shot]!;
  sh.text = `${sh.text.trimEnd()} @${name} `.trimStart();
}

// --- keyframes ------------------------------------------------------------------------------------
/** Put a keyframe at `at` in a scene, replacing one already on that edge. */
export function setKeyframe(project: Project, sceneIndex: number, at: number, media: string): Keyframe {
  const s = project.scenes[sceneIndex]!;
  const edge = edgeOf(project, sceneIndex, at);
  if (edge) s.keyframes = s.keyframes.filter((k) => edgeOf(project, sceneIndex, k.at) !== edge);
  const k = { id: uid("k"), at, media };
  s.keyframes.push(k);
  return k;
}
/** A keyframe at film time `t`; near a scene's edge (where the empty slots sit) means that edge. */
export function addKeyframe(project: Project, t: number, media: string): Keyframe {
  const p = placeAt(project, t);
  const s = project.scenes[p.scene]!;
  const at = p.local < 0.4 ? 0 : p.local > s.seconds - 0.4 ? s.seconds : Math.round(p.local * 100) / 100;
  return setKeyframe(project, p.scene, at, media);
}
export function moveKeyframe(project: Project, id: string, t: number) {
  const si = project.scenes.findIndex((s) => s.keyframes.some((k) => k.id === id));
  if (si < 0) return;
  const s = project.scenes[si]!;
  const k = s.keyframes.find((x) => x.id === id)!;
  const local = t - sceneStarts(project)[si]!;
  k.at = local < 0.1 ? 0 : local > s.seconds - 0.1 ? s.seconds : Math.round(local * 100) / 100;
}
export function removeKeyframe(project: Project, id: string) {
  for (const s of project.scenes) s.keyframes = s.keyframes.filter((k) => k.id !== id);
}

// --- references -----------------------------------------------------------------------------------
function nameFor(project: Project, media: string): string {
  const base = (media.split("/").pop() ?? "ref").replace(/\.[^.]+$/, "").replace(/[^\w-]+/g, "_").slice(0, 20) || "ref";
  let name = base;
  for (let n = 2; project.refs.some((r) => r.name === name); n++) name = `${base}${n}`;
  return name;
}
export function addRefs(project: Project, media: string[]): Ref[] {
  const added = media.map((m): Ref => {
    const ref: Ref = {
      id: uid("r"),
      media: m,
      kind: mediaKind(m),
      name: nameFor(project, m),
      note: "",
      role: "reference",
      retain: mediaKind(m) === "audio" ? "reference" : "fully_preserved",
      scenes: [],
    };
    project.refs.push(ref);
    return ref;
  });
  return added;
}
/** A unique reference name from `base` ("anna", then "anna2", …). */
export function freeRefName(project: Project, base: string): string {
  const clean = base.replace(/[^\w-]+/g, "_").slice(0, 20) || "ref";
  let name = clean;
  for (let n = 2; project.refs.some((r) => r.name.toLowerCase() === name.toLowerCase()); n++) name = `${clean}${n}`;
  return name;
}
/** A proxy: a named reference with no media yet, described in words until it gets some. */
export function addProxy(
  project: Project,
  name = "character",
  note = "",
  kind: Ref["kind"] = "image",
  role: Ref["role"] = "reference",
): Ref {
  const ref: Ref = { id: uid("r"), media: "", kind, name: freeRefName(project, name), note, role, retain: kind === "audio" ? "reference" : "fully_preserved", scenes: [] };
  project.refs.push(ref);
  return ref;
}
/** Give a reference its media, or swap it — the name (and every @mention) stays. */
export function setRefMedia(project: Project, id: string, media: string) {
  const r = project.refs.find((x) => x.id === id);
  if (!r) return;
  r.media = media;
  r.kind = mediaKind(media);
  if (r.role === "blocking" && r.kind !== "video") r.role = "reference";
  if (r.role === "semantic" && r.kind !== "image") r.role = "reference";
  if (r.kind === "audio" && r.retain !== "reference") r.retain = "reference";
}
export function removeRef(project: Project, id: string) {
  project.refs = project.refs.filter((r) => r.id !== id);
}
export function toggleRefScene(project: Project, refId: string, sceneId: string) {
  const r = project.refs.find((x) => x.id === refId);
  if (!r) return;
  const current = r.scenes === "all" ? project.scenes.map((s) => s.id) : r.scenes;
  r.scenes = current.includes(sceneId) ? current.filter((id) => id !== sceneId) : [...current, sceneId];
}

// --- dialogue -------------------------------------------------------------------------------------
export function findLine(project: Project, id: string) {
  for (const scene of project.scenes)
    for (const shot of scene.shots) {
      const line = shot.lines?.find((l) => l.id === id);
      if (line) return { scene, shot, line };
    }
  return null;
}
/** A line dropped at film time `t` — into another scene if that's where it landed. */
export function dropLine(project: Project, id: string, t: number) {
  const found = findLine(project, id);
  if (!found) return;
  const si = placeAt(project, t).scene;
  const into = project.scenes[si]!;
  if (into !== found.scene) {
    found.shot.lines = found.shot.lines!.filter((l) => l !== found.line);
    into.shots[0]!.lines = [...(into.shots[0]!.lines ?? []), found.line];
  }
  moveLine(into, id, t - sceneStarts(project)[si]!);
}

// --- track order ----------------------------------------------------------------------------------
/** `list` with the item whose track is `trackId` moved to just before `beforeId`'s (or the end). */
function reorder<T extends { id: string }>(list: T[], prefix: string, trackId: string, beforeId: string | null): T[] | null {
  const moving = list.find((x) => `${prefix}${x.id}` === trackId);
  if (!moving) return null;
  const rest = list.filter((x) => x !== moving);
  const at = beforeId?.startsWith(prefix) ? rest.findIndex((x) => `${prefix}${x.id}` === beforeId) : rest.length;
  rest.splice(at < 0 ? rest.length : at, 0, moving);
  return rest;
}
/** A lane dragged up or down. A reference's order is H3's numbering (<Picture 1>, …). */
export function reorderTrack(project: Project, trackId: string, beforeId: string | null) {
  if (trackId.startsWith("voice:")) project.cast = reorder(project.cast ?? [], "voice:", trackId, beforeId) ?? project.cast;
  else if (trackId.startsWith("lora:")) project.loras = reorder(project.loras ?? [], "lora:", trackId, beforeId) ?? project.loras;
  else project.refs = reorder(project.refs, "ref:", trackId, beforeId) ?? project.refs;
}
