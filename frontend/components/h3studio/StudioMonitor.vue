<template>
  <div class="monitor" @contextmenu.prevent.stop="emit('context', $event)">
    <div class="screen" :style="{ '--ar': project.canvas.width / project.canvas.height }">
      <!-- Render: the scene's finished clip, driven by the studio's transport -->
      <template v-if="view === 'render'">
        <video
          v-if="clip"
          ref="clipEl"
          :key="clip"
          class="render"
          :src="clipUrl"
          :muted="props.muted || props.volume === 0"
          :volume="props.volume"
          playsinline
          preload="auto"
          @loadedmetadata="syncClip(true)"
        />
        <div v-else class="card">
          <i class="mdi mdi-movie-open-off-outline" />
          <span class="card-shot">Scene {{ place.scene + 1 }} has no render yet</span>
          <span class="card-hint">Run the workflow — H3 Studio Clip saves each scene's clip for this view.</span>
        </div>
      </template>

      <!-- Preview: the sampler's steps for this scene, placed at the playhead -->
      <template v-else-if="view === 'preview'">
        <template v-if="shown">
          <canvas v-if="shown.frames" ref="framesEl" class="render" />
          <video
            v-else-if="shown.video"
            ref="previewEl"
            :key="shown.url"
            class="render"
            :src="shown.url"
            :muted="!shown.audio || props.muted || props.volume === 0"
            :volume="props.volume"
            playsinline
            preload="auto"
            @loadedmetadata="placePreview(true)"
          />
          <img v-else class="render" :src="shown.url" alt="" draggable="false" />
        </template>
        <div v-else class="card">
          <i class="mdi" :class="rendering ? 'mdi-timer-sand' : 'mdi-image-off-outline'" />
          <span class="card-shot">
            {{ rendering ? "Waiting for the sampler…" : `No previews for scene ${place.scene + 1} yet` }}
          </span>
          <span v-if="!rendering" class="card-hint">They appear here, step by step, while the scene renders.</span>
        </div>
      </template>

      <!-- Plan: the animatic -->
      <template v-else>
        <Transition name="cut">
          <video
            v-if="picture && mediaKind(picture.media) === 'video'"
            :key="picture.media"
            class="plan-pic"
            :style="{ '--push': push }"
            :src="pictureUrl"
            muted
            loop
            autoplay
            playsinline
          />
          <img v-else-if="picture" :key="picture.media" class="plan-pic" :style="{ '--push': push }" :src="pictureUrl" alt="" draggable="false" />
        </Transition>
        <div v-if="others.length" class="cast-strip" title="Also in this shot">
          <img v-for="r in others" :key="r.id" :src="thumbUrl(r.media, 96)" :alt="`@${r.name}`" :title="`@${r.name}`" draggable="false" />
        </div>
        <div v-if="spoken" class="subtitle" :class="{ vo: spoken.line.mode === 'voiceover', sung: spoken.line.mode === 'sing' }">
          <b>{{ speakerNames(project, spoken.line) }}</b>
          <span>{{ spoken.line.mode === "sing" ? `♪ ${spoken.line.words} ♪` : spoken.line.words }}</span>
        </div>
        <div v-if="!picture" class="card">
          <span class="card-scene">Scene {{ place.scene + 1 }}</span>
          <span class="card-shot">Shot {{ place.shot + 1 }}</span>
        </div>
      </template>

      <div class="tag tl">
        <b>S{{ place.scene + 1 }}</b> · shot {{ place.shot + 1 }}
        <span v-if="view === 'plan' && picture?.kind === 'reference'" class="soft">· reference</span>
      </div>
      <div class="tag tr">{{ timecode }}</div>
      <div v-if="view === 'preview' && shown" class="tag bl" :class="{ live: rendering }">
        <i class="mdi" :class="rendering ? 'mdi-record-circle' : 'mdi-image-outline'" />
        {{ rendering ? "Rendering" : "Last run" }} · step {{ shown.step }}{{ shown.total ? `/${shown.total}` : "" }}
      </div>
      <div v-if="caption && view === 'plan'" class="caption" :title="caption">
        <template v-for="(part, i) in captionParts" :key="i">
          <b v-if="part.ref" :class="{ unknown: !part.known }">{{ part.text }}</b>
          <template v-else>{{ part.text }}</template>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// The monitor, in three modes:
//   • plan    — an animatic of the film at the playhead: the latest keyframe (or the scene's
//               reference) as the frame and the shot's description as a caption.
//   • preview — the sampler's newest step for the scene at the playhead (the step-by-step chart
//               lives in Model Preview Override).
//   • render  — the scene's finished clip, following the studio's playhead: play, scrub and step
//               shots with the transport and timeline as for the animatic.
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { mediaKind, mediaRefUrl } from "@/framework";
import { pictureAt, shotRefs, stableUrl, thumbUrl, type Place, type Project } from "@/lib/h3studio";
import { lineTimes, speakerNames } from "@/lib/h3dialogue";
import type { LiveRun } from "@/lib/h3live";

export type MonitorMode = "follow" | "plan" | "preview" | "render";

const props = withDefaults(
  defineProps<{
    project: Project;
    place: Place;
    time: number;
    mode?: MonitorMode;
    /** Preview: the latest sampling run of the scene at the playhead. */
    run?: LiveRun | null;
    /** The scene's length, to place a preview clip by the playhead. */
    sceneSeconds?: number;
    /** Preview: that scene is sampling right now. */
    rendering?: boolean;
    /** Render: the scene's finished clip, and where the playhead is in it. */
    clip?: string;
    offset?: number;
    playing?: boolean;
    /** The studio's volume (its transport owns the control). */
    volume?: number;
    muted?: boolean;
  }>(),
  { mode: "follow", run: null, sceneSeconds: 0, rendering: false, clip: undefined, offset: 0, playing: false, volume: 0.8, muted: false },
);
const emit = defineEmits<{ context: [event: MouseEvent]; sound: [hasSound: boolean] }>();

const picture = computed(() => pictureAt(props.project, props.place));
/** What the monitor shows. Follow picks for the scene at the playhead: its live steps while it
 *  renders, its finished clip once there is one, else its last preview, else the plan. */
const view = computed<Exclude<MonitorMode, "follow">>(() => {
  if (props.mode !== "follow") return props.mode;
  if (props.rendering) return "preview";
  if (props.clip) return "render";
  return props.run?.steps.length ? "preview" : "plan";
});
// URLs computed once per file: `mediaRefUrl` adds a fresh cache-buster on every call, and the
// template re-renders every frame of playback — called there, it restarts the load each frame.
const pictureUrl = computed(() => (picture.value ? stableUrl(picture.value.media) : ""));
// --- plan: a slow push through each shot, its other references, and what is being said ----------
const shotSpan = computed(() => {
  const scene = props.project.scenes[props.place.scene];
  const shot = scene?.shots[props.place.shot];
  if (!scene || !shot) return { start: 0, end: 1 };
  return { start: shot.at, end: scene.shots[props.place.shot + 1]?.at ?? scene.seconds };
});
/** How far into the shot the playhead is, as the push-in's scale: tied to the playhead, so a
 *  scrub or a pause holds it exactly. */
const push = computed(() => {
  const { start, end } = shotSpan.value;
  const p = end > start ? Math.min(Math.max((props.place.local - start) / (end - start), 0), 1) : 0;
  return (1 + 0.06 * p).toFixed(4);
});
const others = computed(() => shotRefs(props.project, props.place).filter((r) => r.kind !== "audio" && r.media && r.media !== picture.value?.media));
const spoken = computed(() => {
  const scene = props.project.scenes[props.place.scene];
  if (!scene) return null;
  return lineTimes(scene).find((x) => props.place.local >= x.start && props.place.local < x.end) ?? null;
});
const clipUrl = computed(() => (props.clip ? mediaRefUrl(props.clip) : ""));
const caption = computed(() => props.project.scenes[props.place.scene]?.shots[props.place.shot]?.text.trim() ?? "");
const names = computed(() => new Set(props.project.refs.map((r) => r.name.toLowerCase())));
const captionParts = computed(() =>
  caption.value.split(/(@[\w-]+)/).map((text) => ({
    text,
    ref: text.startsWith("@"),
    known: names.value.has(text.slice(1).toLowerCase()),
  })),
);
const timecode = computed(() => {
  const t = props.time;
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  const f = Math.floor((t % 1) * 24);
  return `${String(m).padStart(2, "0")}:${String(Math.floor(s)).padStart(2, "0")}:${String(f).padStart(2, "0")}`;
});

// --- preview -------------------------------------------------------------------------------------
// A step's preview is a clip of the whole scene, so it is placed by the studio's playhead rather
// than played on its own clock: a new step joins at the same moment, pausing freezes it with the
// timeline, and a scene loop loops it in step with everything else.
const shown = computed(() => props.run?.steps[props.run.steps.length - 1] ?? null);
/** Where the playhead is through the scene, 0–1. */
const position = computed(() => (props.sceneSeconds > 0 ? Math.min(Math.max(props.offset / props.sceneSeconds, 0), 1) : 0));

const previewEl = ref<HTMLVideoElement | null>(null);
const framesEl = ref<HTMLCanvasElement | null>(null);
function placePreview(force = false) {
  syncVideo(previewEl.value, (d) => position.value * Math.max(0, d - 0.01), force);
}
watch([position, shown, view, () => props.playing], () => void nextTick(() => placePreview()));

// A step's preview has only a few frames (Model Preview Override's preview_frames) spread over the
// whole scene, so each would hold for several of the film's frames and stutter. Instead the two
// frames either side of the playhead are blended by how far it is between them: smooth, and still
// exactly in time with the timeline. Drawn from its own animation loop, only when the moment or the
// step changes.
let framesRaf = 0;
let drawn = "";
function drawFrames() {
  framesRaf = requestAnimationFrame(drawFrames);
  const c = framesEl.value;
  const frames = shown.value?.frames;
  if (!c || !frames?.length) return;
  const key = `${position.value}|${shown.value?.step}|${frames.length}`;
  if (key === drawn) return;
  drawn = key;
  const at = Math.min(Math.max(position.value * frames.length - 0.5, 0), frames.length - 1);
  const first = frames[Math.floor(at)]!;
  const next = frames[Math.min(frames.length - 1, Math.floor(at) + 1)]!;
  const mix = at - Math.floor(at);
  if (c.width !== first.displayWidth || c.height !== first.displayHeight) {
    c.width = first.displayWidth;
    c.height = first.displayHeight;
  }
  const ctx = c.getContext("2d");
  if (!ctx) return;
  ctx.globalAlpha = 1;
  ctx.drawImage(first, 0, 0);
  if (mix > 0.01 && next !== first) {
    ctx.globalAlpha = mix;
    ctx.drawImage(next, 0, 0);
    ctx.globalAlpha = 1;
  }
}
watch(
  framesEl,
  (el) => {
    cancelAnimationFrame(framesRaf);
    drawn = "";
    if (el) framesRaf = requestAnimationFrame(drawFrames);
  },
  { immediate: true },
);
onBeforeUnmount(() => cancelAnimationFrame(framesRaf));

// --- render --------------------------------------------------------------------------------------
const clipEl = ref<HTMLVideoElement | null>(null);
/** Whether what's showing has sound — the transport's volume control dims when it hasn't. */
const hasSound = computed(() => (view.value === "render" && !!props.clip) || (view.value === "preview" && !!shown.value?.audio));
/** Keep a video on the playhead (`want` maps its duration to the time it should be at): seek while
 *  paused or scrubbing; while the transport plays, let it play — with sound — and correct only a
 *  drift that is actually visible, never while it is still seeking or loading (each seek restarts
 *  the load, and correcting a loading video stalls it for good). */
function syncVideo(v: HTMLVideoElement | null, want: (duration: number) => number, force = false) {
  if (!v || !Number.isFinite(v.duration)) return;
  const end = Math.max(0, v.duration - 0.01);
  const at = Math.min(Math.max(want(v.duration), 0), end);
  if (props.playing) {
    const settled = !v.seeking && v.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA;
    if (force || (settled && Math.abs(v.currentTime - at) > 0.4)) v.currentTime = at;
    if (v.paused && at < end) void v.play().catch(() => {});
  } else {
    if (!v.paused) v.pause();
    if (force || Math.abs(v.currentTime - at) > 1 / 48) v.currentTime = at;
  }
}
function syncClip(force = false) {
  if (view.value === "render") syncVideo(clipEl.value, () => props.offset, force);
}
watch(() => [props.offset, props.playing, props.clip, view.value] as const, () => syncClip());
watch(hasSound, (sound) => emit("sound", sound), { immediate: true });
</script>

<style scoped>
.monitor {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  container-type: size;
  box-sizing: border-box;
  border: 1px solid var(--h3-line);
  border-radius: var(--h3-radius);
  background: #050506;
  /* Near-black on a dark theme, a soft tint of the theme on a light one. */
  background: oklch(from var(--h3-bg) calc(l - 0.14) c h);
}
.screen {
  position: relative;
  flex: none;
  width: min(100cqw, 100cqh * var(--ar));
  height: min(100cqh, 100cqw / var(--ar));
  overflow: hidden;
  background: radial-gradient(circle at 50% 40%, #1b1b22, #08080a 70%);
}
.screen img,
.screen video {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.card {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  color: rgb(255 255 255 / 35%);
}
.card-scene {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.02em;
}
.card-shot {
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.tag {
  position: absolute;
  top: 8px;
  padding: 2px 7px;
  border-radius: calc(var(--h3-radius) * 0.6);
  background: rgb(0 0 0 / 55%);
  color: #fff;
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  backdrop-filter: blur(4px);
}
.tag.tl {
  left: 8px;
}
.tag.tr {
  right: 8px;
  font-family: var(--zen-mono, ui-monospace, monospace);
}
.tag.bl {
  top: 32px;
  left: 8px;
  display: flex;
  align-items: center;
  gap: 4px;
}
.tag.bl.live .mdi {
  color: #ff5a5f;
  animation: rec 1.2s ease-in-out infinite;
}
@keyframes rec {
  50% {
    opacity: 0.35;
  }
}
/* A render preview is what H3 will make, so show all of it rather than the animatic's crop. */
.screen .render {
  object-fit: contain;
  background: #000;
}
.soft {
  opacity: 0.6;
}
/* The shot's description: a slim note along the top, out of the subtitles' way. */
.caption {
  position: absolute;
  top: 34px;
  right: 12%;
  left: 12%;
  display: -webkit-box;
  overflow: hidden;
  padding: 4px 10px;
  border-radius: calc(var(--h3-radius) * 0.6);
  background: rgb(0 0 0 / 45%);
  backdrop-filter: blur(6px);
  color: rgb(255 255 255 / 88%);
  font-size: 11.5px;
  line-height: 1.4;
  text-align: center;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
/* What is being said at the playhead, as subtitles. */
.subtitle {
  position: absolute;
  right: 8%;
  bottom: 7%;
  left: 8%;
  color: #fff;
  font-size: 15px;
  line-height: 1.35;
  text-align: center;
  text-shadow:
    0 0 3px rgb(0 0 0 / 90%),
    0 1px 2px rgb(0 0 0 / 90%);
}
.subtitle b {
  display: block;
  color: rgb(255 255 255 / 70%);
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.subtitle.vo span,
.subtitle.sung span {
  font-style: italic;
}
.cast-strip {
  position: absolute;
  right: 10px;
  bottom: 10px;
  display: flex;
  gap: 4px;
}
.cast-strip img {
  width: 34px;
  height: 34px;
  border: 1.5px solid rgb(255 255 255 / 80%);
  border-radius: 6px;
  object-fit: cover;
  box-shadow: 0 2px 6px rgb(0 0 0 / 50%);
}
.plan-pic {
  transform: scale(var(--push, 1));
  transform-origin: 50% 45%;
}
@media (prefers-reduced-motion: reduce) {
  .plan-pic {
    transform: none;
  }
}
:global(body.disable-animations) .plan-pic {
  transform: none;
}
.caption b {
  color: #9db7ff;
  font-weight: 600;
}
.caption b.unknown {
  color: #ff8a8a;
  text-decoration: wavy underline #ff8a8a;
}
.cut-enter-active {
  transition: opacity 0.12s ease;
}
.cut-enter-from {
  opacity: 0;
}
.card .mdi {
  font-size: 28px;
  opacity: 0.6;
}
.card-hint {
  max-width: 80%;
  opacity: 0.6;
  font-size: 11px;
  text-align: center;
}
.mute {
  position: absolute;
  right: 8px;
  bottom: 8px;
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border: 0;
  border-radius: 50%;
  background: rgb(0 0 0 / 55%);
  color: #fff;
  cursor: pointer;
}
</style>
