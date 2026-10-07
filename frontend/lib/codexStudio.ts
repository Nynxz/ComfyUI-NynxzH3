// Codex → H3 Studio: an entry becomes a reference the studio's shots can @mention (its picture,
// and its prompt line as the reference's description); a character also brings its voice into
// the cast and its LoRAs as lanes. Adding the same entry again updates what it added before.
import { app } from "@comfy/app";
import { mediaKind } from "@/framework";
import {
  coverOf,
  freeHandle,
  handleOf,
  newEntry,
  promptOf,
  type Entry,
  type EntryKind,
  type Show,
} from "./codex";
import { withShow } from "./codexStore";
import { freeRefName } from "./h3edits";
import { newLoraLane, uid, useProject, type Project, type Ref } from "./h3studio";

interface GraphNode {
  id: number | string;
  type: string;
  title?: string;
  widgets?: { name: string; value: unknown; callback?: (v: unknown) => void }[];
}

export interface StudioTarget {
  id: string;
  label: string;
  project: Project;
}

/** The H3 Studios in the open workflow, each with its live project. */
export function studiosInGraph(): StudioTarget[] {
  const nodes = (app as { graph?: { nodes?: GraphNode[] } }).graph?.nodes ?? [];
  return nodes
    .filter((n) => n.type === "nynxz.H3.Studio")
    .flatMap((n) => {
      const widget = n.widgets?.find((w) => w.name === "project");
      if (!widget) return [];
      const project = useProject(widget);
      const scenes = project.scenes.length;
      return [
        {
          id: String(n.id),
          label: `#${n.id} · ${n.title || "H3 Studio"} — ${scenes} scene${scenes === 1 ? "" : "s"}`,
          project,
        },
      ];
    });
}

/** The reference this entry added before (its `codex` id), if it's still there. */
const refFor = (project: Project, entry: Entry) =>
  project.refs.find((r) => (r as Ref & { codex?: string }).codex === entry.id);

/** The reference `entry` added to `project` before, brought up to date, or a new one. */
function upsertRef(project: Project, entry: Entry, media: string, note: string): Ref {
  let ref = refFor(project, entry);
  if (ref) {
    if (media) {
      ref.media = media;
      ref.kind = mediaKind(media);
    }
    ref.note = note;
  } else {
    ref = {
      id: uid("r"),
      media,
      kind: media ? mediaKind(media) : "image",
      name: freeRefName(project, entry.handle),
      note,
      role: "reference",
      retain: media && mediaKind(media) === "audio" ? "reference" : "fully_preserved",
      scenes: [],
    } as Ref;
    (ref as Ref & { codex?: string }).codex = entry.id;
    project.refs.push(ref);
  }
  return ref;
}

/** Put `entry` into `project`, in `variantId`'s version when given. A character also brings its
 *  voice: the clip of the sound linked as its "voice" becomes its timbre. Returns the mention. */
export function addToStudio(
  project: Project,
  entry: Entry,
  show: Show,
  variantId?: string,
): string {
  const variant = entry.variants.find((v) => v.id === variantId);
  const media = variant?.pictures[0]?.media || coverOf(entry);
  const ref = upsertRef(project, entry, media, promptOf(entry, variantId));
  bringCharacter(project, entry, show, ref);
  return `@${ref.name}`;
}

/** A character's voice (and the clip of the sound linked as its "voice") into the cast, and its
 *  LoRAs as lanes. Nothing for other kinds. */
function bringCharacter(project: Project, entry: Entry, show: Show, ref: Ref) {
  if (entry.kind === "character") {
    const sound = show.entries.find(
      (e) => e.id === entry.links.find((l) => l.label === "voice")?.to,
    );
    const clip = sound?.pictures.find((p) => mediaKind(p.media) === "audio")?.media;
    const timbre = sound && clip ? upsertRef(project, sound, clip, promptOf(sound)).id : "";
    project.cast ??= [];
    const voice = project.cast.find((v) => v.ref === ref.id);
    if (voice) {
      voice.name = entry.name;
      if (timbre) voice.timbre = timbre;
      if (entry.voice.description) voice.voice = entry.voice.description;
      if (entry.voice.language) voice.language = entry.voice.language;
    } else if (entry.voice.description || timbre) {
      project.cast.push({
        id: uid("v"),
        name: entry.name,
        ref: ref.id,
        timbre,
        voice: entry.voice.description,
        language: entry.voice.language || "English",
      });
    }
    for (const lora of entry.loras) {
      const lane = project.loras?.find((l) => l.name === lora.name);
      if (lane) lane.strength = lora.strength;
      else
        project.loras = [
          ...(project.loras ?? []),
          { ...newLoraLane(lora.name), strength: lora.strength },
        ];
    }
  }
}

// --- a whole studio against a show -------------------------------------------------------------
// A script writes @ren as a placeholder; the show already has Ren. These match the two by name
// (`@spoon_interior` and the handle `spoon-interior` are the same), so a pasted act gets its
// pictures and descriptions from the Codex — and placeholders the Codex lacks can start entries.

const codexOf = (r: Ref) => (r as Ref & { codex?: string }).codex;

export interface CodexMatch {
  ref: Ref;
  entry: Entry;
  /** Already tied to this entry (by an earlier fill or an add), rather than matched by name. */
  linked: boolean;
}

/** Each reference of `project` that has an entry in `show`: tied to it before, else same name. */
export function matchRefs(project: Project, show: Show): { matches: CodexMatch[]; missing: Ref[] } {
  const matches: CodexMatch[] = [];
  const missing: Ref[] = [];
  for (const ref of project.refs) {
    if (ref.name === "setting") continue;
    const tied = show.entries.find((e) => e.id === codexOf(ref));
    const named = tied ?? show.entries.find((e) => e.handle === handleOf(ref.name));
    if (named) matches.push({ ref, entry: named, linked: !!tied });
    else if (!ref.media) missing.push(ref);
  }
  return { matches, missing };
}

/** Bring the matched references up to date from the Codex: the entry's picture (over a
 *  placeholder, or over an earlier fill — never over a picture you dropped in yourself), its
 *  prompt line as the description, and a character's voice and LoRAs. Returns what changed. */
export function fillFromCodex(project: Project, show: Show): string[] {
  const changed: string[] = [];
  for (const { ref, entry, linked } of matchRefs(project, show).matches) {
    const cover = coverOf(entry);
    const before = `${ref.media}|${ref.note}`;
    if (cover && (!ref.media || linked)) {
      ref.media = cover;
      ref.kind = mediaKind(cover);
    }
    const line = promptOf(entry);
    if (line) ref.note = line;
    (ref as Ref & { codex?: string }).codex = entry.id;
    bringCharacter(project, entry, show, ref);
    if (`${ref.media}|${ref.note}` !== before || !linked) changed.push(`@${ref.name}`);
  }
  return changed;
}

const nameOf = (handle: string) =>
  handle.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

/** Start Codex entries from placeholders the show doesn't have: the name from the @name, the
 *  description as its prompt line, its picture if it has one, and — for a character with a
 *  voice in the cast — that voice. The references are tied to the new entries. */
export async function addToCodex(
  project: Project,
  showId: string,
  rows: { ref: Ref; kind: EntryKind }[],
): Promise<number> {
  const made = await withShow(showId, (show) =>
    rows.map(({ ref, kind }) => {
      const entry = newEntry(kind, nameOf(ref.name));
      entry.handle = freeHandle(show, handleOf(ref.name));
      entry.prompt = ref.note.trim();
      if (ref.media) {
        entry.pictures = [{ media: ref.media, label: "" }];
        entry.cover = ref.media;
      }
      const voice = project.cast?.find((v) => v.ref === ref.id);
      if (kind === "character" && voice) {
        entry.name = voice.name || entry.name;
        entry.voice = { description: voice.voice ?? "", language: voice.language || "English" };
      }
      entry.updated = Date.now();
      show.entries.push(entry);
      return { ref, id: entry.id };
    }),
  );
  for (const { ref, id } of made) (ref as Ref & { codex?: string }).codex = id;
  return made.length;
}
