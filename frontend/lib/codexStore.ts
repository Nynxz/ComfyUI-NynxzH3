// How a show sits on disk, under the ComfyUI user directory. It is laid out to be read — and
// edited — by people and AI without the Codex open; README.md in each show says how:
//
//   nynxz-codex/<show>/
//     README.md                     the format, for whoever opens the folder
//     show.json                     name, logline, folders, map positions
//     notes.md                      the show notes
//     CODEX.md                      the whole show as one text (rewritten on every save)
//     codex/<folder>/<handle>.json  one file per entry, in the folder it sits in
//     episodes/e01-<title>.json     one file per episode
//     films/e01-<name>.json         H3 Studio projects saved into the show, by episode
//
// Files refer to each other by mention (`@mara`, `#booth`), never by internal id, and leave out
// what's empty. Saving writes only what changed and deletes what went away; a change made on disk
// by someone else is picked up and the show reloads.
import { reactive, watch } from "vue";
import { api } from "@comfy/api";
import {
  KINDS,
  ROOT,
  cleanFolder,
  handleOf,
  mentionOf,
  showContext,
  toEntry,
  toEpisode,
  toShow,
  uid,
  type Entry,
  type EntryKind,
  type Episode,
  type Film,
  type Show,
} from "./codex";

interface UserApi {
  getUserData(file: string): Promise<Response>;
  storeUserData(
    file: string,
    data: unknown,
    options: { overwrite: boolean; stringify: boolean; throwOnError: boolean },
  ): Promise<Response>;
  deleteUserData(file: string): Promise<Response>;
  listUserDataFullInfo(dir: string): Promise<{ path: string; modified: number }[]>;
}
const user = api as unknown as UserApi;

const dirOf = (id: string) => `${ROOT}/${id}`;
const json = (v: unknown) => `${JSON.stringify(v, null, 2)}\n`;
const epKey = (ep: Episode) => `e${String(ep.number).padStart(2, "0")}`;

// --- writing ---------------------------------------------------------------------------------------

/** Only the fields that say something, in the order given. */
function compact(o: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(o)) {
    if (v === undefined || v === "" || v === null) continue;
    if (Array.isArray(v) && !v.length) continue;
    out[k] = v;
  }
  return out;
}

const pictureJson = (p: { media: string; label: string }) =>
  p.label ? { media: p.media, label: p.label } : p.media;

function entryJson(e: Entry, mention: (id: string) => string | null) {
  return compact({
    kind: e.kind,
    name: e.name,
    handle: e.handle,
    about: e.about,
    prompt: e.prompt,
    tags: e.tags,
    pictures: e.pictures.map(pictureJson),
    cover: e.cover && e.cover !== e.pictures[0]?.media ? e.cover : "",
    variants: e.variants.map((v) =>
      compact({ name: v.name, prompt: v.prompt, pictures: v.pictures.map(pictureJson) }),
    ),
    voice:
      e.kind === "character" && e.voice.description
        ? compact({ description: e.voice.description, language: e.voice.language })
        : undefined,
    loras: e.loras,
    links: e.links.flatMap((l) => {
      const to = mention(l.to);
      return to ? [compact({ to, label: l.label })] : [];
    }),
    notes: e.notes,
  });
}

function episodeFile(ep: Episode, taken: Set<string>) {
  const base = `episodes/${epKey(ep)}${ep.title ? `-${handleOf(ep.title)}` : ""}`;
  let path = `${base}.json`;
  for (let n = 2; taken.has(path); n++) path = `${base}-${n}.json`;
  taken.add(path);
  return path;
}

/** Every file the show is, by path inside its folder, with its contents. */
function filesOf(show: Show): Map<string, string> {
  const byId = new Map(show.entries.map((e) => [e.id, e]));
  const mention = (id: string) => {
    const e = byId.get(id);
    return e ? mentionOf(e) : null;
  };
  const epById = new Map(show.episodes.map((ep) => [ep.id, ep]));
  const mapOut: Record<string, { x: number; y: number }> = {};
  for (const [id, p] of Object.entries(show.map)) {
    const ep = epById.get(id);
    const key = mention(id) ?? (ep ? epKey(ep) : null);
    if (key) mapOut[key] = p;
  }
  const files = new Map<string, string>();
  files.set("README.md", README);
  files.set(
    "show.json",
    json(compact({ name: show.name, logline: show.logline, folders: show.folders, map: mapOut })),
  );
  files.set("notes.md", show.notes.endsWith("\n") || !show.notes ? show.notes : `${show.notes}\n`);
  files.set("CODEX.md", showContext(show));
  for (const e of show.entries)
    files.set(
      `codex/${e.folder ? `${e.folder}/` : ""}${e.handle}.json`,
      json(entryJson(e, mention)),
    );
  const taken = new Set<string>();
  for (const f of show.films) {
    const ep = epById.get(f.episode);
    const base = `films/${ep ? `${epKey(ep)}-` : ""}${handleOf(f.name)}`;
    let path = `${base}.json`;
    for (let n = 2; taken.has(path); n++) path = `${base}-${n}.json`;
    taken.add(path);
    files.set(
      path,
      json({
        id: f.id,
        name: f.name,
        ...(ep ? { episode: epKey(ep) } : {}),
        updated: new Date(f.updated).toISOString(),
        project: f.project,
      }),
    );
  }
  for (const ep of [...show.episodes].sort((a, b) => a.number - b.number))
    files.set(
      episodeFile(ep, taken),
      json(
        compact({
          number: ep.number,
          title: ep.title,
          status: ep.status,
          logline: ep.logline,
          uses: ep.uses.flatMap((id) => mention(id) ?? []),
          outline: ep.outline,
          notes: ep.notes,
        }),
      ),
    );
  return files;
}

// --- reading ---------------------------------------------------------------------------------------

async function readText(path: string): Promise<string | null> {
  const res = await user.getUserData(path);
  return res.ok ? res.text() : null;
}
function parse<T>(text: string | null): T | null {
  if (text === null) return null;
  try {
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

/** A handle or mention ("@mara", "#booth", "mara") as a bare handle. */
const bare = (ref: string) => handleOf(String(ref).replace(/^[@#%~]/, ""));

function asPicture(p: unknown) {
  if (typeof p === "string") return { media: p, label: "" };
  const o = (p ?? {}) as { media?: unknown; label?: unknown };
  return { media: String(o.media ?? ""), label: String(o.label ?? "") };
}
const pictures = (v: unknown) => (Array.isArray(v) ? v.map(asPicture).filter((p) => p.media) : []);

/** An entry from its file — written by the Codex, or by hand: what's missing is filled in. */
function readEntry(raw: Record<string, unknown>, file: string, folder: string): Entry {
  const kind = (
    typeof raw.kind === "string" && raw.kind in KINDS ? raw.kind : "character"
  ) as EntryKind;
  const handle = handleOf(String(raw.handle ?? file.replace(/\.json$/, "")));
  return toEntry({
    ...(raw as Partial<Entry>),
    // The same entry gets the same id every time it's loaded, so anything that remembers it (a
    // studio's references) still finds it.
    id: `e:${handle}`,
    kind,
    name: String(raw.name ?? handle.replace(/-/g, " ")),
    handle,
    folder,
    pictures: pictures(raw.pictures),
    variants: (Array.isArray(raw.variants) ? raw.variants : []).map(
      (v: Record<string, unknown>) => ({
        id: uid(),
        name: String(v?.name ?? "Variant"),
        prompt: String(v?.prompt ?? ""),
        pictures: pictures(v?.pictures),
      }),
    ),
    links: [],
    updated: Date.now(),
  });
}

export interface ShowSummary {
  id: string;
  name: string;
  modified: number;
}

/** Every show, most recently changed first. */
export async function listShows(): Promise<ShowSummary[]> {
  const files = await user.listUserDataFullInfo(ROOT).catch(() => []);
  const found = new Map<string, number>();
  for (const f of files) {
    const m = /^([^/]+)\/(show\.json|codex\.json)$/.exec(f.path);
    if (m) found.set(m[1]!, Math.max(found.get(m[1]!) ?? 0, f.modified));
  }
  const shows = await Promise.all(
    [...found].map(async ([id, modified]) => {
      const head =
        parse<{ name?: string }>(await readText(`${dirOf(id)}/show.json`)) ??
        parse<{ name?: string }>(await readText(`${dirOf(id)}/codex.json`));
      return { id, modified, name: head?.name || id };
    }),
  );
  return shows.sort((a, b) => b.modified - a.modified);
}

/** A loaded show, what each of its files held, and when each last changed. */
export interface Loaded {
  show: Show;
  onDisk: Map<string, string>;
  stamps: Map<string, number>;
}

export async function loadShow(id: string): Promise<Loaded | null> {
  const dir = dirOf(id);
  const listing = await user.listUserDataFullInfo(dir).catch(() => []);
  const stamps = new Map(listing.map((f) => [f.path, f.modified]));
  const headText = await readText(`${dir}/show.json`);
  const head = parse<Record<string, unknown>>(headText);
  if (!head) {
    // From before the folder layout: one codex.json. The first save lays it out and removes it.
    const old = parse<Partial<Show>>(await readText(`${dir}/codex.json`));
    if (!old) return null;
    return { show: toShow(old, id), onDisk: new Map([["codex.json", ""]]), stamps };
  }
  const onDisk = new Map<string, string>([["show.json", headText ?? ""]]);
  const entries: { entry: Entry; raw: Record<string, unknown> }[] = [];
  const episodes: { ep: Episode; raw: Record<string, unknown> }[] = [];
  const films: { film: Film; episode: string }[] = [];
  await Promise.all(
    listing.map(async ({ path }) => {
      const entry = /^codex\/(?:(.+)\/)?([^/]+\.json)$/.exec(path);
      const episode = /^episodes\/[^/]+\.json$/.test(path);
      if (/^films\/[^/]+\.json$/.test(path)) {
        const text = await readText(`${dir}/${path}`);
        const raw = parse<Record<string, unknown>>(text);
        if (!raw || !raw.project || typeof raw.project !== "object") return;
        onDisk.set(path, text ?? "");
        films.push({
          film: {
            id: typeof raw.id === "string" && raw.id ? raw.id : uid(),
            name: String(raw.name ?? path.slice(6, -5)),
            episode: "",
            project: raw.project as Record<string, unknown>,
            updated: Date.parse(String(raw.updated ?? "")) || Date.now(),
          },
          episode: String(raw.episode ?? ""),
        });
        return;
      }
      if (!entry && !episode) {
        if (["README.md", "notes.md", "CODEX.md"].includes(path))
          onDisk.set(path, (await readText(`${dir}/${path}`)) ?? "");
        return;
      }
      const text = await readText(`${dir}/${path}`);
      const raw = parse<Record<string, unknown>>(text);
      if (!raw) return;
      onDisk.set(path, text ?? "");
      if (entry)
        entries.push({ entry: readEntry(raw, entry[2]!, cleanFolder(entry[1] ?? "")), raw });
      else
        episodes.push({
          ep: toEpisode({ ...(raw as Partial<Episode>), id: uid(), uses: [] }, episodes.length),
          raw,
        });
    }),
  );
  // References are mentions on disk; in memory they're ids.
  const byHandle = new Map(entries.map(({ entry }) => [entry.handle, entry.id]));
  const resolve = (ref: unknown) => byHandle.get(bare(String(ref)));
  for (const { entry, raw } of entries)
    entry.links = (Array.isArray(raw.links) ? raw.links : []).flatMap(
      (l: Record<string, unknown>) => {
        const to = resolve(l?.to);
        return to && to !== entry.id ? [{ to, label: String(l?.label ?? "") }] : [];
      },
    );
  // Episodes too: an episode's id comes from its number.
  const seen = new Set<string>();
  for (const { ep } of episodes.sort((a, b) => a.ep.number - b.ep.number)) {
    let id = `ep:${ep.number}`;
    for (let n = 2; seen.has(id); n++) id = `ep:${ep.number}-${n}`;
    seen.add(id);
    ep.id = id;
  }
  for (const { ep, raw } of episodes)
    ep.uses = (Array.isArray(raw.uses) ? raw.uses : []).flatMap((u) => resolve(u) ?? []);

  const show = toShow({ ...head, notes: "", entries: [], episodes: [], map: {} }, id);
  show.notes = (onDisk.get("notes.md") ?? "").replace(/\n$/, "");
  show.entries = entries.map((x) => x.entry).sort((a, b) => a.name.localeCompare(b.name));
  show.episodes = episodes.map((x) => x.ep).sort((a, b) => a.number - b.number);
  const epByKey = new Map(show.episodes.map((ep) => [epKey(ep), ep.id]));
  show.films = films
    .map(({ film, episode }) => ({ ...film, episode: epByKey.get(episode) ?? "" }))
    .sort((a, b) => b.updated - a.updated);
  const map = (head.map && typeof head.map === "object" ? head.map : {}) as Record<
    string,
    { x: number; y: number }
  >;
  for (const [key, p] of Object.entries(map)) {
    const target = resolve(key) ?? epByKey.get(key);
    if (target && typeof p?.x === "number" && typeof p?.y === "number") show.map[target] = p;
  }
  for (const e of show.entries)
    if (e.folder && !show.folders.includes(e.folder)) show.folders.push(e.folder);
  return { show, onDisk, stamps };
}

/** Write what changed since `written`, delete what's gone; returns what's on disk now. */
async function save(show: Show, written: Map<string, string>): Promise<Map<string, string>> {
  const dir = dirOf(show.id);
  const files = filesOf(show);
  for (const [path, body] of files) {
    if (written.get(path) === body) continue;
    await user.storeUserData(`${dir}/${path}`, body, {
      overwrite: true,
      stringify: false,
      throwOnError: true,
    });
  }
  for (const path of written.keys())
    if (!files.has(path)) await user.deleteUserData(`${dir}/${path}`);
  return files;
}

export async function createShow(name: string): Promise<Show> {
  const id = `${handleOf(name)}-${uid().slice(0, 4)}`;
  const show = toShow({ name }, id);
  await save(show, new Map());
  return show;
}

/** An entry as its file has it: mentions for links, nothing empty. */
export function entryToJson(show: Show, e: Entry) {
  const byId = new Map(show.entries.map((x) => [x.id, x]));
  return entryJson(e, (id) => {
    const to = byId.get(id);
    return to ? mentionOf(to) : null;
  });
}

/** An entry from file-shaped JSON (as an agent or a person writes it), with its links resolved
 *  against `show` — mentions that name nothing are dropped. */
export function entryFromJson(show: Show, raw: Record<string, unknown>, folder = ""): Entry {
  const entry = readEntry(
    raw,
    `${String(raw.handle ?? raw.name ?? "entry")}.json`,
    cleanFolder(folder),
  );
  const byHandle = new Map(show.entries.map((e) => [e.handle, e.id]));
  entry.links = (Array.isArray(raw.links) ? raw.links : []).flatMap(
    (l: Record<string, unknown>) => {
      const to = byHandle.get(bare(String(l?.to ?? "")));
      return to && to !== entry.id ? [{ to, label: String(l?.label ?? "") }] : [];
    },
  );
  return entry;
}

/** A mention, handle or name ("@mara", "mara", "Mara") as the entry it means. */
export function findEntry(show: Show, ref: string): Entry | undefined {
  const handle = bare(ref);
  return (
    show.entries.find((e) => e.handle === handle) ??
    show.entries.find((e) => e.name.toLowerCase() === String(ref).trim().toLowerCase())
  );
}

/** Shows open in a Codex panel right now, by id: changes to those go through the live copy. */
export const liveShows = new Map<string, ReturnType<typeof useShow>>();

/** A show being edited: changes save themselves shortly after they stop, and edits made to its
 *  files from outside (an AI, a text editor) are picked up and reloaded. */
export function useShow(loaded: Loaded) {
  const show = reactive(loaded.show) as Show;
  const state = reactive({ saving: false, error: "", reloaded: 0, canUndo: false, canRedo: false });
  // Undo history: snapshots of the show, one per settled change.
  const snap = () => JSON.stringify(show);
  let base = snap();
  const past: string[] = [];
  const future: string[] = [];
  const syncHistory = () => {
    state.canUndo = past.length > 0 || snap() !== base;
    state.canRedo = future.length > 0;
  };
  function checkpoint() {
    const now = snap();
    if (now === base) return;
    past.push(base);
    if (past.length > 100) past.shift();
    future.length = 0;
    base = now;
  }
  function restore(to: string) {
    const was = JSON.parse(to) as Show;
    Object.assign(show, was);
    base = to;
  }
  let written = loaded.onDisk;
  let stamps = loaded.stamps;
  let timer = 0;
  let pending = false;
  let applying = false;
  let running: Promise<void> = Promise.resolve();

  const flush = () => {
    window.clearTimeout(timer);
    pending = false;
    checkpoint();
    syncHistory();
    running = running.then(async () => {
      state.saving = true;
      try {
        written = await save(JSON.parse(JSON.stringify(show)) as Show, written);
        const listing = await user.listUserDataFullInfo(dirOf(show.id)).catch(() => []);
        stamps = new Map(listing.map((f) => [f.path, f.modified]));
        state.error = "";
      } catch (e) {
        state.error = e instanceof Error ? e.message : String(e);
      } finally {
        state.saving = false;
      }
    });
    return running;
  };
  if (written.has("codex.json")) void flush();

  const stopWatch = watch(
    show,
    () => {
      if (applying) return;
      pending = true;
      state.canUndo = true;
      window.clearTimeout(timer);
      timer = window.setTimeout(() => void flush(), 600);
    },
    { deep: true },
  );

  /** Reload when a file changed on disk that we didn't write — unless an edit here is unsaved. */
  async function poll() {
    if (pending || state.saving) return;
    const listing = await user.listUserDataFullInfo(dirOf(show.id)).catch(() => null);
    if (!listing) return;
    const now = new Map(listing.map((f) => [f.path, f.modified]));
    const changed =
      now.size !== stamps.size || [...now].some(([path, t]) => stamps.get(path) !== t);
    if (!changed) return;
    const fresh = await loadShow(show.id);
    if (!fresh || pending || state.saving) return;
    // Keep ids for what's still there, so the selection and map positions survive.
    const oldIds = new Map(show.entries.map((e) => [e.handle, e.id]));
    const remap = new Map<string, string>();
    for (const e of fresh.show.entries) {
      const old = oldIds.get(e.handle);
      if (old) {
        remap.set(e.id, old);
        e.id = old;
      }
    }
    for (const e of fresh.show.entries)
      e.links = e.links.map((l) => ({ ...l, to: remap.get(l.to) ?? l.to }));
    for (const ep of fresh.show.episodes) ep.uses = ep.uses.map((u) => remap.get(u) ?? u);
    fresh.show.map = Object.fromEntries(
      Object.entries(fresh.show.map).map(([k, v]) => [remap.get(k) ?? k, v]),
    );
    applying = true;
    Object.assign(show, fresh.show);
    // Someone else changed the files: the history before that no longer applies.
    base = snap();
    past.length = 0;
    future.length = 0;
    syncHistory();
    written = fresh.onDisk;
    stamps = fresh.stamps;
    state.reloaded++;
    await Promise.resolve();
    applying = false;
  }
  const pollTimer = window.setInterval(() => void poll(), 2500);

  const handle = {
    show,
    state,
    flush,
    undo() {
      checkpoint();
      const to = past.pop();
      if (to === undefined) return;
      future.push(base);
      restore(to);
      syncHistory();
    },
    redo() {
      checkpoint();
      const to = future.pop();
      if (to === undefined) return;
      past.push(base);
      restore(to);
      syncHistory();
    },
    stop: () => {
      stopWatch();
      window.clearInterval(pollTimer);
      if (liveShows.get(show.id) === handle) liveShows.delete(show.id);
      return pending ? flush() : running;
    },
  };
  liveShows.set(show.id, handle);
  return handle;
}

/** Change a show — the live one when a Codex panel has it open, else loaded, changed and saved. */
export async function withShow<T>(id: string, change: (show: Show) => T): Promise<T> {
  const live = liveShows.get(id);
  if (live) {
    const out = change(live.show);
    await live.flush();
    return out;
  }
  const loaded = await loadShow(id);
  if (!loaded) throw new Error(`There is no show "${id}".`);
  const session = useShow(loaded);
  try {
    const out = change(session.show);
    await session.flush();
    return out;
  } finally {
    await session.stop();
  }
}

// --- the format, for whoever opens the folder ----------------------------------------------------

const README = `# A Codex show

This folder is one show from the Codex (Nynxz H3). It's plain files, meant to be read and edited
by people and AI alike; the Codex panel picks up changes made here within a few seconds.

## Layout

- \`show.json\` — \`name\`, \`logline\`, \`folders\` (every folder path, empty ones included), \`map\`
  (node positions on the Codex map, by mention).
- \`notes.md\` — the show notes: rules the whole show follows.
- \`CODEX.md\` — the whole show as one text. Generated on every save: read it, don't edit it.
- \`codex/\` — one JSON file per entry, named \`<handle>.json\`. Subfolders are the Codex's folders;
  moving a file moves the entry.
- \`episodes/\` — one JSON file per episode, \`e01-<title>.json\`.

## Entries — \`codex/<folder>/<handle>.json\`

\`\`\`json
{
  "kind": "character",
  "name": "Mara",
  "handle": "mara",
  "about": "Who she is, for the writers. Not sent to image models.",
  "prompt": "What a shot gets when it mentions @mara: how she looks.",
  "tags": ["lead"],
  "pictures": ["input/codex/<show>/mara-front.png"],
  "variants": [{ "name": "Rain coat", "prompt": "in a long yellow rain coat" }],
  "voice": { "description": "a low, dry voice, unhurried", "language": "English" },
  "loras": [{ "name": "folder/file.safetensors", "strength": 0.8 }],
  "links": [{ "to": "#home-lounge-room", "label": "lives in" }],
  "notes": "Anything else."
}
\`\`\`

- \`kind\`: \`character\`, \`place\`, \`prop\`, \`look\` or \`sound\`. Only \`kind\` and \`name\` are needed; the
  handle defaults to the file name.
- Handles are unique in the show: lowercase letters, numbers and dashes.
- Everything refers to entries by mention — \`@\` characters, \`#\` places and props, \`%\` looks,
  \`~\` sounds — e.g. \`"to": "@mara"\`.
- \`variants\` are a character's wardrobe, a place's times of day, a prop's states.
- \`voice\` is for characters; a character's voice clip is a link to a sound labelled \`"voice"\`.
- \`pictures\` are media refs (\`input/…\`, \`output/…\`); sounds hold audio clips the same way.
- Empty fields are left out.

## Episodes — \`episodes/e01-<title>.json\`

\`\`\`json
{
  "number": 1,
  "title": "Pilot",
  "status": "writing",
  "logline": "What happens, in a sentence or two.",
  "uses": ["@mara", "#home-lounge-room"],
  "outline": "The beats, in order — each one happening because of the one before.",
  "notes": "Anything else."
}
\`\`\`

\`status\`: \`idea\`, \`writing\`, \`making\` or \`done\`.

## Films — \`films/e01-<name>.json\`

H3 Studio projects saved into the show from the studio's Codex menu, filed by episode, to open
again later and render. \`project\` is the studio's own document; leave it to the studio.
`;
