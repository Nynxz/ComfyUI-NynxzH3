<template>
  <div class="gb" tabindex="0" @keydown="onKey">
    <!-- toolbar -->
    <div class="bar">
      <span v-if="!inPanel" class="brand"><i class="mdi mdi-cube-scan" /> Grey Box</span>
      <ZenSelect
        v-if="s.state.projects.length"
        size="sm"
        class="pick"
        :model-value="s.state.project"
        :options="s.state.projects.map((p) => ({ value: p.id, label: p.name }))"
        placeholder="Project"
        @update:model-value="chooseProject"
      />
      <ZenSelect
        v-if="s.state.project && s.state.scenes.length"
        size="sm"
        class="pick"
        :model-value="s.state.sceneName"
        :options="s.state.scenes.map((n) => ({ value: n, label: n }))"
        placeholder="Scene"
        @update:model-value="openScene"
      />
      <ZenIconButton
        v-if="s.state.project"
        icon="mdi mdi-plus"
        size="sm"
        title="New scene"
        @click="creating = true"
      />
      <ZenPopover v-if="s.state.project" placement="bottom-start">
        <template #trigger="{ toggle }">
          <ZenIconButton
            icon="mdi mdi-dots-horizontal"
            size="sm"
            title="Scenes, sets and the example"
            @click="
              arming = '';
              toggle();
            "
          />
        </template>
        <template #default="{ close }">
          <div class="menu">
            <ZenMenuItem
              icon="mdi mdi-silverware-fork-knife"
              @select="
                close();
                example(hasExample);
              "
              >{{ hasExample ? "Update the example" : "Add the example" }}
              <template v-if="hasExample" #hint>replaces its scenes and set</template>
            </ZenMenuItem>
            <template v-if="s.state.loaded">
              <ZenMenuSeparator />
              <ZenMenuItem
                icon="mdi mdi-delete-outline"
                danger
                @select="confirmThen(`scene:${s.state.sceneName}`, close, deleteScene)"
                >{{
                  arming === `scene:${s.state.sceneName}`
                    ? `Click again to delete ${s.state.sceneName}`
                    : `Delete scene ${s.state.sceneName}`
                }}</ZenMenuItem
              >
            </template>
            <template v-if="s.state.sets.length">
              <ZenMenuSeparator />
              <ZenMenuItem
                v-for="set in s.state.sets"
                :key="set"
                icon="mdi mdi-delete-outline"
                danger
                @select="confirmThen(`set:${set}`, close, () => deleteSet(set))"
                >{{
                  arming === `set:${set}` ? `Click again to delete ${set}` : `Delete set ${set}`
                }}</ZenMenuItem
              >
            </template>
          </div>
        </template>
      </ZenPopover>
      <template v-if="s.state.loaded">
        <span class="sep" />
        <ZenToggleGroup v-model="mode" size="sm" :options="MODES" />
        <ZenSelect
          size="sm"
          class="shotpick"
          :model-value="currentShot"
          :options="s.doc.scene.shots.map((x) => ({ value: x.name, label: `Shot ${x.name}` }))"
          @update:model-value="chooseShot"
        />
        <ZenIconButton
          :icon="followCuts ? 'mdi mdi-content-cut' : 'mdi mdi-pin-outline'"
          size="sm"
          :title="
            followCuts
              ? 'Following cuts: the shot changes as time passes (click to stay on this shot)'
              : 'Staying on this shot (click to follow cuts)'
          "
          @click="followCuts = !followCuts"
        />
        <span class="grow" />
        <ZenIconButton
          icon="mdi mdi-undo"
          size="sm"
          title="Undo (Ctrl+Z)"
          :disabled="!s.state.canUndo"
          @click="s.undo()"
        />
        <ZenIconButton
          icon="mdi mdi-redo"
          size="sm"
          title="Redo (Ctrl+Shift+Z)"
          :disabled="!s.state.canRedo"
          @click="s.redo()"
        />
        <ZenButton
          size="sm"
          icon="mdi mdi-camera-iris"
          title="The exact render of this moment of the shot"
          :disabled="busy"
          @click="still"
          >Still</ZenButton
        >
        <ZenPopover placement="bottom-end">
          <template #trigger="{ toggle }">
            <ZenButton
              size="sm"
              icon="mdi mdi-movie-open-play-outline"
              title="Render grey video (saved to output/greybox)"
              :disabled="busy"
              @click="toggle"
              >Render</ZenButton
            >
          </template>
          <template #default="{ close }">
            <div class="menu">
              <ZenMenuItem
                icon="mdi mdi-filmstrip"
                @select="
                  close();
                  renderVideo('shot');
                "
                >Shot {{ currentShot }}</ZenMenuItem
              >
              <ZenMenuItem
                icon="mdi mdi-movie-open-outline"
                :disabled="!s.doc.scene.shots.length"
                @select="
                  close();
                  renderVideo('cut');
                "
                >The whole scene
                <template #hint>one video, as it cuts</template>
              </ZenMenuItem>
              <ZenMenuItem
                icon="mdi mdi-view-sequential-outline"
                :disabled="s.doc.scene.shots.length < 2"
                @select="
                  close();
                  renderVideo('each');
                "
                >Every shot
                <template #hint>a video each, for H3</template>
              </ZenMenuItem>
            </div>
          </template>
        </ZenPopover>
        <span class="status" :class="{ bad: s.state.error }">{{
          s.state.error ? "Not saved" : s.state.saving ? "Saving…" : "Saved"
        }}</span>
      </template>
      <span v-else class="grow" />
      <ZenIconButton
        v-if="canPopOut && !inPanel"
        icon="mdi mdi-open-in-new"
        size="sm"
        title="Pop out into a panel"
        @click="emit('popOut')"
      />
    </div>

    <!-- nothing open yet -->
    <div v-if="!s.state.loaded || creating" class="start">
      <ZenEmpty :title="creating ? 'New scene' : 'Grey box'" icon="mdi mdi-cube-scan">
        <template v-if="creating">A scene is a set, the characters in it, and its shots.</template>
        <template v-else-if="!s.state.projects.length">
          Grey box scenes live in a Codex show. Make a show in the Codex first, then come back.
        </template>
        <template v-else-if="!s.state.project"
          >Pick a project — a Codex show — to block its scenes.</template
        >
        <template v-else-if="!s.state.scenes.length"
          >This show has no grey box scenes yet.</template
        >
        <template v-else>Pick a scene.</template>
        <template #actions>
          <form v-if="creating" class="newscene" @submit.prevent="create">
            <ZenInput v-model="newName" sm placeholder="scene-name" />
            <ZenSelect
              size="sm"
              :model-value="newSet"
              :options="setOptions"
              @update:model-value="newSet = $event"
            />
            <ZenInput v-if="newSet === NEW_SET" v-model="newSetName" sm placeholder="set-name" />
            <ZenButton size="sm" variant="primary" :disabled="!canCreate" @click="create"
              >Create</ZenButton
            >
            <ZenButton size="sm" @click="creating = false">Cancel</ZenButton>
          </form>
          <template v-else-if="s.state.project">
            <ZenButton size="sm" variant="primary" icon="mdi mdi-plus" @click="creating = true"
              >New scene</ZenButton
            >
            <ZenButton
              size="sm"
              icon="mdi mdi-silverware-fork-knife"
              :title="
                hasExample
                  ? 'Replace the example\'s scenes and set with the current ones (your other scenes stay)'
                  : 'Copy the worked example (Midnight Spoon, its cast and two scenes) into this project'
              "
              @click="example(hasExample)"
              >{{ hasExample ? "Update the example" : "Add the example" }}</ZenButton
            >
          </template>
        </template>
      </ZenEmpty>
    </div>

    <ZenSplit
      v-else
      class="body"
      direction="vertical"
      gutter="gap"
      :panes="[{ min: 200 }, { size: 200, min: 90, max: 420 }]"
    >
      <template #pane-0>
        <ZenSplit
          class="upper"
          gutter="gap"
          :panes="[
            { size: 200, min: 150, max: 340, collapsible: true },
            { min: 260 },
            { size: 290, min: 240, max: 480, collapsible: true },
          ]"
        >
          <template #pane-0>
            <div class="panel">
              <GbOutliner
                :session="s"
                :sel="selection"
                :shot="currentShot"
                :time="time"
                @select="selection = $event"
                @seek="seek"
                @save-camera="saveCamera"
              />
            </div>
          </template>
          <template #pane-1>
            <div class="stage">
              <GbViewport
                v-model:selection="selection"
                :session="s"
                :time="time"
                :mode="mode"
                :shot="currentShot"
                :aspect="aspect"
              />
              <div v-if="overlay" class="overlay">
                <header>
                  <span>{{ overlay.title }}</span>
                  <ZenIconButton
                    icon="mdi mdi-close"
                    size="sm"
                    title="Close"
                    @click="overlay = null"
                  />
                </header>
                <img v-if="overlay.kind === 'image'" :src="overlay.src" alt="" />
                <div v-else-if="overlay.clips" class="clips">
                  <figure v-for="c in overlay.clips" :key="c.src">
                    <video :src="c.src" controls autoplay loop muted playsinline />
                    <figcaption>{{ c.title }}</figcaption>
                  </figure>
                </div>
                <video v-else :src="overlay.src" controls autoplay loop muted playsinline />
                <small v-if="overlay.note" class="soft">{{ overlay.note }}</small>
              </div>
              <div v-if="s.state.message" class="msg">{{ s.state.message }}</div>
            </div>
          </template>
          <template #pane-2>
            <div class="panel">
              <GbInspector
                :session="s"
                :sel="selection"
                :time="time"
                @select="selection = $event"
                @seek="seek"
              />
            </div>
          </template>
        </ZenSplit>
      </template>
      <template #pane-1>
        <div class="panel tl">
          <div class="transport">
            <ZenIconButton
              :icon="playing ? 'mdi mdi-pause' : 'mdi mdi-play'"
              size="sm"
              :title="playing ? 'Pause (Space)' : 'Play (Space)'"
              @click="toggle"
            />
            <span class="tc">{{ time.toFixed(2) }}s / {{ length.toFixed(2) }}s</span>
            <span class="soft">{{ shotNow ? `in shot ${shotNow.name}` : "" }}</span>
          </div>
          <ZenTimeline
            class="timeline"
            :duration="length"
            :tracks="tracks"
            :selected="selectedItem"
            :snap="0.05"
            :guides="guides"
            v-model:playhead="time"
            @move="onMove"
            @select="onTimelineSelect"
          />
        </div>
      </template>
    </ZenSplit>
  </div>
</template>

<script lang="ts">
import type { Selection as ViewSelection } from "./GbViewport.vue";

/** Where a shared session's editor was looking, for the editor that takes it over. */
const views = new Map<
  string,
  { mode: "free" | "shot" | "plan"; selection: ViewSelection | null; time: number; followCuts: boolean }
>();
</script>

<script setup lang="ts">
// Grey Box Studio: block a scene in 3D — the set, the characters moving between marks, a camera
// per shot — and render shots as grey video for H3 to follow. The scene's files are the truth
// (lib/greyboxDoc.ts); every change is an action (lib/greyboxActions.ts), the same ones agents use.
import { computed, onBeforeUnmount, ref, watch } from "vue";
import {
  ZenButton,
  ZenEmpty,
  ZenIconButton,
  ZenInput,
  ZenMenuItem,
  ZenMenuSeparator,
  ZenPopover,
  ZenSelect,
  ZenSplit,
  ZenTimeline,
  ZenToggleGroup,
  type TimelineTrack,
} from "@nynxz/zenkit-ui";
import { mediaRefUrl } from "@/framework";
import { Evaluator } from "@/lib/greybox";
import {
  holdGreyBox,
  liveSessions,
  releaseGreyBox,
  renderShot,
  renderStill,
  useGreyBox,
} from "@/lib/greyboxDoc";
import GbInspector from "./GbInspector.vue";
import GbOutliner from "./GbOutliner.vue";
import GbViewport, { type Selection } from "./GbViewport.vue";

export interface StudioValue {
  project: string;
  scene: string;
  shot: string;
}
const props = defineProps<{
  value: StudioValue;
  inPanel?: boolean;
  canPopOut?: boolean;
  width?: number;
  height?: number;
  /** Editors with the same key share one session: a node's editor and its popped-out panel. */
  sessionKey?: string;
}>();
const emit = defineEmits<{ change: [StudioValue]; popOut: [] }>();

const MODES = [
  { value: "free", label: "Free", icon: "mdi mdi-rotate-orbit", title: "Orbit around the set" },
  {
    value: "shot",
    label: "Shot",
    icon: "mdi mdi-camera-outline",
    title: "Through the shot's camera",
  },
  { value: "plan", label: "Plan", icon: "mdi mdi-floor-plan", title: "From above" },
];
const NEW_SET = "__new__";

const s = props.sessionKey ? holdGreyBox(props.sessionKey) : useGreyBox();
if (!props.sessionKey) liveSessions.add(s);
const kept = props.sessionKey ? views.get(props.sessionKey) : undefined;
const mode = ref<"free" | "shot" | "plan">(kept?.mode ?? "free");
const selection = ref<Selection | null>(kept?.selection ?? null);
const time = ref(kept?.time ?? 0);
const chosenShot = ref(props.value.shot ?? "");
const followCuts = ref(kept?.followCuts ?? true);
const creating = ref(false);
const busy = ref(false);
const overlay = ref<{
  kind: "image" | "video";
  src: string;
  title: string;
  note?: string;
  /** Several videos side by side: every shot rendered at once. */
  clips?: { title: string; src: string }[];
} | null>(
  null,
);
const aspect = computed(() => (props.width ?? 832) / (props.height ?? 480));

const evaluator = computed(() => new Evaluator(s.doc.scene, s.doc.set, s.doc.cast));
const length = computed(() => evaluator.value.length);
const shotNow = computed(() => evaluator.value.shotAt(time.value));
const currentShot = computed(() => {
  if (followCuts.value && shotNow.value) return shotNow.value.name;
  return s.doc.scene.shots.some((x) => x.name === chosenShot.value)
    ? chosenShot.value
    : (s.doc.scene.shots[0]?.name ?? "");
});
watch(currentShot, (name) => {
  if (name && name !== props.value.shot) emit("change", { ...props.value, shot: name });
});

// --- opening ------------------------------------------------------------------------------------------
void (async () => {
  await s.listProjects();
  const p = props.value.project && s.state.projects.find((x) => x.id === props.value.project);
  if (
    s.state.loaded &&
    s.state.project === props.value.project &&
    s.state.sceneName === props.value.scene
  )
    return;
  if (p) {
    s.state.project = p.id;
    s.state.scenes = p.scenes;
    s.state.sets = p.sets;
    if (props.value.scene && p.scenes.includes(props.value.scene))
      await openScene(props.value.scene);
  } else if (s.state.projects.length === 1) chooseProject(s.state.projects[0]!.id);
})();
onBeforeUnmount(() => {
  if (props.sessionKey) {
    views.set(props.sessionKey, {
      mode: mode.value,
      selection: selection.value,
      time: time.value,
      followCuts: followCuts.value,
    });
    releaseGreyBox(props.sessionKey);
  } else {
    liveSessions.delete(s);
    s.stop();
  }
  cancelAnimationFrame(raf);
});

function chooseProject(id: string) {
  const p = s.state.projects.find((x) => x.id === id);
  if (!p) return;
  s.state.project = id;
  s.state.scenes = p.scenes;
  s.state.sets = p.sets;
  s.state.loaded = false;
  emit("change", { project: id, scene: "", shot: "" });
  if (p.scenes.length === 1) void openScene(p.scenes[0]!);
}
async function openScene(name: string) {
  try {
    await s.open(s.state.project, name);
    s.state.message = "";
    selection.value = null;
    time.value = 0;
    creating.value = false;
    emit("change", {
      project: s.state.project,
      scene: name,
      shot: s.doc.scene.shots[0]?.name ?? "",
    });
  } catch (e) {
    s.state.message = e instanceof Error ? e.message : String(e);
  }
}
const EXAMPLE_SCENE = "mika-arrives";
const hasExample = computed(() => s.state.scenes.includes(EXAMPLE_SCENE));
async function example(replace = false) {
  try {
    await s.addExample(replace);
    await s.listProjects();
    const scene = replace && s.state.loaded ? s.state.sceneName : EXAMPLE_SCENE;
    if (s.state.scenes.includes(scene)) await openScene(scene);
    if (replace) s.state.message = "The example is up to date.";
  } catch (e) {
    s.state.message = e instanceof Error ? e.message : String(e);
  }
}

/** Deleting asks twice: the first click arms the item, the second does it. */
const arming = ref("");
async function confirmThen(key: string, close: () => void, run: () => Promise<void>) {
  if (arming.value !== key) {
    arming.value = key;
    return;
  }
  arming.value = "";
  close();
  try {
    await run();
  } catch (e) {
    s.state.message = e instanceof Error ? e.message : String(e);
  }
}
async function deleteScene() {
  const name = s.state.sceneName;
  await s.remove("scene", name);
  selection.value = null;
  emit("change", { project: s.state.project, scene: "", shot: "" });
  s.state.message = `Deleted the scene ${name}.`;
}
async function deleteSet(name: string) {
  await s.remove("set", name);
  s.state.message = `Deleted the set ${name}.`;
}

const newName = ref("");
const newSet = ref("");
const newSetName = ref("");
const setOptions = computed(() => [
  ...s.state.sets.map((x) => ({ value: x, label: `Set: ${x}` })),
  { value: NEW_SET, label: "A new set…" },
]);
watch(creating, (on) => {
  if (on) newSet.value = s.state.sets[0] ?? NEW_SET;
});
const slug = (v: string) =>
  v
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
const canCreate = computed(
  () => !!slug(newName.value) && (newSet.value !== NEW_SET || !!slug(newSetName.value)),
);
async function create() {
  if (!canCreate.value) return;
  const set = newSet.value === NEW_SET ? slug(newSetName.value) : newSet.value;
  await s.newScene(slug(newName.value), set);
  creating.value = false;
  newName.value = "";
  newSetName.value = "";
  emit("change", {
    project: s.state.project,
    scene: s.state.sceneName,
    shot: s.doc.scene.shots[0]?.name ?? "",
  });
}

// --- time and playing --------------------------------------------------------------------------------
const playing = ref(false);
let raf = 0;
let last = 0;
function tick(now: number) {
  if (!playing.value) return;
  const dt = Math.min(0.1, (now - last) / 1000);
  last = now;
  let next = time.value + dt;
  if (!followCuts.value) {
    const shot = s.doc.scene.shots.find((x) => x.name === currentShot.value);
    if (shot && (next >= shot.end || next < shot.start)) next = shot.start;
  } else if (next >= length.value) next = 0;
  time.value = next;
  raf = requestAnimationFrame(tick);
}
function toggle() {
  playing.value = !playing.value;
  if (playing.value) {
    last = performance.now();
    raf = requestAnimationFrame(tick);
  }
}
function seek(t: number) {
  time.value = Math.max(0, t);
}
function chooseShot(name: string) {
  chosenShot.value = name;
  const shot = s.doc.scene.shots.find((x) => x.name === name);
  if (shot && (time.value < shot.start || time.value >= shot.end)) time.value = shot.start;
  if (followCuts.value) followCuts.value = false;
}

// --- the timeline: shots, everyone's keys, the cameras' keys --------------------------------------------
const tracks = computed<TimelineTrack[]>(() => [
  {
    id: "shots",
    label: "Shots",
    icon: "mdi mdi-filmstrip",
    items: s.doc.scene.shots.map((x) => ({
      id: `shot|${x.name}`,
      start: x.start,
      end: x.end,
      label: x.name,
      resize: "both" as const,
      movable: true,
      commit: "drop" as const,
      color: x.name === currentShot.value ? "#6d8cff" : undefined,
    })),
  },
  ...s.doc.scene.actors.map((a) => ({
    id: `actor|${a.id}`,
    label: a.id,
    icon: "mdi mdi-account-outline",
    items: a.keys.map((k) => ({
      id: `key|${a.id}|${k.t}`,
      start: k.t,
      kind: "marker" as const,
      label: k.pose === "sit" ? "sit" : "",
      commit: "drop" as const,
    })),
  })),
  {
    id: "camera",
    label: "Camera",
    icon: "mdi mdi-camera-outline",
    items: s.doc.scene.shots.flatMap((x) =>
      x.camera.map((k) => ({
        id: `cam|${x.name}|${k.t}`,
        start: k.t,
        kind: "marker" as const,
        label: x.name,
        commit: "drop" as const,
      })),
    ),
  },
]);
const guides = computed(() => s.doc.scene.shots.map((x) => x.start));
const selectedItem = computed(() => {
  const sel = selection.value;
  if (!sel) return null;
  if (sel.type === "shot") return `shot|${sel.id}`;
  if (sel.type === "key") return `key|${sel.id}|${sel.t}`;
  if (sel.type === "camkey") return `cam|${sel.id}|${sel.t}`;
  return null;
});
function parse(itemId: string) {
  const [kind, id, t] = itemId.split("|");
  return { kind, id: id ?? "", t: Number(t) };
}
function onTimelineSelect(itemId: string | null) {
  if (!itemId) return;
  const p = parse(itemId);
  if (p.kind === "shot") selection.value = { type: "shot", id: p.id };
  if (p.kind === "key") selection.value = { type: "key", id: p.id, t: p.t };
  if (p.kind === "cam") selection.value = { type: "camkey", id: p.id, t: p.t };
}
function onMove(itemId: string, _track: string, change: { start?: number; end?: number }) {
  const p = parse(itemId);
  if (p.kind === "shot") {
    const shot = s.doc.scene.shots.find((x) => x.name === p.id);
    if (!shot) return;
    const args: Record<string, unknown> = { name: p.id };
    if (change.start !== undefined) args.start = change.start;
    if (change.end !== undefined) args.end = change.end;
    else if (change.start !== undefined) args.end = change.start + (shot.end - shot.start);
    s.run("shot.update", args);
  } else if (p.kind === "key" && change.start !== undefined) {
    if (s.run("key.move", { actor: p.id, t: p.t, to: change.start }))
      selection.value = { type: "key", id: p.id, t: Math.round(change.start * 1000) / 1000 };
  } else if (p.kind === "cam" && change.start !== undefined) {
    if (s.run("camkey.move", { shot: p.id, t: p.t, to: change.start }))
      selection.value = { type: "camkey", id: p.id, t: Math.round(change.start * 1000) / 1000 };
  }
}

// --- renders ------------------------------------------------------------------------------------------
async function still() {
  busy.value = true;
  try {
    const src = await renderStill(
      s,
      currentShot.value,
      time.value,
      960,
      Math.round(960 / aspect.value),
    );
    overlay.value = {
      kind: "image",
      src,
      title: `Shot ${currentShot.value} at ${time.value.toFixed(2)}s — the exact render`,
    };
  } catch (e) {
    s.state.message = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}
/** Render grey video: the current shot, the whole scene as it cuts, or every shot on its own. */
async function renderVideo(what: "shot" | "cut" | "each") {
  busy.value = true;
  const w = props.width ?? 832;
  const h = props.height ?? 480;
  try {
    await s.flush();
    if (what === "each") {
      const shots = [...s.doc.scene.shots].sort((a, b) => a.start - b.start);
      const clips: { title: string; src: string }[] = [];
      for (const [i, shot] of shots.entries()) {
        s.state.message = `Rendering shot ${shot.name} (${i + 1} of ${shots.length})…`;
        const ref = await renderShot(s, shot.name, w, h);
        clips.push({ title: `${shot.name} · ${ref}`, src: mediaRefUrl(ref) });
      }
      overlay.value = {
        kind: "video",
        src: "",
        title: `Every shot (${shots.length})`,
        note: "Saved to output/greybox",
        clips,
      };
      s.state.message = `Rendered ${shots.length} shots.`;
      return;
    }
    const shot = what === "cut" ? "*" : currentShot.value;
    s.state.message = what === "cut" ? "Rendering the whole scene…" : `Rendering shot ${shot}…`;
    const ref = await renderShot(s, shot, w, h);
    overlay.value = {
      kind: "video",
      src: mediaRefUrl(ref),
      title: what === "cut" ? "The whole scene" : `Shot ${shot}`,
      note: `Saved as ${ref}`,
    };
    s.state.message = `Rendered ${ref}`;
  } catch (e) {
    s.state.message = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}

/** The current shot's camera now, kept as a named set camera. */
function saveCamera() {
  const shot = s.doc.scene.shots.find((x) => x.name === currentShot.value);
  if (!shot) return;
  const c = evaluator.value.camera(shot, time.value);
  const taken = new Set(Object.keys(s.doc.set.cameras));
  let name = `cam-${shot.name.toLowerCase()}`;
  for (let n = 2; taken.has(name); n++) name = `cam-${shot.name.toLowerCase()}-${n}`;
  if (s.run("setcam.set", { name, at: c.at, look: c.look, lens: Math.round(c.lens) }))
    selection.value = { type: "setcam", id: name };
}

function onKey(e: KeyboardEvent) {
  const t = e.target as HTMLElement | null;
  if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
  const mod = e.ctrlKey || e.metaKey;
  if (mod && e.key.toLowerCase() === "z") {
    e.preventDefault();
    e.stopPropagation();
    if (e.shiftKey) s.redo();
    else s.undo();
  } else if (e.key === " ") {
    e.preventDefault();
    e.stopPropagation();
    toggle();
  } else if (e.key === "Escape") selection.value = null;
}
</script>

<style scoped>
.gb {
  --h3-radius: var(--zen-radius, 8px);
  --h3-bg: var(--zen-bg, var(--comfy-menu-bg, #18181c));
  --h3-panel: var(--zen-surface, #202026);
  --h3-field: var(--zen-field-bg, var(--zen-input, #15151a));
  --h3-line: var(--zen-border, #34343c);
  --h3-text: var(--zen-text, #e5e5ea);
  --h3-muted: var(--zen-muted, #9aa0aa);
  display: flex;
  flex-direction: column;
  gap: 8px;
  box-sizing: border-box;
  height: 100%;
  min-height: 0;
  padding: 8px;
  border-radius: var(--h3-radius);
  background: var(--h3-bg);
  color: var(--h3-text);
  font-size: 12px;
  outline: none;
}
.menu {
  display: flex;
  flex-direction: column;
  min-width: 220px;
  padding: 4px;
}
.bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.brand {
  display: flex;
  align-items: center;
  gap: 5px;
  font-weight: 700;
  white-space: nowrap;
}
.pick {
  min-width: 130px;
  max-width: 200px;
}
.shotpick {
  min-width: 100px;
}
.sep {
  width: 1px;
  height: 18px;
  background: var(--h3-line);
}
.grow {
  flex: 1;
}
.status {
  color: var(--h3-muted);
  font-size: 11px;
}
.status.bad {
  color: var(--zen-danger, #f87171);
}
.start {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
}
.newscene {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.body,
.upper {
  flex: 1;
  height: 100%;
  min-height: 0;
}
.panel {
  box-sizing: border-box;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--h3-line);
  border-radius: var(--h3-radius);
  background: var(--h3-panel);
}
.stage {
  position: relative;
  height: 100%;
  min-height: 0;
}
.overlay {
  position: absolute;
  right: 10px;
  bottom: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: min(46%, 520px);
  padding: 8px;
  border: 1px solid var(--h3-line);
  border-radius: var(--h3-radius);
  background: var(--h3-panel);
  box-shadow: 0 8px 28px rgb(0 0 0 / 45%);
}
.overlay header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  font-weight: 600;
}
.clips {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 6px;
  max-height: 60vh;
  overflow-y: auto;
}
.clips figure {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0;
}
.clips figcaption {
  overflow: hidden;
  color: var(--h3-muted);
  font-size: 10.5px;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.overlay img,
.overlay video {
  width: 100%;
  border-radius: 5px;
  background: #000;
}
.msg {
  position: absolute;
  bottom: 10px;
  left: 10px;
  max-width: 50%;
  padding: 4px 9px;
  border-radius: 6px;
  background: rgb(0 0 0 / 60%);
  color: #e5e5ea;
  font-size: 11.5px;
  pointer-events: none;
}
.soft {
  color: var(--h3-muted);
}
.tl {
  display: flex;
  flex-direction: column;
}
.transport {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border-bottom: 1px solid var(--h3-line);
}
.tc {
  font-family: ui-monospace, monospace;
  white-space: nowrap;
}
.timeline {
  flex: 1;
  min-height: 0;
}
</style>
