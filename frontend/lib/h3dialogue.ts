// H3 Studio's dialogue on the frontend: making voices and lines, guessing how long a line takes to
// say, and reading a screenplay-style script into lines. The prompt itself is written by
// nodes/h3studio/_dialogue.py, which follows MiniMax's H3 prompt-writing guide.
import { thumbUrl, uid, type Line, type LineMode, type Project, type Scene, type Voice } from "./h3studio";

export const LANGUAGES = ["English", "Chinese", "Japanese", "Korean", "Spanish", "French", "German", "Italian", "Portuguese", "Russian"];

export const MODES: { value: LineMode; label: string; icon: string; title: string }[] = [
  { value: "say", label: "Says", icon: "mdi mdi-account-voice", title: "Spoken on screen" },
  { value: "voiceover", label: "Voice-over", icon: "mdi mdi-microphone-outline", title: "Heard off-screen; the speaker's lips stay closed" },
  { value: "sing", label: "Sings", icon: "mdi mdi-music-note", title: "Sung" },
];

/** One-click ways of saying a line. */
export const DELIVERIES = ["softly", "in a whisper", "loudly", "with a laugh", "through tears", "hesitantly", "angrily", "sarcastically", "warmly", "out of breath"];

export function newVoice(name: string, ref = ""): Voice {
  return { id: uid("v"), name, ref, timbre: "", voice: "", language: "English" };
}
export function newLine(speakers: string[] = []): Line {
  return { id: uid("d"), speakers, mode: "say", delivery: "", words: "", next: "", cutoff: false, language: "" };
}

const CJK = /[぀-ヿ㐀-鿿가-힯]/g;
/** Roughly how long a line takes: ~2.6 words a second spoken (slower sung), ~4.5 characters a
 *  second in Chinese, Japanese or Korean. */
export function speechSeconds(text: string, mode: LineMode = "say"): number {
  const cjk = text.match(CJK)?.length ?? 0;
  const words = text.replace(CJK, " ").split(/\s+/).filter(Boolean).length;
  const seconds = words / 2.6 + cjk / 4.5;
  return text.trim() ? Math.max(0.6, seconds * (mode === "sing" ? 1.6 : 1)) : 0;
}

/** Who a line's speakers are, by name. */
export function speakerNames(project: Project, line: Line): string {
  return line.speakers.map((id) => project.cast?.find((v) => v.id === id)?.name ?? "?").join(" & ") || "nobody";
}

/** The voice a name means: a cast member by name, or a reference by its @name (made into a voice). */
function voiceFor(project: Project, name: string, made: Voice[]): Voice {
  const key = name.trim().replace(/^@/, "").toLowerCase();
  const known = [...(project.cast ?? []), ...made].find((v) => v.name.toLowerCase() === key || project.refs.find((r) => r.id === v.ref)?.name.toLowerCase() === key);
  if (known) return known;
  const ref = project.refs.find((r) => r.name.toLowerCase() === key && r.kind !== "audio");
  const plain = name.trim().replace(/^@/, "");
  // Scripts shout their names (ANNA); a voice is called Anna.
  const title = plain === plain.toUpperCase() ? plain.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase()) : plain;
  const voice = newVoice(ref ? ref.name : title, ref?.id ?? "");
  made.push(voice);
  return voice;
}

/**
 * Lines from a script in the usual form, one per line:
 *
 *     ANNA: I get off at the next station.
 *     BEN (whispering): Wait.
 *     ANNA (V.O.): I still remember that road.
 *     ANNA & BEN: Wait for us!
 *     @hero (sings): La la la.
 *
 * A name is a cast voice, or a reference's @name, or else a new voice. The parenthetical is the
 * delivery, except V.O. / O.S. (a voice-over) and "sings". Text that isn't `NAME: words` joins the
 * line before it. Returns the lines and any voices it had to make.
 */
export function parseScript(project: Project, text: string): { lines: Line[]; voices: Voice[] } {
  const voices: Voice[] = [];
  const lines: Line[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const row = raw.trim();
    if (!row) continue;
    const m = /^([^:()]{1,40}?)\s*(?:\(([^)]*)\))?\s*:\s*(.+)$/.exec(row);
    if (!m) {
      const prev = lines[lines.length - 1];
      if (prev) prev.words = `${prev.words} ${row}`.trim();
      continue;
    }
    const [, who, paren = "", words] = m;
    const speakers = who!.split(/\s*(?:&|,|\band\b)\s*/i).filter(Boolean).map((n) => voiceFor(project, n, voices).id);
    const line = newLine([...new Set(speakers)]);
    const note = paren.trim();
    if (/^(v\.?\s*o\.?|o\.?\s*s\.?|voice-?over|off-?screen)$/i.test(note)) line.mode = "voiceover";
    else if (/^sing(s|ing)?$/i.test(note)) line.mode = "sing";
    else line.delivery = note;
    line.words = words!.trim();
    lines.push(line);
  }
  return { lines, voices };
}

// --- who is who ---------------------------------------------------------------------------------

export const VOICE_COLORS = ["#4fae84", "#a07ad0", "#d0975a", "#5a9ed0", "#d05a86", "#9fb84a"];
export function voiceColor(project: Project, id: string | undefined): string {
  const i = (project.cast ?? []).findIndex((v) => v.id === id);
  return i < 0 ? "#6b7280" : VOICE_COLORS[i % VOICE_COLORS.length]!;
}
/** The picture of a voice: its reference's thumbnail, when it has one. */
export function voiceThumb(project: Project, voice: Voice | undefined, size = 64): string {
  const ref = voice?.ref ? project.refs.find((r) => r.id === voice.ref) : undefined;
  return ref && ref.kind !== "audio" ? thumbUrl(ref.media, size) : "";
}

// --- when lines are said ------------------------------------------------------------------------

/** Below this, a gap before a line is just breath; above it, the prompt says there's a pause. */
export const PAUSE = 0.8;

export interface LineTime {
  line: Line;
  shot: number;
  /** Seconds into the scene. */
  start: number;
  end: number;
  /** Silence before it since the shot started or the line before ended. */
  gap: number;
  /** It probably runs past the end of its shot. */
  over: boolean;
}
/** When each of a scene's lines is said: from its `at`, but never before the previous line in the
 *  shot has finished (as nodes/h3studio/_dialogue.py places them). */
export function lineTimes(scene: Scene): LineTime[] {
  const out: LineTime[] = [];
  scene.shots.forEach((sh, i) => {
    const end = scene.shots[i + 1]?.at ?? scene.seconds;
    let cursor = sh.at;
    for (const line of sh.lines ?? []) {
      if (!line.words.trim()) continue;
      const start = Math.max(cursor, line.at ?? cursor);
      const finish = start + speechSeconds(line.words, line.mode);
      out.push({ line, shot: i, start, end: finish, gap: start - cursor, over: finish > end + 0.05 });
      cursor = finish;
    }
  });
  return out;
}

/** Drop a line at `local` seconds into the scene. Landing on another line reorders: on its first
 *  half it goes before it (taking its place), on its second half straight after it. Landing in a
 *  gap places it there, in whichever shot that falls in. */
export function moveLine(scene: Scene, id: string, local: number) {
  const from = scene.shots.find((sh) => sh.lines?.some((l) => l.id === id));
  const line = from?.lines?.find((l) => l.id === id);
  if (!from || !line) return;
  const t = Math.min(Math.max(0, local), scene.seconds - 0.1);
  // Where the others are said with this line out of the way.
  const others = lineTimes({ ...scene, shots: scene.shots.map((sh) => ({ ...sh, lines: (sh.lines ?? []).filter((l) => l !== line) })) });
  const hit = others.find((x) => t >= x.start && t < x.end);
  let to = 0;
  scene.shots.forEach((sh, i) => {
    if (t >= sh.at - 1e-6) to = i;
  });
  const target = scene.shots[hit ? hit.shot : to]!;
  const rest = (target.lines ?? []).filter((l) => l !== line);
  let index: number;
  if (hit) {
    const before = t < (hit.start + hit.end) / 2;
    index = rest.indexOf(hit.line) + (before ? 0 : 1);
    line.at = before ? hit.line.at : undefined;
  } else {
    const start = new Map(others.map((x) => [x.line.id, x.start]));
    index = rest.findIndex((l) => (start.get(l.id) ?? 0) > t);
    line.at = Math.round(t * 100) / 100;
  }
  if (target !== from) from.lines = from.lines!.filter((l) => l !== line);
  rest.splice(index < 0 ? rest.length : index, 0, line);
  target.lines = rest;
}
