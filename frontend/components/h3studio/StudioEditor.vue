<template>
  <div
    ref="rootEl"
    class="studio zen-scroll"
    tabindex="0"
    data-capture-wheel="true"
    @contextmenu.prevent.stop
    @pointerenter="onEnter"
    @pointerleave="onLeave"
    @focus.self="keySink?.focus({ preventScroll: true })"
  >
    <!-- Holds focus while the pointer is over the studio: ComfyUI leaves Ctrl+Z to a focused text
         field, so the studio's own undo gets it instead of the workflow's. -->
    <textarea ref="keySink" class="keysink" readonly tabindex="-1" aria-hidden="true" />
    <!-- Shift over any thumbnail shows it large. -->
    <ZenPeek />
    <!-- toolbar -->
    <div class="bar">
      <button
        type="button"
        class="rendersbtn"
        :class="{ on: rendersOpen }"
        :title="
          live.rendering !== null
            ? `Renders — S${live.rendering + 1} is rendering`
            : 'Renders — now, up next and every take'
        "
        :aria-pressed="rendersOpen"
        @click="rendersOpen = !rendersOpen"
      >
        <i class="mdi mdi-history" />
        <span v-if="live.rendering !== null" class="recdot" />
      </button>
      <span
        v-if="!inPanel"
        class="brand"
        :title="`${project.scenes.length} scene${project.scenes.length === 1 ? '' : 's'} · ${formatTime(length)}`"
      >
        <i class="mdi mdi-movie-open-star-outline" /> H3 Studio
      </span>
      <ZenToggleGroup
        v-model="monitorMode"
        class="modes"
        collapse
        :options="[
          {
            value: 'follow',
            label: 'Follow',
            icon: 'mdi mdi-auto-fix',
            title:
              'Shows each scene as far as it has got: its steps while it renders, its clip when done, else the plan',
          },
          {
            value: 'plan',
            label: 'Plan',
            icon: 'mdi mdi-animation-outline',
            title: 'The animatic: keyframes, references and shot text',
          },
          {
            value: 'preview',
            label: 'Preview',
            icon: 'mdi mdi-progress-clock',
            title: 'The sampler\'s steps for this scene — hover or click to scrub',
          },
          {
            value: 'render',
            label: 'Render',
            icon: 'mdi mdi-movie-check-outline',
            title: 'The finished clip, played and scrubbed with the timeline',
          },
        ]"
      />
      <button
        v-if="live.rendering !== null"
        type="button"
        class="livechip"
        :title="`Scene ${live.rendering + 1} is rendering — show its steps`"
        @click="watchRender"
      >
        <i class="mdi mdi-record-circle" /> S{{ live.rendering + 1 }}
        <template v-if="renderingStep">· {{ renderingStep }}</template>
      </button>
      <span class="grow" />
      <StudioCodex :project="project" />
      <ZenButton
        sm
        icon="mdi mdi-play-box-multiple-outline"
        :title="
          outOfDate.length
            ? `Render scenes — ${outOfDate.length} out of date or not rendered yet`
            : 'Render scenes — every scene is up to date'
        "
        @click="openRenderMenu"
      >
        Render<span v-if="outOfDate.length" class="due">{{ outOfDate.length }}</span>
      </ZenButton>
      <span
        class="task"
        :class="{ warned: compiled?.warnings.length }"
        :title="taskTitle"
        @click="copyPrompt"
      >
        <b>S{{ place.scene + 1 }}</b>
        <span>{{
          copied ? "Prompt copied" : compiled ? (TASK_SHORT[compiled.task] ?? compiled.task) : "…"
        }}</span>
        <template v-if="compiled?.warnings.length"
          ><i class="mdi mdi-alert-outline" />{{ compiled.warnings.length }}</template
        >
      </span>
      <ZenPopover placement="bottom-end">
        <template #trigger="{ toggle }">
          <ZenButton sm icon="mdi mdi-aspect-ratio" title="Canvas size" @click="toggle">
            {{ project.canvas.width }}×{{ project.canvas.height }}
          </ZenButton>
        </template>
        <ZenResolution
          :width="project.canvas.width"
          :height="project.canvas.height"
          :snap="32"
          :presets="[0.5, 0.75, 1.5, 2]"
          :native="nativeCanvas"
          :max-side="2048"
          :max-mp="4"
          @update:width="(w: number) => (project.canvas = { ...project.canvas, width: w })"
          @update:height="(h: number) => (project.canvas = { ...project.canvas, height: h })"
        />
      </ZenPopover>
      <ZenIconButton
        icon="mdi mdi-script-text-outline"
        title="Script — paste scenes as text, copy them out, or write them with an LLM"
        @click="scriptOpen = true"
      />
      <ZenIconButton
        icon="mdi mdi-view-dashboard-outline"
        title="Reference sheet — the references packed onto one board, to look over or share"
        :disabled="!project.refs.length"
        @click="sheetOpen = true"
      />
      <ZenIconButton
        icon="mdi mdi-cog-outline"
        title="Studio settings"
        @click="settingsOpen = true"
      />
      <ZenIconButton
        icon="mdi mdi-undo"
        title="Undo (Ctrl+Z)"
        :disabled="!history.canUndo"
        @click="history.undo()"
      />
      <ZenIconButton
        icon="mdi mdi-redo"
        title="Redo (Ctrl+Shift+Z)"
        :disabled="!history.canRedo"
        @click="history.redo()"
      />
      <ZenIconButton
        :icon="LAYOUT_ICON[layout]"
        :title="`Layout: ${LAYOUT_TITLE[layout]} — click to change`"
        @click="cycleLayout"
      />
      <ZenIconButton
        v-if="canPopOut && !inPanel"
        icon="mdi mdi-open-in-new"
        title="Pop out into a panel"
        @click="emit('popOut')"
      />
    </div>

    <!-- monitor + inspector, over the transport; then the timeline. Both splits are ZenSplit: drag
         the gap to resize, double-click it to reset, arrow keys on it nudge. -->
    <div class="main">
      <StudioRenders
        v-if="rendersOpen"
        :project="project"
        :node-id="props.nodeId ?? ''"
        :live="live"
        @close="rendersOpen = false"
        @changed="renderStatus.refresh()"
      />
      <ZenSplit
        class="body"
        direction="vertical"
        gutter="gap"
        :panes="[{ min: 180 }, { size: 232, min: 96, max: 640 }]"
        :sizes="[1, timelineHeight]"
        @update:sizes="onTimelineSizes"
      >
        <template #pane-0>
          <div class="upper">
            <div ref="stageEl" class="stage" :class="{ stacked }">
              <ZenSplit
                :key="stacked ? 'stacked' : 'side'"
                class="stagesplit"
                :direction="stacked ? 'vertical' : 'horizontal'"
                gutter="gap"
                :panes="stagePanes"
                :sizes="stageSizes"
                @update:sizes="onStageSizes"
              >
                <template #pane-0>
                  <StudioMonitor
                    :project="project"
                    :place="place"
                    :time="playhead"
                    :mode="monitorMode"
                    :run="live.runs[place.scene] ?? null"
                    :scene-seconds="project.scenes[place.scene]?.seconds ?? 0"
                    :rendering="live.rendering === place.scene"
                    :clip="project.scenes[place.scene]?.render"
                    :offset="playhead - (starts[place.scene] ?? 0)"
                    :playing="playing"
                    :volume="volume"
                    :muted="muted"
                    @sound="(v: boolean) => (monitorHasSound = v)"
                    @context="monitorMenu"
                  />
                </template>
                <template #pane-1>
                  <div class="side">
                    <ZenToggleGroup
                      v-model="tab"
                      class="tabs"
                      :options="[
                        { value: 'edit', label: 'Edit', icon: 'mdi mdi-pencil-outline' },
                        {
                          value: 'refs',
                          label: `Refs · ${sceneRefCount}`,
                          icon: 'mdi mdi-account-box-multiple-outline',
                        },
                        {
                          value: 'cast',
                          label: `Cast · ${project.cast?.length ?? 0}`,
                          icon: 'mdi mdi-account-voice',
                        },
                      ]"
                    />
                    <div class="sidebody">
                      <!-- Both stay mounted: switching tabs mustn't rebuild every thumbnail. -->
                      <StudioInspector
                        v-show="tab === 'edit'"
                        :project="project"
                        :sel="editSelection"
                        :current-scene="place.scene"
                        :compiled="compiled"
                        @select="(t) => selectAndShow(t.kind, t.id)"
                        @seconds="setSeconds"
                        @remove-keyframe="removeKeyframe"
                        @set-keyframe="pickEdgeKeyframe"
                        @remove-shot="removeShot"
                        @add-shot="addShotTo"
                        @voice="showVoice"
                      />
                      <StudioCast v-show="tab === 'cast'" :project="project" :focus="castFocus" />
                      <StudioRefs
                        v-show="tab === 'refs'"
                        :project="project"
                        :scene-index="place.scene"
                        :compiled="compiled"
                        :selected="selection.kind === 'ref' ? selection.id : null"
                        :view="view"
                        :strip="stacked"
                        @select="(id: string) => select('ref', id)"
                        @menu="(id: string, e: MouseEvent) => openMenu(refMenu(id), e)"
                        @add="(accept: string) => pickRefs(accept)"
                        @drop="dropRefs"
                        @remove="removeRef"
                        @toggle-scene="toggleRefScene"
                        @pick="pickRefMedia"
                        @replace="dropRefMedia"
                        @add-proxy="addProxy"
                      />
                    </div>
                  </div>
                </template>
              </ZenSplit>
            </div>

            <!-- transport -->
            <div class="transport">
              <ZenIconButton icon="mdi mdi-skip-backward" title="To the start" @click="seek(0)" />
              <ZenIconButton
                icon="mdi mdi-skip-previous"
                title="Previous shot (←)"
                @click="stepShot(-1)"
              />
              <ZenButton
                variant="primary"
                :icon="playing ? 'mdi mdi-pause' : 'mdi mdi-play'"
                :title="playing ? 'Pause (space)' : 'Play (space)'"
                @click="togglePlay"
              />
              <ZenIconButton icon="mdi mdi-skip-next" title="Next shot (→)" @click="stepShot(1)" />
              <button
                type="button"
                class="loopbtn"
                :class="{ on: loopMode !== 'off' }"
                :title="`Loop: ${LOOP_TITLE[loopMode]} — click to change`"
                @click="cycleLoop"
              >
                <i
                  class="mdi"
                  :class="
                    loopMode === 'off'
                      ? 'mdi-repeat-off'
                      : loopMode === 'film'
                        ? 'mdi-repeat'
                        : 'mdi-repeat-once'
                  "
                />
                <span v-if="loopMode !== 'off'">{{ loopMode }}</span>
              </button>
              <ZenVolume
                v-model:volume="volume"
                v-model:muted="muted"
                :disabled="!monitorHasSound"
                disabled-title="What the monitor shows has no sound — Render plays a finished clip's audio, Preview a preview clip's"
              />
              <span class="tc"
                >{{ formatTime(playhead) }}
                <span class="soft">/ {{ formatTime(length) }}</span></span
              >
              <span class="grow" />
              <span class="filters" title="Show or hide groups of tracks">
                <button
                  v-for="f in FILTERS"
                  :key="f.id"
                  type="button"
                  class="filter"
                  :class="{ off: view.hide?.includes(f.id) }"
                  :title="`${view.hide?.includes(f.id) ? 'Show' : 'Hide'} ${f.label.toLowerCase()} on the timeline`"
                  @click="toggleFilter(f.id)"
                >
                  <i class="mdi" :class="f.icon" /> {{ filterCount(f.id) }}
                </button>
              </span>
              <ZenButton
                sm
                icon="mdi mdi-plus"
                title="Add a LoRA lane"
                @click="loraBrowserOpen = true"
                >LoRA</ZenButton
              >
              <ZenButton
                sm
                icon="mdi mdi-plus"
                title="Add a scene at the end"
                @click="addScene(project.scenes.length)"
                >Scene</ZenButton
              >
              <span class="divider" />
              <ZenIconButton
                icon="mdi mdi-magnify-minus-outline"
                title="Zoom out (alt + scroll)"
                @click="zoomBy(1 / 1.4)"
              />
              <ZenIconButton
                icon="mdi mdi-arrow-expand-horizontal"
                :active="zoom === 0"
                title="Fit the whole film"
                @click="zoom = 0"
              />
              <ZenIconButton
                icon="mdi mdi-magnify-plus-outline"
                title="Zoom in (alt + scroll)"
                @click="zoomBy(1.4)"
              />
            </div>
          </div>
        </template>
        <!-- the timeline: the whole film on one clock; tracks past its height scroll -->
        <template #pane-1>
          <ZenTimeline
            ref="timeline"
            class="tl"
            v-model:playhead="playhead"
            v-model:zoom="zoom"
            :duration="length"
            :tracks="tracks"
            :selected="selectedItemIds"
            :guides="starts.slice(1)"
            :range="loopRange"
            @select="onTimelineSelect"
            @move="onTimelineMove"
            @context="onTimelineContext"
            @drop="onTimelineDrop"
            @dblclick="onTimelineDblClick"
            @reorder="onTrackReorder"
            @level="onLevel"
            @shape="onShape"
            @action="onTrackAction"
          />
        </template>
      </ZenSplit>
    </div>

    <StudioSettings v-model:open="settingsOpen" :project="project" />
    <StudioScript v-model:open="scriptOpen" :project="project" />
    <StudioSheet v-model:open="sheetOpen" :project="project" :scene-index="place.scene" />
    <ZenContextMenu ref="menu" :items="menuItems" />
    <LoraBrowser v-model:open="loraBrowserOpen" @pick="addLora" />
    <ZenMediaPicker
      :open="picker.open"
      :library="mediaLibrary"
      :kinds="picker.kinds"
      :multiple="picker.multiple"
      :title="picker.title"
      :confirm-label="picker.confirmLabel"
      :selected="picker.selected"
      :subfolder="UPLOADS"
      @update:open="onPickerOpen"
      @pick="onPicked"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, shallowRef, watch } from "vue";
import {
  LoraBrowser,
  ZenButton,
  ZenContextMenu,
  ZenIconButton,
  ZenMediaPicker,
  ZenPeek,
  ZenPopover,
  ZenResolution,
  ZenSplit,
  ZenTimeline,
  ZenToggleGroup,
  ZenVolume,
  type ContextMenuItem,
  type MediaPickerKind,
  type TimelineTarget,
  type TimelineTrack,
} from "@nynxz/zenkit-ui";
import {
  hasMediaDrop,
  hasZenPanels,
  mediaLibrary,
  readMediaDrop,
  uploadOrReuse,
} from "@/framework";
import {
  compileScene,
  nativeCanvas,
  filmLength,
  formatTime,
  placeAt,
  refInScene,
  sceneStarts,
  type Compiled,
  type Project,
  type Ref,
  newLoraLane,
  type StudioView,
  loadCapabilities,
  stepShapesWork,
} from "@/lib/h3studio";
import * as edit from "@/lib/h3edits";
import { buildTracks, FILTERS, filterCount as filterCount_ } from "@/lib/h3tracks";
import { useProjectHistory } from "@/lib/h3history";
import { useStudioLive } from "@/lib/h3live";
import { renderScenes, useRenderStatus } from "@/lib/h3render";
import StudioInspector, { type Selection } from "./StudioInspector.vue";
import type { MonitorMode } from "./StudioMonitor.vue";
import StudioCodex from "./StudioCodex.vue";
import StudioRenders from "./StudioRenders.vue";
import StudioMonitor from "./StudioMonitor.vue";
import StudioRefs from "./StudioRefs.vue";
import StudioCast from "./StudioCast.vue";
import StudioSettings from "./StudioSettings.vue";
import StudioScript from "./StudioScript.vue";
import StudioSheet from "./StudioSheet.vue";
import { studioMenus } from "./studioMenus";

const props = defineProps<{
  project: Project;
  view?: StudioView;
  nodeId?: string;
  inPanel?: boolean;
}>();
/** How the editor was left (mode, loop, tab, zoom, playhead), kept on the node. */
const view: StudioView = props.view ?? reactive({});
const emit = defineEmits<{ popOut: [] }>();
const project = props.project;
const history = useProjectHistory(project);
loadCapabilities();
const settingsOpen = ref(false);
const scriptOpen = ref(false);
const sheetOpen = ref(false);

// --- monitor modes and renders --------------------------------------------------------------------
// The monitor shows what you pick — the plan, the sampler's steps, or the finished clip — and a
// run never takes it over: a chip in the toolbar says which scene is rendering, and jumps there.
const live = useStudioLive(props.nodeId ?? "");
// --- partial renders: which scenes are up to date, and rendering just some (lib/h3render.ts) -----
const renderStatus = useRenderStatus(project);
// The Renders sidebar: toggled from the toolbar, remembered.
const rendersOpen = ref(
  (() => {
    try {
      return localStorage.getItem("nynxz.h3.renders") === "1";
    } catch {
      return false;
    }
  })(),
);
watch(rendersOpen, (v) => {
  try {
    localStorage.setItem("nynxz.h3.renders", v ? "1" : "0");
  } catch {
    /* not remembered */
  }
});
onBeforeUnmount(renderStatus.stop);
/** Scenes whose latest render is out of date, or that have none yet. */
const outOfDate = computed(() =>
  project.scenes.filter((s) => renderStatus.status.get(s.id)?.state !== "current").map((s) => s.id),
);
const render = (ids: string[] | null) => void renderScenes(project, props.nodeId ?? "", ids);
function openRenderMenu(e: MouseEvent) {
  const i = place.value.scene;
  openMenu(
    [
      { heading: "Render" },
      {
        label: `This scene (scene ${i + 1})`,
        icon: "mdi mdi-play-box-outline",
        run: () => render([project.scenes[i]!.id]),
      },
      {
        label: `From scene ${i + 1} to the end`,
        icon: "mdi mdi-play-box-multiple-outline",
        disabled: i === project.scenes.length - 1,
        run: () => render(project.scenes.slice(i).map((s) => s.id)),
      },
      {
        label: outOfDate.value.length
          ? `What's out of date (${outOfDate.value.length})`
          : "What's out of date (nothing)",
        icon: "mdi mdi-update",
        disabled: !outOfDate.value.length,
        run: () => render(outOfDate.value),
      },
      { label: "Every scene", icon: "mdi mdi-filmstrip", run: () => render(null) },
    ],
    e,
  );
}
const monitorMode = ref<MonitorMode>((view.mode as MonitorMode) ?? "follow");
watch(monitorMode, (m) => (view.mode = m));

// The monitor's volume, owned by the transport and remembered between sessions.
const VOLUME_KEY = "nynxz.h3studio.volume";
const volume = ref(0.8);
const muted = ref(false);
const monitorHasSound = ref(false);
try {
  const saved = JSON.parse(localStorage.getItem(VOLUME_KEY) ?? "null") as {
    v: number;
    m: boolean;
  } | null;
  if (saved) [volume.value, muted.value] = [saved.v, saved.m];
} catch {
  // a remembered volume is a convenience
}
watch([volume, muted], () => {
  try {
    localStorage.setItem(VOLUME_KEY, JSON.stringify({ v: volume.value, m: muted.value }));
  } catch {
    // a remembered volume is a convenience
  }
});
// Following, the playhead goes to each scene as it starts rendering. Mid-playback only when a
// scene or shot loop is on — then the loop moves on to the scene now rendering, so you watch each
// one come in without clicking through; otherwise playback isn't interrupted.
watch(
  () => live.rendering,
  (scene) => {
    if (scene === null || monitorMode.value !== "follow") return;
    const looping = loopMode.value === "scene" || loopMode.value === "shot";
    if (playing.value && !looping) return;
    if (place.value.scene !== scene) playhead.value = starts.value[scene]! + 0.01;
  },
);
const renderingStep = computed(() => {
  const run = live.rendering === null ? [] : (live.runs[live.rendering]?.steps ?? []);
  const last = run[run.length - 1];
  return last ? `${last.step}${last.total ? `/${last.total}` : ""}` : "";
});
/** How far the scene now rendering has sampled, 0–1 (0 until its first step lands). */
const renderProgress = computed(() => {
  const run = live.rendering === null ? [] : (live.runs[live.rendering]?.steps ?? []);
  const lastStep = run[run.length - 1];
  return lastStep?.total ? lastStep.step / lastStep.total : 0;
});
function watchRender() {
  if (live.rendering === null) return;
  monitorMode.value = "preview";
  if (place.value.scene !== live.rendering) playhead.value = starts.value[live.rendering]! + 0.01;
}
// H3 Studio Clip reports each saved clip; keep it on its scene, so it is there after a reload.
watch(
  () => ({ ...live.clips }),
  (clips) => {
    for (const [i, media] of Object.entries(clips)) {
      const scene = project.scenes[Number(i)];
      if (scene && scene.render !== media) scene.render = media;
    }
  },
  { immediate: true },
);

const UPLOADS = "h3studio";
const canPopOut = hasZenPanels();
const rootEl = ref<HTMLElement | null>(null);
const timeline = ref<InstanceType<typeof ZenTimeline> | null>(null);
const menu = ref<InstanceType<typeof ZenContextMenu> | null>(null);

// --- clock -------------------------------------------------------------------------------------
const playhead = ref(view.time ?? sceneStarts(project)[project.active] ?? 0);
const zoom = ref(view.zoom ?? 0);
// Fits the ruler, scenes, shots, keyframes and about four references; more references scroll.
const timelineHeight = ref(view.timeline ?? 232);
/** The timeline's height, from its split (saved on the node). */
function onTimelineSizes(sizes?: number[]) {
  const h = sizes?.[1];
  if (h == null) return;
  timelineHeight.value = Math.round(h);
  view.timeline = timelineHeight.value;
}
watch(zoom, (z) => (view.zoom = z));
const starts = computed(() => sceneStarts(project));
const length = computed(() => filmLength(project));
const place = computed(() =>
  placeAt(project, Math.min(playhead.value, Math.max(0, length.value - 1e-3))),
);
const seek = (t: number) => (playhead.value = Math.min(Math.max(t, 0), length.value));
function zoomBy(factor: number) {
  const base = zoom.value || (rootEl.value?.clientWidth ?? 800) / Math.max(length.value, 1);
  zoom.value = Math.min(2000, base * factor);
}

// --- playback: the animatic (or the renders) run in real time over the film ----------------------
const playing = ref(false);
/** The shot the inspector edits when nothing is picked: the one under the playhead, but held while
 *  playback runs, so the editor stays put instead of jumping from shot to shot. */
const editPlace = shallowRef(place.value);
watch(place, (p) => {
  if (!playing.value) editPlace.value = p;
});
// The scene you are on (in the project) and the exact playhead (in the view) are remembered — but
// not while playback runs through the film, which would rewrite the workflow at every cut.
watch(
  () => [place.value.scene, playing.value] as const,
  ([scene, isPlaying]) => {
    if (!isPlaying && project.active !== scene) project.active = scene;
  },
);
watch([playhead, playing], () => {
  if (!playing.value && view.time !== playhead.value) view.time = playhead.value;
});
type LoopMode = "off" | "film" | "scene" | "shot";
const LOOPS: LoopMode[] = ["off", "film", "scene", "shot"];
const LOOP_TITLE: Record<LoopMode, string> = {
  off: "off",
  film: "the whole film",
  scene: "the scene at the playhead",
  shot: "the shot at the playhead",
};
const loopMode = ref<LoopMode>(
  LOOPS.includes(view.loop as LoopMode) ? (view.loop as LoopMode) : "off",
);
watch(loopMode, (m) => (view.loop = m));
const cycleLoop = () =>
  (loopMode.value = LOOPS[(LOOPS.indexOf(loopMode.value) + 1) % LOOPS.length]!);
/** The span playback stays inside: the scene or shot under the playhead, or the whole film. */
const loopRange = computed(() => {
  const p = place.value;
  const start = starts.value[p.scene] ?? 0;
  const scene = project.scenes[p.scene];
  if (!scene) return null;
  if (loopMode.value === "scene") return { start, end: start + scene.seconds };
  if (loopMode.value === "shot") {
    const shot = scene.shots[p.shot];
    const next = scene.shots[p.shot + 1];
    return shot ? { start: start + shot.at, end: start + (next?.at ?? scene.seconds) } : null;
  }
  return null;
});
let raf = 0;
let last = 0;
function frame(now: number) {
  const dt = (now - last) / 1000;
  last = now;
  const range = loopRange.value;
  const end = range?.end ?? length.value;
  let t = playhead.value + dt;
  if (t >= end - 1e-3) {
    if (loopMode.value === "off") {
      playhead.value = length.value;
      return stop();
    }
    t = range?.start ?? 0;
  }
  playhead.value = t;
  timeline.value?.follow();
  raf = requestAnimationFrame(frame);
}
function stop() {
  playing.value = false;
  cancelAnimationFrame(raf);
}
function togglePlay() {
  if (playing.value) return stop();
  const range = loopRange.value;
  if (range && (playhead.value < range.start || playhead.value >= range.end - 0.01))
    playhead.value = range.start;
  else if (playhead.value >= length.value - 0.01) playhead.value = 0;
  playing.value = true;
  last = performance.now();
  raf = requestAnimationFrame(frame);
}
const stepFrame = (by: number) => {
  stop();
  seek(Math.round(playhead.value * 24 + by) / 24);
};
onBeforeUnmount(() => cancelAnimationFrame(raf));

/** Every shot on the film clock, in order. */
const shotTimes = computed(() =>
  project.scenes.flatMap((s, i) => s.shots.map((sh) => starts.value[i]! + sh.at)),
);
function stepShot(by: number) {
  const t = playhead.value;
  const times = shotTimes.value;
  const next =
    by > 0 ? times.find((x) => x > t + 0.01) : [...times].reverse().find((x) => x < t - 0.01);
  if (next !== undefined) seek(next);
  else if (by < 0) seek(0);
}

// --- selection -----------------------------------------------------------------------------------
const explicit = ref<{ kind: Selection["kind"]; id: string } | null>(null);
function locate(kind: Selection["kind"], id: string): Selection | null {
  if (kind === "lora")
    return project.loras?.some((l) => l.id === id)
      ? { kind, id, sceneIndex: editPlace.value.scene, shotIndex: 0 }
      : null;
  if (kind === "ref")
    return project.refs.some((r) => r.id === id)
      ? { kind, id, sceneIndex: editPlace.value.scene, shotIndex: 0 }
      : null;
  for (let si = 0; si < project.scenes.length; si++) {
    const s = project.scenes[si]!;
    if (kind === "scene" && s.id === id) return { kind, id, sceneIndex: si, shotIndex: 0 };
    if (kind === "shot") {
      const shotIndex = s.shots.findIndex((x) => x.id === id);
      if (shotIndex >= 0) return { kind, id, sceneIndex: si, shotIndex };
    }
    if (kind === "keyframe" && s.keyframes.some((k) => k.id === id))
      return { kind, id, sceneIndex: si, shotIndex: 0 };
  }
  return null;
}
/** What the inspector shows: the explicit selection, else the shot under the playhead. */
const selection = computed<Selection>(() => {
  const found = explicit.value && locate(explicit.value.kind, explicit.value.id);
  if (found) return found;
  const p = editPlace.value;
  const shot = project.scenes[p.scene]!.shots[p.shot]!;
  return { kind: "shot", id: shot.id, sceneIndex: p.scene, shotIndex: p.shot };
});
const tab = ref<"edit" | "refs" | "cast">(
  view.tab === "refs" || view.tab === "cast" ? view.tab : "edit",
);
const castFocus = ref<string | null>(null);
/** A new voice from a line: off to the Cast tab to name and describe it. */
function showVoice(id: string) {
  castFocus.value = id;
  tab.value = "cast";
}
watch(tab, (t) => (view.tab = t));
function select(kind: Selection["kind"], id: string) {
  explicit.value = { kind, id };
  tab.value = kind === "ref" ? "refs" : "edit";
}
/** The inspector edits shots, scenes and keyframes; with a reference selected it follows the playhead. */
const editSelection = computed<Selection>(() => {
  if (selection.value.kind !== "ref") return selection.value;
  const p = editPlace.value;
  const shot = project.scenes[p.scene]!.shots[p.shot]!;
  return { kind: "shot", id: shot.id, sceneIndex: p.scene, shotIndex: p.shot };
});
const sceneRefCount = computed(() => {
  const s = project.scenes[place.value.scene]!;
  return project.refs.filter((r) => refInScene(project, r, s)).length;
});

// --- the timeline's tracks -----------------------------------------------------------------------
const tracks = computed<TimelineTrack[]>(() =>
  buildTracks(project, {
    starts: starts.value,
    rendering: live.rendering,
    renderProgress: renderProgress.value,
    hide: view.hide ?? [],
    loraSteps: view.loraSteps,
    stepShapes: stepShapesWork(project),
    status: renderStatus.status,
  }),
);
const filterCount = (id: string) => filterCount_(project, id);
function toggleFilter(id: string) {
  const hide = new Set(view.hide ?? []);
  if (hide.has(id)) hide.delete(id);
  else hide.add(id);
  view.hide = [...hide];
}
const selectedItemIds = computed(() => {
  const s = selection.value;
  if (s.kind !== "ref") return [s.id];
  return tracks.value.flatMap((t) =>
    t.items.filter((i) => i.id.startsWith(`${s.id}|`)).map((i) => i.id),
  );
});

// --- LoRA lanes ---------------------------------------------------------------------------------
const loraBrowserOpen = ref(false);
function addLora(name: string) {
  loraBrowserOpen.value = false;
  const lane = newLoraLane(name);
  project.loras = [...(project.loras ?? []), lane];
  if (view.hide?.includes("loras")) toggleFilter("loras");
  select("lora", lane.id);
}
function removeLora(id: string) {
  project.loras = (project.loras ?? []).filter((l) => l.id !== id);
  explicit.value = null;
}
const laneOf = (trackId: string) => project.loras?.find((l) => `lora:${l.id}` === trackId);
/** A scene's bar dragged to `v`, or (null) back to following the lane's strength. */
function onLevel(trackId: string, sceneId: string, v: number | null) {
  const lane = laneOf(trackId);
  if (!lane) return;
  const scenes = { ...(lane.scenes ?? {}) };
  if (v === null) delete scenes[sceneId];
  else scenes[sceneId] = v;
  lane.scenes = scenes;
}
/** A scene's step shape edited on the timeline: from then on the scene has its own. */
function onShape(trackId: string, sceneId: string, points: { x: number; y: number }[]) {
  const lane = laneOf(trackId);
  if (lane)
    lane.steps = { ...(lane.steps ?? {}), [sceneId]: points.map((p) => ({ p: p.x, v: p.y })) };
}
/** A LoRA lane's Strength / Steps buttons. */
function onTrackAction(trackId: string, action: string) {
  const id = trackId.replace(/^lora:/, "");
  const others = (view.loraSteps ?? []).filter((x) => x !== id);
  view.loraSteps = action === "steps" ? [...others, id] : others;
}

// --- the timeline's events ------------------------------------------------------------------------
const onTrackReorder = (trackId: string, beforeId: string | null) =>
  edit.reorderTrack(project, trackId, beforeId);
function onTimelineSelect(itemId: string | null, trackId: string) {
  if (!itemId) return (explicit.value = null);
  if (itemId.startsWith("curve:lora:")) return select("lora", trackId.replace(/^lora:/, ""));
  if (itemId.startsWith("ghost:")) {
    const [, edge, sceneId] = itemId.split(":");
    const i = project.scenes.findIndex((s) => s.id === sceneId);
    if (i >= 0) void pickEdgeKeyframe(i, edge as "first" | "last");
    return;
  }
  if (trackId === "scenes") select("scene", itemId);
  else if (trackId === "shots") select("shot", itemId);
  else if (trackId === "keyframes") select("keyframe", itemId);
  else if (trackId.startsWith("voice:")) {
    const found = edit.findLine(project, itemId.split("@")[0]!);
    if (found) selectAndShow("shot", found.shot.id);
  } else select("ref", itemId.split("|")[0]!);
}
function onTimelineMove(itemId: string, trackId: string, change: { start?: number; end?: number }) {
  if (trackId === "scenes" && change.end !== undefined) {
    const i = project.scenes.findIndex((s) => s.id === itemId);
    if (i >= 0) setSeconds(i, change.end - starts.value[i]!);
  } else if (change.start === undefined) return;
  // A whole shot dragged and dropped reorders; its start edge alone moves the cut.
  else if (trackId === "shots" && change.end !== undefined)
    edit.dropShot(project, itemId, change.start);
  else if (trackId === "shots") edit.moveShot(project, itemId, change.start);
  else if (trackId.startsWith("voice:"))
    edit.dropLine(project, itemId.split("@")[0]!, change.start);
  else if (trackId === "keyframes") edit.moveKeyframe(project, itemId, change.start);
}
function onTimelineDblClick(trackId: string, t: number) {
  if (trackId === "shots") splitAt(t);
}
async function onTimelineDrop(trackId: string, t: number, e: DragEvent) {
  if (!hasMediaDrop(e)) return;
  e.preventDefault();
  e.stopPropagation();
  const media = await readDrop(e);
  if (trackId === "keyframes" && media[0]) addKeyframe(t, media[0]);
  else addRefs(media);
}

// --- edits (lib/h3edits), and what each selects ---------------------------------------------------
const setSeconds = (i: number, v: number) => edit.setSeconds(project, i, v);
function addScene(at: number) {
  const scene = edit.insertScene(project, at);
  seek(sceneStarts(project)[at]!);
  select("scene", scene.id);
}
const duplicateScene = (i: number) => select("scene", edit.duplicateScene(project, i).id);
function removeScene(i: number) {
  if (!edit.removeScene(project, i)) return;
  explicit.value = null;
  seek(Math.min(playhead.value, filmLength(project)));
}
function splitAt(t: number) {
  const shot = edit.splitShotAt(project, t);
  if (shot) select("shot", shot.id);
}
/** Select from the inspector's scene panel, and bring the monitor along: the playhead moves to the
 *  scene or shot if it isn't already in it. */
function selectAndShow(kind: Selection["kind"], id: string) {
  select(kind, id);
  const sel = locate(kind, id);
  if (!sel || (kind !== "scene" && kind !== "shot")) return;
  const s = project.scenes[sel.sceneIndex]!;
  const start = starts.value[sel.sceneIndex]!;
  const from = kind === "shot" ? start + s.shots[sel.shotIndex]!.at : start;
  const to =
    kind === "shot" ? start + (s.shots[sel.shotIndex + 1]?.at ?? s.seconds) : start + s.seconds;
  if (playhead.value < from || playhead.value >= to) playhead.value = from + 0.01;
}
function addShotTo(i: number) {
  const shot = edit.addShotTo(project, i);
  if (shot) select("shot", shot.id);
}
function removeShot(id: string) {
  if (edit.removeShot(project, id)) explicit.value = null;
}
const addKeyframe = (t: number, media: string) =>
  select("keyframe", edit.addKeyframe(project, t, media).id);
async function pickEdgeKeyframe(sceneIndex: number, edge: "first" | "last") {
  const m = await pickImage(`Scene ${sceneIndex + 1} · ${edge} frame`);
  if (m)
    select(
      "keyframe",
      edit.setKeyframe(
        project,
        sceneIndex,
        edge === "first" ? 0 : project.scenes[sceneIndex]!.seconds,
        m,
      ).id,
    );
}
function removeKeyframe(id: string) {
  edit.removeKeyframe(project, id);
  explicit.value = null;
}
function addRefs(media: string[]) {
  const added = edit.addRefs(project, media);
  const last = added[added.length - 1];
  if (last) select("ref", last.id);
}
function removeRef(id: string) {
  edit.removeRef(project, id);
  explicit.value = null;
}
const toggleRefScene = (refId: string, sceneId: string) =>
  edit.toggleRefScene(project, refId, sceneId);
const PROXY_NAMES = { image: "character", video: "clip", audio: "sound" } as const;
const addProxy = (kind: Ref["kind"] = "image") =>
  select("ref", edit.addProxy(project, PROXY_NAMES[kind], "", kind).id);
/** Pick media for a reference: a placeholder's first picture, or a new one swapped in. */
async function pickRefMedia(id: string) {
  const r = project.refs.find((x) => x.id === id);
  if (!r) return;
  const refs = await pickMedia({
    kinds: r.media ? [r.kind] : ["image", "video", "audio"],
    title: `@${r.name}`,
    confirmLabel: r.media ? "Replace" : "Use",
    selected: r.media ? [r.media] : [],
  });
  if (refs[0]) edit.setRefMedia(project, id, refs[0]);
}

// --- media picker --------------------------------------------------------------------------------
type Kind = MediaPickerKind;
const picker = reactive({
  open: false,
  kinds: ["image"] as Kind[],
  multiple: false,
  title: "",
  confirmLabel: "",
  selected: [] as string[],
  resolve: (() => {}) as (refs: string[]) => void,
});
/** Open the picker over ComfyUI's folders; resolves with the chosen refs ([] when cancelled). */
function pickMedia(opts: {
  kinds?: Kind[];
  multiple?: boolean;
  title: string;
  confirmLabel?: string;
  selected?: string[];
}): Promise<string[]> {
  picker.resolve([]);
  return new Promise((resolve) => {
    Object.assign(picker, {
      open: true,
      kinds: opts.kinds ?? ["image"],
      multiple: opts.multiple ?? false,
      title: opts.title,
      confirmLabel: opts.confirmLabel ?? "Use",
      selected: opts.selected ?? [],
      resolve,
    });
  });
}
function onPickerOpen(open: boolean) {
  picker.open = open;
  if (!open) picker.resolve([]);
}
function onPicked(refs: string[]) {
  const resolve = picker.resolve;
  picker.resolve = () => {};
  resolve(refs);
}
const kindsOf = (accept: string): Kind[] => accept.split(",").map((a) => a.split("/")[0] as Kind);
const pickImage = (title: string, selected?: string) =>
  pickMedia({ title, selected: selected ? [selected] : [] }).then((refs) => refs[0]);
const pickRefs = async (accept = "image/*,video/*,audio/*") =>
  addRefs(
    await pickMedia({
      kinds: kindsOf(accept),
      multiple: true,
      title: "Add references",
      confirmLabel: "Add",
    }),
  );
async function pickKeyframe(t: number) {
  const m = await pickImage("Keyframe picture");
  if (m) addKeyframe(t, m);
}
/** What a drop carries; dropped files already in the input folder are reused, not re-uploaded. */
const readDrop = (e: DragEvent) => readMediaDrop(e, UPLOADS, uploadOrReuse);
/** New media dropped onto a reference: fills a placeholder, or swaps the picture keeping the name. */
async function dropRefMedia(id: string, e: DragEvent) {
  const [media] = await readDrop(e);
  if (media) edit.setRefMedia(project, id, media);
  select("ref", id);
}
async function dropRefs(e: DragEvent) {
  if (!hasMediaDrop(e)) return;
  e.preventDefault();
  e.stopPropagation();
  addRefs(await readDrop(e));
}
function playFrom(t: number) {
  seek(t);
  if (!playing.value) togglePlay();
}

// --- right-click menus (studioMenus.ts) -----------------------------------------------------------
const menuItems = ref<ContextMenuItem[]>([]);
function openMenu(items: ContextMenuItem[], e: MouseEvent) {
  menuItems.value = items;
  void menu.value?.show(e);
}
const menus = studioMenus(project, {
  playhead: () => playhead.value,
  place: () => place.value,
  playing: () => playing.value,
  starts: () => starts.value,
  select,
  selectAndShow,
  showVoice,
  showEditTab: () => (tab.value = "edit"),
  addScene,
  duplicateScene,
  removeScene,
  splitAt,
  removeShot,
  removeKeyframe,
  removeRef,
  removeLora,
  addRefs,
  pickImage,
  pickKeyframe: (t) => void pickKeyframe(t),
  pickRefs: () => void pickRefs(),
  openLoraBrowser: () => (loraBrowserOpen.value = true),
  playFrom,
  togglePlay,
  seek,
  render,
  staleIds: () => outOfDate.value,
});
const refMenu = menus.refMenu;
function onTimelineContext(target: TimelineTarget, t: number, e: MouseEvent) {
  const items = menus.timelineMenu(target, t);
  if (items) openMenu(items, e);
  else if (target.itemId) onTimelineSelect(target.itemId, target.trackId);
}
const monitorMenu = (e: MouseEvent) => openMenu(menus.monitorMenu(), e);

// --- keys ----------------------------------------------------------------------------------------
// Keys work while the pointer is over the studio, not only when it has focus: on the canvas the
// focus usually stays with the graph, and Space there would pan it instead of playing.
const hovered = ref(false);
const keySink = ref<HTMLTextAreaElement | null>(null);
// Over the studio, the wheel is the studio's (volume, timeline) — ComfyUI hands wheel events to the
// canvas unless focus is inside an element that captures them. So hovering takes focus, unless you
// are typing somewhere else, and leaving gives it back.
function onEnter() {
  hovered.value = true;
  const active = document.activeElement as HTMLElement | null;
  const typing = active?.closest?.("input, textarea, select, [contenteditable='true']");
  if (!typing && rootEl.value && !rootEl.value.contains(active))
    keySink.value?.focus({ preventScroll: true });
}
function onLeave() {
  hovered.value = false;
  const active = document.activeElement;
  if (active === rootEl.value || active === keySink.value) (active as HTMLElement).blur();
}
function onKey(e: KeyboardEvent) {
  const root = rootEl.value;
  if (!root || !(hovered.value || root.contains(document.activeElement))) return;
  const target = e.target as HTMLElement | null;
  if (
    target !== keySink.value &&
    target?.closest?.("input, textarea, select, [contenteditable='true']")
  )
    return;
  // A focused step chart steps through the run with the arrows itself.
  if (
    target?.closest?.(".zsc") &&
    (e.key === "ArrowLeft" || e.key === "ArrowRight" || e.key === "Escape")
  )
    return;
  // Undo / redo, before the graph's own Ctrl+Z gets it.
  if (
    (e.ctrlKey || e.metaKey) &&
    !e.altKey &&
    (e.key.toLowerCase() === "z" || e.key.toLowerCase() === "y")
  ) {
    e.preventDefault();
    e.stopPropagation();
    if (e.key.toLowerCase() === "y" || e.shiftKey) history.redo();
    else history.undo();
    return;
  }
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const handled = (): void => {
    e.preventDefault();
    e.stopPropagation();
  };
  switch (e.key) {
    case " ":
    case "k":
      handled();
      return togglePlay();
    case ",":
      handled();
      return stepFrame(-1);
    case ".":
      handled();
      return stepFrame(1);
    case "ArrowRight":
      handled();
      return stepShot(1);
    case "ArrowLeft":
      handled();
      return stepShot(-1);
    case "Home":
      handled();
      return seek(loopRange.value?.start ?? 0);
    case "End":
      handled();
      return seek(loopRange.value?.end ?? length.value);
    case "Delete":
    case "Backspace": {
      const sel = explicit.value;
      if (!sel || !root.contains(document.activeElement)) return;
      handled();
      if (sel.kind === "keyframe") removeKeyframe(sel.id);
      else if (sel.kind === "shot") removeShot(sel.id);
      else if (sel.kind === "ref") removeRef(sel.id);
    }
  }
}
onMounted(() => window.addEventListener("keydown", onKey, true));
onBeforeUnmount(() => window.removeEventListener("keydown", onKey, true));

// --- compiled scene ------------------------------------------------------------------------------
const compiled = ref<Compiled | null>(null);
let timer = 0;
watch(
  [project, () => place.value.scene],
  () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(
      async () => (compiled.value = await compileScene(project, place.value.scene)),
      250,
    );
  },
  { deep: true, immediate: true },
);
onBeforeUnmount(() => window.clearTimeout(timer));
const TASKS: Record<string, string> = {
  t2va: "Text to video",
  i2va: "From a first frame",
  l2va: "Toward a last frame",
  fl2va: "Between a first and last frame",
  ref2va: "From references",
};
const TASK_SHORT: Record<string, string> = {
  t2va: "Text",
  i2va: "First frame",
  l2va: "Last frame",
  fl2va: "First + last",
  ref2va: "References",
};
/** The scene chip's details: what H3 is asked to do, the scene's length, and any warnings. */
const taskTitle = computed(() => {
  const c = compiled.value;
  if (!c) return "";
  const head = `Scene ${place.value.scene + 1} · ${TASKS[c.task] ?? c.task} (${c.task}) · ${c.seconds.toFixed(2)}s · ${c.frames} frames`;
  const shown = c.refs.length
    ? `Shown to H3:\n${c.refs.map((r) => `${r.tag}  @${r.name}${r.role === "blocking" ? " (blocking)" : ""}${r.alias ? " (same file)" : ""}`).join("\n")}`
    : "Shown to H3: no references (words only)";
  const warned = c.warnings.length ? `\n\n${c.warnings.map((w) => `⚠ ${w}`).join("\n")}` : "";
  return `${head}\n\n${shown}${warned}\n\nClick to copy the prompt H3 gets.`;
});
/** The exact prompt for this scene, on the clipboard — to see what H3 is told. */
const copied = ref(false);
async function copyPrompt() {
  if (!compiled.value) return;
  await navigator.clipboard.writeText(compiled.value.prompt);
  copied.value = true;
  window.setTimeout(() => (copied.value = false), 1500);
}

// --- layout: the inspector beside the monitor or under it ------------------------------------------
// Auto picks whichever shows the picture bigger for the canvas's shape at the editor's current
// size — a landscape film in a wide node goes stacked, a portrait one stays side by side.
type Layout = "auto" | "side" | "stacked";
const LAYOUTS: Layout[] = ["auto", "side", "stacked"];
const LAYOUT_ICON: Record<Layout, string> = {
  auto: "mdi mdi-view-dashboard-variant-outline",
  side: "mdi mdi-dock-right",
  stacked: "mdi mdi-dock-bottom",
};
const LAYOUT_TITLE: Record<Layout, string> = {
  auto: "auto (whichever shows the picture bigger)",
  side: "inspector beside the monitor",
  stacked: "inspector under the monitor",
};
const layout = computed<Layout>(() => project.layout ?? "auto");
const cycleLayout = () =>
  (project.layout = LAYOUTS[(LAYOUTS.indexOf(layout.value) + 1) % LAYOUTS.length]);
const GAP = 8;
const stageEl = ref<HTMLElement | null>(null);
const stageSize = ref({ w: 900, h: 400 });
// The inspector's size: dragged on the split between it and the monitor, kept on the node. Until
// dragged, stacked it takes about 40% of the stage, and beside the monitor 320px.
const stackH = ref<number | null>(view.stackH ?? null);
const sideW = ref<number | null>(view.sideW ?? null);
const clampStack = (h: number) =>
  Math.round(Math.min(Math.max(h, 170), Math.max(170, stageSize.value.h - 140)));
const clampSide = (w: number) =>
  Math.round(Math.min(Math.max(w, 260), Math.max(260, stageSize.value.w - 260)));
const STACK_H = computed(() => clampStack(stackH.value ?? stageSize.value.h * 0.42));
const SIDE_W = computed(() => clampSide(sideW.value ?? 320));
/** The monitor/inspector split: the inspector a px pane (its default is what a double-click on the
 *  gap goes back to), the monitor taking the rest. */
const stagePanes = computed(() =>
  stacked.value
    ? [
        { min: 140 },
        {
          size: clampStack(stageSize.value.h * 0.42),
          min: 170,
          max: Math.max(170, stageSize.value.h - 140),
        },
      ]
    : [{ min: 260 }, { size: 320, min: 260, max: Math.max(260, stageSize.value.w - 260) }],
);
const stageSizes = computed(() => {
  const px = stacked.value ? stackH.value : sideW.value;
  return px == null ? undefined : [1, px];
});
function onStageSizes(sizes?: number[]) {
  const px = sizes?.[1];
  if (px == null) return;
  if (stacked.value) stackH.value = Math.round(px);
  else sideW.value = Math.round(px);
  view.stackH = stackH.value ?? undefined;
  view.sideW = sideW.value ?? undefined;
}
/** The picture's fitted area in a box `w` × `h`. */
function pictureArea(w: number, h: number) {
  const ar = project.canvas.width / project.canvas.height;
  const fw = Math.max(0, Math.min(w, h * ar));
  return fw * (fw / ar);
}
const stacked = computed(() => {
  if (layout.value !== "auto") return layout.value === "stacked";
  const { w, h } = stageSize.value;
  if (w < 720) return true;
  return pictureArea(w, h - STACK_H.value - GAP) > pictureArea(w - SIDE_W.value - GAP, h);
});
let ro: ResizeObserver | null = null;
onMounted(() => {
  if (!stageEl.value || typeof ResizeObserver === "undefined") return;
  ro = new ResizeObserver(([entry]) => {
    const r = entry?.contentRect;
    if (r) stageSize.value = { w: r.width, h: r.height };
  });
  ro.observe(stageEl.value);
});
onBeforeUnmount(() => ro?.disconnect());
</script>

<style scoped>
.keysink {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  border: 0;
  opacity: 0;
  resize: none;
  pointer-events: none;
}
.studio {
  --h3-radius: var(--zen-radius, 8px);
  --h3-bg: var(--zen-bg, var(--comfy-menu-bg, #18181c));
  --h3-panel: var(--zen-surface, color-mix(in srgb, var(--zen-text, #fff) 4%, var(--h3-bg)));
  --h3-field: var(--zen-field-bg, var(--zen-input, color-mix(in srgb, #000 22%, var(--h3-bg))));
  --h3-line: var(--zen-border, color-mix(in srgb, var(--zen-text, #fff) 10%, transparent));
  --h3-text: var(--zen-text, var(--input-text, #e8e8ee));
  /* ZenKit's thin scrollbars everywhere in the studio, tinted from the text so they show on its
     panels (ComfyUI's thumb colour is close to a panel's). */
  --zen-scrollbar: color-mix(in srgb, var(--h3-text) 28%, transparent);
  --h3-muted: var(--zen-muted, var(--descrip-text, #9aa0aa));
  --h3-accent: var(--zen-accent, var(--p-primary-color, #4f7cff));

  display: flex;
  flex-direction: column;
  gap: 8px;
  box-sizing: border-box;
  width: 100%;
  height: 100%;
  min-height: 0;
  padding: 8px;
  color: var(--h3-text);
  font-family: var(--p-font-family, -apple-system, system-ui, sans-serif);
  font-size: 12px;
  outline: none;
  cursor: default;
}
.grow {
  flex: 1;
}
.soft {
  color: var(--h3-muted);
}
.bar,
.transport,
.status {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.due {
  margin-left: 2px;
  padding: 0 5px;
  border-radius: 999px;
  background: color-mix(in srgb, #e0a54a 30%, transparent);
  color: #f2c27a;
  font-size: 10px;
}
.brand {
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  font-weight: 700;
}
.brand .mdi {
  color: var(--h3-accent);
  font-size: 16px;
}

/* The stage takes the height the rest leaves, and is first to give it up: the timeline below
   is never cut short. */
.stage {
  flex: 1 1 0;
  min-height: 120px;
}
.bar,
.transport,
.status,
.studio > :deep(.ztl) {
  flex: none;
}
/* The splits fill what they're given; each pane's content fills its pane. */
.main {
  display: flex;
  flex: 1 1 0;
  gap: 8px;
  min-height: 0;
}
.body {
  flex: 1 1 0;
  min-width: 0;
  min-height: 0;
}
.rendersbtn {
  position: relative;
  display: flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--h3-muted);
  font-size: 16px;
  cursor: pointer;
}
.rendersbtn:hover,
.rendersbtn.on {
  border-color: var(--h3-line);
  background: var(--h3-field);
  color: var(--h3-text);
}
.recdot {
  position: absolute;
  top: 3px;
  right: 3px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--zen-danger, #ef4444);
  box-shadow: 0 0 0 2px var(--h3-bg);
  animation: recpulse 1.2s ease-in-out infinite;
}
@keyframes recpulse {
  50% {
    opacity: 0.35;
  }
}
.upper {
  display: flex;
  flex-direction: column;
  gap: 8px;
  height: 100%;
  min-height: 0;
}
.stagesplit {
  height: 100%;
}
.stagesplit :deep(.zsp-pane > *),
.body :deep(.zsp-pane > .tl) {
  box-sizing: border-box;
  height: 100%;
}
/* The strip under the monitor is its own container: the inspector's wide, short layouts
   (@container h3strip) are for it alone, never for a side panel dragged wide. */
.stage.stacked .side {
  overflow: hidden;
  container-name: h3strip;
}

.side {
  container: h3side / inline-size;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  min-height: 0;
  padding: 8px;
  border: 1px solid var(--h3-line);
  border-radius: var(--h3-radius);
  background: var(--h3-panel);
}
.tabs :deep(.zen-tg) {
  display: flex;
  width: 100%;
}
.tabs :deep(.zen-tg-b) {
  flex: 1;
}
.sidebody {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.divider {
  width: 1px;
  height: 18px;
  margin: 0 2px;
  background: var(--h3-line);
}
/* The transport, the inspector, the monitor and the timeline are each a framed card on the
   studio's background — the same as ZenCut, so a popped-out studio reads as a set of panels. */
.transport {
  padding: 4px 6px;
  border: 1px solid var(--h3-line);
  border-radius: var(--h3-radius);
  background: var(--h3-panel);
}
.tl {
  flex: none;
  box-sizing: border-box;
  overflow: hidden;
  border: 1px solid var(--h3-line);
  border-radius: var(--h3-radius);
}
.tc {
  flex: none;
  margin-left: 6px;
  white-space: nowrap;
  font-family: var(--zen-mono, ui-monospace, monospace);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.status {
  color: var(--h3-muted);
  font-size: 10.5px;
}
.filters {
  display: inline-flex;
  gap: 2px;
  margin-right: 4px;
}
.filter {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  height: 24px;
  padding: 0 7px;
  border: 1px solid var(--h3-line);
  border-radius: var(--h3-radius);
  background: none;
  color: var(--h3-text);
  font: inherit;
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  cursor: pointer;
}
.filter .mdi {
  color: var(--h3-accent);
  font-size: 13px;
}
.filter.off {
  border-style: dashed;
  color: var(--h3-muted);
  opacity: 0.6;
}
.filter.off .mdi {
  color: inherit;
}
.loopbtn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  height: 26px;
  padding: 0 6px;
  border: 0;
  border-radius: var(--h3-radius);
  background: none;
  color: var(--h3-muted);
  font: inherit;
  font-size: 10.5px;
  font-weight: 700;
  text-transform: capitalize;
  cursor: pointer;
}
.loopbtn .mdi {
  font-size: 16px;
}
.loopbtn:hover {
  background: color-mix(in srgb, var(--h3-text) 9%, transparent);
  color: var(--h3-text);
}
.loopbtn.on {
  color: var(--h3-accent);
}
.livechip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 22px;
  padding: 0 8px;
  border: 1px solid color-mix(in srgb, #ff5a5f 50%, transparent);
  border-radius: 11px;
  background: color-mix(in srgb, #ff5a5f 14%, transparent);
  color: var(--h3-text);
  font: inherit;
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  cursor: pointer;
}
.livechip .mdi {
  color: #ff5a5f;
  animation: rec 1.2s ease-in-out infinite;
}
@keyframes rec {
  50% {
    opacity: 0.35;
  }
}
.task {
  cursor: copy;
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--h3-accent) 16%, transparent);
  color: var(--h3-muted);
  font-size: 11px;
  white-space: nowrap;
}
.task b {
  color: var(--h3-text);
  font-weight: 600;
}
.task.warned {
  background: color-mix(in srgb, #f2b04a 18%, transparent);
}
.task .mdi {
  margin-left: 2px;
  color: #e09a2d;
}
</style>
