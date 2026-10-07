// H3 Studio's script format: a whole project as plain text, for writing scenes with an LLM (or by
// hand) and pasting them in, and for copying a project out to revise. Readable first; pictures
// can't travel in text, so references are named (@anna) and must exist in the studio.
//
//   # Night Train                                  (a label, not stored)
//   style: Live-action, cinematic, soft tungsten light
//   canvas: 1344x768
//   ambience: …      music: …                      (the film's defaults)
//
//   ## References                                 (pictures, videos, sounds, by name; ones the
//   - @anna: a young woman in a blue cardigan        studio lacks become placeholders, described
//   - @platform: a rainy night platform (picture)    in words until they get media)
//
//   ## Cast
//   - Anna (@anna): a quiet, breathy young female voice [English]
//
//   ## Scene 1: Departure (6s, cut)   (cut | continues | from last frame | same place — how it follows the last scene)
//   ambience: rain on glass                        (this scene's own, optional)
//
//   ### 0:00
//   @anna walks down the platform toward the train.
//   ANNA (softly): I get off at the next station.
//
//   ### 0:03 (no cut, timed)                       (cut | dissolve | fade | wipe | no cut | no cut, timed)
//   She stops at the door and looks back.
//
// Dialogue is `NAME (how): words` — NAME in capitals, or a cast name, or an @reference; (V.O.) is
// a voice-over and (sings) sung; `>>` splits off what is heard over the next cut; a line ending in
// `--` is cut off. JSON (exportJson / importJson) carries everything exactly, ids and all.
import {
  type Ref,
  continuationOf,
  newScene,
  refUsedIn,
  snapSeconds,
  toProject,
  uid,
  type Line,
  type Project,
  type Scene,
  type Shot,
  type Transition,
  type Voice,
} from "./h3studio";
import { newLine, newVoice } from "./h3dialogue";
import { addProxy } from "./h3edits";

// --- writing a project out ---------------------------------------------------------------------
const TRANSITION_WORDS: Record<Transition, string> = {
  cut: "cut",
  dissolve: "dissolve",
  fade: "fade",
  wipe: "wipe",
  continue: "no cut",
  continue_timed: "no cut, timed",
};

function clock(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  const whole = Math.abs(s - Math.round(s)) < 0.005;
  return `${m}:${whole ? String(Math.round(s)).padStart(2, "0") : s.toFixed(2).padStart(5, "0")}`;
}
const secs = (n: number) => `${Number(n.toFixed(2))}s`;

function lineOut(project: Project, line: Line): string {
  const names = line.speakers.map(
    (id) => project.cast?.find((v) => v.id === id)?.name.toUpperCase() ?? "?",
  );
  const note = line.mode === "voiceover" ? "V.O." : line.mode === "sing" ? "sings" : line.delivery;
  const words = `${line.words}${line.next ? ` >> ${line.next}` : ""}${line.cutoff ? " --" : ""}`;
  return `${names.join(" & ")}${note ? ` (${note})` : ""}: ${words}`;
}

export function toScript(project: Project): string {
  const out: string[] = [];
  const top = [
    project.style.trim() && `style: ${project.style.trim()}`,
    project.direction.trim() && `direction: ${project.direction.trim()}`,
    `canvas: ${project.canvas.width}x${project.canvas.height}`,
    project.soundscape.trim() && `ambience: ${project.soundscape.trim()}`,
    project.music.trim() && `music: ${project.music.trim()}`,
  ].filter(Boolean) as string[];
  out.push(...top, "");
  if (project.refs.length) {
    out.push("## References");
    for (const r of project.refs)
      out.push(
        `- @${r.name}${r.note.trim() ? `: ${r.note.trim()}` : ""} (${r.kind === "image" ? "picture" : r.kind}${r.role === "blocking" ? ", blocking" : ""}${r.scenes === "all" ? ", every scene" : ""})`,
      );
    out.push("");
  }
  if (project.cast?.length) {
    out.push("## Cast");
    for (const v of project.cast) {
      const ref = project.refs.find((r) => r.id === v.ref);
      out.push(
        `- ${v.name}${ref ? ` (@${ref.name})` : ""}${v.voice ? `: ${v.voice}` : ""}${v.language && v.language !== "English" ? ` [${v.language}]` : ""}`,
      );
    }
    out.push("");
  }
  project.scenes.forEach((scene, i) => {
    const how = i === 0 ? "" : `, ${continuationOf(scene.continuation.mode).script}`;
    out.push(
      `## Scene ${i + 1}${scene.title ? `: ${scene.title}` : ""} (${secs(scene.seconds)}${how})`,
    );
    if (scene.direction.trim()) out.push(`direction: ${scene.direction.trim()}`);
    if (scene.soundscape.trim()) out.push(`ambience: ${scene.soundscape.trim()}`);
    if (scene.music.trim()) out.push(`music: ${scene.music.trim()}`);
    const marked = project.refs.filter(
      (r) =>
        Array.isArray(r.scenes) && r.scenes.includes(scene.id) && !refUsedIn(project, r, scene),
    );
    if (marked.length) out.push(`with: ${marked.map((r) => `@${r.name}`).join(", ")}`);
    out.push("");
    scene.shots.forEach((shot, j) => {
      const t = shot.transition ?? "cut";
      out.push(`### ${clock(shot.at)}${j > 0 && t !== "cut" ? ` (${TRANSITION_WORDS[t]})` : ""}`);
      if (shot.text.trim()) out.push(shot.text.trim());
      for (const line of shot.lines ?? []) if (line.words.trim()) out.push(lineOut(project, line));
      out.push("");
    });
  });
  return `${out.join("\n").trim()}\n`;
}

// --- reading a script in -----------------------------------------------------------------------
export interface ScriptResult {
  style?: string;
  canvas?: { width: number; height: number };
  direction?: string;
  soundscape?: string;
  music?: string;
  /** Voices named in the script: existing ones (matched by name) or new. */
  cast: Voice[];
  scenes: Scene[];
  /** References the script names that the studio doesn't have: made as placeholders. */
  placeholders: { name: string; note: string; kind: Ref["kind"]; role: Ref["role"] }[];
  /** Descriptions the script gives for references the studio has. */
  notes: { id: string; note: string }[];
  /** Videos the script marks "(video, blocking)", or no longer does, that the studio has. */
  roles: { id: string; role: Ref["role"] }[];
  /** Voices to link to a reference by name once the placeholders exist. */
  links: { voiceId: string; ref: string }[];
  /** Every reference name listed under "## References", lowercased. */
  declared: string[];
  /** References marked "(every scene)", lowercased. */
  every: string[];
  /** References a scene shows without using them ("with: @a, @b"), by scene id. */
  with: { scene: string; names: string[] }[];
  warnings: string[];
}

const TIME = /^(?:(\d+):)?(\d+(?:\.\d+)?)s?$/;
function parseTime(text: string): number | null {
  const m = TIME.exec(text.trim());
  if (!m) return null;
  return (m[1] ? Number(m[1]) * 60 : 0) + Number(m[2]);
}
function parseTransition(text: string): Transition | null {
  const t = text
    .toLowerCase()
    .replace(/[^a-z, -]/g, "")
    .trim();
  if (!t) return null;
  if (/no ?cut.*timed|continue.*timed|timed/.test(t)) return "continue_timed";
  if (/no ?cut|continue/.test(t)) return "continue";
  if (/dissolve/.test(t)) return "dissolve";
  if (/fade/.test(t)) return "fade";
  if (/wipe/.test(t)) return "wipe";
  if (/cut/.test(t)) return "cut";
  return null;
}
const keyOf = (s: string) => s.trim().replace(/^@/, "").toLowerCase();

/**
 * A script read against a project: its @names matched to the project's references, its speakers to
 * the project's voices (by name or reference), new voices made for the rest.
 */
export function parseProjectScript(project: Project, text: string): ScriptResult {
  const result: ScriptResult = {
    cast: [],
    scenes: [],
    placeholders: [],
    notes: [],
    roles: [],
    links: [],
    declared: [],
    every: [],
    with: [],
    warnings: [],
  };
  const placeholder = (
    name: string,
    note = "",
    kind: Ref["kind"] = "image",
    role: Ref["role"] = "reference",
  ) => {
    const key = keyOf(name);
    const known = result.placeholders.find((p) => p.name.toLowerCase() === key);
    if (known) {
      if (note && !known.note) known.note = note;
      return;
    }
    result.placeholders.push({ name: name.replace(/^@/, ""), note, kind, role });
  };
  // Copies: reading (and previewing) a script must not touch the project's own voices.
  const voices: Voice[] = (project.cast ?? []).map((v) => ({ ...v }));
  const refByName = new Map(project.refs.map((r) => [r.name.toLowerCase(), r]));
  const voiceFor = (name: string): Voice => {
    const key = keyOf(name);
    const known =
      voices.find((v) => v.name.toLowerCase() === key) ??
      voices.find((v) => project.refs.find((r) => r.id === v.ref)?.name.toLowerCase() === key);
    if (known) {
      if (!result.cast.includes(known)) result.cast.push(known);
      return known;
    }
    const ref = refByName.get(key);
    const plain = name.trim().replace(/^@/, "");
    const title =
      plain === plain.toUpperCase()
        ? plain.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase())
        : plain;
    const voice = newVoice(title, ref?.id ?? "");
    voices.push(voice);
    result.cast.push(voice);
    return voice;
  };
  const isSpeaker = (who: string) =>
    who.split(/\s*(?:&|,|\band\b)\s*/i).every((n) => {
      const k = keyOf(n);
      return (
        (/^[A-Z][A-Z0-9 .'-]*$/.test(n.trim()) && /[A-Z]/.test(n)) ||
        voices.some((v) => v.name.toLowerCase() === k) ||
        (n.trim().startsWith("@") && refByName.has(k))
      );
    });

  let section: "top" | "refs" | "cast" | "scene" = "top";
  let scene: Scene | null = null;
  let shot: Shot | null = null;
  const textOf = new Map<Shot, string[]>();

  const startShot = (into: Scene, at: number, transition: Transition | null): Shot => {
    const made: Shot = {
      id: uid("sh"),
      at,
      text: "",
      lines: [],
      ...(into.shots.length && transition && transition !== "cut" ? { transition } : {}),
    };
    into.shots.push(made);
    textOf.set(made, []);
    return made;
  };

  for (const raw of text.split(/\r?\n/)) {
    const row = raw.trim();
    if (!row || row.startsWith("//")) continue;
    let m: RegExpExecArray | null;
    if (/^#{2}\s*references?\s*$/i.test(row)) {
      section = "refs";
      continue;
    }
    if (/^#{2}\s*cast\s*$/i.test(row)) {
      section = "cast";
      continue;
    }
    if ((m = /^#{2}\s*scene\b[^:(]*(?::\s*([^(]*))?(?:\(([^)]*)\))?\s*$/i.exec(row))) {
      section = "scene";
      const opts = (m[2] ?? "").split(",").map((o) => o.trim());
      const len = opts.map(parseTime).find((n) => n !== null);
      scene = { ...newScene(len ?? 5), shots: [], title: (m[1] ?? "").trim() };
      scene.seconds = snapSeconds(Math.min(Math.max(len ?? 5, 1), 30));
      scene.continuation.mode = opts.some((o) => /sound|music carries|audio carries/i.test(o))
        ? "sound"
        : opts.some((o) => /same place|setting|reference/i.test(o))
          ? "reference"
          : opts.some((o) => /last frame|first frame|picks? up/i.test(o))
            ? "first_frame"
            : opts.some((o) => /contin/i.test(o))
              ? "guide"
              : "cut";
      result.scenes.push(scene);
      shot = null;
      continue;
    }
    if (row.startsWith("# ")) continue;
    if ((m = /^#{3}\s*([\d:.]+s?)?\s*(?:\(([^)]*)\))?\s*$/.exec(row))) {
      if (!scene) {
        result.warnings.push(`A shot before any "## Scene" heading was skipped: ${row}`);
        continue;
      }
      const at = m[1] ? parseTime(m[1]) : null;
      const before = scene.shots[scene.shots.length - 1];
      shot = startShot(
        scene,
        scene.shots.length === 0 ? 0 : (at ?? (before ? before.at + 2 : 0)),
        m[2] ? parseTransition(m[2]) : null,
      );
      continue;
    }
    const field =
      /^(style|direction|canvas|ambience|soundscape|music|title|with)\s*:\s*(.*)$/i.exec(row);
    if (field && !shot) {
      const [, key, value] = field;
      const k = key!.toLowerCase();
      if (section === "scene" && scene) {
        if (k === "ambience" || k === "soundscape") scene.soundscape = value!;
        else if (k === "direction") scene.direction = value!;
        else if (k === "music") scene.music = value!;
        else if (k === "title") scene.title = value!;
        else if (k === "with")
          result.with.push({
            scene: scene.id,
            names: (value!.match(/@[\w-]+/g) ?? []).map((n) => n.slice(1).toLowerCase()),
          });
      } else if (k === "style") result.style = value;
      else if (k === "direction") result.direction = value;
      else if (k === "ambience" || k === "soundscape") result.soundscape = value;
      else if (k === "music") result.music = value;
      else if (k === "canvas") {
        const c = /(\d+)\s*[x×]\s*(\d+)/.exec(value!);
        if (c)
          result.canvas = {
            width: Math.round(Number(c[1]) / 32) * 32,
            height: Math.round(Number(c[2]) / 32) * 32,
          };
      }
      continue;
    }
    if (section === "refs") {
      const r =
        /^[-*]?\s*@([\w-]+)\s*(?::\s*(.*?))?\s*(?:\(((?:\s*(?:picture|image|video|audio|blocking|placeholder|every scene|all scenes)\s*,?)+)\))?\s*$/i.exec(
          row,
        );
      if (r) {
        result.declared.push(r[1]!.toLowerCase());
        const note = (r[2] ?? "").trim();
        const opts = (r[3] ?? "").toLowerCase();
        if (/every scene|all scenes/.test(opts)) result.every.push(r[1]!.toLowerCase());
        const word = /video|audio/.exec(opts)?.[0] ?? "";
        // "blocking" is a video's: its staging, timing and camera, none of its look.
        const blocking = /blocking/.test(opts);
        const kind: Ref["kind"] =
          word === "video" || blocking ? "video" : word === "audio" ? "audio" : "image";
        const known = refByName.get(r[1]!.toLowerCase());
        if (known) {
          if (note && note !== known.note) result.notes.push({ id: known.id, note });
          if (known.kind === "video" && blocking !== (known.role === "blocking"))
            result.roles.push({ id: known.id, role: blocking ? "blocking" : "reference" });
        } else placeholder(r[1]!, note, kind, blocking ? "blocking" : "reference");
      }
      continue;
    }
    if (section === "cast") {
      const c =
        /^[-*]?\s*([^(:[\]]+?)\s*(?:\((@[\w-]+)\))?\s*(?::\s*([^[]*?))?\s*(?:\[([^\]]+)\])?\s*$/.exec(
          row,
        );
      if (c) {
        const voice = voiceFor(c[1]!);
        const ref = c[2] ? refByName.get(keyOf(c[2])) : undefined;
        if (ref) voice.ref = ref.id;
        else if (c[2]) {
          placeholder(c[2]);
          result.links.push({ voiceId: voice.id, ref: keyOf(c[2]) });
        }
        if (c[3]?.trim()) voice.voice = c[3].trim();
        if (c[4]?.trim()) voice.language = c[4].trim();
      }
      continue;
    }
    if (section !== "scene" || !scene) continue;
    const current = shot ?? (shot = startShot(scene, 0, null));
    const d = /^([^:()]{1,40}?)\s*(?:\(([^)]*)\))?\s*:\s*(.+)$/.exec(row);
    if (d && isSpeaker(d[1]!)) {
      const [, who, note = "", rest] = d;
      const line = newLine([
        ...new Set(
          who!
            .split(/\s*(?:&|,|\band\b)\s*/i)
            .filter(Boolean)
            .map((n) => voiceFor(n).id),
        ),
      ]);
      const how = note.trim();
      if (/^(v\.?\s*o\.?|o\.?\s*s\.?|voice-?over|off-?screen)$/i.test(how)) line.mode = "voiceover";
      else if (/^sing(s|ing)?$/i.test(how)) line.mode = "sing";
      else line.delivery = how;
      let words = rest!.trim();
      if (words.endsWith("--")) {
        line.cutoff = true;
        words = words.slice(0, -2).trim();
      }
      const split = words.split(/\s*>>\s*/);
      line.words = split[0]!;
      line.next = split.slice(1).join(" ");
      current.lines!.push(line);
    } else textOf.get(current)!.push(row);
  }

  for (const sc of result.scenes) {
    if (!sc.shots.length) sc.shots.push({ id: uid("sh"), at: 0, text: "", lines: [] });
    sc.shots.sort((a, b) => a.at - b.at);
    sc.shots[0]!.at = 0;
    delete sc.shots[0]!.transition;
    for (const sh of sc.shots) {
      sh.text = (textOf.get(sh) ?? []).join(" ").trim();
      if (sh.at >= sc.seconds)
        result.warnings.push(
          `A shot at ${clock(sh.at)} is past the end of its ${secs(sc.seconds)} scene.`,
        );
    }
  }
  const mentioned = new Set(
    result.scenes.flatMap((sc) => sc.shots.flatMap((sh) => sh.text.match(/@[\w-]+/g) ?? [])),
  );
  // @setting is the previous scene's last frame in a "same place" scene, made at render time —
  // not a placeholder, unless the script declares a reference of that name itself.
  for (const name of mentioned)
    if (
      !refByName.has(keyOf(name)) &&
      !(keyOf(name) === "setting" && !result.declared.includes("setting"))
    )
      placeholder(name);
  if (!result.scenes.length) result.warnings.push('No "## Scene" headings were found.');
  return result;
}

/** The references and voices a script names: those it declares, mentions or links to a voice. */
function scriptUses(project: Project, script: ScriptResult) {
  const names = new Set([
    ...script.declared,
    ...script.placeholders.map((p) => p.name.toLowerCase()),
    ...script.links.map((l) => l.ref),
    ...script.scenes.flatMap((sc) =>
      sc.shots.flatMap((sh) =>
        (sh.text.match(/@[\w-]+/g) ?? []).map((m) => m.slice(1).toLowerCase()),
      ),
    ),
  ]);
  const linked = new Set(script.cast.map((v) => v.ref).filter(Boolean));
  const voices = new Set(script.cast.map((v) => v.id));
  return {
    ref: (r: Ref) => names.has(r.name.toLowerCase()) || linked.has(r.id),
    voice: (v: Voice) => voices.has(v.id),
  };
}

/** What replacing the project with this script would drop: the references and voices it doesn't use. */
export function replaceDrops(project: Project, script: ScriptResult) {
  const uses = scriptUses(project, script);
  return {
    refs: project.refs.filter((r) => !uses.ref(r)),
    voices: (project.cast ?? []).filter((v) => !uses.voice(v)),
  };
}

/** Put a read script into the project, as one change (one undo).
 *  - "replace": the script becomes the film — its scenes, style, ambience and music, its voices,
 *    and only the references it uses (those keep their pictures). LoRA lanes stay, with their
 *    per-scene strengths and step shapes reset; render settings and the canvas stay. With
 *    `keepUnused`, references and voices the script doesn't use are kept too.
 *  - "append": its scenes go after the ones there; voices are merged, nothing is removed. */
export function applyScript(
  project: Project,
  script: ScriptResult,
  how: "replace" | "append",
  keepUnused = false,
) {
  const drops = how === "replace" && !keepUnused ? replaceDrops(project, script) : null;
  for (const p of script.placeholders) addProxy(project, p.name, p.note, p.kind, p.role);
  for (const x of script.roles) {
    const r = project.refs.find((ref) => ref.id === x.id);
    if (r) r.role = x.role;
  }
  for (const n of script.notes) {
    const r = project.refs.find((x) => x.id === n.id);
    if (r) r.note = n.note;
  }
  for (const l of script.links) {
    const v = script.cast.find((x) => x.id === l.voiceId);
    const r = project.refs.find((x) => x.name.toLowerCase() === l.ref);
    if (v && r) v.ref = r.id;
  }
  const cast = [...(project.cast ?? [])];
  for (const v of script.cast) {
    const at = cast.findIndex((x) => x.id === v.id);
    if (at >= 0) cast[at] = v;
    else cast.push(v);
  }
  project.cast = cast;
  // Where each reference shows without being used: "(every scene)" and "with:" set it; replacing
  // starts every other reference from none, as the old scenes it was marked for are gone.
  for (const r of project.refs) {
    const name = r.name.toLowerCase();
    if (script.every.includes(name)) r.scenes = "all";
    else if (how === "replace") r.scenes = [];
    const marked = script.with.filter((w) => w.names.includes(name)).map((w) => w.scene);
    if (marked.length && r.scenes !== "all") r.scenes = [...r.scenes, ...marked];
  }
  if (how === "replace") {
    project.scenes = script.scenes;
    project.style = script.style ?? "";
    project.direction = script.direction ?? "";
    project.soundscape = script.soundscape ?? "";
    project.music = script.music ?? "";
    if (script.canvas) project.canvas = script.canvas;
    for (const lane of project.loras ?? []) {
      lane.scenes = {};
      lane.steps = {};
    }
    if (drops) {
      project.refs = project.refs.filter((r) => !drops.refs.includes(r));
      project.cast = project.cast.filter((v) => !drops.voices.includes(v));
    }
    project.active = 0;
  } else {
    project.scenes = [...project.scenes, ...script.scenes];
    if (script.style !== undefined && !project.style.trim()) project.style = script.style;
    if (script.direction !== undefined && !project.direction.trim())
      project.direction = script.direction;
  }
}

// --- exact copies ------------------------------------------------------------------------------
export const exportJson = (project: Project) => JSON.stringify({ h3studio: 1, project }, null, 2);
/** A project from exported JSON (or a bare project object), filled out like a loaded workflow. */
export function importJson(text: string): Project {
  const data = JSON.parse(text) as { h3studio?: number; project?: unknown };
  return toProject(data && typeof data === "object" && "project" in data ? data.project : data);
}

// --- for an LLM --------------------------------------------------------------------------------
/** The format and H3's writing rules, with this project's references and voices, ready to paste
 *  into a chat with any LLM so that what it writes pastes straight back in. */
export function llmInstructions(project: Project): string {
  const refs = project.refs.map(
    (r) =>
      `- @${r.name} (${r.kind ?? "image"}${r.role === "blocking" ? ", blocking" : ""})${r.note.trim() ? `: ${r.note.trim()}` : ""}`,
  );
  const cast = (project.cast ?? []).map((v) => `- ${v.name}${v.voice ? `: ${v.voice}` : ""}`);
  return `You are writing a short film for MiniMax H3, a model that makes video with sound from text. Write it in the H3 Studio script format below, and reply with only the script.

FORMAT
# Title (optional)
style: the look of the whole film, e.g. "Live-action, cinematic, 35mm, soft tungsten light"
direction: how it's made, said in every scene after the style, e.g. "Animated on twos, with held poses" (optional; a scene can set its own)
ambience: sounds under the whole film (optional)
music: background music only the audience hears, or leave it out for none

## References
- @name: what it looks like, concretely (picture)   (one line per character, place or object that recurs)

## Cast
- Name (@reference): how the voice sounds [Language]   (one line per speaking character; the @reference and [Language] are optional)

## Scene 1: Title (5s, cut)
ambience: this scene's sounds (optional)
music: this scene's music (optional)

### 0:00
What the camera sees in this shot, in order, in the present tense.
NAME (how it's said): The exact words they speak.

### 0:03 (no cut)
What happens next, as part of the same shot.

RULES
- A scene is one generation of 2 to 15 seconds (write its length in the heading). How it follows the previous scene goes after the length: "cut" starts fresh (a new place or time); "continues" carries the previous scene's motion and camera straight on; "from last frame" opens exactly on the previous scene's last picture and moves on from there; "same place" shows that last picture as a reference (@setting), so the place and light carry over in a new shot — use it after a cut that stays in the same location; "sound carries" cuts the picture but lets the previous scene's sound (music, ambience) run on across the cut. Mention @setting in a shot to anchor it there.
- "### m:ss" starts a shot at that time into its scene; the first is 0:00. A new shot is a camera cut. "(dissolve)", "(fade)" or "(wipe)" changes how it starts. "(no cut)" or "(no cut, timed)" continues the same shot instead, for continuous motion.
- Describe what is visible and audible: composition, who is where, light, how things move, and the camera ("the camera pushes in with small amplitude at slow speed", "tracking shot", "static shot", "pans left"). Concrete and visual, not mood words.
- Give every character, place or object that appears in more than one shot a @name in "## References", with a concrete visual description (age, hair, clothes; or materials, light, layout). Mention it by @name in the shots. Until someone adds a picture for it, H3 reads that description in its place, so make it specific enough to keep the character consistent.
- A scene shows H3 only the references it uses: those its shots mention by @name, and those whose voices speak in it. To show one in a scene without mentioning it (a soundtrack, a style picture), add a line "with: @name" under that scene's heading; add "(every scene)" to a reference's line to show it everywhere.
- A video can be blocking: a grey-box render or rough animatic that shows where everyone stands and moves, the timing and the camera, but not the look. Declare it "(video, blocking)". Make it exactly as long as its scene, add "with: @name" under that scene's heading, and still describe everything in words — people, place, light and camera — because H3 takes nothing else from it. Don't use a blocking video for a character's or a place's look.
- Never put 's after an @name: write "the reflection of @anna", not "@anna's reflection".
- Reuse the references listed below where they fit, spelled exactly.
- Dialogue lines are NAME: words, with the name in capitals. (V.O.) means heard off-screen, (sings) means sung, other words in brackets say how it is delivered. Write ">>" where a line continues over the next cut, and end a line with "--" if it is cut off by the end of the scene.
- Keep speech short enough to say in its shot (about 2.5 words a second).
- Visible text, like a sign, goes in "double quotes".

REFERENCES IN THIS PROJECT
${refs.length ? refs.join("\n") : "(none yet)"}

VOICES IN THIS PROJECT
${cast.length ? cast.join("\n") : "(none yet)"}
`;
}
