<template>
  <div class="insp zen-scroll">
    <!-- a shape of the set -->
    <template v-if="sel?.type === 'shape' && shape">
      <header>
        <i class="mdi mdi-cube-outline" /><b>{{ shape.id }}</b
        ><span class="kind">{{ shape.type ?? "box" }}</span>
      </header>
      <ZenField label="Name" stack
        ><ZenInput sm :model-value="shape.id ?? ''" @change="rename($event)"
      /></ZenField>
      <template v-if="shape.type === 'capsule'">
        <ZenField label="From" stack
          ><GbVec :model-value="shape.a ?? [0, 0, 0]" @update:model-value="up({ a: $event })"
        /></ZenField>
        <ZenField label="To" stack
          ><GbVec :model-value="shape.b ?? [0, 1, 0]" @update:model-value="up({ b: $event })"
        /></ZenField>
      </template>
      <ZenField v-else :label="shape.type === 'cylinder' ? 'Base at' : 'Centre at'" stack>
        <GbVec :model-value="shape.at ?? [0, 0, 0]" @update:model-value="up({ at: $event })" />
      </ZenField>
      <ZenField v-if="(shape.type ?? 'box') === 'box'" label="Size" stack>
        <GbVec :model-value="shape.size ?? [1, 1, 1]" @update:model-value="up({ size: $event })" />
      </ZenField>
      <div class="row2">
        <ZenField v-if="shape.type !== 'box' && shape.type" label="Radius" stack>
          <ZenNumber
            size="sm"
            :model-value="shape.radius ?? 0.5"
            :min="0.01"
            :step="0.02"
            :precision="2"
            @update:model-value="up({ radius: $event })"
          />
        </ZenField>
        <ZenField v-if="shape.type === 'cylinder'" label="Height" stack>
          <ZenNumber
            size="sm"
            :model-value="shape.height ?? 1"
            :min="0.01"
            :step="0.05"
            :precision="2"
            @update:model-value="up({ height: $event })"
          />
        </ZenField>
        <ZenField v-if="(shape.type ?? 'box') === 'box'" label="Turn" stack>
          <ZenNumber
            size="sm"
            :model-value="shape.yaw ?? 0"
            :step="5"
            :precision="0"
            @update:model-value="up({ yaw: $event })"
          />
        </ZenField>
      </div>
      <ZenField label="Grey" stack>
        <ZenSlider
          :model-value="shape.tone ?? 0.7"
          :min="0"
          :max="1"
          :step="0.01"
          @update:model-value="up({ tone: $event })"
        />
      </ZenField>
      <div class="actions">
        <ZenButton
          size="sm"
          icon="mdi mdi-content-copy"
          @click="run('shape.duplicate', { id: shape.id })"
          >Duplicate</ZenButton
        >
        <ZenButton
          size="sm"
          icon="mdi mdi-delete-outline"
          @click="remove('shape.remove', { id: shape.id })"
          >Delete</ZenButton
        >
      </div>
    </template>

    <!-- a mark -->
    <template v-else-if="sel?.type === 'mark' && mark">
      <header>
        <i class="mdi mdi-map-marker-outline" /><b>{{ sel.id }}</b
        ><span class="kind">mark</span>
      </header>
      <ZenField label="Name" stack hint="Renaming updates every key that uses it.">
        <ZenInput sm :model-value="sel.id" @change="renameMark($event)" />
      </ZenField>
      <ZenField label="At" stack
        ><GbVec
          :model-value="mark"
          @update:model-value="run('mark.set', { name: sel.id, at: $event })"
      /></ZenField>
      <div class="actions">
        <ZenButton
          size="sm"
          icon="mdi mdi-delete-outline"
          @click="remove('mark.remove', { name: sel.id })"
          >Delete</ZenButton
        >
      </div>
    </template>

    <!-- a set camera -->
    <template v-else-if="sel?.type === 'setcam' && setcam">
      <header>
        <i class="mdi mdi-cctv" /><b>{{ sel.id }}</b
        ><span class="kind">set camera</span>
      </header>
      <ZenField label="At" stack
        ><GbVec
          :model-value="setcam.at"
          @update:model-value="run('setcam.set', { name: sel.id, at: $event })"
      /></ZenField>
      <ZenField label="Looks at" stack
        ><GbRef
          :model-value="setcam.look"
          :options="lookOptions"
          @update:model-value="$event && run('setcam.set', { name: sel.id, look: $event })"
      /></ZenField>
      <ZenField label="Lens (mm)" stack>
        <ZenNumber
          size="sm"
          :model-value="setcam.lens ?? 35"
          :min="8"
          :max="400"
          :step="1"
          :precision="0"
          @update:model-value="run('setcam.set', { name: sel.id, lens: $event })"
        />
      </ZenField>
      <div class="actions">
        <ZenButton
          size="sm"
          icon="mdi mdi-delete-outline"
          @click="remove('setcam.remove', { name: sel.id })"
          >Delete</ZenButton
        >
      </div>
    </template>

    <!-- an actor (or one of its keys) -->
    <template v-else-if="(sel?.type === 'actor' || sel?.type === 'key') && actor">
      <header>
        <i class="mdi mdi-account-outline" /><b>{{ actor.id }}</b
        ><span class="kind">character</span>
      </header>
      <div class="row3">
        <ZenField label="Height" stack>
          <ZenNumber
            size="sm"
            :model-value="member.height"
            :min="0.3"
            :max="3"
            :step="0.01"
            :precision="2"
            @update:model-value="run('cast.set', { id: actor.id, height: $event })"
          />
        </ZenField>
        <ZenField label="Build" stack>
          <ZenNumber
            size="sm"
            :model-value="member.build"
            :min="0.4"
            :max="2.5"
            :step="0.05"
            :precision="2"
            @update:model-value="run('cast.set', { id: actor.id, build: $event })"
          />
        </ZenField>
        <ZenField label="Grey" stack>
          <ZenNumber
            size="sm"
            :model-value="member.tone"
            :min="0"
            :max="1"
            :step="0.02"
            :precision="2"
            @update:model-value="run('cast.set', { id: actor.id, tone: $event })"
          />
        </ZenField>
      </div>
      <p class="soft small">Height, build and grey are the cast's: every scene uses them.</p>
      <h4>Keys</h4>
      <div class="keys">
        <button
          v-for="k in sortedKeys"
          :key="k.t"
          type="button"
          class="krow"
          :class="{ on: sel.type === 'key' && near(sel.t, k.t) }"
          @click="(emit('select', { type: 'key', id: actor.id, t: k.t }), emit('seek', k.t))"
        >
          <b>{{ k.t.toFixed(2) }}s</b>
          <span class="ellipsis">{{ describeRef(k.at) }}</span>
          <span v-if="k.pose === 'sit'" class="tag">sit</span>
        </button>
      </div>
      <ZenButton size="sm" icon="mdi mdi-plus" @click="keyHere"
        >Key at {{ time.toFixed(2) }}s</ZenButton
      >

      <template v-if="sel.type === 'key' && key">
        <h4>Key at {{ key.t.toFixed(2) }}s</h4>
        <ZenField label="Time" stack>
          <ZenNumber
            size="sm"
            :model-value="key.t"
            :min="0"
            :step="0.1"
            :precision="2"
            @update:model-value="moveKey($event)"
          />
        </ZenField>
        <ZenField label="At" stack hint="A point, a mark, or @someone."
          ><GbRef
            :model-value="key.at"
            :options="placeOptions"
            @update:model-value="
              $event && run('key.set', { actor: actor.id, t: key.t, at: $event })
            "
        /></ZenField>
        <ZenField
          label="Faces"
          stack
          hint="Degrees (0 faces +z), path, a mark or @someone. Empty: keeps facing as before."
        >
          <GbRef
            :model-value="typeof key.face === 'number' ? String(key.face) : key.face"
            :options="['path', ...placeOptions]"
            @update:model-value="setFace($event)"
          />
        </ZenField>
        <div class="row2">
          <ZenField label="Pose" stack>
            <ZenSelect
              size="sm"
              :model-value="key.pose ?? ''"
              :options="POSES"
              @update:model-value="
                run('key.set', { actor: actor.id, t: key.t, pose: $event || null })
              "
            />
          </ZenField>
          <ZenField label="Move" stack>
            <ZenSelect
              size="sm"
              :model-value="key.ease ?? 'linear'"
              :options="EASES"
              @update:model-value="run('key.set', { actor: actor.id, t: key.t, ease: $event })"
            />
          </ZenField>
        </div>
        <div class="actions">
          <ZenButton
            size="sm"
            icon="mdi mdi-delete-outline"
            :disabled="actor.keys.length < 2"
            @click="remove('key.remove', { actor: actor.id, t: key.t })"
            >Delete key</ZenButton
          >
        </div>
      </template>
      <div class="actions">
        <ZenButton
          size="sm"
          icon="mdi mdi-account-remove-outline"
          @click="remove('actor.remove', { id: actor.id })"
          >Take out of the scene</ZenButton
        >
      </div>
    </template>

    <!-- a shot (or a key of its camera) -->
    <template v-else-if="(sel?.type === 'shot' || sel?.type === 'camkey') && shot">
      <header>
        <i class="mdi mdi-filmstrip" /><b>Shot {{ shot.name }}</b
        ><span class="kind">{{ (shot.end - shot.start).toFixed(2) }}s</span>
      </header>
      <ZenField label="Name" stack
        ><ZenInput sm :model-value="shot.name" @change="renameShot($event)"
      /></ZenField>
      <div class="row2">
        <ZenField label="Starts" stack>
          <ZenNumber
            size="sm"
            :model-value="shot.start"
            :min="0"
            :step="0.1"
            :precision="2"
            @update:model-value="run('shot.update', { name: shot.name, start: $event })"
          />
        </ZenField>
        <ZenField label="Ends" stack>
          <ZenNumber
            size="sm"
            :model-value="shot.end"
            :min="shot.start + 0.1"
            :step="0.1"
            :precision="2"
            @update:model-value="run('shot.update', { name: shot.name, end: $event })"
          />
        </ZenField>
      </div>
      <h4>Camera keys</h4>
      <div class="keys">
        <button
          v-for="k in shotKeys"
          :key="k.t"
          type="button"
          class="krow"
          :class="{ on: sel.type === 'camkey' && near(sel.t, k.t) }"
          @click="(emit('select', { type: 'camkey', id: shot.name, t: k.t }), emit('seek', k.t))"
        >
          <b>{{ k.t.toFixed(2) }}s</b>
          <span class="ellipsis">{{ describeRef(k.at) }} → {{ describeRef(k.look) }}</span>
          <span class="tag">{{ Math.round(k.lens ?? 35) }}mm</span>
        </button>
      </div>
      <ZenButton size="sm" icon="mdi mdi-plus" @click="camKeyHere"
        >Camera key at {{ time.toFixed(2) }}s</ZenButton
      >
      <template v-if="sel.type === 'camkey' && camkey">
        <h4>Camera at {{ camkey.t.toFixed(2) }}s</h4>
        <ZenField label="Time" stack>
          <ZenNumber
            size="sm"
            :model-value="camkey.t"
            :step="0.1"
            :precision="2"
            @update:model-value="moveCamKey($event)"
          />
        </ZenField>
        <ZenField label="From" stack hint="A point, a mark, or a set camera's name.">
          <GbRef
            :model-value="camkey.at"
            :options="camOptions"
            @update:model-value="
              $event && run('camkey.set', { shot: shot.name, t: camkey.t, at: $event })
            "
          />
        </ZenField>
        <ZenField label="Looks at" stack hint="A point, a mark, or @someone (it follows them).">
          <GbRef
            :model-value="camkey.look"
            :options="lookOptions"
            @update:model-value="run('camkey.set', { shot: shot.name, t: camkey.t, look: $event })"
          />
        </ZenField>
        <div class="row2">
          <ZenField label="Lens (mm)" stack>
            <ZenNumber
              size="sm"
              :model-value="camkey.lens ?? 35"
              :min="8"
              :max="400"
              :step="1"
              :precision="0"
              @update:model-value="
                run('camkey.set', { shot: shot.name, t: camkey.t, lens: $event })
              "
            />
          </ZenField>
          <ZenField label="Move" stack>
            <ZenSelect
              size="sm"
              :model-value="camkey.ease ?? 'smooth'"
              :options="EASES"
              @update:model-value="
                run('camkey.set', { shot: shot.name, t: camkey.t, ease: $event })
              "
            />
          </ZenField>
        </div>
        <div class="actions">
          <ZenButton
            size="sm"
            icon="mdi mdi-delete-outline"
            :disabled="shot.camera.length < 2"
            @click="remove('camkey.remove', { shot: shot.name, t: camkey.t })"
            >Delete key</ZenButton
          >
        </div>
      </template>
      <div class="actions">
        <ZenButton
          size="sm"
          icon="mdi mdi-delete-outline"
          :disabled="doc.scene.shots.length < 2"
          @click="remove('shot.remove', { name: shot.name })"
          >Delete shot</ZenButton
        >
      </div>
    </template>

    <!-- nothing selected: the scene and its set -->
    <template v-else>
      <header>
        <i class="mdi mdi-movie-open-outline" /><b>{{
          doc.scene.name || session.state.sceneName
        }}</b
        ><span class="kind">scene</span>
      </header>
      <ZenField label="Name" stack
        ><ZenInput
          sm
          :model-value="doc.scene.name ?? ''"
          @change="run('scene.update', { name: $event })"
      /></ZenField>
      <div class="row2">
        <ZenField label="Frame rate" stack>
          <ZenNumber
            size="sm"
            :model-value="doc.scene.fps ?? 24"
            :min="1"
            :max="120"
            :step="1"
            :precision="0"
            @update:model-value="run('scene.update', { fps: $event })"
          />
        </ZenField>
        <ZenField label="Set" stack
          ><span class="soft">{{ session.state.setName || "—" }}</span></ZenField
        >
      </div>
      <ZenField label="Notes" stack>
        <ZenInput
          type="textarea"
          :rows="3"
          :model-value="doc.scene.notes ?? ''"
          placeholder="What happens, for whoever blocks it."
          @change="run('scene.update', { notes: $event })"
        />
      </ZenField>
      <h4>Set: {{ doc.set.name }}</h4>
      <ZenField
        label="Notes"
        stack
        hint="Its layout in words: which way is the street, where the kitchen is…"
      >
        <ZenInput
          type="textarea"
          :rows="3"
          :model-value="doc.set.notes ?? ''"
          @change="run('set.update', { notes: $event })"
        />
      </ZenField>
      <p class="soft small">
        Click something in the view or the list to edit it. W / E / R: move, turn, resize; F: frame it.
      </p>
    </template>
  </div>
</template>

<script setup lang="ts">
// The Grey Box Studio inspector: the exact values of what's selected, each change an action.
import { computed } from "vue";
import { ZenButton, ZenField, ZenInput, ZenNumber, ZenSelect, ZenSlider } from "@nynxz/zenkit-ui";
import { Evaluator, describeRef, member as memberOf, type KeyData, type Ref } from "@/lib/greybox";
import type { GreyBoxSession } from "@/lib/greyboxDoc";
import type { Selection } from "./GbViewport.vue";
import GbRef from "./GbRef.vue";
import GbVec from "./GbVec.vue";

const props = defineProps<{ session: GreyBoxSession; sel: Selection | null; time: number }>();
const emit = defineEmits<{ select: [Selection | null]; seek: [number] }>();
const doc = computed(() => props.session.doc);
const run = (name: string, args: Record<string, unknown>) => props.session.run(name, args);
const near = (a: number, b: number) => Math.abs(a - b) < 1e-3;
const POSES = [
  { value: "", label: "As before" },
  { value: "stand", label: "Stand" },
  { value: "sit", label: "Sit" },
];
const EASES = [
  { value: "linear", label: "Steady" },
  { value: "smooth", label: "Ease in & out" },
  { value: "in", label: "Speed up" },
  { value: "out", label: "Slow down" },
];

const shape = computed(() =>
  props.sel?.type === "shape"
    ? doc.value.set.shapes.find((s) => s.id === props.sel!.id)
    : undefined,
);
const mark = computed(() =>
  props.sel?.type === "mark" ? doc.value.set.marks[props.sel.id] : undefined,
);
const setcam = computed(() =>
  props.sel?.type === "setcam" ? doc.value.set.cameras[props.sel.id] : undefined,
);
const actor = computed(() =>
  props.sel?.type === "actor" || props.sel?.type === "key"
    ? doc.value.scene.actors.find((a) => a.id === props.sel!.id)
    : undefined,
);
const member = computed(() => memberOf(doc.value.cast, actor.value?.id ?? ""));
const sortedKeys = computed(() => [...(actor.value?.keys ?? [])].sort((a, b) => a.t - b.t));
const key = computed<KeyData | undefined>(() =>
  props.sel?.type === "key"
    ? actor.value?.keys.find((k) => near(k.t, (props.sel as { t: number }).t))
    : undefined,
);
const shot = computed(() =>
  props.sel?.type === "shot" || props.sel?.type === "camkey"
    ? doc.value.scene.shots.find((s) => s.name === props.sel!.id)
    : undefined,
);
const shotKeys = computed(() => [...(shot.value?.camera ?? [])].sort((a, b) => a.t - b.t));
const camkey = computed<KeyData | undefined>(() =>
  props.sel?.type === "camkey"
    ? shot.value?.camera.find((k) => near(k.t, (props.sel as { t: number }).t))
    : undefined,
);

const marks = computed(() => Object.keys(doc.value.set.marks));
const actors = computed(() => doc.value.scene.actors.map((a) => a.id));
const placeOptions = computed(() => [...marks.value, ...actors.value]);
const lookOptions = computed(() => [...actors.value, ...marks.value]);
const camOptions = computed(() => [...Object.keys(doc.value.set.cameras), ...marks.value]);

function up(patch: Record<string, unknown>) {
  run("shape.update", { id: shape.value!.id, ...patch });
}
function rename(v: unknown) {
  const id = shape.value!.id;
  if (run("shape.update", { id, rename: String(v) })) {
    const next = doc.value.set.shapes.find((s) => s.id === String(v).trim());
    if (next) emit("select", { type: "shape", id: next.id! });
  }
}
function renameMark(v: unknown) {
  const from = (props.sel as { id: string }).id;
  if (run("mark.rename", { name: from, to: String(v) }))
    emit("select", { type: "mark", id: String(v).trim() });
}
function renameShot(v: unknown) {
  const from = shot.value!.name;
  if (run("shot.update", { name: from, rename: String(v) })) {
    const s = doc.value.scene.shots.find((x) => x.name === String(v).trim());
    if (s) emit("select", { type: "shot", id: s.name });
  }
}
function remove(name: string, args: Record<string, unknown>) {
  if (run(name, args)) emit("select", null);
}
function setFace(v: Ref | null) {
  const k = key.value!;
  const n = typeof v === "string" ? Number(v) : NaN;
  run("key.set", {
    actor: actor.value!.id,
    t: k.t,
    face: v === null ? null : Number.isFinite(n) ? n : v,
  });
}
function moveKey(to: number) {
  const k = key.value!;
  if (run("key.move", { actor: actor.value!.id, t: k.t, to }))
    emit("select", { type: "key", id: actor.value!.id, t: to });
}
function moveCamKey(to: number) {
  const k = camkey.value!;
  if (run("camkey.move", { shot: shot.value!.name, t: k.t, to }))
    emit("select", { type: "camkey", id: shot.value!.name, t: to });
}
/** A key where the character is now — the start of a move from here. */
function keyHere() {
  const a = actor.value!;
  const ev = new Evaluator(doc.value.scene, doc.value.set, doc.value.cast);
  const now = ev.actor(a.id, props.time);
  if (
    run("key.set", { actor: a.id, t: props.time, at: now ? [now.at[0], 0, now.at[2]] : [0, 0, 0] })
  )
    emit("select", { type: "key", id: a.id, t: Math.round(props.time * 1000) / 1000 });
}
/** A camera key where the shot's camera is now. */
function camKeyHere() {
  const s = shot.value!;
  const ev = new Evaluator(doc.value.scene, doc.value.set, doc.value.cast);
  const c = ev.camera(s, props.time);
  if (
    run("camkey.set", {
      shot: s.name,
      t: props.time,
      at: c.at,
      look: c.look,
      lens: Math.round(c.lens),
    })
  )
    emit("select", { type: "camkey", id: s.name, t: Math.round(props.time * 1000) / 1000 });
}
</script>

<style scoped>
.insp {
  display: flex;
  flex-direction: column;
  gap: 10px;
  box-sizing: border-box;
  height: 100%;
  padding: 10px;
  overflow-y: auto;
  color: var(--h3-text, #e5e5ea);
  font-size: 12px;
}
header {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}
header b {
  overflow: hidden;
  font-size: 14px;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.kind {
  margin-left: auto;
  color: var(--h3-muted, #9aa0aa);
  font-size: 11px;
}
h4 {
  margin: 6px 0 0;
  color: var(--h3-muted, #9aa0aa);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.row2,
.row3 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}
.row3 {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.soft {
  color: var(--h3-muted, #9aa0aa);
}
.small {
  margin: 0;
  font-size: 11px;
}
.keys {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.krow {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 5px 7px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: var(--h3-field, #15151a);
  color: var(--h3-text, #e5e5ea);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.krow.on {
  border-color: var(--zen-accent, #6366f1);
}
.ellipsis {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.tag {
  color: var(--h3-muted, #9aa0aa);
  font-size: 10.5px;
}
</style>
