<template>
  <div ref="root" class="outl zen-scroll">
    <template v-if="editing">
      <div class="banner">
        <i class="mdi mdi-package-variant-closed" />
        <span class="name"
          >Editing <b>{{ doc.focus }}</b></span
        >
        <ZenButton size="sm" variant="primary" @click="done">Done</ZenButton>
      </div>
      <section>
        <div class="head">
          <h4>Shapes</h4>
          <ZenPopover placement="bottom-end">
            <template #trigger="{ toggle }">
              <ZenIconButton
                icon="mdi mdi-shape-plus-outline"
                size="sm"
                title="Add a shape to the prop"
                @click="toggle"
              />
            </template>
            <div class="pop">
              <button
                v-for="k in KINDS"
                :key="k.label"
                type="button"
                class="row"
                @click="addShape(k.kind, k.args)"
              >
                <i class="mdi" :class="k.icon" /><span class="name">{{ k.label }}</span>
              </button>
            </div>
          </ZenPopover>
        </div>
        <button
          v-for="s in shapes"
          :key="s.id"
          type="button"
          class="row"
          :class="{ on: isOn('shape', s.id ?? '') }"
          @click="pick({ type: 'shape', id: s.id ?? '' })"
        >
          <i class="mdi" :class="iconOf(s)" />
          <span class="name">{{ s.id }}</span>
        </button>
      </section>
      <p class="soft">
        The prop's origin is the spot on the floor it's placed at; +z is its front. Darker shapes
        read as glass or openings.
      </p>
    </template>
    <template v-else>
      <section>
        <div class="head">
          <h4>Shots</h4>
          <ZenIconButton
            icon="mdi mdi-plus"
            size="sm"
            title="Add a shot after the last one"
            @click="addShot"
          />
        </div>
        <button
          v-for="s in doc.scene.shots"
          :key="s.name"
          type="button"
          class="row"
          :class="{
            on: isOn('shot', s.name) || (sel?.type === 'camkey' && sel.id === s.name),
            current: s.name === shot,
          }"
          @click="pick({ type: 'shot', id: s.name }, s.start)"
        >
          <i class="mdi mdi-filmstrip" />
          <span class="name">{{ s.name }}</span>
          <span class="meta">{{ s.start.toFixed(1) }}–{{ s.end.toFixed(1) }}s</span>
        </button>
      </section>

      <section>
        <div class="head">
          <h4>Characters</h4>
          <ZenPopover placement="bottom-end">
            <template #trigger="{ toggle }">
              <ZenIconButton
                icon="mdi mdi-account-plus-outline"
                size="sm"
                title="Put a character in the scene"
                @click="toggle"
              />
            </template>
            <div class="pop">
              <button v-for="c in castOut" :key="c" type="button" class="row" @click="addActor(c)">
                <i class="mdi mdi-account-outline" /><span class="name">{{ c }}</span>
              </button>
              <form class="new" @submit.prevent="addActor(newActor)">
                <input v-model="newActor" placeholder="@name" spellcheck="false" />
                <ZenButton size="sm" :disabled="!newActor.trim()" @click="addActor(newActor)"
                  >Add</ZenButton
                >
              </form>
            </div>
          </ZenPopover>
        </div>
        <p v-if="!doc.scene.actors.length" class="soft">No one yet.</p>
        <button
          v-for="a in doc.scene.actors"
          :key="a.id"
          type="button"
          class="row"
          :class="{ on: sel && (sel.type === 'actor' || sel.type === 'key') && sel.id === a.id }"
          @click="pick({ type: 'actor', id: a.id })"
        >
          <i class="mdi mdi-account-outline" />
          <span class="name">{{ a.id }}</span>
          <span class="meta">{{ a.keys.length }} key{{ a.keys.length === 1 ? "" : "s" }}</span>
        </button>
      </section>

      <section>
        <div class="head">
          <button
            type="button"
            class="fold"
            :title="shapesOpen ? 'Hide the shapes' : 'Show the shapes'"
            @click="shapesOpen = !shapesOpen"
          >
            <i class="mdi" :class="shapesOpen ? 'mdi-chevron-down' : 'mdi-chevron-right'" />
            <h4>Set · {{ doc.set.name }}</h4>
            <span class="meta">{{ doc.set.shapes.length }}</span>
          </button>
          <ZenPopover placement="bottom-end">
            <template #trigger="{ toggle }">
              <ZenIconButton
                icon="mdi mdi-shape-plus-outline"
                size="sm"
                title="Add a shape"
                @click="toggle"
              />
            </template>
            <div class="pop">
              <button
                v-for="k in KINDS"
                :key="k.label"
                type="button"
                class="row"
                @click="addShape(k.kind, k.args)"
              >
                <i class="mdi" :class="k.icon" /><span class="name">{{ k.label }}</span>
              </button>
            </div>
          </ZenPopover>
        </div>
        <template v-if="shapesOpen">
          <button
            v-for="s in doc.set.shapes"
            :key="s.id"
            type="button"
            class="row"
            :class="{ on: isOn('shape', s.id ?? '') }"
            @click="pick({ type: 'shape', id: s.id ?? '' })"
          >
            <i class="mdi" :class="iconOf(s)" />
            <span class="name">{{ s.id }}</span>
            <span v-if="s.type === 'prop'" class="meta">{{ s.prop }}</span>
          </button>
        </template>
      </section>

      <section>
        <div class="head">
          <h4>Props</h4>
          <ZenPopover placement="bottom-end">
            <template #trigger="{ toggle }">
              <ZenIconButton
                icon="mdi mdi-package-variant-plus"
                size="sm"
                title="A new prop: an object built once from shapes, placed as often as you like"
                @click="toggle"
              />
            </template>
            <form class="pop new" @submit.prevent="newProp">
              <input v-model="propName" placeholder="truck" spellcheck="false" />
              <ZenButton size="sm" :disabled="!propName.trim()" @click="newProp"
                >New prop</ZenButton
              >
            </form>
          </ZenPopover>
        </div>
        <p v-if="!propNames.length" class="soft">
          Objects built once from shapes and placed as often as you like: a truck, a table.
        </p>
        <div v-for="name in propNames" :key="name" class="row prop">
          <i class="mdi mdi-package-variant-closed" />
          <span class="name">{{ name }}</span>
          <span class="meta">{{ placedCount(name) ? `${placedCount(name)}×` : "" }}</span>
          <ZenIconButton
            icon="mdi mdi-plus"
            size="sm"
            :title="`Place ${name} in the set`"
            @click="placeProp(name)"
          />
          <ZenIconButton
            icon="mdi mdi-pencil-outline"
            size="sm"
            :title="`Edit ${name}: every place it's used follows`"
            @click="editProp(name)"
          />
        </div>
      </section>

      <section>
        <div class="head">
          <h4>Marks</h4>
          <ZenIconButton
            icon="mdi mdi-map-marker-plus-outline"
            size="sm"
            title="Add a mark at the middle of the set"
            @click="addMark"
          />
        </div>
        <p v-if="!Object.keys(doc.set.marks).length" class="soft">
          Named spots where people stand, sit or come in.
        </p>
        <button
          v-for="(p, name) in doc.set.marks"
          :key="name"
          type="button"
          class="row"
          :class="{ on: isOn('mark', String(name)) }"
          @click="pick({ type: 'mark', id: String(name) })"
        >
          <i class="mdi mdi-map-marker-outline" />
          <span class="name">{{ name }}</span>
        </button>
      </section>

      <section>
        <div class="head">
          <h4>Set cameras</h4>
          <ZenIconButton
            icon="mdi mdi-camera-plus-outline"
            size="sm"
            title="Save the current shot camera as a set camera"
            @click="emit('saveCamera')"
          />
        </div>
        <button
          v-for="(c, name) in doc.set.cameras"
          :key="name"
          type="button"
          class="row"
          :class="{ on: isOn('setcam', String(name)) }"
          @click="pick({ type: 'setcam', id: String(name) })"
        >
          <i class="mdi mdi-cctv" />
          <span class="name">{{ name }}</span>
          <span class="meta">{{ Math.round(c.lens ?? 35) }}mm</span>
        </button>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
// The Grey Box Studio outliner: the scene's shots and characters, and the set's shapes, marks and
// cameras — click to select, + to add.
import { computed, ref, watch } from "vue";
import { ZenButton, ZenIconButton, ZenPopover } from "@nynxz/zenkit-ui";
import { isRod, type ShapeData } from "@/lib/greybox";
import { shapesOf } from "@/lib/greyboxActions";
import type { GreyBoxSession } from "@/lib/greyboxDoc";
import type { Selection } from "./GbViewport.vue";

const props = defineProps<{
  session: GreyBoxSession;
  sel: Selection | null;
  shot: string;
  time: number;
}>();
const emit = defineEmits<{ select: [Selection | null]; seek: [number]; saveCamera: [] }>();
const doc = computed(() => props.session.doc);
const KINDS: { kind: string; label: string; icon: string; args?: Record<string, unknown> }[] = [
  { kind: "box", label: "Box", icon: "mdi mdi-cube-outline" },
  { kind: "cylinder", label: "Cylinder", icon: "mdi mdi-cylinder" },
  {
    kind: "cylinder",
    label: "Lying cylinder (wheel, pipe)",
    icon: "mdi mdi-pipe",
    args: { a: [-0.5, 0.3, 0], b: [0.5, 0.3, 0] },
  },
  { kind: "sphere", label: "Sphere", icon: "mdi mdi-circle-outline" },
  { kind: "capsule", label: "Capsule", icon: "mdi mdi-pill" },
];
const iconOf = (s: ShapeData) =>
  s.type === "prop"
    ? "mdi mdi-package-variant-closed"
    : isRod(s)
      ? "mdi mdi-pipe"
      : KINDS.find((k) => k.kind === (s.type ?? "box"))?.icon;
const editing = computed(() => !!doc.value.focus && !!doc.value.props[doc.value.focus]);
const root = ref<HTMLElement | null>(null);
// Opening or closing a prop swaps the whole list: start it from the top, where its banner is.
watch(editing, () => root.value?.scrollTo({ top: 0 }));
const shapes = computed(() => shapesOf(doc.value));
// A long list of shapes starts folded: marks, cameras and props are what's usually wanted.
const shapesOpen = ref(doc.value.set.shapes.length <= 12);
const propNames = computed(() => Object.keys(doc.value.props).sort());
const placedCount = (name: string) =>
  doc.value.set.shapes.filter((s) => s.type === "prop" && s.prop === name).length;
const isOn = (type: string, id: string) => props.sel?.type === type && props.sel.id === id;
function pick(s: Selection, seek?: number) {
  emit("select", s);
  if (seek !== undefined) emit("seek", seek);
}

const castOut = computed(() =>
  Object.keys(doc.value.cast).filter((c) => !doc.value.scene.actors.some((a) => a.id === c)),
);
const newActor = ref("");
function addActor(id: string) {
  const name = id.trim();
  if (!name) return;
  const mark = Object.keys(doc.value.set.marks)[0];
  const mention = name.startsWith("@") ? name : `@${name}`;
  if (props.session.run("actor.add", { id: mention, at: mark ?? [0, 0, 0] })) {
    newActor.value = "";
    emit("select", { type: "actor", id: mention });
  }
}
function addShape(kind: string, args: Record<string, unknown> = {}) {
  const before = new Set(shapes.value.map((s) => s.id));
  if (props.session.run("shape.add", { kind, ...args })) {
    const added = shapes.value.find((s) => !before.has(s.id));
    if (added) emit("select", { type: "shape", id: added.id! });
  }
}
const propName = ref("");
function newProp() {
  const name = propName.value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-");
  if (!name || !props.session.run("prop.new", { name })) return;
  propName.value = "";
  emit("select", { type: "shape", id: "body" });
}
function placeProp(name: string) {
  addShape("prop", { prop: name });
  shapesOpen.value = true;
}
function editProp(name: string) {
  if (props.session.run("prop.edit", { name })) emit("select", null);
}
function done() {
  if (props.session.run("prop.done")) emit("select", null);
}
function addMark() {
  const taken = new Set(Object.keys(doc.value.set.marks));
  let name = "mark";
  for (let n = 2; taken.has(name); n++) name = `mark-${n}`;
  if (props.session.run("mark.set", { name, at: [0, 0, 0] }))
    emit("select", { type: "mark", id: name });
}
function addShot() {
  const before = new Set(doc.value.scene.shots.map((s) => s.name));
  if (props.session.run("shot.add", {})) {
    const added = doc.value.scene.shots.find((s) => !before.has(s.name));
    if (added) pick({ type: "shot", id: added.name }, added.start);
  }
}
</script>

<style scoped>
.outl {
  display: flex;
  flex-direction: column;
  gap: 12px;
  box-sizing: border-box;
  height: 100%;
  padding: 8px;
  overflow-y: auto;
  color: var(--h3-text, #e5e5ea);
  font-size: 12px;
}
section {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 0 2px 3px;
}
h4 {
  margin: 0;
  overflow: hidden;
  color: var(--h3-muted, #9aa0aa);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.row {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  height: 26px;
  padding: 0 7px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--h3-text, #e5e5ea);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.row:hover {
  background: color-mix(in srgb, var(--h3-text, #e5e5ea) 6%, transparent);
}
.row.on {
  background: color-mix(in srgb, var(--zen-accent, #6366f1) 22%, transparent);
}
.row.current .name {
  font-weight: 700;
}
.name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.meta {
  color: var(--h3-muted, #9aa0aa);
  font-size: 10.5px;
}
.soft {
  margin: 0 6px;
  color: var(--h3-muted, #9aa0aa);
  font-size: 11px;
}
.pop {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 180px;
  padding: 6px;
  color: var(--h3-text, #e5e5ea);
  font-size: 12px;
}
.banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--zen-accent, #6366f1) 18%, transparent);
}
.fold {
  display: flex;
  flex: 1;
  align-items: center;
  gap: 4px;
  min-width: 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--h3-muted, #9aa0aa);
  font: inherit;
  cursor: pointer;
}
.row.prop {
  cursor: default;
}
.new {
  display: flex;
  gap: 4px;
  margin-top: 4px;
}
.new input {
  flex: 1;
  min-width: 0;
  height: 24px;
  padding: 0 6px;
  border: 1px solid var(--h3-line, #34343c);
  border-radius: 5px;
  background: var(--h3-field, #15151a);
  color: inherit;
  font: inherit;
}
</style>
