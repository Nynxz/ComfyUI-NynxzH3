// The Codex: what a show is made of — its characters, places, props, looks and sounds, how they
// relate, and its episodes — kept once and used in every episode. How a show is laid out on disk
// is lib/codexStore.ts; pictures are ordinary media refs, uploaded into `input/codex/<id>/`.

export const ROOT = "nynxz-codex";

export type EntryKind = "character" | "place" | "prop" | "look" | "sound";

export interface KindInfo {
  label: string;
  plural: string;
  icon: string;
  /** What a mention looks like: `@mara`, `#booth`. */
  sigil: string;
  /** What its variants are called. */
  variants: string;
  hint: string;
  /** Its colour on the map and cards. */
  color: string;
}

export const KINDS: Record<EntryKind, KindInfo> = {
  character: {
    label: "Character",
    plural: "Characters",
    icon: "mdi mdi-account-outline",
    sigil: "@",
    variants: "Wardrobe",
    hint: "Faces, wardrobe, voices and LoRAs — set up once, used in every episode.",
    color: "#8b90ff",
  },
  place: {
    label: "Place",
    plural: "Places",
    icon: "mdi mdi-door-open",
    sigil: "#",
    variants: "Time of day",
    hint: "Rooms and locations, with how they look at different times.",
    color: "#3fb8a9",
  },
  prop: {
    label: "Prop",
    plural: "Props",
    icon: "mdi mdi-cube-outline",
    sigil: "#",
    variants: "States",
    hint: "Objects that have to look the same every time they appear.",
    color: "#e0a84a",
  },
  look: {
    label: "Look",
    plural: "Looks",
    icon: "mdi mdi-palette-outline",
    sigil: "%",
    variants: "Variants",
    hint: "Film stock, grade and light the scenes start from.",
    color: "#e27bb0",
  },
  sound: {
    label: "Sound",
    plural: "Sounds",
    icon: "mdi mdi-waveform",
    sigil: "~",
    variants: "Takes",
    hint: "Voice clips, music and sounds — link a voice to the character who speaks with it.",
    color: "#7cc56f",
  },
};
export const EPISODE_COLOR = "#b4b4c0";
export const KIND_ORDER: EntryKind[] = ["character", "place", "prop", "look", "sound"];

/** A relation from one entry to another, in words: "lives in", "voice", "sister of". */
export interface Link {
  to: string;
  label: string;
}
/** Labels offered when linking, by the kind linked to. */
export const LINK_LABELS: Record<EntryKind, string[]> = {
  character: ["knows", "family of", "works with", "against"],
  place: ["lives in", "works at", "found in"],
  prop: ["owns", "uses"],
  look: ["look"],
  sound: ["voice", "theme", "sound"],
};

export type EpisodeStatus = "idea" | "writing" | "making" | "done";
export const EPISODE_STATUS: { value: EpisodeStatus; label: string; icon: string }[] = [
  { value: "idea", label: "Idea", icon: "mdi mdi-lightbulb-outline" },
  { value: "writing", label: "Writing", icon: "mdi mdi-pencil-outline" },
  { value: "making", label: "Making", icon: "mdi mdi-movie-open-outline" },
  { value: "done", label: "Done", icon: "mdi mdi-check-circle-outline" },
];
export interface Episode {
  id: string;
  number: number;
  title: string;
  status: EpisodeStatus;
  /** What happens, in a sentence or two. */
  logline: string;
  /** Beats, scenes, anything — free text for now. */
  outline: string;
  /** Entries it uses (ids). */
  uses: string[];
  notes: string;
}

/** An H3 Studio project saved into the show — a cut of (part of) an episode, to come back to. */
export interface Film {
  id: string;
  name: string;
  /** The episode it belongs to (id), "" for none. */
  episode: string;
  /** The whole H3 Studio project, as the studio keeps it. */
  project: Record<string, unknown>;
  updated: number;
}

export interface Picture {
  media: string;
  label: string;
}
export interface Variant {
  id: string;
  name: string;
  /** Added to the entry's prompt line when this variant is used. */
  prompt: string;
  pictures: Picture[];
}
export interface EntryVoice {
  /** How it sounds, e.g. "a low, dry female voice". */
  description: string;
  language: string;
}
export interface EntryLora {
  name: string;
  strength: number;
}
export interface Entry {
  id: string;
  kind: EntryKind;
  name: string;
  /** What a mention is written as, without its sigil. */
  handle: string;
  /** For people: who this is, in a line or two. */
  about: string;
  /** What a shot gets when it mentions this entry. */
  prompt: string;
  tags: string[];
  pictures: Picture[];
  /** The picture that stands for it (a media ref), else the first. */
  cover: string;
  variants: Variant[];
  voice: EntryVoice;
  loras: EntryLora[];
  links: Link[];
  /** The folder it sits in ("Main cast/Family"), "" for none. */
  folder: string;
  notes: string;
  updated: number;
}

export interface Show {
  v: 2;
  id: string;
  name: string;
  /** The show in a sentence. */
  logline: string;
  entries: Entry[];
  episodes: Episode[];
  notes: string;
  /** Every folder ("Main cast", "Main cast/Family"), empty ones included. */
  folders: string[];
  films: Film[];
  /** Where each node sits on the map (entry and episode ids), once placed. */
  map: Record<string, { x: number; y: number }>;
}

export const uid = () => Math.random().toString(36).slice(2, 10);

export const handleOf = (name: string) =>
  name
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "untitled";

export function newEntry(kind: EntryKind, name = ""): Entry {
  const fallback = `New ${KINDS[kind].label.toLowerCase()}`;
  return {
    id: uid(),
    kind,
    name: name || fallback,
    handle: handleOf(name || fallback),
    about: "",
    prompt: "",
    tags: [],
    pictures: [],
    cover: "",
    variants: [],
    voice: { description: "", language: "English" },
    loras: [],
    links: [],
    folder: "",
    notes: "",
    updated: Date.now(),
  };
}

export function newEpisode(show: Show): Episode {
  const number = Math.max(0, ...show.episodes.map((e) => e.number)) + 1;
  return {
    id: uid(),
    number,
    title: "",
    status: "idea",
    logline: "",
    outline: "",
    uses: [],
    notes: "",
  };
}

/** How many scenes, and how long, a film's project runs. */
export function filmSummary(f: Film): string {
  const scenes = Array.isArray(f.project.scenes)
    ? (f.project.scenes as { seconds?: number }[])
    : [];
  const seconds = scenes.reduce((t, s) => t + (Number(s.seconds) || 0), 0);
  return `${scenes.length} scene${scenes.length === 1 ? "" : "s"} · ${seconds.toFixed(1)}s`;
}

export const episodeName = (e: Episode) =>
  `E${String(e.number).padStart(2, "0")}${e.title ? ` · ${e.title}` : ""}`;

export const newVariant = (name: string): Variant => ({
  id: uid(),
  name,
  prompt: "",
  pictures: [],
});

export const coverOf = (e: Entry) => e.cover || e.pictures[0]?.media || "";

export const mentionOf = (e: Entry) => `${KINDS[e.kind].sigil}${e.handle}`;

/** The prompt line a shot gets for this entry, with a variant's words when one is picked. */
export function promptOf(e: Entry, variantId?: string): string {
  const v = e.variants.find((x) => x.id === variantId);
  return [e.prompt.trim(), v?.prompt.trim()].filter(Boolean).join(", ");
}

export function toEntry(raw: Partial<Entry>): Entry {
  const kind = raw.kind && raw.kind in KINDS ? raw.kind : "character";
  const base = newEntry(kind, raw.name);
  return {
    ...base,
    ...raw,
    kind,
    tags: Array.isArray(raw.tags) ? raw.tags.map(String) : [],
    pictures: Array.isArray(raw.pictures) ? raw.pictures : [],
    variants: Array.isArray(raw.variants) ? raw.variants : [],
    voice: { ...base.voice, ...(raw.voice ?? {}) },
    loras: Array.isArray(raw.loras) ? raw.loras : [],
    links: Array.isArray(raw.links) ? raw.links.filter((l) => l && typeof l.to === "string") : [],
    folder: typeof raw.folder === "string" ? cleanFolder(raw.folder) : "",
  };
}

export function toEpisode(raw: Partial<Episode>, i: number): Episode {
  return {
    id: raw.id || uid(),
    number: typeof raw.number === "number" ? raw.number : i + 1,
    title: raw.title ?? "",
    status: EPISODE_STATUS.some((s) => s.value === raw.status) ? raw.status! : "idea",
    logline: raw.logline ?? "",
    outline: raw.outline ?? "",
    uses: Array.isArray(raw.uses) ? raw.uses.map(String) : [],
    notes: raw.notes ?? "",
  };
}

export function toShow(raw: unknown, id: string): Show {
  const o = (raw && typeof raw === "object" ? raw : {}) as Partial<Show>;
  return {
    v: 2,
    id,
    name: typeof o.name === "string" && o.name ? o.name : "Untitled show",
    logline: typeof o.logline === "string" ? o.logline : "",
    entries: Array.isArray(o.entries) ? o.entries.map(toEntry) : [],
    episodes: Array.isArray(o.episodes) ? o.episodes.map(toEpisode) : [],
    notes: typeof o.notes === "string" ? o.notes : "",
    films: Array.isArray(o.films) ? o.films.filter((f) => f && typeof f.project === "object") : [],
    folders: Array.isArray(o.folders)
      ? [...new Set(o.folders.map(cleanFolder).filter(Boolean))]
      : [],
    map: o.map && typeof o.map === "object" ? o.map : {},
  };
}

/** A folder path as stored: trimmed segments joined by "/", nothing a file path would trip on. */
export function cleanFolder(path: string): string {
  return path
    .split("/")
    .map((seg) => seg.replace(/[\\:*?"<>|]+/g, "").trim())
    .filter((seg) => seg && seg !== "." && seg !== "..")
    .join("/");
}

/** A handle no other entry in the show uses yet: `base`, then `base-2`, … */
export function freeHandle(show: Show, base: string, except?: string): string {
  const taken = new Set(show.entries.filter((e) => e.id !== except).map((e) => e.handle));
  let handle = base;
  for (let n = 2; taken.has(handle); n++) handle = `${base}-${n}`;
  return handle;
}

/** Where a show's uploaded pictures go, under ComfyUI's input folder. */
export const uploadsOf = (showId: string) => `codex/${showId}`;

/** Every link touching `id`, either way: those it makes and those made to it. */
export function linksOf(show: Show, id: string): { entry: Entry; label: string; out: boolean }[] {
  const byId = new Map(show.entries.map((e) => [e.id, e]));
  const self = byId.get(id);
  const out = (self?.links ?? []).flatMap((l) => {
    const entry = byId.get(l.to);
    return entry ? [{ entry, label: l.label, out: true }] : [];
  });
  const back = show.entries.flatMap((e) =>
    e.links.filter((l) => l.to === id).map((l) => ({ entry: e, label: l.label, out: false })),
  );
  return [...out, ...back];
}

/** Remove an entry and everything pointing at it. */
export function removeEntry(show: Show, id: string) {
  show.entries = show.entries.filter((e) => e.id !== id);
  for (const e of show.entries) e.links = e.links.filter((l) => l.to !== id);
  for (const ep of show.episodes) ep.uses = ep.uses.filter((u) => u !== id);
  delete show.map[id];
}

/** The whole show as plain text — for a writing agent, or anyone — with every entry's prompt
 *  line, how things relate, and the episodes. */
export function showContext(show: Show): string {
  const byId = new Map(show.entries.map((e) => [e.id, e]));
  const lines: string[] = [`# ${show.name}`];
  if (show.logline.trim()) lines.push("", show.logline.trim());
  if (show.notes.trim()) lines.push("", "## Show notes", "", show.notes.trim());
  for (const kind of KIND_ORDER) {
    const list = show.entries.filter((e) => e.kind === kind);
    if (!list.length) continue;
    lines.push("", `## ${KINDS[kind].plural}`);
    for (const e of list) {
      lines.push("", `### ${e.name} (${mentionOf(e)})`);
      if (e.about.trim()) lines.push(e.about.trim());
      if (e.prompt.trim()) lines.push(`Looks: ${e.prompt.trim()}`);
      for (const v of e.variants)
        lines.push(`- ${KINDS[kind].variants} "${v.name}": ${v.prompt.trim() || "(no words yet)"}`);
      if (e.kind === "character" && e.voice.description.trim())
        lines.push(`Voice: ${e.voice.description.trim()} (${e.voice.language})`);
      for (const l of e.links) {
        const to = byId.get(l.to);
        if (to) lines.push(`- ${l.label || "linked to"} ${to.name} (${mentionOf(to)})`);
      }
      if (e.tags.length) lines.push(`Tags: ${e.tags.join(", ")}`);
      if (e.notes.trim()) lines.push(`Notes: ${e.notes.trim()}`);
    }
  }
  if (show.episodes.length) {
    lines.push("", "## Episodes");
    for (const ep of [...show.episodes].sort((a, b) => a.number - b.number)) {
      lines.push("", `### ${episodeName(ep)} — ${ep.status}`);
      if (ep.logline.trim()) lines.push(ep.logline.trim());
      const uses = ep.uses.flatMap((u) => (byId.has(u) ? [mentionOf(byId.get(u)!)] : []));
      if (uses.length) lines.push(`Uses: ${uses.join(", ")}`);
      const films = show.films.filter((f) => f.episode === ep.id).map((f) => f.name);
      if (films.length) lines.push(`Films (H3 Studio): ${films.join(", ")}`);
      if (ep.outline.trim()) lines.push("", ep.outline.trim());
    }
  }
  return lines.join("\n") + "\n";
}
