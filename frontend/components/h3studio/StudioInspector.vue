<template>
  <div class="inspector" :class="sel.kind">
    <!-- scene + its shots: one panel for both, so a scene is worked through without the timeline -->
    <template v-if="(sel.kind === 'shot' || sel.kind === 'scene') && scene">
      <header class="ih scenehead">
        <ZenIconButton
          icon="mdi mdi-chevron-left"
          title="Previous scene"
          :disabled="sel.sceneIndex === 0"
          @click="goScene(-1)"
        />
        <ZenSelect
          class="scenepick"
          :model-value="scene.id"
          :options="
            project.scenes.map((s, i) => ({
              value: s.id,
              label: `Scene ${i + 1}${s.title ? ` · ${s.title}` : ''}`,
            }))
          "
          @update:model-value="(id: string) => emit('select', { kind: 'scene', id })"
        />
        <ZenIconButton
          icon="mdi mdi-chevron-right"
          title="Next scene"
          :disabled="sel.sceneIndex === project.scenes.length - 1"
          @click="goScene(1)"
        />
        <span class="meta len" :title="`${framesFor(scene.seconds)} frames at 24 fps`"
          >{{ scene.seconds.toFixed(1) }}s</span
        >
        <span class="grow" />
        <ZenPopover v-if="sceneRefs.length" placement="bottom-end">
          <template #trigger="{ toggle }">
            <button
              type="button"
              class="refsbtn"
              :title="
                openShot
                  ? 'Insert a reference into the open shot'
                  : 'Open a shot to insert references'
              "
              :disabled="!openShot"
              @click="toggle"
            >
              <i class="mdi mdi-at" />{{ sceneRefs.length }}
            </button>
          </template>
          <template #default="{ close }">
            <div class="refgrid">
              <button
                v-for="r in sceneRefs"
                :key="r.id"
                type="button"
                class="refcard"
                :title="`Insert @${r.name}${r.note ? ` — ${r.note}` : ''}`"
                @click="
                  mention(r.name);
                  close();
                "
              >
                <span class="refthumb"><MediaThumb :media="r.media" :badge="false" /></span>
                <b>@{{ r.name }}</b>
                <small>{{ tagOf(r.id) || (r.kind === "image" ? "picture" : r.kind) }}</small>
              </button>
            </div>
          </template>
        </ZenPopover>
      </header>

      <div class="scenebody">
        <input
          v-model="scene.title"
          class="scenetitle"
          spellcheck="true"
          placeholder="Name this scene…"
          :aria-label="`Scene ${sel.sceneIndex + 1} title`"
        />
        <!-- Shots or Settings, one click apart; Settings is this scene's or the whole film's -->
        <ZenToggleGroup
          v-model="view"
          class="viewpick"
          :options="[
            { value: 'shots', label: `Shots · ${scene.shots.length}`, icon: 'mdi mdi-filmstrip' },
            { value: 'settings', label: 'Settings', icon: 'mdi mdi-tune-variant' },
          ]"
        />
        <ZenToggleGroup
          v-model="level"
          class="levelpick"
          :class="{ away: view !== 'settings' }"
          :options="[
            {
              value: 'scene',
              label: 'This scene',
              title: 'This scene\'s own settings; what it leaves empty comes from the film',
            },
            {
              value: 'film',
              label: 'Whole film',
              title: 'What every scene says unless it says its own',
            },
          ]"
        />

        <!-- film settings: what every scene says unless it says its own -->
        <section
          v-if="level === 'film'"
          class="settings pane setpane"
          :class="{ away: view !== 'settings' }"
        >
          <div class="accbody">
            <label class="col">
              <span class="lbl">style</span>
              <textarea
                class="fits"
                v-model="film.style"
                rows="2"
                placeholder="the look, e.g. 2D cel animation, painted backgrounds, warm amber light"
              />
            </label>
            <label class="col">
              <span class="lbl">direction</span>
              <textarea
                class="fits"
                v-model="film.direction"
                rows="2"
                placeholder="how it's made, e.g. animated on twos, held poses, smear frames on fast moves"
              />
            </label>
            <label class="col">
              <span class="lbl">ambience</span>
              <textarea
                class="fits"
                v-model="film.soundscape"
                rows="2"
                placeholder="e.g. rain on glass, distant traffic"
              />
            </label>
            <label class="col">
              <span class="lbl">music</span>
              <textarea
                class="fits"
                v-model="film.music"
                rows="2"
                placeholder="leave empty for none"
              />
            </label>
            <label
              class="row"
              title="Frames a continued scene fades in over, where it joins the one before"
            >
              <span class="lbl">crossfade</span>
              <ZenNumber
                :model-value="project.film?.crossfade ?? 8"
                :min="0"
                :max="39"
                :step="1"
                :precision="0"
                @update:model-value="(v: number) => setFilm({ crossfade: v })"
              />
              <span class="soft">frames</span>
            </label>
            <label
              class="row"
              title="When a render of every scene finishes, join them into the film and save it (Renders shows it). Export film saves it any time."
            >
              <span class="lbl">save the film after a full render</span>
              <ZenSwitch
                :model-value="project.film?.auto ?? true"
                @update:model-value="(v: boolean) => setFilm({ auto: v })"
              />
            </label>
          </div>
        </section>

        <!-- scene settings -->
        <section v-else class="settings pane setpane" :class="{ away: view !== 'settings' }">
          <div class="accbody">
            <label
              class="row"
              title="H3 renders in steps of 17 frames, so the length rounds up a little"
            >
              <span class="lbl">length</span>
              <ZenNumber
                :model-value="scene.seconds"
                :min="1"
                :max="30"
                :step="0.5"
                :precision="2"
                @update:model-value="(v: number) => emit('seconds', sel.sceneIndex, v)"
              />
              <span class="soft">s</span>
            </label>
            <div class="row">
              <span
                class="lbl"
                title="This scene's noise seed. H3 Studio Outputs' noise is drawn from it."
                >seed</span
              >
              <ZenNumber
                class="seed"
                :model-value="scene.seed"
                :min="0"
                :max="4294967295"
                :step="1"
                :precision="0"
                @update:model-value="(v: number) => (scene!.seed = Math.round(v))"
              />
              <ZenIconButton
                icon="mdi mdi-dice-5-outline"
                title="Re-roll: a new seed for this scene — only it (and scenes continuing from it) render again"
                @click="scene!.seed = randomSeed()"
              />
            </div>
            <div v-if="sel.sceneIndex > 0" class="row">
              <span class="lbl">from previous</span>
              <ZenSelect
                class="carry"
                :model-value="scene.continuation.mode"
                :options="CONTINUATIONS.map((c) => ({ value: c.value, label: c.label }))"
                @update:model-value="(v: string) => setContinuation(v)"
              />
              <ZenSelect
                v-if="scene.continuation.mode === 'guide' || scene.continuation.mode === 'sound'"
                :model-value="String(scene.continuation.frames)"
                :options="CONTEXT_FRAMES.map((f) => ({ value: String(f), label: `${f} frames` }))"
                class="ctx"
                @update:model-value="(v: string) => (scene.continuation.frames = Number(v))"
              />
              <span class="soft carryhint">
                <i class="mdi" :class="continuationOf(scene.continuation.mode).icon" />
                {{ continuationOf(scene.continuation.mode).title }}.
              </span>
            </div>
            <div
              v-if="sel.sceneIndex > 0"
              class="row"
              title="Experimental. Snippets of the previous scene, spread across it, shown to H3 for the whole scene so its ambience, engines and music carry on past the first second. Audio shows them as sound alone (sharing H3's 3 audio slots with voices); black video can cost picture detail; with picture, its look can pull this scene towards the previous one."
            >
              <span class="lbl">carry sound</span>
              <ZenToggleGroup
                :model-value="String(scene.continuation.soundRefs ?? 0)"
                :options="[
                  { value: '0', label: 'Off' },
                  { value: '1', label: '1' },
                  { value: '2', label: '2' },
                  { value: '3', label: '3' },
                ]"
                @update:model-value="(v: string) => (scene!.continuation.soundRefs = Number(v))"
              />
              <ZenToggleGroup
                v-if="(scene.continuation.soundRefs ?? 0) > 0"
                :model-value="scene.continuation.soundPicture ?? 'guides'"
                :options="[
                  {
                    value: 'guides',
                    label: 'Guides',
                    title:
                      'Pinned through the scene as audio guides: H3 reproduces each where it sits, so the sound can\'t drop away; the picture is untouched',
                  },
                  {
                    value: 'audio',
                    label: 'Audio',
                    title:
                      'As audio references: nothing to see, but they share H3\'s 3 audio slots with voices',
                  },
                  {
                    value: 'black',
                    label: 'Black video',
                    title: 'As black video with their sound: can cost the picture detail',
                  },
                  {
                    value: 'real',
                    label: 'With picture',
                    title:
                      'As the clip itself: its look can pull this scene towards the previous one',
                  },
                ]"
                @update:model-value="
                  (v: string) =>
                    (scene!.continuation.soundPicture = v as 'guides' | 'audio' | 'black' | 'real')
                "
              />
              <span class="soft">experimental</span>
            </div>
            <div class="kfs">
              <span class="lbl">keyframes</span>
              <button
                v-for="edge in ['first', 'last'] as const"
                :key="edge"
                type="button"
                class="kf"
                :class="{ set: !!edgeKeyframe(edge) }"
                :title="
                  edgeKeyframe(edge)
                    ? `The ${edge} frame — click to select`
                    : `Set the ${edge} frame`
                "
                @click="
                  edgeKeyframe(edge)
                    ? emit('select', { kind: 'keyframe', id: edgeKeyframe(edge)!.id })
                    : emit('setKeyframe', sel.sceneIndex, edge)
                "
              >
                <MediaThumb
                  v-if="edgeKeyframe(edge)"
                  :media="edgeKeyframe(edge)!.media"
                  :badge="false"
                />
                <i
                  v-else
                  class="mdi"
                  :class="edge === 'first' ? 'mdi-page-first' : 'mdi-page-last'"
                />
                <span class="kfl">{{ edge }}</span>
              </button>
              <span v-if="keyframeHint" class="hintline">{{ keyframeHint }}</span>
            </div>
            <label class="col">
              <span class="lbl own"
                >direction
                <span v-if="scene.direction" class="ownmark">this scene's</span>
                <span v-else class="soft">the film's</span>
                <button
                  v-if="scene.direction"
                  type="button"
                  class="reset"
                  title="Use the film's again"
                  @click.prevent="scene.direction = ''"
                >
                  <i class="mdi mdi-close" />
                </button>
              </span>
              <textarea
                class="fits"
                v-model="scene.direction"
                rows="2"
                :placeholder="project.direction || 'the film\'s direction (Film, above)'"
              />
            </label>
            <label class="col">
              <span class="lbl own"
                >ambience
                <span v-if="scene.soundscape" class="ownmark">this scene's</span>
                <span v-else class="soft">the film's</span>
                <button
                  v-if="scene.soundscape"
                  type="button"
                  class="reset"
                  title="Use the film's again"
                  @click.prevent="scene.soundscape = ''"
                >
                  <i class="mdi mdi-close" />
                </button>
              </span>
              <textarea
                class="fits"
                v-model="scene.soundscape"
                rows="2"
                :placeholder="project.soundscape || 'e.g. rain on glass, distant traffic'"
              />
            </label>
            <label class="col">
              <span class="lbl own"
                >music
                <span v-if="scene.music" class="ownmark">this scene's</span>
                <span v-else class="soft">the film's</span>
                <button
                  v-if="scene.music"
                  type="button"
                  class="reset"
                  title="Use the film's again"
                  @click.prevent="scene.music = ''"
                >
                  <i class="mdi mdi-close" />
                </button>
              </span>
              <textarea
                class="fits"
                v-model="scene.music"
                rows="2"
                :placeholder="project.music || 'leave empty for none'"
              />
            </label>
          </div>
        </section>

        <!-- shots -->
        <section class="shots pane" :class="{ away: view !== 'shots' }">
          <div ref="shotsEl" class="accbody shotlist">
            <div
              v-for="(sh, i) in scene.shots"
              :key="sh.id"
              class="shotcard"
              :class="{ open: openShot?.id === sh.id, lifted: draggingShot === sh.id }"
            >
              <div class="shothead" @click="openShotCard(sh.id)">
                <span
                  v-if="scene.shots.length > 1"
                  class="grip"
                  title="Drag to reorder — the shot keeps its length, text and lines"
                  @pointerdown.stop="startShotDrag($event, sh.id)"
                  @click.stop
                >
                  <i class="mdi mdi-drag-vertical" />
                </span>
                <span class="swatch" :style="{ background: colors[i] }" />
                <b>Shot {{ i + 1 }}</b>
                <i
                  v-if="i > 0 && (sh.transition ?? 'cut') !== 'cut'"
                  class="mdi trans"
                  :class="transitionOf(sh).icon"
                  :title="transitionOf(sh).title"
                />
                <span class="soft"
                  >{{ formatTime(sh.at) }} –
                  {{ formatTime(scene.shots[i + 1]?.at ?? scene.seconds) }}</span
                >
                <span
                  v-if="openShot?.id !== sh.id"
                  class="shotpeek"
                  :class="{ empty: !sh.text.trim() }"
                >
                  <template v-if="sh.text.trim()">
                    <template v-for="(part, j) in mentionParts(sh.text)" :key="j">
                      <b v-if="part.ref" :class="{ unknown: !part.known }">{{ part.text }}</b>
                      <template v-else>{{ part.text }}</template>
                    </template>
                  </template>
                  <template v-else>no text yet</template>
                </span>
                <span class="grow" />
                <span
                  v-if="sh.lines?.length"
                  class="shotlines"
                  :title="`${sh.lines.length} line${sh.lines.length === 1 ? '' : 's'} of dialogue`"
                >
                  <i class="mdi mdi-comment-quote-outline" />{{ sh.lines.length }}
                </span>
                <StudioDraft
                  v-if="openShot?.id === sh.id"
                  :project="project"
                  :scene-index="sel.sceneIndex"
                  :shot-index="i"
                  part="button"
                />
                <ZenIconButton
                  v-if="scene.shots.length > 1"
                  icon="mdi mdi-trash-can-outline"
                  title="Remove this shot"
                  @click.stop="emit('removeShot', sh.id)"
                />
              </div>
              <template v-if="openShot?.id === sh.id">
                <ZenMentionInput
                  v-model="sh.text"
                  class="prompt"
                  resizable
                  :items="mentionItems"
                  :placeholder="
                    i === 0
                      ? 'What happens in this shot? Type @ to bring in a reference.'
                      : 'The camera cuts to… (@ for references)'
                  "
                >
                  <template #thumb="{ item }">
                    <MediaThumb :media="mediaOf(item.key)" :badge="false" />
                  </template>
                  <template #preview="{ item }">
                    <div class="peek">
                      <MediaThumb :media="mediaOf(item.key)" :badge="false" play />
                    </div>
                  </template>
                </ZenMentionInput>
                <StudioDraft
                  :project="project"
                  :scene-index="sel.sceneIndex"
                  :shot-index="i"
                  part="box"
                />
                <label v-if="i > 0" class="row" :title="transitionOf(sh).title">
                  <span class="lbl">transition</span>
                  <ZenSelect
                    class="transition"
                    :model-value="sh.transition ?? 'cut'"
                    :options="TRANSITIONS.map((t) => ({ value: t.value, label: t.label }))"
                    @update:model-value="(v: string) => setTransition(sh, v)"
                  />
                </label>

                <label v-if="i > 0" class="row">
                  <span class="lbl">starts at</span>
                  <ZenNumber
                    :model-value="sh.at"
                    :min="0"
                    :max="scene.seconds"
                    :step="0.1"
                    :precision="2"
                    @update:model-value="(v: number) => setShotStart(i, v)"
                  />
                  <span class="soft">s into the scene</span>
                </label>
                <StudioDialogue
                  :project="project"
                  :scene="scene"
                  :shot="sh"
                  :index="i"
                  :seconds="(scene.shots[i + 1]?.at ?? scene.seconds) - sh.at"
                  :last="i === scene.shots.length - 1"
                  @voice="(id: string) => emit('voice', id)"
                />
              </template>
            </div>
            <ZenButton
              sm
              variant="ghost"
              icon="mdi mdi-plus"
              title="Split the last shot in two"
              @click="emit('addShot', sel.sceneIndex)"
              >Shot</ZenButton
            >
          </div>
        </section>
      </div>
    </template>

    <!-- keyframe -->
    <!-- LoRA lane -->
    <template v-else-if="sel.kind === 'lora' && lane">
      <header class="ih">
        <i class="mdi mdi-tune-variant" />
        <span class="ttl">LoRA</span>
        <span class="meta">{{ lane.enabled ? "on" : "off" }}</span>
        <span class="grow" />
        <ZenSwitch v-model="lane.enabled" title="Use this LoRA" />
      </header>
      <LoraPicker v-model="lane.name" />
      <div class="row">
        <span class="lbl">strength</span>
        <ZenNumber v-model="lane.strength" :min="-4" :max="4" :step="0.05" :precision="2" />
        <span class="hintline">for every scene without its own</span>
        <ZenButton
          v-if="ownCount"
          sm
          variant="ghost"
          icon="mdi mdi-backup-restore"
          :title="`${ownCount} scene${ownCount === 1 ? '' : 's'} have their own strength — put them all back to the lane's`"
          @click="lane.scenes = {}"
        >
          Reset scenes
        </ZenButton>
      </div>
      <div class="col">
        <span class="lbl">per scene — a scene renders all its frames at one strength</span>
        <div
          class="lscenes"
          title="Or drag each scene's bar on the timeline. Dashed bars follow the lane's strength."
        >
          <label
            v-for="(sc, i) in project.scenes"
            :key="sc.id"
            class="lscene"
            :class="{
              here: i === currentScene,
              own: lane.scenes?.[sc.id] !== undefined,
              zero: laneScenes[i] === 0,
            }"
            :title="
              lane.scenes?.[sc.id] !== undefined
                ? `Scene ${i + 1} has its own strength`
                : `Scene ${i + 1} follows the lane's strength`
            "
          >
            S{{ i + 1 }}
            <ZenNumber
              :model-value="laneScenes[i] ?? 0"
              :min="-4"
              :max="4"
              :step="0.05"
              :precision="2"
              @update:model-value="(v: number) => setSceneStrength(sc.id, v)"
            />
            <button
              v-if="lane.scenes?.[sc.id] !== undefined"
              type="button"
              class="unown"
              title="Follow the lane's strength again"
              @click="setSceneStrength(sc.id, null)"
            >
              <i class="mdi mdi-close" />
            </button>
          </label>
        </div>
      </div>
      <p v-if="!stepShapesWork(project) && hasShapes" class="shapenote">
        <i class="mdi mdi-information-outline" />
        This lane has step shapes, but with dynamic VRAM on they can't change over the steps, so
        they apply as their average:
        <b>×{{ shapeMean(lane.sampling).toFixed(2) }}</b
        ><template v-if="shapedScenes.length">
          for the lane, and their own for {{ shapedScenes.length }} scene{{
            shapedScenes.length === 1 ? "" : "s"
          }}</template
        >.
        <button type="button" class="linkbtn" @click="clearShapes">Remove step shapes</button>
      </p>
      <section v-if="stepShapesWork(project)" class="settings" :class="{ open: stepsOpen }">
        <button type="button" class="sechead" @click="stepsOpen = !stepsOpen">
          <i class="mdi" :class="stepsOpen ? 'mdi-chevron-down' : 'mdi-chevron-right'" />
          ∿ Within each scene: over the sampling steps
          <span class="soft">{{
            isShaped(lane.sampling) || shapedScenes.length ? "shaped" : "constant"
          }}</span>
        </button>
        <div v-if="stepsOpen" class="col">
          <span class="lbl">the lane's shape — for every scene without its own</span>
          <ZenCurveEditor
            v-model="samplingCurve"
            :min="0"
            :max="2"
            :unit="1"
            :x-labels="['high noise · composition', 'low noise · detail']"
            :presets="SAMPLING_PRESETS"
          />
          <span class="hintline">
            Advanced. Multiplies the scene's strength while it is made: the first steps settle the
            layout and motion, the last ones the detail. Flat at 1 does nothing. Give a scene its
            own shape on the timeline (the lane's ∿ button).
          </span>
          <div v-if="shapedScenes.length" class="row">
            <span class="lbl">own shape</span>
            <span v-for="i in shapedScenes" :key="i" class="lscene own">
              S{{ i + 1 }}
              <button
                type="button"
                class="unown"
                title="Follow the lane's shape again"
                @click="unshape(project.scenes[i]!.id)"
              >
                <i class="mdi mdi-close" />
              </button>
            </span>
          </div>
        </div>
      </section>
    </template>

    <template v-else-if="sel.kind === 'keyframe' && keyframe">
      <header class="ih">
        <i class="mdi mdi-rhombus" />
        <span class="ttl">Keyframe</span>
        <span class="meta">scene {{ sel.sceneIndex + 1 }} · {{ keyframeRole }}</span>
      </header>
      <div
        class="fitframe"
        :style="{ aspectRatio: `${project.canvas.width} / ${project.canvas.height}` }"
        title="Drop a picture here to replace it"
        @dragover="onKeyframeDragOver"
        @dragleave="onKeyframeDragLeave"
        @drop="onKeyframeDrop"
      >
        <img :class="keyframe.fit ?? 'crop'" :src="stableUrl(keyframe.media)" alt="" />
        <div v-if="keyframeDropping" class="replacing">
          <i class="mdi mdi-swap-horizontal" />
          <span>Replace</span>
        </div>
      </div>
      <div class="row">
        <span class="lbl">fit</span>
        <ZenToggleGroup
          :model-value="keyframe.fit ?? 'crop'"
          :options="[
            {
              value: 'crop',
              label: 'Crop',
              title: 'Fill the canvas, cutting off what doesn\'t fit',
            },
            {
              value: 'stretch',
              label: 'Stretch',
              title: 'Squash it onto the canvas, keeping everything',
            },
          ]"
          @update:model-value="
            (v: string) => (keyframe!.fit = v === 'stretch' ? 'stretch' : 'crop')
          "
        />
        <span class="soft">as H3 will see it, in the canvas's shape</span>
      </div>
      <div class="row">
        <ZenButton sm icon="mdi mdi-page-first" @click="keyframe.at = 0">First frame</ZenButton>
        <ZenButton sm icon="mdi mdi-page-last" @click="keyframe.at = scene!.seconds"
          >Last frame</ZenButton
        >
        <span class="grow" />
        <ZenButton
          sm
          variant="danger"
          icon="mdi mdi-trash-can-outline"
          @click="emit('removeKeyframe', keyframe.id)"
          >Remove</ZenButton
        >
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
// The inspector: an editor for whatever is selected on the timeline, over the current scene's
// references laid out as numbered picture slots (the order H3 reads them in).
import { computed, ref, watch } from "vue";
import MediaThumb from "./MediaThumb.vue";
import StudioDialogue from "./StudioDialogue.vue";
import StudioDraft from "./StudioDraft.vue";
import {
  LoraPicker,
  ZenButton,
  ZenCurveEditor,
  ZenIconButton,
  ZenMentionInput,
  ZenNumber,
  ZenPopover,
  ZenSelect,
  ZenSwitch,
  ZenToggleGroup,
  type CurvePoint,
  type CurvePreset,
  type MentionItem,
} from "@nynxz/zenkit-ui";
import {
  CONTEXT_FRAMES,
  CONTINUATIONS,
  randomSeed,
  continuationOf,
  formatTime,
  framesFor,
  TRANSITIONS,
  sceneLoraStrength,
  shapeMean,
  stepShapesWork,
  shotColors,
  stableUrl,
  type Compiled,
  type FilmSettings,
  type Project,
  type Shot,
} from "@/lib/h3studio";
import { isShaped } from "@/lib/h3tracks";
import { hasMediaDrop } from "@/framework";
import { reorderShot } from "@/lib/h3edits";

export interface Selection {
  kind: "shot" | "scene" | "keyframe" | "ref" | "lora";
  id: string;
  sceneIndex: number;
  shotIndex: number;
}

const props = defineProps<{
  project: Project;
  sel: Selection;
  currentScene: number;
  compiled: Compiled | null;
}>();
const emit = defineEmits<{
  select: [target: { kind: Selection["kind"]; id: string }];
  seconds: [scene: number, seconds: number];
  removeKeyframe: [id: string];
  replaceKeyframe: [id: string, event: DragEvent];
  setKeyframe: [scene: number, edge: "first" | "last"];
  removeShot: [id: string];
  addShot: [scene: number];
  voice: [id: string];
}>();

const scene = computed(() => props.project.scenes[props.sel.sceneIndex]);
// --- keyframe: new media dropped on its picture replaces it ----------------------------------------
const keyframeDropping = ref(false);
function onKeyframeDragOver(e: DragEvent) {
  if (!hasMediaDrop(e)) return;
  e.preventDefault();
  e.stopPropagation();
  keyframeDropping.value = true;
}
function onKeyframeDragLeave(e: DragEvent) {
  const to = e.relatedTarget as Node | null;
  if (!(e.currentTarget as HTMLElement).contains(to)) keyframeDropping.value = false;
}
function onKeyframeDrop(e: DragEvent) {
  keyframeDropping.value = false;
  if (!hasMediaDrop(e) || !keyframe.value) return;
  e.preventDefault();
  e.stopPropagation();
  emit("replaceKeyframe", keyframe.value.id, e);
}
// --- scene panel ---------------------------------------------------------------------------------
// Selecting a shot opens its card; selecting the scene opens its settings (and keeps whichever
// card you last had open). Cards are opened by selecting the shot, so the timeline follows.
/** What the scene panel shows: its shots, or its settings (this scene's, or the whole film's).
 *  Picking a shot shows the shots; picking the scene, its settings. */
const view = ref<"shots" | "settings">(props.sel.kind === "scene" ? "settings" : "shots");
const level = ref<"scene" | "film">("scene");
/** The film-wide settings: the project itself, edited in place like a scene. */
const film = computed(() => props.project);
const setFilm = (change: Partial<FilmSettings>) =>
  (film.value.film = { ...film.value.film, ...change });
const lastOpenShot = ref<string | null>(props.sel.kind === "shot" ? props.sel.id : null);
watch(
  () => [props.sel.kind, props.sel.id] as const,
  ([kind, id]) => {
    if (kind === "scene") {
      view.value = "settings";
      level.value = "scene";
    } else if (kind === "shot") {
      view.value = "shots";
      lastOpenShot.value = id;
    }
  },
);
const openShot = computed(() =>
  scene.value?.shots.find(
    (s) => s.id === (props.sel.kind === "shot" ? props.sel.id : lastOpenShot.value),
  ),
);
function openShotCard(id: string) {
  emit("select", { kind: "shot", id });
}
function goScene(by: number) {
  const next = props.project.scenes[props.sel.sceneIndex + by];
  if (next) emit("select", { kind: "scene", id: next.id });
}
/** Move a shot's start, kept between its neighbours (a quarter second either side). */
function setShotStart(i: number, v: number) {
  const s = scene.value;
  if (!s) return;
  const lo = (s.shots[i - 1]?.at ?? 0) + 0.25;
  const hi = (s.shots[i + 1]?.at ?? s.seconds) - 0.25;
  s.shots[i]!.at = Math.round(Math.min(hi, Math.max(lo, v)) * 100) / 100;
}
const refNames = computed(() => new Set(sceneRefs.value.map((r) => r.name.toLowerCase())));
function mentionParts(text: string) {
  const line = text.replace(/\s+/g, " ").trim();
  return line.split(/(@[\w-]+)/).map((t) => ({
    text: t,
    ref: t.startsWith("@"),
    known: refNames.value.has(t.slice(1).toLowerCase()),
  }));
}
const keyframe = computed(() => scene.value?.keyframes.find((k) => k.id === props.sel.id));
const colors = computed(() => (scene.value ? shotColors(scene.value) : []));
const transitionOf = (sh: Shot) =>
  TRANSITIONS.find((t) => t.value === (sh.transition ?? "cut")) ?? TRANSITIONS[0]!;
function setContinuation(value: string) {
  const found = CONTINUATIONS.find((c) => c.value === value);
  if (found && scene.value) scene.value.continuation.mode = found.value;
}
function setTransition(sh: Shot, value: string) {
  const found = TRANSITIONS.find((t) => t.value === value);
  if (found) sh.transition = found.value;
}

// --- reordering shots: drag a card by its grip; it swaps with a neighbour past that one's middle ---
const shotsEl = ref<HTMLElement | null>(null);
const draggingShot = ref<string | null>(null);
function startShotDrag(e: PointerEvent, id: string) {
  const list = shotsEl.value;
  if (e.button !== 0 || !list) return;
  e.preventDefault();
  // Captured by the list, which stays put: a card moves in the page as the shots reorder.
  list.setPointerCapture(e.pointerId);
  draggingShot.value = id;
  const move = (m: PointerEvent) => {
    const sc = scene.value;
    if (!sc) return;
    const at = sc.shots.findIndex((x) => x.id === id);
    const cards = [...list.querySelectorAll<HTMLElement>(":scope > .shotcard")];
    const mid = (el: HTMLElement | undefined) => {
      const r = el?.getBoundingClientRect();
      return r ? r.top + r.height / 2 : null;
    };
    const above = mid(cards[at - 1]);
    const below = mid(cards[at + 1]);
    const to =
      above !== null && m.clientY < above
        ? at - 1
        : below !== null && m.clientY > below
          ? at + 1
          : at;
    if (to !== at) reorderShot(props.project, props.sel.sceneIndex, at, to);
  };
  const up = () => {
    draggingShot.value = null;
    list.removeEventListener("pointermove", move);
    list.removeEventListener("pointerup", up);
  };
  list.addEventListener("pointermove", move);
  list.addEventListener("pointerup", up);
}

// --- LoRA lane ----------------------------------------------------------------------------------
const lane = computed(() => props.project.loras?.find((l) => l.id === props.sel.id));
const laneScenes = computed(() =>
  lane.value
    ? props.project.scenes.map((_, i) =>
        lane.value!.enabled ? sceneLoraStrength(props.project, lane.value!, i) : 0,
      )
    : [],
);
const ownCount = computed(
  () =>
    Object.keys(lane.value?.scenes ?? {}).filter((id) =>
      props.project.scenes.some((s) => s.id === id),
    ).length,
);
/** Give a scene its own strength, or (null) let it follow the lane's again. */
function setSceneStrength(sceneId: string, v: number | null) {
  const l = lane.value;
  if (!l) return;
  const scenes = { ...(l.scenes ?? {}) };
  if (v === null) delete scenes[sceneId];
  else scenes[sceneId] = v;
  l.scenes = scenes;
}
/** Scenes (by index) with their own shape over the steps. */
const shapedScenes = computed(() =>
  props.project.scenes.flatMap((sc, i) => (lane.value?.steps?.[sc.id] ? [i] : [])),
);
function unshape(sceneId: string) {
  const l = lane.value;
  if (l) l.steps = Object.fromEntries(Object.entries(l.steps ?? {}).filter(([k]) => k !== sceneId));
}
const hasShapes = computed(
  () => !!lane.value && (isShaped(lane.value.sampling) || shapedScenes.value.length > 0),
);
function clearShapes() {
  if (!lane.value) return;
  lane.value.sampling = [];
  lane.value.steps = {};
}
const stepsOpen = ref(
  lane.value ? isShaped(lane.value.sampling) || shapedScenes.value.length > 0 : false,
);
/** The lane's curve over the steps, as the editor's x/y points. */
const samplingCurve = computed({
  get: () => (lane.value?.sampling ?? []).map((p) => ({ x: p.p, y: p.v })),
  set: (pts: CurvePoint[]) => {
    if (lane.value) lane.value.sampling = pts.map((p) => ({ p: p.x, v: p.y }));
  },
});
const SAMPLING_PRESETS: CurvePreset[] = [
  {
    label: "Constant",
    icon: "mdi mdi-minus",
    title: "The same strength at every step",
    points: [],
  },
  {
    label: "Early only",
    icon: "mdi mdi-arrow-collapse-left",
    title: "High noise only: shapes composition and motion, leaves detail to the base model",
    points: [
      { x: 0, y: 1 },
      { x: 0.4, y: 1 },
      { x: 0.5, y: 0 },
    ],
  },
  {
    label: "Late only",
    icon: "mdi mdi-arrow-collapse-right",
    title: "Low noise only: keeps the base model's composition, adds the LoRA's look and detail",
    points: [
      { x: 0.4, y: 0 },
      { x: 0.5, y: 1 },
    ],
  },
  {
    label: "Fade in",
    icon: "mdi mdi-trending-up",
    title: "From nothing to full over the steps",
    points: [
      { x: 0, y: 0 },
      { x: 1, y: 1 },
    ],
  },
  {
    label: "Fade out",
    icon: "mdi mdi-trending-down",
    title: "From full to nothing over the steps",
    points: [
      { x: 0, y: 1 },
      { x: 1, y: 0 },
    ],
  },
];
const keyframeRole = computed(() => {
  const k = keyframe.value;
  if (!k || !scene.value) return "";
  if (k.at <= 0.01) return "first frame";
  if (k.at >= scene.value.seconds - 0.05) return "last frame";
  return `at ${formatTime(k.at)}`;
});

function edgeKeyframe(edge: "first" | "last") {
  const s = scene.value;
  if (!s) return undefined;
  return s.keyframes.find((k) => (edge === "first" ? k.at <= 0.01 : k.at >= s.seconds - 0.05));
}
const keyframeHint = computed(() => {
  const first = !!edgeKeyframe("first");
  const last = !!edgeKeyframe("last");
  if (first && last) return "The scene travels from the first picture to the last.";
  if (first) return "The scene starts exactly on this picture.";
  if (last) return "The scene ends exactly on this picture.";
  return "";
});

/** Every reference: mentioning one in a shot is what brings it into the scene. */
const sceneRefs = computed(() => props.project.refs);
const tagOf = (id: string) => props.compiled?.refs.find((r) => r.id === id)?.tag ?? "";
const mentionItems = computed<MentionItem[]>(() =>
  sceneRefs.value.map((r) => ({
    key: r.name,
    detail:
      [tagOf(r.id), r.note].filter(Boolean).join(" · ") ||
      (r.kind === "image" ? "picture" : r.kind),
  })),
);
const mediaOf = (name: string) => props.project.refs.find((r) => r.name === name)?.media ?? "";

function mention(name: string) {
  const s = openShot.value;
  if (!s) return;
  s.text = `${s.text.trimEnd()}${s.text.trim() ? " " : ""}@${name} `;
}
</script>

<style scoped>
.inspector {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  min-height: 100%;
}
.ih {
  display: flex;
  align-items: center;
  gap: 7px;
}
.ih .mdi {
  color: var(--h3-muted);
  font-size: 15px;
}
.swatch {
  width: 10px;
  height: 10px;
  border-radius: 3px;
}
.ttl {
  font-size: 13px;
  font-weight: 700;
}
.meta,
.soft {
  color: var(--h3-muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.grow {
  flex: 1;
}
.prompt {
  flex: 1 1 120px;
  min-height: 110px;
}
.prompt :deep(.zmi-area) {
  overflow-y: auto;
}
.inspector textarea,
.line {
  box-sizing: border-box;
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--h3-line);
  border-radius: var(--h3-radius);
  outline: none;
  background: var(--h3-field);
  color: var(--h3-text);
  font-family: inherit;
  font-size: 12.5px;
  line-height: 1.5;
  resize: none;
}
.line {
  padding: 5px 8px;
}
.inspector textarea:focus,
.line:focus {
  border-color: var(--h3-accent);
}
.grow {
  flex: 1;
}
.refsbtn {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  height: 22px;
  padding: 0 7px 0 5px;
  border: 1px solid var(--h3-line);
  border-radius: var(--h3-radius);
  background: none;
  color: #9db7ff;
  font: inherit;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}
.refsbtn .mdi {
  color: inherit;
  font-size: 13px;
}
.refsbtn:hover {
  border-color: var(--h3-accent);
}
/* Fits inside the popover (at most 360px, less its padding), with room kept for the scrollbar so
   the last column isn't squeezed under it. */
.refgrid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(76px, 1fr));
  gap: 6px;
  box-sizing: border-box;
  width: min(348px, calc(92vw - 12px));
  max-height: 320px;
  padding: 2px 4px 2px 2px;
  overflow-y: auto;
  scrollbar-gutter: stable;
}
.refcard {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding: 4px;
  border: 1px solid transparent;
  border-radius: var(--zen-radius, 8px);
  background: none;
  color: var(--zen-text, #e5e5ea);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.refcard:hover {
  border-color: var(--zen-accent, #6366f1);
  background: color-mix(in srgb, var(--zen-accent, #6366f1) 10%, transparent);
}
.refthumb {
  display: block;
  aspect-ratio: 1;
  overflow: hidden;
  border-radius: calc(var(--zen-radius, 8px) - 2px);
  background: #0b0b0e;
}
.refcard b {
  overflow: hidden;
  color: #9db7ff;
  font-size: 11px;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.refcard small {
  color: var(--zen-muted, #9aa0aa);
  font-size: 10px;
}
.row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.col {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.lbl {
  color: var(--h3-muted);
  font-size: 10.5px;
  font-weight: 600;
}
.row .lbl {
  min-width: 36px;
}
.ctx {
  width: 110px;
}
.fitframe {
  position: relative;
  width: 100%;
  max-height: 220px;
  overflow: hidden;
  border-radius: var(--h3-radius);
  background: #000;
}
.replacing {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  background: color-mix(in srgb, var(--zen-accent, #6366f1) 55%, rgb(0 0 0 / 60%));
  color: #fff;
  font-size: 10.5px;
  font-weight: 700;
  pointer-events: none;
}
.replacing .mdi {
  font-size: 20px;
}
.fitframe img {
  display: block;
  width: 100%;
  height: 100%;
}
.fitframe img.crop {
  object-fit: cover;
}
.fitframe img.stretch {
  object-fit: fill;
}
.big {
  width: 100%;
  max-height: 200px;
  border-radius: var(--h3-radius);
  object-fit: contain;
  background: #000;
}
.refbox {
  display: flex;
  gap: 10px;
}
.refthumb {
  flex: none;
  width: 72px;
  height: 72px;
  overflow: hidden;
  border-radius: var(--h3-radius);
}
.mthumb {
  width: 18px;
  height: 18px;
  overflow: hidden;
  border-radius: 50%;
}
.check {
  gap: 8px;
  color: var(--h3-text);
  font-size: 11.5px;
  cursor: pointer;
}
.hintline {
  margin: 0;
  color: var(--h3-muted);
  font-size: 11px;
  line-height: 1.45;
}
.group {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.lscenes {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.lscene {
  padding: 1px 2px 1px 7px;
  border: 1px solid var(--h3-line);
  border-radius: 10px;
  color: var(--h3-muted);
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.lscene :deep(.zen-number) {
  width: 74px;
}
.lscene.own {
  border-color: color-mix(in srgb, var(--h3-text) 35%, var(--h3-line));
  color: var(--h3-text);
}
.lscene:not(.own) {
  border-style: dashed;
}
.shapenote {
  margin: 0;
  padding: 6px 8px;
  border: 1px dashed var(--h3-line);
  border-radius: var(--h3-radius);
  color: var(--h3-muted);
  font-size: 10.5px;
  line-height: 1.45;
}
.shapenote b {
  color: var(--h3-text);
}
.linkbtn {
  padding: 0;
  border: 0;
  background: none;
  color: var(--h3-accent);
  font: inherit;
  text-decoration: underline;
  cursor: pointer;
}
.unown {
  display: grid;
  place-items: center;
  width: 14px;
  height: 14px;
  padding: 0;
  border: 0;
  border-radius: 3px;
  background: none;
  color: var(--h3-muted);
  cursor: pointer;
}
.unown:hover {
  background: color-mix(in srgb, var(--h3-text) 12%, transparent);
  color: var(--h3-text);
}
.lscene.here {
  border-color: var(--h3-accent);
}
.lscene.zero {
  opacity: 0.5;
}
.seed {
  width: 130px;
}
.carryhint {
  display: flex;
  flex-basis: 100%;
  gap: 5px;
  align-items: flex-start;
  line-height: 1.4;
}
.scenetitle {
  width: 100%;
  box-sizing: border-box;
  margin: 0 0 6px;
  padding: 4px 6px;
  border: 1px solid transparent;
  border-radius: var(--zen-radius, 7px);
  outline: none;
  background: transparent;
  color: var(--zen-text, #e5e5ea);
  font: inherit;
  font-size: 13.5px;
  font-weight: 600;
}
.scenetitle:hover {
  border-color: var(--zen-border, #34343c);
}
.scenetitle:focus {
  border-color: var(--zen-accent, #6366f1);
  background: var(--zen-field-bg, var(--zen-input, #1b1b20));
}
.scenetitle::placeholder {
  color: var(--zen-muted, #9aa0aa);
  font-weight: 500;
  opacity: 0.7;
}
.scenehead {
  gap: 4px;
}
.scenepick {
  flex: 0 1 150px;
  min-width: 90px;
}
/* The scene panel fills the sidebar: Film, Scene settings and Shots are an accordion with one
   section open, which takes the room left and scrolls on its own; the others are one-line headers. */
.inspector.scene,
.inspector.shot {
  height: 100%;
  min-height: 0;
}
.scenebody {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
}
.pane {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-height: 0;
}
.viewpick,
.levelpick {
  flex: none;
}
.scenebody .away {
  display: none;
}
.lbl.own {
  display: flex;
  align-items: center;
  gap: 6px;
}
.lbl .ownmark {
  color: var(--zen-accent, #6366f1);
  font-weight: 600;
}
.lbl .reset {
  display: grid;
  place-items: center;
  width: 16px;
  height: 16px;
  padding: 0;
  border: 0;
  border-radius: 4px;
  background: none;
  color: var(--h3-muted);
  cursor: pointer;
}
.lbl .reset:hover {
  background: color-mix(in srgb, var(--h3-text) 10%, transparent);
  color: var(--h3-text);
}
.accbody {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.pane > .accbody {
  flex: 1;
  min-height: 0;
  margin-right: -4px;
  padding-right: 4px;
  overflow-y: auto;
  scrollbar-gutter: stable;
}
/* Settings text is as tall as what's written in it. */
.inspector textarea.fits {
  min-height: 52px;
  max-height: 240px;
  field-sizing: content;
}
.settings {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 6px 8px;
  border: 1px solid var(--h3-line);
  border-radius: var(--h3-radius);
}
.sechead {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 0;
  border: 0;
  background: none;
  color: var(--h3-text);
  font: inherit;
  font-size: 11.5px;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
}
.sechead .soft {
  margin-left: auto;
  font-weight: 400;
}
.sechead .soft.ellipsis {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-align: right;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.shots {
  gap: 8px;
  padding: 6px 8px;
  border: 1px solid var(--h3-line);
  border-radius: var(--h3-radius);
}
.shotlist {
  gap: 5px;
}
.shotlist > :deep(.zen-btn) {
  align-self: flex-start;
}
.shotcard {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 5px 6px 5px 8px;
  border: 1px solid var(--h3-line);
  border-radius: var(--h3-radius);
  background: color-mix(in srgb, var(--h3-text) 2%, transparent);
}
.shotcard.lifted {
  box-shadow: 0 6px 18px rgb(0 0 0 / 40%);
}
.shothead .grip {
  display: grid;
  flex: none;
  place-items: center;
  width: 12px;
  margin-left: -5px;
  color: var(--h3-muted);
  cursor: grab;
  touch-action: none;
}
.shothead .grip:hover {
  color: var(--h3-text);
}
.shotcard.open {
  padding-bottom: 8px;
  border-color: color-mix(in srgb, var(--h3-accent) 60%, var(--h3-line));
  background: color-mix(in srgb, var(--h3-accent) 6%, transparent);
}
.shothead {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  font-size: 11.5px;
  cursor: pointer;
}
.shothead > b {
  flex: none;
}
.shothead > .soft {
  flex: none;
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
}
.shothead :deep(.zen-iconbtn) {
  opacity: 0;
}
.shotcard:hover .shothead :deep(.zen-iconbtn) {
  opacity: 1;
}
.shotpeek {
  min-width: 0;
  overflow: hidden;
  color: var(--h3-muted);
  white-space: nowrap;
  text-overflow: ellipsis;
}
.meta.len {
  flex: none;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.shothead .trans {
  flex: none;
  color: var(--h3-accent);
  font-size: 12px;
}
.row .transition {
  flex: 1 1 140px;
  min-width: 0;
}
.shotlines {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: 2px;
  color: var(--h3-muted);
  font-size: 10.5px;
}
.shotpeek.empty {
  font-style: italic;
  opacity: 0.6;
}
.shotpeek b {
  color: #9db7ff;
  font-weight: 500;
}
.shotpeek b.unknown {
  color: #f17b7b;
}
.shotcard .prompt {
  min-height: 90px;
}
.kfs {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.kf {
  position: relative;
  display: grid;
  place-items: center;
  width: 54px;
  height: 38px;
  overflow: hidden;
  padding: 0;
  border: 1px dashed var(--h3-line);
  border-radius: var(--h3-radius);
  background: var(--h3-field);
  color: var(--h3-muted);
  font-size: 15px;
  cursor: pointer;
}
.kf.set {
  border-style: solid;
}
.kf:hover {
  border-color: var(--h3-accent);
  color: var(--h3-text);
}
.kfl {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  background: rgb(0 0 0 / 55%);
  color: #fff;
  font-size: 9px;
  line-height: 13px;
  text-align: center;
  text-transform: uppercase;
}
.kfs .hintline {
  flex: 1 1 140px;
}
.refgroups {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: auto;
}
.slots-head .mdi {
  font-size: 13px;
}
.slot .st {
  position: absolute;
  right: 3px;
  bottom: 3px;
  display: grid;
  place-items: center;
  width: 15px;
  height: 15px;
  border-radius: 3px;
  background: rgb(0 0 0 / 65%);
  color: #fff;
  font-size: 10px;
}
.wide :deep(.zen-tg) {
  display: flex;
  width: 100%;
}
.wide :deep(.zen-tg-b) {
  flex: 1;
}
.scenechip {
  width: 24px;
  height: 22px;
  border: 1px solid var(--h3-line);
  border-radius: calc(var(--h3-radius) * 0.75);
  background: none;
  color: var(--h3-muted);
  font: inherit;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
}
.scenechip.on {
  border-color: var(--h3-accent);
  background: color-mix(in srgb, var(--h3-accent) 25%, transparent);
  color: var(--h3-text);
}
.slots-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 8px;
  border-top: 1px solid var(--h3-line);
  color: var(--h3-muted);
  font-size: 10.5px;
  font-weight: 600;
}
.slots {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(52px, 1fr));
  gap: 5px;
}
.slot {
  position: relative;
  aspect-ratio: 1;
  overflow: hidden;
  padding: 0;
  border: 1px solid var(--h3-line);
  border-radius: var(--h3-radius);
  background: var(--h3-field);
  color: var(--h3-muted);
  cursor: pointer;
}
.slot img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.slot.semantic img {
  filter: saturate(0.3) brightness(0.85);
}
.slot.on {
  border-color: var(--h3-accent);
  box-shadow: 0 0 0 1px var(--h3-accent);
}
.slot .pn {
  position: absolute;
  top: 3px;
  left: 3px;
  min-width: 14px;
  padding: 0 3px;
  border-radius: 3px;
  background: rgb(0 0 0 / 65%);
  color: #fff;
  font-size: 9.5px;
  font-weight: 700;
  line-height: 14px;
  text-align: center;
}
.slot.empty {
  border-style: dashed;
  font-size: 18px;
}
.slot.empty:hover,
.slot.empty.dropping {
  border-color: var(--h3-accent);
  color: var(--h3-text);
}
.peek {
  height: 150px;
  overflow: hidden;
  border-radius: calc(var(--h3-radius) - 2px);
  background: #0b0b0e;
}
</style>
