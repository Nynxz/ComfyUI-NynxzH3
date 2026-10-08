<template>
  <div
    ref="host"
    class="gbv"
    tabindex="-1"
    data-capture-wheel="true"
    @pointerdown.stop="onDown"
    @pointermove="onMove"
    @pointerup="onUp"
    @wheel.stop
    @contextmenu.prevent.stop
    @pointerenter="claimWheel"
    @pointerleave="releaseWheel"
  >
    <canvas ref="canvas" />
    <div ref="labels" class="labels" />
    <div class="tools" @pointerdown.stop>
      <ZenToggleGroup v-model="gizmoMode" size="sm" :options="GIZMOS" :disabled="!selection" />
      <ZenIconButton
        :icon="showLabels ? 'mdi mdi-label-outline' : 'mdi mdi-label-off-outline'"
        size="sm"
        :title="showLabels ? 'Hide names' : 'Show names'"
        @click="showLabels = !showLabels"
      />
      <ZenIconButton
        v-if="mode === 'free'"
        icon="mdi mdi-fit-to-screen-outline"
        size="sm"
        title="Frame the set (F frames what's selected)"
        @click="frameAll"
      />
      <span v-if="mode === 'shot'" class="lens">{{ lensLabel }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
// The Grey Box Studio's 3D view (three.js): the set, the characters where they are at `time`, their
// paths and keys, the marks, and every shot's camera. Three ways to look: orbiting freely, through
// a shot's camera (framed to the render's shape), or from above. Click to select; drag the gizmo to
// move, turn or resize — each drag one undoable action.
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, toRaw, watch } from "vue";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { TransformControls } from "three/examples/jsm/controls/TransformControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { ZenIconButton, ZenToggleGroup } from "@nynxz/zenkit-ui";
import {
  Evaluator,
  expandShapes,
  figure,
  fovOf,
  heldTime,
  poseHeight,
  isRod,
  isVec,
  type ShapeData,
  type Vec,
} from "@/lib/greybox";
import { shapesOf } from "@/lib/greyboxActions";
import type { GreyBoxSession } from "@/lib/greyboxDoc";

export type Selection =
  | { type: "shape"; id: string }
  | { type: "mark"; id: string }
  | { type: "setcam"; id: string }
  | { type: "actor"; id: string }
  | { type: "key"; id: string; t: number }
  | { type: "camkey"; id: string; t: number }
  | { type: "shot"; id: string };

const props = defineProps<{
  session: GreyBoxSession;
  time: number;
  mode: "free" | "shot" | "plan";
  shot: string;
  aspect: number;
}>();
const selection = defineModel<Selection | null>("selection", { default: null });

const GIZMOS = [
  { value: "translate", label: "", icon: "mdi mdi-cursor-move", title: "Move (W)" },
  { value: "rotate", label: "", icon: "mdi mdi-rotate-3d-variant", title: "Turn (E)" },
  { value: "scale", label: "", icon: "mdi mdi-resize", title: "Resize (R)" },
];
const gizmoMode = ref<"translate" | "rotate" | "scale">("translate");
const showLabels = ref(true);

const host = ref<HTMLElement | null>(null);
const canvas = ref<HTMLCanvasElement | null>(null);
const labels = ref<HTMLElement | null>(null);
// Over the raw objects: playback evaluates every actor key each frame, and reading them through
// Vue's proxies cost more than the evaluation. Edits change these objects in place, so the
// evaluator still sees them; a replaced scene, set or cast makes a new one.
const evaluator = computed(
  () =>
    new Evaluator(
      toRaw(props.session.doc.scene),
      toRaw(props.session.doc.set),
      toRaw(props.session.doc.cast),
    ),
);

// --- three -----------------------------------------------------------------------------------------
let renderer: THREE.WebGLRenderer | null = null;
let css: CSS2DRenderer | null = null;
const world = new THREE.Scene();
world.background = new THREE.Color(0x232328);
const persp = new THREE.PerspectiveCamera(50, 1, 0.05, 500);
persp.position.set(6, 6, 9);
const ortho = new THREE.OrthographicCamera(-10, 10, 10, -10, 0.1, 200);
const shotCam = new THREE.PerspectiveCamera(40, 1, 0.05, 500);
/** Marks, paths, cameras, the grid: everything that isn't in the picture is drawn on this layer,
 *  which the shot camera doesn't see — so the shot view is what the render will be. */
const AIDS = 1;
persp.layers.enableAll();
ortho.layers.enableAll();
let orbit: OrbitControls | null = null;
let gizmo: TransformControls | null = null;
const handle = new THREE.Object3D();
// Yaw first, so a pure turn past ±90° reads back as itself rather than mirrored through x = 180°.
handle.rotation.order = "YXZ";
world.add(handle);

const hemi = new THREE.HemisphereLight(0xffffff, 0x404048, 1.1);
const sun = new THREE.DirectionalLight(0xffffff, 1.9);
sun.position.set(0.45, 0.85, 0.3).multiplyScalar(30);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left: -20, right: 20, top: 20, bottom: -20, near: 1, far: 80 });
world.add(hemi, sun, sun.target);
const grid = new THREE.GridHelper(40, 40, 0x3a3a44, 0x2c2c34);
grid.position.y = -0.001;
grid.layers.set(AIDS);
world.add(grid);

/** What clicking each object selects. */
const picks = new Map<THREE.Object3D, Selection>();
const setGroup = new THREE.Group();
const pathGroup = new THREE.Group();
const liveGroup = new THREE.Group();
world.add(setGroup, pathGroup, liveGroup);

const ACCENT = new THREE.Color(0x7c83ff);
const materials = new Map<string, THREE.MeshStandardMaterial>();
function material(tone: number, selected: boolean) {
  const key = `${tone.toFixed(3)}|${selected}`;
  let m = materials.get(key);
  if (!m) {
    const c = new THREE.Color().setScalar(tone).convertSRGBToLinear();
    m = new THREE.MeshStandardMaterial({ color: c, roughness: 0.92, metalness: 0 });
    if (selected) {
      m.emissive = ACCENT.clone();
      m.emissiveIntensity = 0.35;
    }
    materials.set(key, m);
  }
  return m;
}

/** Geometry shared by every shape of the same kind and size: playback rebuilds the actors every
 *  frame, and without this each rebuild made (and uploaded) new vertex buffers. */
const geometries = new Map<string, THREE.BufferGeometry>();
function shared(key: string, make: () => THREE.BufferGeometry): THREE.BufferGeometry {
  let g = geometries.get(key);
  if (!g) {
    g = make();
    g.userData.shared = true;
    geometries.set(key, g);
  }
  return g;
}
const mm = (v: number) => Math.round(v * 1e4) / 1e4;

function shapeMesh(s: ShapeData, selected: boolean): THREE.Mesh {
  const tone = s.tone ?? 0.7;
  let geo: THREE.BufferGeometry;
  const mesh = new THREE.Mesh();
  if (isRod(s)) {
    const a = new THREE.Vector3(...(s.a ?? [0, 0, 0]));
    const b = new THREE.Vector3(...(s.b ?? [0, 1, 0]));
    const len = Math.max(a.distanceTo(b), 1e-4);
    const r = s.radius ?? 0.5;
    geo = shared(`cyl|${mm(r)}|${mm(len)}`, () => new THREE.CylinderGeometry(r, r, len, 32));
    mesh.position.copy(a.clone().add(b).multiplyScalar(0.5));
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.clone().sub(a).normalize());
  } else if (s.type === "cylinder") {
    const h = s.height ?? 1;
    const r = s.radius ?? 0.5;
    geo = shared(`cyl|${mm(r)}|${mm(h)}`, () => new THREE.CylinderGeometry(r, r, h, 32));
    const at = s.at ?? [0, 0, 0];
    mesh.position.set(at[0], at[1] + h / 2, at[2]);
  } else if (s.type === "sphere") {
    const r = s.radius ?? 0.5;
    geo = shared(`sph|${mm(r)}`, () => new THREE.SphereGeometry(r, 32, 16));
    mesh.position.set(...(s.at ?? [0, 0, 0]));
  } else if (s.type === "capsule") {
    const a = new THREE.Vector3(...(s.a ?? [0, 0, 0]));
    const b = new THREE.Vector3(...(s.b ?? [0, 1, 0]));
    const len = a.distanceTo(b);
    const r = s.radius ?? 0.2;
    geo = shared(`cap|${mm(r)}|${mm(len)}`, () => new THREE.CapsuleGeometry(r, len, 6, 16));
    mesh.position.copy(a.clone().add(b).multiplyScalar(0.5));
    if (len > 1e-6)
      mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.clone().sub(a).normalize());
  } else {
    const [w, h, d] = s.size ?? [1, 1, 1];
    geo = shared(`box|${mm(w)}|${mm(h)}|${mm(d)}`, () => new THREE.BoxGeometry(w, h, d));
    mesh.position.set(...(s.at ?? [0, 0, 0]));
    // As the renderer turns it: its yaw, then its tilt (a lean forward) about its own x.
    mesh.rotation.order = "YXZ";
    mesh.rotation.set(((s.tilt ?? 0) * Math.PI) / 180, ((s.yaw ?? 0) * Math.PI) / 180, 0);
  }
  mesh.geometry = geo;
  mesh.material = material(tone, selected);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  mesh.userData.solid = true;
  return mesh;
}

function clear(g: THREE.Group) {
  for (const o of [...g.children]) {
    g.remove(o);
    o.traverse((x) => {
      picks.delete(x);
      if ((x instanceof THREE.Mesh || x instanceof THREE.Line) && !x.geometry.userData.shared)
        x.geometry.dispose();
      if (x instanceof CSS2DObject) x.element.remove();
    });
  }
}
function label(text: string, at: THREE.Vector3, cls: string, pick?: Selection): CSS2DObject {
  const el = document.createElement("div");
  el.className = `gb-label ${cls}`;
  el.textContent = text;
  if (pick)
    el.addEventListener("pointerdown", (e) => {
      e.stopPropagation();
      selection.value = pick;
    });
  const o = new CSS2DObject(el);
  o.position.copy(at);
  return o;
}

const isSel = (s: Selection) =>
  !!selection.value &&
  selection.value.type === s.type &&
  selection.value.id === s.id &&
  (!("t" in s) || ("t" in selection.value && Math.abs(selection.value.t - s.t) < 1e-3));

// --- building the view -----------------------------------------------------------------------------
/** The view only redraws when something changed: a build, the camera moving, a resize. Drawing
 *  every frame regardless kept the GPU and the main thread busy even with nothing moving. */
let dirty = true;
const invalidate = () => {
  dirty = true;
};
/** Marks, paths, labels and helpers go on the aids layer, which the shot camera doesn't see. Done
 *  once per build, not by walking the whole scene every frame. */
function layer(g: THREE.Group) {
  g.traverse((o) => {
    if (o !== g && !o.userData.solid) o.layers.set(AIDS);
  });
  invalidate();
}
function buildSet() {
  clear(setGroup);
  const { doc } = props.session;
  const set = doc.set;
  const editingProp = !!doc.focus && !!doc.props[doc.focus];
  // Editing a prop shows only the prop, in its own frame.
  pathGroup.visible = liveGroup.visible = !editingProp;
  for (const s of shapesOf(doc)) {
    const pick: Selection = { type: "shape", id: s.id ?? "" };
    // A placed prop is its shapes, picked and highlighted as one.
    for (const part of (s.type ?? "box") === "prop" ? expandShapes([s], doc.props) : [s]) {
      const m = shapeMesh(part, isSel(pick));
      picks.set(m, pick);
      setGroup.add(m);
    }
  }
  if (editingProp) return layer(setGroup);
  for (const [name, p] of Object.entries(set.marks)) {
    const pick: Selection = { type: "mark", id: name };
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.16, 0.22, 32),
      new THREE.MeshBasicMaterial({
        color: isSel(pick) ? ACCENT : 0x9aa0aa,
        side: THREE.DoubleSide,
      }),
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(p[0], p[1] + 0.012, p[2]);
    picks.set(ring, pick);
    setGroup.add(ring);
    if (showLabels.value)
      setGroup.add(
        label(
          name,
          new THREE.Vector3(p[0], p[1] + 0.05, p[2]),
          isSel(pick) ? "mark on" : "mark",
          pick,
        ),
      );
  }
  for (const [name, c] of Object.entries(set.cameras)) {
    const pick: Selection = { type: "setcam", id: name };
    const cone = camMarker(isSel(pick) ? ACCENT : 0x6d6d78);
    cone.position.set(...c.at);
    cone.lookAt(new THREE.Vector3(...evaluator.value.target(c.look, props.time)));
    picks.set(cone.children[0]!, pick);
    setGroup.add(cone);
    // A set camera's name only shows when it's selected: there are often several.
    if (showLabels.value && isSel(pick))
      setGroup.add(
        label(name, new THREE.Vector3(c.at[0], c.at[1] + 0.25, c.at[2]), "setcam", pick),
      );
  }
  layer(setGroup);
}

function camMarker(color: THREE.ColorRepresentation) {
  const g = new THREE.Group();
  const body = new THREE.Mesh(
    new THREE.ConeGeometry(0.16, 0.32, 4),
    new THREE.MeshBasicMaterial({ color, wireframe: false }),
  );
  body.rotation.x = Math.PI / 2;
  body.rotation.y = Math.PI / 4;
  g.add(body);
  return g;
}

/** What changes with the scene but not with time: its own shapes, everyone's path and keys, the
 *  shots' camera paths and keys. */
function buildPaths() {
  clear(pathGroup);
  const ev = evaluator.value;
  const scene = props.session.doc.scene;
  for (const s of scene.shapes ?? []) pathGroup.add(shapeMesh(s, false));
  for (const actor of scene.actors) {
    const keys = [...actor.keys].sort((p, q) => p.t - q.t);
    if (!keys.length) continue;
    const t0 = keys[0]!.t;
    const t1 = Math.max(keys.at(-1)!.t, ev.length);
    const steps = Math.max(2, Math.ceil((t1 - t0) * 12));
    const pts: THREE.Vector3[] = [];
    for (let i = 0; i <= steps; i++) {
      const s = ev.actor(actor.id, t0 + ((t1 - t0) * i) / steps);
      if (s) pts.push(new THREE.Vector3(s.at[0], s.at[1] + 0.03, s.at[2]));
    }
    const sel = selection.value && "id" in selection.value && selection.value.id === actor.id;
    pathGroup.add(
      new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(pts),
        new THREE.LineBasicMaterial({ color: sel ? 0xffb36b : 0xd08a50 }),
      ),
    );
    for (const k of keys) {
      const s = ev.actor(actor.id, k.t);
      if (!s) continue;
      const pick: Selection = { type: "key", id: actor.id, t: k.t };
      const dot = new THREE.Mesh(
        new THREE.SphereGeometry(0.09, 16, 8),
        new THREE.MeshBasicMaterial({ color: isSel(pick) ? ACCENT : 0xffb36b }),
      );
      dot.position.set(s.at[0], s.at[1] + 0.06, s.at[2]);
      picks.set(dot, pick);
      pathGroup.add(dot);
    }
  }
  for (const shot of scene.shots) {
    const active = shot.name === props.shot;
    if (shot.camera.length < 2 && !active) continue;
    const pts: THREE.Vector3[] = [];
    const steps = Math.max(2, Math.ceil((shot.end - shot.start) * 10));
    for (let i = 0; i <= steps; i++)
      pts.push(
        new THREE.Vector3(
          ...ev.camera(shot, shot.start + ((shot.end - shot.start) * i) / steps).at,
        ),
      );
    pathGroup.add(
      new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(pts),
        new THREE.LineDashedMaterial({ color: 0xb4b4c0, dashSize: 0.15, gapSize: 0.1 }),
      ).computeLineDistances(),
    );
    for (const k of shot.camera) {
      const pick: Selection = { type: "camkey", id: shot.name, t: k.t };
      const c = ev.cameraKey(k, k.t);
      const dot = new THREE.Mesh(
        new THREE.BoxGeometry(0.14, 0.14, 0.14),
        new THREE.MeshBasicMaterial({ color: isSel(pick) ? ACCENT : 0xd4d4dc }),
      );
      dot.position.set(...c.at);
      picks.set(dot, pick);
      pathGroup.add(dot);
    }
  }
  layer(pathGroup);
}

/** What moves with time: everyone where they are now, each shot's camera now. Rebuilt every frame
 *  while playing, so it's kept small. */
function buildLive() {
  clear(liveGroup);
  const used = new Set<string>();
  const ev = evaluator.value;
  const t = props.time;
  const scene = props.session.doc.scene;
  for (const a of ev.actors(heldTime(scene, t))) {
    const pick: Selection = { type: "actor", id: a.id };
    const selected =
      isSel(pick) || (selection.value?.type === "key" && selection.value.id === a.id);
    for (const part of figure(a, toRaw(props.session.doc.props))) {
      const m = shapeMesh(part, selected);
      picks.set(m, pick);
      liveGroup.add(m);
    }
    const head = new THREE.Vector3(
      a.at[0],
      a.at[1] + a.member.height * poseHeight(a.pose) + 0.18,
      a.at[2],
    );
    if (showLabels.value) liveLabel(used, `actor:${a.id}`, a.id, head, "actor", pick);
  }
  for (const shot of scene.shots) {
    const active = shot.name === props.shot;
    const cam = ev.camera(shot, Math.min(Math.max(t, shot.start), shot.end));
    const marker = camMarker(active ? 0xffffff : 0x8c8c98);
    marker.position.set(...cam.at);
    marker.lookAt(new THREE.Vector3(...cam.look));
    picks.set(marker.children[0]!, { type: "shot", id: shot.name });
    liveGroup.add(marker);
    if (showLabels.value && active)
      liveLabel(
        used,
        `cam:${shot.name}`,
        `cam ${shot.name}`,
        new THREE.Vector3(cam.at[0], cam.at[1] + 0.3, cam.at[2]),
        "cam on",
        { type: "shot", id: shot.name },
      );
    if (active && props.mode !== "shot") {
      const helperCam = new THREE.PerspectiveCamera(fovOf(cam.lens), props.aspect, 0.2, 2.5);
      helperCam.position.set(...cam.at);
      helperCam.lookAt(new THREE.Vector3(...cam.look));
      helperCam.updateMatrixWorld();
      liveGroup.add(new THREE.CameraHelper(helperCam));
    }
  }
  for (const [key, o] of liveLabels) o.visible = used.has(key);
  layer(liveGroup);
  layer(liveLabelGroup);
  attachGizmo();
}

/** The labels that move with time, kept from frame to frame and moved, rather than new elements
 *  added to the page on every frame of playback. */
const liveLabels = new Map<string, CSS2DObject>();
const liveLabelGroup = new THREE.Group();
world.add(liveLabelGroup);
function liveLabel(
  used: Set<string>,
  key: string,
  text: string,
  at: THREE.Vector3,
  cls: string,
  pick: Selection,
) {
  used.add(key);
  let o = liveLabels.get(key);
  if (!o) {
    o = label(text, at, cls, pick);
    liveLabels.set(key, o);
    liveLabelGroup.add(o);
  }
  o.position.copy(at);
  o.visible = true;
}

// --- the gizmo: what's selected, moved by dragging -------------------------------------------------
let dragging = false;
function selectedPoint(): {
  at: Vec;
  yaw?: number;
  size?: Vec;
  radius?: number;
  scale?: number;
} | null {
  const sel = selection.value;
  if (!sel) return null;
  const { doc } = props.session;
  const ev = evaluator.value;
  if (sel.type === "shape") {
    const s = shapesOf(doc).find((x) => x.id === sel.id);
    if (!s) return null;
    if (s.type === "capsule" || isRod(s)) {
      const a = s.a ?? [0, 0, 0];
      const b = s.b ?? [0, 1, 0];
      return { at: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2], radius: s.radius };
    }
    if (s.type === "prop") return { at: s.at ?? [0, 0, 0], yaw: s.yaw ?? 0, scale: s.scale ?? 1 };
    return { at: s.at ?? [0, 0, 0], yaw: s.yaw ?? 0, size: s.size, radius: s.radius };
  }
  if (sel.type === "mark") return doc.set.marks[sel.id] ? { at: doc.set.marks[sel.id]! } : null;
  if (sel.type === "setcam")
    return doc.set.cameras[sel.id] ? { at: doc.set.cameras[sel.id]!.at } : null;
  if (sel.type === "key") {
    const a = ev.actor(sel.id, sel.t);
    return a ? { at: a.at, yaw: a.yaw } : null;
  }
  if (sel.type === "camkey") {
    const shot = doc.scene.shots.find((s) => s.name === sel.id);
    const k = shot?.camera.find((x) => Math.abs(x.t - sel.t) < 1e-3);
    return k ? { at: ev.cameraKey(k, k.t).at } : null;
  }
  return null;
}
let startSize: Vec | null = null;
let startRadius: number | null = null;
let startScale: number | null = null;
function attachGizmo() {
  if (!gizmo || dragging) return;
  const p = selectedPoint();
  if (!p || props.mode === "shot") {
    gizmo.detach();
    return;
  }
  handle.position.set(...p.at);
  handle.rotation.set(0, ((p.yaw ?? 0) * Math.PI) / 180, 0);
  handle.scale.set(1, 1, 1);
  const sel = selection.value!;
  const flat = sel.type === "mark" || sel.type === "key";
  gizmo.setMode(
    sel.type === "shape"
      ? gizmoMode.value
      : sel.type === "key" && gizmoMode.value === "rotate"
        ? "rotate"
        : "translate",
  );
  gizmo.showY = !flat || gizmo.mode === "rotate";
  gizmo.showX = gizmo.mode !== "rotate";
  gizmo.showZ = gizmo.mode !== "rotate";
  gizmo.attach(handle);
}
function onGizmoChange() {
  if (!dragging) return;
  const sel = selection.value;
  if (!sel) return;
  const s = props.session;
  const pos: Vec = [handle.position.x, handle.position.y, handle.position.z];
  const yaw = (handle.rotation.y * 180) / Math.PI;
  if (sel.type === "shape") {
    const shape = shapesOf(s.doc).find((x) => x.id === sel.id);
    if (!shape) return;
    if (gizmo!.mode === "scale") {
      if (shape.type === "prop" && startScale !== null)
        s.run(
          "shape.update",
          {
            id: sel.id,
            scale: Math.max(
              0.05,
              startScale * Math.max(handle.scale.x, handle.scale.y, handle.scale.z),
            ),
          },
          { settle: false },
        );
      else if (shape.type === "box" && startSize)
        s.run(
          "shape.update",
          {
            id: sel.id,
            size: [
              startSize[0] * handle.scale.x,
              startSize[1] * handle.scale.y,
              startSize[2] * handle.scale.z,
            ].map((v) => Math.max(0.02, v)),
          },
          { settle: false },
        );
      else if (startRadius !== null)
        s.run(
          "shape.update",
          {
            id: sel.id,
            radius: Math.max(0.02, startRadius * Math.max(handle.scale.x, handle.scale.z)),
          },
          { settle: false },
        );
    } else if (gizmo!.mode === "rotate")
      s.run("shape.update", { id: sel.id, yaw }, { settle: false });
    else if (shape.type === "capsule" || isRod(shape)) {
      const a = shape.a ?? [0, 0, 0];
      const b = shape.b ?? [0, 1, 0];
      const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2];
      const d = [pos[0] - mid[0]!, pos[1] - mid[1]!, pos[2] - mid[2]!];
      s.run(
        "shape.update",
        { id: sel.id, a: a.map((v, i) => v + d[i]!), b: b.map((v, i) => v + d[i]!) },
        { settle: false },
      );
    } else s.run("shape.update", { id: sel.id, at: pos }, { settle: false });
  } else if (sel.type === "mark")
    s.run("mark.set", { name: sel.id, at: [pos[0], 0, pos[2]] }, { settle: false });
  else if (sel.type === "setcam") s.run("setcam.set", { name: sel.id, at: pos }, { settle: false });
  else if (sel.type === "key") {
    if (gizmo!.mode === "rotate")
      s.run("key.set", { actor: sel.id, t: sel.t, face: yaw }, { settle: false });
    else s.run("key.set", { actor: sel.id, t: sel.t, at: [pos[0], 0, pos[2]] }, { settle: false });
  } else if (sel.type === "camkey") {
    const shot = s.doc.scene.shots.find((x) => x.name === sel.id);
    const k = shot?.camera.find((x) => Math.abs(x.t - sel.t) < 1e-3);
    // A key that used a set camera's spot keeps where it looked, as its own.
    const look =
      k && typeof k.at === "string" && s.doc.set.cameras[k.at] && k.look === undefined
        ? s.doc.set.cameras[k.at]!.look
        : undefined;
    s.run(
      "camkey.set",
      { shot: sel.id, t: sel.t, at: pos, ...(look ? { look } : {}) },
      { settle: false },
    );
  }
}

// --- views ---------------------------------------------------------------------------------------
const lensLabel = computed(() => {
  const shot = props.session.doc.scene.shots.find((x) => x.name === props.shot);
  if (!shot) return "";
  return `${shot.name} · ${Math.round(evaluator.value.camera(shot, props.time).lens)}mm`;
});
function fitPlan() {
  const box = new THREE.Box3().setFromObject(setGroup);
  if (box.isEmpty()) box.set(new THREE.Vector3(-5, 0, -5), new THREE.Vector3(5, 0, 5));
  const c = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const el = host.value!;
  const aspect = el.clientWidth / Math.max(1, el.clientHeight);
  const half = Math.max(size.x / aspect, size.z) * 0.6 + 0.5;
  Object.assign(ortho, { left: -half * aspect, right: half * aspect, top: half, bottom: -half });
  ortho.position.set(c.x, 60, c.z);
  ortho.up.set(0, 0, -1);
  ortho.lookAt(c.x, 0, c.z);
  ortho.zoom = 1;
  ortho.updateProjectionMatrix();
  if (orbit) {
    orbit.target.set(c.x, 0, c.z);
  }
}
function activeCamera(): THREE.Camera {
  if (props.mode === "plan") return ortho;
  if (props.mode === "shot") return shotCam;
  return persp;
}
function setupControls() {
  orbit?.dispose();
  const cam = props.mode === "plan" ? ortho : persp;
  if (props.mode === "shot" || !canvas.value) {
    orbit = null;
  } else {
    orbit = new OrbitControls(cam as THREE.PerspectiveCamera, canvas.value);
    orbit.enableDamping = true;
    // The middle button pans the graph (ComfyUI takes it before the view sees it); the wheel zooms.
    // The right button is the fly camera (see `startFly`); Shift + left drag pans.
    orbit.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: null, RIGHT: null };
    if (props.mode === "plan") {
      orbit.enableRotate = false;
      fitPlan();
    } else orbit.target.set(0, 0.8, 0);
  }
  if (gizmo) {
    gizmo.camera = cam;
  }
  attachGizmo();
}

// --- loop ----------------------------------------------------------------------------------------
let frame = 0;
let viewW = 1;
let viewH = 1;
let lastCamKey = "";
function size() {
  const el = host.value;
  if (!el || !renderer || !css) return;
  const w = (viewW = el.clientWidth);
  const h = (viewH = el.clientHeight);
  invalidate();
  renderer.setSize(w, h, false);
  css.setSize(w, h);
  persp.aspect = w / Math.max(1, h);
  persp.updateProjectionMatrix();
  ortho.left = ortho.bottom * persp.aspect;
  ortho.right = ortho.top * persp.aspect;
  ortho.updateProjectionMatrix();
}
function draw() {
  frame = requestAnimationFrame(draw);
  if (!renderer || !css || !host.value || document.hidden) return;
  if (fly) {
    stepFly();
    dirty = true;
  } else orbit?.update();
  const cam = activeCamera();
  // Any move of the camera — orbiting, framing, fitting the plan — redraws.
  cam.updateMatrixWorld();
  const camKey = `${cam.matrixWorld.elements.join()}|${cam.projectionMatrix.elements.join()}`;
  if (camKey !== lastCamKey) {
    lastCamKey = camKey;
    dirty = true;
  }
  if (!dirty) return;
  dirty = false;
  const w = viewW;
  const h = viewH;
  if (props.mode === "shot") {
    const shot = props.session.doc.scene.shots.find((x) => x.name === props.shot);
    if (shot) {
      const c = evaluator.value.camera(shot, heldTime(props.session.doc.scene, props.time));
      shotCam.fov = fovOf(c.lens);
      shotCam.aspect = props.aspect;
      shotCam.position.set(...c.at);
      shotCam.lookAt(new THREE.Vector3(...c.look));
      shotCam.updateProjectionMatrix();
    }
    // Framed to the render's shape, with bars around it.
    let vw = w;
    let vh = Math.round(w / props.aspect);
    if (vh > h) {
      vh = h;
      vw = Math.round(h * props.aspect);
    }
    renderer.setScissorTest(false);
    renderer.setViewport(0, 0, w, h);
    renderer.setClearColor(0x0b0b0e);
    renderer.clear();
    renderer.setScissorTest(true);
    renderer.setScissor((w - vw) / 2, (h - vh) / 2, vw, vh);
    renderer.setViewport((w - vw) / 2, (h - vh) / 2, vw, vh);
    labels.value!.style.visibility = "hidden";
  } else {
    renderer.setScissorTest(false);
    renderer.setViewport(0, 0, w, h);
    labels.value!.style.visibility = "";
  }
  renderer.render(world, cam);
  if (props.mode !== "shot") css.render(world, cam);
}

onMounted(() => {
  renderer = new THREE.WebGLRenderer({ canvas: canvas.value!, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  css = new CSS2DRenderer({ element: labels.value! });
  gizmo = new TransformControls(persp, canvas.value!);
  gizmo.setSize(0.8);
  world.add(gizmo.getHelper());
  gizmo.addEventListener("dragging-changed", (e) => {
    dragging = !!e.value;
    if (orbit) orbit.enabled = !dragging;
    if (dragging) {
      props.session.beginChange();
      const p = selectedPoint();
      startSize = p?.size ?? null;
      startRadius = p?.radius ?? null;
      startScale = p?.scale ?? null;
    } else {
      props.session.endChange();
      attachGizmo();
    }
  });
  gizmo.addEventListener("objectChange", onGizmoChange);
  gizmo.addEventListener("change", invalidate);
  size();
  new ResizeObserver(size).observe(host.value!);
  setupControls();
  buildSet();
  buildPaths();
  buildLive();
  frameAll();
  draw();
  window.addEventListener("keydown", onKey);
  window.addEventListener("keydown", flyKey, true);
  window.addEventListener("keyup", flyKey, true);
  window.addEventListener("blur", endFly);
});
onBeforeUnmount(() => {
  cancelAnimationFrame(frame);
  window.removeEventListener("keydown", onKey);
  window.removeEventListener("keydown", flyKey, true);
  window.removeEventListener("keyup", flyKey, true);
  window.removeEventListener("blur", endFly);
  orbit?.dispose();
  gizmo?.dispose();
  clear(setGroup);
  clear(pathGroup);
  clear(liveGroup);
  renderer?.dispose();
});

// Three rebuilds, from most to least work: the set when it changes; paths and keys when the scene
// does; and what moves with time (cheap) every frame of playback.
const docKey = computed(
  () => JSON.stringify(props.session.doc.scene) + JSON.stringify(props.session.doc.cast),
);
watch(
  () =>
    JSON.stringify(props.session.doc.set) +
    JSON.stringify(props.session.doc.props) +
    (props.session.doc.focus ?? ""),
  () => {
    buildSet();
    buildPaths();
    buildLive();
  },
);
watch([docKey, () => props.shot], () => {
  buildPaths();
  buildLive();
});
watch([() => props.time, () => props.mode], () => buildLive());
watch([selection, showLabels], () => {
  buildSet();
  buildPaths();
  buildLive();
});
watch(
  () => props.mode,
  () => {
    endFly();
    setupControls();
  },
);
watch(gizmoMode, attachGizmo);

// --- picking --------------------------------------------------------------------------------------
const down = shallowRef<{ x: number; y: number } | null>(null);
// The graph takes the wheel for itself unless focus is inside an element marked
// data-capture-wheel, so hovering the view takes focus (unless you're typing) and leaving gives it
// back. Pointer events stop here too: the node around us drags itself and opens its menu on them.
// But OrbitControls follows a drag from `document`, so moves and releases go on there directly,
// past the node.
function toDocument(e: PointerEvent) {
  e.stopPropagation();
  document.dispatchEvent(new PointerEvent(e.type, e));
}
function claimWheel() {
  const active = document.activeElement as HTMLElement | null;
  if (active?.closest?.("input, textarea, select, [contenteditable='true']")) return;
  if (!host.value?.contains(active)) host.value?.focus({ preventScroll: true });
}
function releaseWheel() {
  if (document.activeElement === host.value) host.value?.blur();
}
function onDown(e: PointerEvent) {
  if (e.button === 2 && props.mode === "free") return startFly(e);
  down.value = { x: e.clientX, y: e.clientY };
}
function onMove(e: PointerEvent) {
  if (fly) {
    e.stopPropagation();
    fly.yaw -= e.movementX * 0.0025;
    fly.pitch = Math.max(-1.5, Math.min(1.5, fly.pitch - e.movementY * 0.0025));
    return;
  }
  toDocument(e);
}

// --- fly camera ------------------------------------------------------------------------------------
// Hold the right button in the free view: the mouse looks around, W/A/S/D move, Q/E go down and
// up, Shift goes faster. Letting go orbits again, around what's in front of the camera.
let fly: { yaw: number; pitch: number; last: number; reach: number; pointer: number } | null = null;
const held = new Set<string>();
function startFly(e: PointerEvent) {
  e.preventDefault();
  host.value?.setPointerCapture(e.pointerId);
  const look = new THREE.Euler().setFromQuaternion(persp.quaternion, "YXZ");
  fly = {
    yaw: look.y,
    pitch: look.x,
    last: performance.now(),
    reach: orbit ? persp.position.distanceTo(orbit.target) : 6,
    pointer: e.pointerId,
  };
  if (orbit) orbit.enabled = false;
}
function endFly() {
  if (!fly) return;
  host.value?.releasePointerCapture?.(fly.pointer);
  const ahead = new THREE.Vector3(0, 0, -1).applyQuaternion(persp.quaternion);
  if (orbit) {
    orbit.target.copy(persp.position).addScaledVector(ahead, Math.max(fly.reach, 2));
    orbit.enabled = true;
  }
  fly = null;
  held.clear();
}
function stepFly() {
  const f = fly!;
  const now = performance.now();
  const dt = Math.min((now - f.last) / 1000, 0.1);
  f.last = now;
  persp.quaternion.setFromEuler(new THREE.Euler(f.pitch, f.yaw, 0, "YXZ"));
  const move = new THREE.Vector3(
    (held.has("d") ? 1 : 0) - (held.has("a") ? 1 : 0),
    (held.has("e") ? 1 : 0) - (held.has("q") ? 1 : 0),
    (held.has("s") ? 1 : 0) - (held.has("w") ? 1 : 0),
  );
  if (move.lengthSq() === 0) return;
  const speed = (held.has("shift") ? 12 : 4) * dt;
  // Forward and sideways follow the view; Q/E are straight down and up.
  const vertical = move.y;
  move.y = 0;
  move.normalize().applyQuaternion(persp.quaternion).multiplyScalar(speed);
  move.y += vertical * speed;
  persp.position.add(move);
}
/** While flying, the fly keys are the view's alone: not the gizmo's W/E/R, nor ComfyUI's. */
function flyKey(e: KeyboardEvent) {
  if (!fly) return;
  const key = e.key.toLowerCase();
  if (!["w", "a", "s", "d", "q", "e", "shift"].includes(key)) return;
  e.preventDefault();
  e.stopImmediatePropagation();
  if (e.type === "keydown") held.add(key);
  else held.delete(key);
}
function onUp(e: PointerEvent) {
  if (fly && e.button === 2) {
    e.stopPropagation();
    return endFly();
  }
  toDocument(e);
  const d = down.value;
  down.value = null;
  if (!d || Math.hypot(e.clientX - d.x, e.clientY - d.y) > 4 || dragging || props.mode === "shot")
    return;
  const rect = canvas.value!.getBoundingClientRect();
  const ndc = new THREE.Vector2(
    ((e.clientX - rect.left) / rect.width) * 2 - 1,
    -((e.clientY - rect.top) / rect.height) * 2 + 1,
  );
  const ray = new THREE.Raycaster();
  ray.layers.enableAll();
  ray.setFromCamera(ndc, activeCamera());
  const hits = ray.intersectObjects(
    [...picks.keys()].filter((o) => o.parent),
    false,
  );
  if (gizmo?.dragging) return;
  selection.value = hits.length ? (picks.get(hits[0]!.object) ?? null) : null;
}
function onKey(e: KeyboardEvent) {
  const t = e.target as HTMLElement | null;
  if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
  if (!host.value?.matches(":hover")) return;
  if (e.key.toLowerCase() === "f" && !e.ctrlKey && !e.metaKey) {
    if (props.mode === "plan") fitPlan();
    else if (!frameSelected()) frameAll();
    return;
  }
  const map: Record<string, "translate" | "rotate" | "scale"> = {
    w: "translate",
    e: "rotate",
    r: "scale",
  };
  const m = map[e.key.toLowerCase()];
  if (m && !e.ctrlKey && !e.metaKey) gizmoMode.value = m;
}

/** Orbit view framing the whole set, from a three-quarter angle above. */
function frameAll() {
  const box = new THREE.Box3().setFromObject(setGroup);
  if (box.isEmpty()) box.set(new THREE.Vector3(-4, 0, -4), new THREE.Vector3(4, 2, 4));
  const c = box.getCenter(new THREE.Vector3());
  const r = box.getSize(new THREE.Vector3()).length() / 2;
  const dist = (r / Math.sin(((persp.fov / 2) * Math.PI) / 180)) * 0.85;
  persp.position.set(c.x + dist * 0.55, c.y + dist * 0.6, c.z + dist * 0.6);
  persp.lookAt(c);
  if (orbit && props.mode === "free") orbit.target.copy(c);
}

/** Orbit view closing in on what's selected; false when nothing on screen is. */
function frameSelected(): boolean {
  const sel = selection.value;
  if (!sel) return false;
  const box = new THREE.Box3();
  for (const [obj, s] of picks)
    if (obj.parent && s.type === sel.type && s.id === sel.id) box.expandByObject(obj);
  if (box.isEmpty()) return false;
  const c = box.getCenter(new THREE.Vector3());
  const r = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 0.6);
  const dir = persp.position
    .clone()
    .sub(orbit?.target ?? c)
    .normalize();
  const dist = (r / Math.sin(((persp.fov / 2) * Math.PI) / 180)) * 1.1;
  persp.position.copy(c).addScaledVector(dir, dist);
  persp.lookAt(c);
  if (orbit) orbit.target.copy(c);
  return true;
}

defineExpose({ fitPlan, frameAll, isVec });
</script>

<style scoped>
.gbv {
  position: relative;
  outline: none;
  overflow: hidden;
  width: 100%;
  height: 100%;
  border-radius: var(--h3-radius, 8px);
  background: #0b0b0e;
}
canvas {
  display: block;
  width: 100%;
  height: 100%;
}
.labels {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
.labels :deep(.gb-label) {
  padding: 1px 6px;
  border-radius: 999px;
  background: rgb(0 0 0 / 55%);
  color: #e5e5ea;
  font:
    600 10.5px system-ui,
    sans-serif;
  white-space: nowrap;
  pointer-events: auto;
  cursor: pointer;
}
.labels :deep(.gb-label.mark) {
  padding: 0 5px;
  background: rgb(0 0 0 / 35%);
  color: #9aa0aa;
  font-weight: 500;
  font-size: 9.5px;
}
.labels :deep(.gb-label.mark.on) {
  color: #fff;
  /* it's already selected, and it sits on its gizmo: let drags through to it */
  pointer-events: none;
}
.labels :deep(.gb-label.actor) {
  color: #ffd2ad;
}
.labels :deep(.gb-label.cam.on) {
  outline: 1px solid #fff;
}
.tools {
  position: absolute;
  top: 8px;
  left: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.lens {
  padding: 2px 8px;
  border-radius: 999px;
  background: rgb(0 0 0 / 55%);
  color: #e5e5ea;
  font-size: 11px;
}
</style>
