// The Codex as ZenKit capabilities — which agents (ZenAgent) see as tools: read a show, and add
// to it. Entries and episodes go in and come out in the same shape as their files (README.md in a
// show's folder), referring to each other by mention. Writes go through the open Codex when it has
// the show, so what the agent does shows up there straight away.
import { registerZenCapability } from "@/framework";
import {
  EPISODE_STATUS,
  KIND_ORDER,
  KINDS,
  cleanFolder,
  freeHandle,
  handleOf,
  mentionOf,
  newEpisode,
  showContext,
  uid,
  type EpisodeStatus,
  type Show,
} from "./codex";
import {
  entryFromJson,
  entryToJson,
  findEntry,
  listShows,
  liveShows,
  loadShow,
  withShow,
} from "./codexStore";

const LAST = "nynxz.codex.last";

/** The show an agent means: the one named, else the one open in the Codex, else the newest. */
async function showId(name: unknown): Promise<string> {
  const shows = await listShows();
  if (!shows.length) throw new Error("There are no shows in the Codex yet — make one first.");
  const want = typeof name === "string" ? name.trim().toLowerCase() : "";
  if (want) {
    const hit = shows.find((s) => s.id.toLowerCase() === want || s.name.toLowerCase() === want);
    if (!hit) throw new Error(`No show "${name}". Shows: ${shows.map((s) => s.name).join(", ")}.`);
    return hit.id;
  }
  let last = "";
  try {
    last = localStorage.getItem(LAST) ?? "";
  } catch {
    /* no preference */
  }
  return [...liveShows.keys()][0] ?? shows.find((s) => s.id === last)?.id ?? shows[0]!.id;
}

async function readShow(id: string): Promise<Show> {
  const live = liveShows.get(id);
  if (live) return live.show;
  const loaded = await loadShow(id);
  if (!loaded) throw new Error(`There is no show "${id}".`);
  return loaded.show;
}

const SHOW_PARAM = {
  show: {
    type: "string",
    description: "The show's name. Leave out for the one open in the Codex.",
  },
};
const KIND_LIST = KIND_ORDER.join(", ");

export function registerCodexCapabilities() {
  void registerZenCapability({
    id: "codex.shows",
    effect: "read",
    description:
      "List the shows in the Codex (the user's show bible: characters, places, props, looks, sounds and episodes).",
    run: async () => (await listShows()).map((s) => ({ name: s.name, id: s.id })),
  });

  void registerZenCapability({
    id: "codex.read",
    effect: "read",
    description:
      "Read a whole show from the Codex as text: its logline and notes, every entry (with its mention, " +
      "e.g. @mara or #booth, what it looks like, its variants, voice and links) and every episode. " +
      "Read this before writing for the show.",
    params: { type: "object", properties: SHOW_PARAM },
    run: async (args) => showContext(await readShow(await showId(args.show))),
  });

  void registerZenCapability({
    id: "codex.entry",
    effect: "read",
    description: "Get one Codex entry as JSON, by its mention (@mara), handle or name.",
    params: {
      type: "object",
      properties: {
        ...SHOW_PARAM,
        entry: { type: "string", description: "Mention, handle or name." },
      },
      required: ["entry"],
    },
    run: async (args) => {
      const show = await readShow(await showId(args.show));
      const entry = findEntry(show, String(args.entry ?? ""));
      if (!entry) throw new Error(`No entry "${args.entry}" in ${show.name}.`);
      return { ...entryToJson(show, entry), folder: entry.folder || undefined };
    },
  });

  void registerZenCapability({
    id: "codex.write_entry",
    effect: "write",
    description:
      `Add an entry to a Codex show, or change one (matched by handle, else by name). kind is one of ${KIND_LIST}. ` +
      "prompt is what an image/video model gets when a shot mentions it (how it looks); about is who " +
      "it is, for writers. variants are a character's outfits, a place's times of day or a prop's states: " +
      '[{name, prompt}]. voice ({description, language}) is for characters. links: [{to: "@mara", label: "knows"}]. ' +
      "Fields left out keep their current value. Returns the entry's mention.",
    params: {
      type: "object",
      properties: {
        ...SHOW_PARAM,
        kind: { type: "string", enum: KIND_ORDER },
        name: { type: "string" },
        handle: {
          type: "string",
          description: "Lowercase-and-dashes; made from the name if left out.",
        },
        about: { type: "string" },
        prompt: { type: "string" },
        tags: { type: "array", items: { type: "string" } },
        variants: {
          type: "array",
          items: {
            type: "object",
            properties: { name: { type: "string" }, prompt: { type: "string" } },
          },
        },
        voice: {
          type: "object",
          properties: { description: { type: "string" }, language: { type: "string" } },
        },
        links: {
          type: "array",
          items: {
            type: "object",
            properties: { to: { type: "string" }, label: { type: "string" } },
          },
        },
        notes: { type: "string" },
        folder: { type: "string", description: 'A folder like "Main cast" or "Sets/Night".' },
      },
      required: ["name"],
    },
    run: async (args) =>
      withShow(await showId(args.show), (show) => {
        const handle = typeof args.handle === "string" && args.handle ? handleOf(args.handle) : "";
        const existing =
          (handle && show.entries.find((e) => e.handle === handle)) ||
          findEntry(show, String(args.name ?? ""));
        const base = existing ? entryToJson(show, existing) : {};
        const given = Object.fromEntries(
          Object.entries(args).filter(
            ([k, v]) => v !== undefined && k !== "show" && k !== "folder",
          ),
        );
        const merged = { ...base, ...given };
        if (!existing && !(String(merged.kind) in KINDS)) merged.kind = "character";
        const folder =
          typeof args.folder === "string" ? cleanFolder(args.folder) : (existing?.folder ?? "");
        const entry = entryFromJson(show, merged, folder);
        if (existing) {
          const keep = existing.id;
          Object.assign(existing, entry, { id: keep, cover: existing.cover || entry.cover });
          existing.handle = freeHandle(show, existing.handle, keep);
          if (folder && !show.folders.includes(folder)) show.folders.push(folder);
          return { mention: mentionOf(existing), changed: true };
        }
        entry.handle = freeHandle(show, entry.handle);
        entry.id = uid();
        show.entries.push(entry);
        if (folder && !show.folders.includes(folder)) show.folders.push(folder);
        return { mention: mentionOf(entry), added: true };
      }),
  });

  void registerZenCapability({
    id: "codex.write_episode",
    effect: "write",
    description:
      "Add an episode to a Codex show, or change one (matched by number). uses lists the entries it " +
      'features by mention (["@mara", "#booth"]). outline is the beats in order. status is one of ' +
      `${EPISODE_STATUS.map((s) => s.value).join(", ")}. Fields left out keep their current value.`,
    params: {
      type: "object",
      properties: {
        ...SHOW_PARAM,
        number: { type: "integer", description: "Leave out to add the next episode." },
        title: { type: "string" },
        status: { type: "string", enum: EPISODE_STATUS.map((s) => s.value) },
        logline: { type: "string" },
        uses: { type: "array", items: { type: "string" } },
        outline: { type: "string" },
        notes: { type: "string" },
      },
    },
    run: async (args) =>
      withShow(await showId(args.show), (show) => {
        const number = typeof args.number === "number" ? Math.round(args.number) : null;
        let ep = number !== null ? show.episodes.find((e) => e.number === number) : undefined;
        const added = !ep;
        if (!ep) {
          ep = newEpisode(show);
          if (number !== null) ep.number = number;
          show.episodes.push(ep);
        }
        if (typeof args.title === "string") ep.title = args.title;
        if (EPISODE_STATUS.some((s) => s.value === args.status))
          ep.status = args.status as EpisodeStatus;
        if (typeof args.logline === "string") ep.logline = args.logline;
        if (typeof args.outline === "string") ep.outline = args.outline;
        if (typeof args.notes === "string") ep.notes = args.notes;
        const unknown: string[] = [];
        if (Array.isArray(args.uses))
          ep.uses = args.uses.flatMap((u) => {
            const e = findEntry(show, String(u));
            if (!e) unknown.push(String(u));
            return e ? [e.id] : [];
          });
        return {
          episode: ep.number,
          added,
          ...(unknown.length ? { not_in_codex: unknown } : {}),
        };
      }),
  });

  void registerZenCapability({
    id: "codex.write_show",
    effect: "write",
    description:
      "Change a Codex show's name, logline (the show in a sentence) or notes (the rules the whole " +
      "show follows). Fields left out keep their current value.",
    params: {
      type: "object",
      properties: {
        ...SHOW_PARAM,
        name: { type: "string" },
        logline: { type: "string" },
        notes: { type: "string" },
      },
    },
    run: async (args) =>
      withShow(await showId(args.show), (show) => {
        if (typeof args.name === "string" && args.name.trim()) show.name = args.name.trim();
        if (typeof args.logline === "string") show.logline = args.logline;
        if (typeof args.notes === "string") show.notes = args.notes;
        return { show: show.name };
      }),
  });
}
