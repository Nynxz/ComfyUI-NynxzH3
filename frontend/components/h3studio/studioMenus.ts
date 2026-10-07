// H3 Studio's right-click menus. Each is built when it opens, from the project and the editor's
// actions, so it always shows the current state.
import { loraLibrary as lib, type ContextMenuItem, type TimelineTarget } from "@nynxz/zenkit-ui";
import {
  CONTINUATIONS,
  TRANSITIONS,
  formatTime,
  randomSeed,
  refInScene,
  refUsedIn,
  placeAt,
  type Place,
  type Project,
} from "@/lib/h3studio";
import { MODES as DIALOGUE_MODES, moveLine, newLine } from "@/lib/h3dialogue";
import * as edit from "@/lib/h3edits";
import { isShaped } from "@/lib/h3tracks";
import type { Selection } from "./StudioInspector.vue";

/** What the menus can make the editor do. */
export interface MenuActions {
  playhead: () => number;
  place: () => Place;
  playing: () => boolean;
  starts: () => number[];
  select: (kind: Selection["kind"], id: string) => void;
  selectAndShow: (kind: Selection["kind"], id: string) => void;
  showVoice: (id: string) => void;
  showEditTab: () => void;
  addScene: (at: number) => void;
  duplicateScene: (i: number) => void;
  removeScene: (i: number) => void;
  splitAt: (t: number) => void;
  removeShot: (id: string) => void;
  removeKeyframe: (id: string) => void;
  removeRef: (id: string) => void;
  removeLora: (id: string) => void;
  addRefs: (media: string[]) => void;
  pickImage: (title: string, selected?: string) => Promise<string | undefined>;
  pickKeyframe: (t: number) => void;
  pickRefs: () => void;
  openLoraBrowser: () => void;
  playFrom: (t: number) => void;
  togglePlay: () => void;
  seek: (t: number) => void;
  /** Render these scenes (by id), or all of them (lib/h3render.ts). */
  render: (ids: string[] | null) => void;
  /** Ids of the scenes whose latest render is out of date. */
  staleIds: () => string[];
}

export function studioMenus(project: Project, a: MenuActions) {
  function sceneMenu(i: number): ContextMenuItem[] {
    const s = project.scenes[i]!;
    return [
      { heading: `Scene ${i + 1}` },
      {
        label: "Insert scene before",
        icon: "mdi mdi-table-column-plus-before",
        run: () => a.addScene(i),
      },
      {
        label: "Insert scene after",
        icon: "mdi mdi-table-column-plus-after",
        run: () => a.addScene(i + 1),
      },
      { label: "Duplicate", icon: "mdi mdi-content-duplicate", run: () => a.duplicateScene(i) },
      { label: "Re-roll seed", icon: "mdi mdi-dice-5-outline", run: () => (s.seed = randomSeed()) },
      "-",
      { heading: "Render" },
      { label: "This scene", icon: "mdi mdi-play-box-outline", run: () => a.render([s.id]) },
      {
        label: "From here to the end",
        icon: "mdi mdi-play-box-multiple-outline",
        disabled: i === project.scenes.length - 1,
        run: () => a.render(project.scenes.slice(i).map((x) => x.id)),
      },
      "-",
      ...(i > 0
        ? [
            { heading: "From the previous scene" },
            ...CONTINUATIONS.map((c) => ({
              label: c.label,
              icon: `mdi ${s.continuation.mode === c.value ? "mdi-check" : c.icon}`,
              run: () => (s.continuation.mode = c.value),
            })),
            "-" as const,
          ]
        : []),
      {
        label: "Move earlier",
        icon: "mdi mdi-arrow-left",
        disabled: i === 0,
        run: () => edit.moveScene(project, i, -1),
      },
      {
        label: "Move later",
        icon: "mdi mdi-arrow-right",
        disabled: i === project.scenes.length - 1,
        run: () => edit.moveScene(project, i, 1),
      },
      "-",
      {
        label: "Delete scene",
        icon: "mdi mdi-trash-can-outline",
        danger: true,
        disabled: project.scenes.length < 2,
        run: () => a.removeScene(i),
      },
    ];
  }
  function shotMenu(id: string, t: number): ContextMenuItem[] {
    const at = edit.findShot(project, id)!;
    const s = project.scenes[at.scene]!;
    return [
      { heading: `Shot ${at.shot + 1} · scene ${at.scene + 1}` },
      {
        label: "Split here",
        icon: "mdi mdi-content-cut",
        hint: "double-click",
        run: () => a.splitAt(t),
      },
      {
        label: "Play from here",
        icon: "mdi mdi-play",
        run: () => a.playFrom(a.starts()[at.scene]! + s.shots[at.shot]!.at),
      },
      {
        label: "Add a keyframe here…",
        icon: "mdi mdi-rhombus-outline",
        run: () => a.pickKeyframe(t),
      },
      "-",
      ...(at.shot > 0
        ? [
            { heading: "From the shot before" },
            ...TRANSITIONS.map((tr) => ({
              label: tr.label,
              title: tr.title,
              icon:
                (s.shots[at.shot]!.transition ?? "cut") === tr.value
                  ? "mdi mdi-check"
                  : `mdi ${tr.icon}`,
              run: () => (s.shots[at.shot]!.transition = tr.value),
            })),
            "-" as const,
          ]
        : []),
      {
        label: "Move earlier",
        icon: "mdi mdi-arrow-left",
        disabled: at.shot === 0,
        run: () => edit.reorderShot(project, at.scene, at.shot, at.shot - 1),
      },
      {
        label: "Move later",
        icon: "mdi mdi-arrow-right",
        disabled: at.shot === s.shots.length - 1,
        run: () => edit.reorderShot(project, at.scene, at.shot, at.shot + 1),
      },
      "-",
      {
        label: "Delete shot",
        icon: "mdi mdi-trash-can-outline",
        danger: true,
        disabled: s.shots.length < 2,
        run: () => a.removeShot(id),
      },
    ];
  }
  function keyframeMenu(id: string): ContextMenuItem[] {
    const si = project.scenes.findIndex((sc) => sc.keyframes.some((k) => k.id === id));
    const s = project.scenes[si]!;
    const k = s.keyframes.find((x) => x.id === id)!;
    return [
      { heading: `Keyframe · scene ${si + 1}` },
      { label: "Make it the first frame", icon: "mdi mdi-page-first", run: () => (k.at = 0) },
      { label: "Make it the last frame", icon: "mdi mdi-page-last", run: () => (k.at = s.seconds) },
      {
        label: "Replace image…",
        icon: "mdi mdi-image-edit-outline",
        run: async () => {
          const m = await a.pickImage("Replace keyframe picture", k.media);
          if (m) k.media = m;
        },
      },
      {
        label: "Use as a reference too",
        icon: "mdi mdi-account-box-plus-outline",
        run: () => a.addRefs([k.media]),
      },
      "-",
      {
        label: "Remove keyframe",
        icon: "mdi mdi-trash-can-outline",
        danger: true,
        run: () => a.removeKeyframe(id),
      },
    ];
  }
  function refMenu(id: string, t = a.playhead()): ContextMenuItem[] {
    const r = project.refs.find((x) => x.id === id)!;
    const p = placeAt(project, t);
    const scene = project.scenes[p.scene]!;
    const used = refUsedIn(project, r, scene);
    const inScene = refInScene(project, r, scene);
    const full = r.role === "reference";
    return [
      { heading: `@${r.name}` },
      {
        label: used
          ? `Used in scene ${p.scene + 1}`
          : inScene
            ? `Leave out of scene ${p.scene + 1}`
            : `Show in scene ${p.scene + 1} anyway`,
        icon: inScene ? "mdi mdi-eye-off-outline" : "mdi mdi-eye-outline",
        disabled: used,
        run: () => edit.toggleRefScene(project, id, scene.id),
      },
      r.scenes === "all"
        ? {
            label: "Only where used or marked",
            icon: "mdi mdi-filmstrip-off",
            run: () => (r.scenes = []),
          }
        : {
            label: "Show in every scene",
            icon: "mdi mdi-filmstrip",
            run: () => (r.scenes = "all"),
          },
      {
        label: full ? "Meaning only (looser)" : "Look + meaning",
        icon: full ? "mdi mdi-text-box-outline" : "mdi mdi-image-filter-center-focus",
        run: () => (r.role = full ? "semantic" : "reference"),
      },
      {
        label: "Mention in this shot",
        icon: "mdi mdi-at",
        run: () => edit.mentionInShot(project, r.name, p.scene, p.shot),
      },
      { label: "Edit…", icon: "mdi mdi-pencil-outline", run: () => a.select("ref", id) },
      "-",
      {
        label: "Remove reference",
        icon: "mdi mdi-trash-can-outline",
        danger: true,
        run: () => a.removeRef(id),
      },
    ];
  }
  function loraMenu(id: string, t: number): ContextMenuItem[] {
    const lane = project.loras?.find((l) => l.id === id);
    if (!lane) return [];
    const si = placeAt(project, t).scene;
    const scene = project.scenes[si]!;
    const ownStrength = lane.scenes?.[scene.id] !== undefined;
    const ownShape = lane.steps?.[scene.id];
    const without = <T>(map: Record<string, T> | undefined) =>
      Object.fromEntries(Object.entries(map ?? {}).filter(([k]) => k !== scene.id));
    return [
      { heading: lib.short(lane.name) || "LoRA" },
      ...(ownStrength
        ? [
            {
              label: `Scene ${si + 1}: back to the lane's strength`,
              icon: "mdi mdi-backup-restore",
              run: () => (lane.scenes = without(lane.scenes)),
            },
          ]
        : []),
      ...(ownShape
        ? [
            {
              label: `Scene ${si + 1}: follow the lane's step shape`,
              icon: "mdi mdi-backup-restore",
              run: () => (lane.steps = without(lane.steps)),
            },
            {
              label: `Use scene ${si + 1}'s step shape everywhere`,
              icon: "mdi mdi-content-copy",
              run: () => {
                lane.sampling = ownShape.map((p) => ({ ...p }));
                lane.steps = {};
              },
            },
          ]
        : []),
      ...(ownStrength || ownShape ? ["-" as const] : []),
      {
        label: lane.enabled ? "Turn off" : "Turn on",
        icon: lane.enabled ? "mdi mdi-eye-off-outline" : "mdi mdi-eye-outline",
        run: () => (lane.enabled = !lane.enabled),
      },
      ...(Object.keys(lane.scenes ?? {}).length
        ? [
            {
              label: "Every scene to the lane's strength",
              icon: "mdi mdi-backup-restore",
              run: () => (lane.scenes = {}),
            },
          ]
        : []),
      ...(isShaped(lane.sampling) || Object.keys(lane.steps ?? {}).length
        ? [
            {
              label: "Flatten every step shape",
              icon: "mdi mdi-minus",
              run: () => {
                lane.sampling = [];
                lane.steps = {};
              },
            },
          ]
        : []),
      "-",
      {
        label: "Remove LoRA lane",
        icon: "mdi mdi-trash-can-outline",
        danger: true,
        run: () => a.removeLora(id),
      },
    ];
  }
  function lineMenu(id: string): ContextMenuItem[] {
    const found = edit.findLine(project, id);
    if (!found) return [];
    const { shot, line } = found;
    return [
      { heading: `“${line.words.length > 32 ? `${line.words.slice(0, 32)}…` : line.words}”` },
      ...(project.cast ?? []).map((v) => ({
        label: v.name,
        icon: line.speakers.includes(v.id) ? "mdi mdi-check" : "mdi mdi-account-voice",
        run: () => (line.speakers = [v.id]),
      })),
      "-",
      ...DIALOGUE_MODES.map((m) => ({
        label: m.label,
        icon: line.mode === m.value ? "mdi mdi-check" : m.icon,
        run: () => (line.mode = m.value),
      })),
      ...(line.at !== undefined
        ? [
            "-" as const,
            {
              label: "Follow straight on",
              icon: "mdi mdi-arrow-collapse-left",
              run: () => (line.at = undefined),
            },
          ]
        : []),
      "-",
      {
        label: "Edit in its shot",
        icon: "mdi mdi-pencil-outline",
        run: () => a.selectAndShow("shot", shot.id),
      },
      {
        label: "Remove the line",
        icon: "mdi mdi-trash-can-outline",
        run: () => (shot.lines = shot.lines!.filter((l) => l !== line)),
      },
    ];
  }
  /** Right-click a voice's lane: a new line for that voice, starting there. */
  function voiceLaneMenu(voiceId: string, t: number): ContextMenuItem[] {
    const voice = project.cast?.find((v) => v.id === voiceId);
    if (!voice) return [];
    const p = placeAt(project, t);
    return [
      { heading: voice.name },
      {
        label: `A line for ${voice.name} here`,
        icon: "mdi mdi-comment-plus-outline",
        run: () => {
          const scene = project.scenes[p.scene]!;
          const shot = scene.shots[p.shot]!;
          const line = { ...newLine([voiceId]), at: Math.round(p.local * 100) / 100 };
          shot.lines = [...(shot.lines ?? []), line];
          moveLine(scene, line.id, p.local);
          a.selectAndShow("shot", shot.id);
          a.showEditTab();
        },
      },
      {
        label: "Edit the voice",
        icon: "mdi mdi-account-edit-outline",
        run: () => a.showVoice(voiceId),
      },
    ];
  }
  /** The menu for a right-click on the timeline, or null when the click means something else. */
  function timelineMenu(target: TimelineTarget, t: number): ContextMenuItem[] | null {
    const { trackId, itemId } = target;
    if (trackId.startsWith("lora:")) return loraMenu(trackId.replace(/^lora:/, ""), t);
    if (trackId.startsWith("voice:"))
      return itemId
        ? lineMenu(itemId.split("@")[0]!)
        : voiceLaneMenu(trackId.replace(/^voice:/, ""), t);
    if (itemId && trackId === "scenes")
      return sceneMenu(project.scenes.findIndex((s) => s.id === itemId));
    if (itemId && trackId === "shots") return shotMenu(itemId, t);
    if (itemId?.startsWith("ghost:")) return null;
    if (itemId && trackId === "keyframes") return keyframeMenu(itemId);
    if (itemId) return refMenu(itemId.split("|")[0]!, t);
    const p = placeAt(project, t);
    return [
      { heading: `${formatTime(t)} · scene ${p.scene + 1}` },
      { label: "Split the shot here", icon: "mdi mdi-content-cut", run: () => a.splitAt(t) },
      {
        label: "Add a keyframe here…",
        icon: "mdi mdi-rhombus-outline",
        run: () => a.pickKeyframe(t),
      },
      {
        label: "Add references…",
        icon: "mdi mdi-account-box-plus-outline",
        run: () => a.pickRefs(),
      },
      { label: "Add a LoRA lane…", icon: "mdi mdi-tune-variant", run: () => a.openLoraBrowser() },
      "-",
      {
        label: "Add a scene at the end",
        icon: "mdi mdi-plus",
        run: () => a.addScene(project.scenes.length),
      },
      { label: "Move the playhead here", icon: "mdi mdi-ray-vertex", run: () => a.seek(t) },
    ];
  }
  function monitorMenu(): ContextMenuItem[] {
    const t = a.playhead();
    const scene = a.place().scene;
    const playing = a.playing();
    return [
      { heading: `${formatTime(t)} · scene ${scene + 1}` },
      {
        label: playing ? "Pause" : "Play",
        icon: playing ? "mdi mdi-pause" : "mdi mdi-play",
        hint: "space",
        run: a.togglePlay,
      },
      {
        label: "Add a keyframe at the playhead…",
        icon: "mdi mdi-rhombus-outline",
        run: () => a.pickKeyframe(t),
      },
      {
        label: "Split the shot at the playhead",
        icon: "mdi mdi-content-cut",
        run: () => a.splitAt(t),
      },
      ...(project.scenes[scene]?.render
        ? [
            {
              label: "Forget this scene's render",
              icon: "mdi mdi-movie-remove-outline",
              run: () => delete project.scenes[scene]!.render,
            },
          ]
        : []),
      "-",
      ...sceneMenu(scene).slice(1),
    ];
  }
  return { refMenu, timelineMenu, monitorMenu };
}
