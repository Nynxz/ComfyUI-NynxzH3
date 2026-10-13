// H3 Studio's timeline, from the project: scenes, shots, keyframes, a lane per voice, a lane per
// LoRA and one per reference. Pure — the editor wraps it in a computed.
import { loraLibrary as lib, type TimelineItem, type TimelineTrack } from "@nynxz/zenkit-ui";
import { mediaKind } from "@/framework";
import {
  TRANSITIONS,
  continuationOf,
  formatTime,
  onTrack,
  refInScene,
  trackSpan,
  sceneLoraStrength,
  shotColors,
  stableUrl,
  thumbUrl,
  type Project,
  type Ref,
} from "./h3studio";
import { lineTimes, speakerNames, voiceColor, voiceThumb } from "./h3dialogue";
import type { SceneState, SceneStatus } from "./h3render";
import { songOf, wave } from "./h3music";

/** Whether a curve over the sampling steps changes anything (flat at 1 doesn't). */
export const isShaped = (sampling: { v: number }[]) =>
  sampling.some((p) => Math.abs(p.v - 1) > 1e-6);

export const LORA_COLORS = ["#e0a54a", "#3fbf9b", "#d96aa7", "#4fb0d9", "#8f7cf0"];

/** "first frame" / "last frame" for a keyframe on a scene's edge, else null. */
export function edgeOf(project: Project, sceneIndex: number, at: number): string | null {
  const s = project.scenes[sceneIndex]!;
  if (at <= 0.01) return "first frame";
  if (at >= s.seconds - 0.05) return "last frame";
  return null;
}

export interface TrackContext {
  /** Where each scene starts on the film's clock. */
  starts: number[];
  /** The scene now rendering, and how far it has sampled (0–1). */
  rendering: number | null;
  renderProgress: number;
  /** Track groups the filters hide. */
  hide: string[];
  /** LoRA lanes (by id) showing their shapes over the sampling steps instead of strengths. */
  loraSteps?: string[];
  /** Whether step shapes really change over the steps here (else they are averages, and hidden). */
  stepShapes?: boolean;
  /** Each scene's render status by id (lib/h3render.ts). */
  status?: Map<string, SceneStatus>;
}

const STATE: Record<SceneState, { icon?: string; title: string }> = {
  current: { icon: "mdi-check-circle-outline", title: "rendered, up to date" },
  stale: {
    icon: "mdi-update",
    title: "out of date — it, or the scene it continues from, changed since its last render",
  },
  none: { title: "not rendered yet" },
};

export function buildTracks(project: Project, ctx: TrackContext): TimelineTrack[] {
  const { starts } = ctx;
  const state = (i: number) => {
    const s = ctx.status?.get(project.scenes[i]!.id);
    return s ? STATE[s.state] : undefined;
  };
  const scenes = project.scenes.map((s, i) => ({
    id: s.id,
    start: starts[i]!,
    end: starts[i]! + s.seconds,
    label: `Scene ${i + 1}${s.title ? ` · ${s.title}` : ""}`,
    icon:
      ctx.rendering === i
        ? "mdi-record-circle-outline"
        : (state(i)?.icon ??
          (s.render && mixed(s.render) ? "mdi-vector-combine" : undefined) ??
          (i > 0 && s.continuation.mode !== "cut"
            ? continuationOf(s.continuation.mode).icon
            : undefined)),
    title: `Scene ${i + 1} · ${s.seconds.toFixed(2)}s${i > 0 ? ` · ${continuationOf(s.continuation.mode).label.toLowerCase()}` : ""}${state(i) ? ` · ${state(i)!.title}` : ""}${s.render && mixed(s.render) ? " · its clip is mixed from several takes" : ""} — right-click to render it`,
    color: ctx.status?.get(s.id)?.state === "stale" ? "#8a6a2c" : "var(--zen-muted, #5b6b8c)",
    resize: "end" as const,
    progress: ctx.rendering === i ? ctx.renderProgress : undefined,
    peek: s.render
      ? peekOf(
          s.render,
          `Scene ${i + 1} · ${mixed(s.render) ? "mixed from takes" : "latest render"}`,
        )
      : undefined,
  }));
  const shots = project.scenes.flatMap((s, si) => {
    const colours = shotColors(s);
    return s.shots.map((sh, i) => {
      const how = i > 0 ? TRANSITIONS.find((t) => t.value === (sh.transition ?? "cut")) : undefined;
      return {
        id: sh.id,
        start: starts[si]! + sh.at,
        end: starts[si]! + (s.shots[i + 1]?.at ?? s.seconds),
        label: sh.text.trim() || `Shot ${i + 1}`,
        title: `${sh.text.trim() || `Shot ${i + 1}`}${how && how.value !== "cut" ? ` — ${how.label.toLowerCase()} from the shot before` : ""}`,
        icon: how && how.value !== "cut" ? how.icon : undefined,
        color: colours[i],
        resize: i === 0 ? (false as const) : ("start" as const),
        movable: s.shots.length > 1,
        commit: "drop" as const,
      };
    });
  });
  const keyframes = project.scenes.flatMap((s, si) => {
    const set = s.keyframes.map((k) => {
      const title = `Keyframe · scene ${si + 1} · ${edgeOf(project, si, k.at) ?? `at ${formatTime(k.at)}`}`;
      return {
        id: k.id,
        start: starts[si]! + k.at,
        kind: "marker" as const,
        thumb: thumbUrl(k.media, 96),
        peek: k.media ? peekOf(k.media, title) : undefined,
        title,
      };
    });
    return set;
  });
  const refTracks: TimelineTrack[] = project.refs.map((r) => {
    // One bar per run of consecutive scenes the reference is used in.
    const runs: { start: number; end: number }[] = [];
    project.scenes.forEach((s, i) => {
      const used = refInScene(project, r, s);
      if (!used) return;
      const prev = runs[runs.length - 1];
      if (prev && Math.abs(prev.end - starts[i]!) < 1e-6) prev.end += s.seconds;
      else runs.push({ start: starts[i]!, end: starts[i]! + s.seconds });
    });
    const kind = r.kind ?? mediaKind(r.media);
    const proxy = !r.media;
    const control = r.role === "control" && kind === "video" && !proxy;
    return {
      id: `ref:${r.id}`,
      label: `@${r.name}`,
      title: `@${r.name}${r.note ? ` — ${r.note}` : ""}${proxy ? " (a placeholder: no picture yet, so it is described in words)" : ""}`,
      thumb: kind === "image" && !proxy ? thumbUrl(r.media, 96) : undefined,
      icon:
        kind === "video"
          ? "mdi mdi-video-outline"
          : kind === "audio"
            ? "mdi mdi-music-note-outline"
            : "mdi mdi-image-outline",
      height: 26,
      movable: true,
      items: control
        ? controlItems(project, r, starts)
        : runs.map((run, i) => ({
            id: `${r.id}|${i}`,
            ...run,
            label: `@${r.name}${r.note ? ` — ${r.note}` : ""}`,
            icon: proxy
              ? "mdi-account-question-outline"
              : kind === "video"
                ? "mdi-video-outline"
                : kind === "audio"
                  ? "mdi-waveform"
                  : r.role === "reference"
                    ? "mdi-eye"
                    : "mdi-text-box-outline",
            ghost: proxy,
            peek: proxy ? undefined : peekOf(r.media, `@${r.name}${r.note ? ` — ${r.note}` : ""}`),
            color:
              kind === "audio"
                ? "#3d8f7a"
                : kind === "video"
                  ? "#b5684a"
                  : r.role === "reference"
                    ? "#8b6fd6"
                    : "#5f6a7a",
            resize: false as const,
          })),
    };
  });
  // A LoRA's strength is one value per scene: a flat bar each, dragged up or down. In the steps
  // view each scene shows instead the lane's shape over the sampling steps (shared by every scene).
  const loraTracks: TimelineTrack[] = (project.loras ?? []).map((lane, i) => {
    const shaped = isShaped(lane.sampling) || Object.values(lane.steps ?? {}).some(isShaped);
    const stepShapes = ctx.stepShapes ?? true;
    const steps = stepShapes && (ctx.loraSteps?.includes(lane.id) ?? false);
    return {
      id: `lora:${lane.id}`,
      label: `${shaped && !steps ? "∿ " : ""}${lib.short(lane.name) || "LoRA"}`,
      title: steps
        ? `${lane.name} — each scene's shape over the sampling steps: left is the first (rough) steps, right the last (detail). Double-click to add a point, drag one, right-click to remove it. Dashed scenes follow the lane's shape.`
        : `${lane.name}${lane.enabled ? "" : " (off)"} — one strength per scene: drag a bar up or down (Shift: finer), double-click it to go back to the lane's strength${shaped ? (stepShapes ? ". ∿ shaped over the sampling steps" : ". ∿ has step shapes, applied as their average here (see the LoRA panel)") : ""}`,
      thumb: lane.name && lib.hasPreview(lane.name) ? lib.preview(lane.name) : undefined,
      icon: "mdi mdi-tune-variant",
      height: 56,
      movable: true,
      items: [],
      actions: stepShapes
        ? [
            {
              id: "strength",
              icon: "mdi mdi-equalizer-outline",
              title: "Show each scene's strength",
              active: !steps,
            },
            {
              id: "steps",
              icon: "mdi mdi-chart-bell-curve",
              title: "Show each scene's shape over the sampling steps",
              active: steps,
            },
          ]
        : undefined,
      levels: {
        segments: project.scenes.map((sc, si) => {
          const v = lane.enabled ? sceneLoraStrength(project, lane, si) : 0;
          const inherited = lane.scenes?.[sc.id] === undefined;
          return {
            id: sc.id,
            start: starts[si]!,
            end: starts[si]! + sc.seconds,
            v,
            inherited,
            title: `Scene ${si + 1}: ${v.toFixed(2)}${inherited ? " (the lane's strength)" : ""}`,
            shape: (lane.steps?.[sc.id] ?? lane.sampling).map((p) => ({ x: p.p, y: p.v })),
            shapeInherited: lane.steps?.[sc.id] === undefined,
          };
        }),
        min: 0,
        max: 2,
        unit: 1,
        color: lane.enabled ? LORA_COLORS[i % LORA_COLORS.length] : "#666a74",
        mode: steps ? ("shape" as const) : ("levels" as const),
        shapeFlat: 1,
      },
    };
  });
  // One lane per voice, with its reference's picture: each line sits where it is said (drag it to
  // another time or shot); a line spoken together shows on every speaker's lane.
  const said = project.scenes.flatMap((s, si) => lineTimes(s).map((x) => ({ ...x, si })));
  const lineItem = (x: (typeof said)[number], lane: string) => {
    const l = x.line;
    const how = l.mode === "voiceover" ? " (voice-over)" : l.mode === "sing" ? " (sings)" : "";
    return {
      id: `${l.id}@${lane}`,
      start: starts[x.si]! + x.start,
      end: starts[x.si]! + x.end,
      label: l.words,
      title: `${speakerNames(project, l)}${how}${l.delivery ? `, ${l.delivery}` : ""}: “${l.words}” · ${(x.end - x.start).toFixed(1)}s${l.seconds ? "" : " (estimated)"}${x.over ? " — runs on past its shot's cut" : ""} — drag to move it, drag its end to set how long it lasts`,
      icon:
        l.mode === "voiceover"
          ? "mdi-microphone-outline"
          : l.mode === "sing"
            ? "mdi-music-note"
            : l.speakers.length > 1
              ? "mdi-account-multiple"
              : undefined,
      color: voiceColor(project, lane),
      resize: "end" as const,
      movable: true,
      commit: "drop" as const,
    };
  };
  const voiceTracks: TimelineTrack[] = (project.cast ?? []).map((v) => ({
    id: `voice:${v.id}`,
    label: v.name,
    title: `${v.name}${v.voice ? ` — ${v.voice}` : ""}`,
    thumb: voiceThumb(project, v) || undefined,
    icon: "mdi mdi-account-voice",
    color: voiceColor(project, v.id),
    height: 26,
    movable: true,
    items: said.filter((x) => x.line.speakers.includes(v.id)).map((x) => lineItem(x, v.id)),
  }));
  const nobody = said.filter(
    (x) => !x.line.speakers.some((id) => project.cast?.some((v) => v.id === id)),
  );
  if (nobody.length)
    voiceTracks.push({
      id: "voice:",
      label: "No speaker",
      icon: "mdi mdi-account-question-outline",
      height: 26,
      items: nobody.map((x) => lineItem(x, "")),
    });
  const hide = new Set(ctx.hide);
  return [
    { id: "scenes", label: "Scenes", icon: "mdi mdi-filmstrip", height: 30, items: scenes },
    { id: "shots", label: "Shots", icon: "mdi mdi-camera-outline", height: 34, items: shots },
    ...(project.track?.media && !hide.has("music") ? [musicTrack(project, starts)] : []),
    ...(hide.has("keyframes")
      ? []
      : [
          {
            id: "keyframes",
            label: "Keyframes",
            icon: "mdi mdi-rhombus-outline",
            height: 32,
            // A keyframe belongs where a shot starts (or on a scene's edge): catch those, from further.
            snapTo: ["shots", "scenes"],
            magnet: 14,
            items: keyframes,
          },
        ]),
    ...(hide.has("dialogue") ? [] : voiceTracks),
    ...(hide.has("loras") ? [] : loraTracks),
    ...(hide.has("refs") ? [] : refTracks),
  ];
}

// --- filters: show or hide whole groups of tracks, with how many each holds -----------------------
export const FILTERS = [
  { id: "music", label: "Music", icon: "mdi mdi-music" },
  { id: "keyframes", label: "Keyframes", icon: "mdi mdi-rhombus-outline" },
  { id: "dialogue", label: "Dialogue", icon: "mdi mdi-comment-quote-outline" },
  { id: "loras", label: "LoRAs", icon: "mdi mdi-tune-variant" },
  { id: "refs", label: "References", icon: "mdi mdi-image-multiple-outline" },
] as const;
export function filterCount(project: Project, id: string): number {
  if (id === "music") return project.track?.media ? 1 : 0;
  if (id === "keyframes") return project.scenes.reduce((n, s) => n + s.keyframes.length, 0);
  if (id === "dialogue")
    return project.scenes.reduce(
      (n, s) =>
        n + s.shots.reduce((m, sh) => m + (sh.lines?.filter((l) => l.words.trim()).length ?? 0), 0),
      0,
    );
  if (id === "loras") return (project.loras ?? []).length;
  return project.refs.length;
}

/** A control video's track: per scene it steers, the scene (dashed) and the stretch it steers on
 *  top — drag its ends or the whole bar (ids `<ref>|ctl|<scene index>`). */
function controlItems(project: Project, r: Ref, starts: number[]): TimelineItem[] {
  return project.scenes.flatMap((s, i) => {
    if (!refInScene(project, r, s)) return [];
    const at = starts[i]!;
    const from = r.controlFrom ?? 0;
    const to = r.controlTo ?? s.seconds;
    const whole = r.controlFrom === undefined && r.controlTo === undefined;
    const span = whole ? "the whole scene" : `${formatTime(from)}–${formatTime(to)}`;
    return [
      { id: `${r.id}|scene|${i}`, start: at, end: at + s.seconds, ghost: true, color: "#b5684a" },
      {
        id: `${r.id}|ctl|${i}`,
        start: at + Math.min(from, s.seconds),
        end: at + Math.min(to, s.seconds),
        label: `@${r.name} steers ${span}`,
        title: `@${r.name} steers scene ${i + 1}: ${span}. Drag its ends, or the bar, to steer just part of it; stretch it to the scene's ends to steer all of it`,
        icon: "mdi-vector-square",
        color: "#b5684a",
        peek: peekOf(r.media, `@${r.name} · control video`),
        resize: "both" as const,
        movable: true,
      },
    ];
  });
}

export const MUSIC_COLOR = "#c0609a";

/** The film's song, one bar per scene: its stretch of the song (ids `music|<scene id>`); scenes
 *  off the track show dimmed. */
function musicTrack(project: Project, starts: number[]): TimelineTrack {
  const media = project.track!.media;
  const song = songOf(media);
  const name = media.split("/").pop() ?? media;
  return {
    id: "music",
    label: "Music",
    title: `${name} — each scene renders to its stretch of the song, so lips and beats land on it. Right-click a scene's bar to take it off the track; drop another song here to swap it.`,
    icon: "mdi mdi-music",
    color: MUSIC_COLOR,
    height: 34,
    items: project.scenes.map((s, i) => {
      const { from, to } = trackSpan(project, i);
      const on = onTrack(project, i);
      const past = song && from >= song.duration;
      const span = `${formatTime(from)}–${formatTime(Math.min(to, song?.duration ?? to))}`;
      return {
        id: `music|${s.id}`,
        start: starts[i]!,
        end: starts[i]! + s.seconds,
        label: !on ? "off the track" : past ? "the song has ended" : `♪ ${span}`,
        title: on
          ? `Scene ${i + 1} renders to ${name} ${span}${past ? " — but the song ends before it" : ""}`
          : `Scene ${i + 1} is off the music track: H3 makes its sound, and the film keeps it`,
        color: MUSIC_COLOR,
        muted: !on || !!past,
        wave: song ? wave(song, from, to, Math.max(8, Math.round(s.seconds * 12))) : undefined,
        resize: false as const,
        peek: peekOf(media, name),
      };
    }),
  };
}

/** What Shift over a timeline item shows large (ZenPeek): its picture, video or sound. */
function peekOf(media: string, label: string): TimelineItem["peek"] {
  const kind = mediaKind(media);
  return {
    src: stableUrl(media),
    kind: kind === "video" || kind === "audio" ? kind : "image",
    label,
  };
}

/** Whether a scene's clip is mixed from several takes (nodes/h3studio/mix.py names it so). */
const mixed = (render: string) => /_mix_\d+_\.\w+$/.test(render);
