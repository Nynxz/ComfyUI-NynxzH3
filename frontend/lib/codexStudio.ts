// Codex → H3 Studio: an entry becomes a reference the studio's shots can @mention (its picture,
// and its prompt line as the reference's description); a character also brings its voice into
// the cast and its LoRAs as lanes. Adding the same entry again updates what it added before.
import { app } from "@comfy/app";
import { mediaKind } from "@/framework";
import { coverOf, promptOf, type Entry, type Show } from "./codex";
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
  return `@${ref.name}`;
}
