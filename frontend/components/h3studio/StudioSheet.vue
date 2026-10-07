<template>
  <ZenModal
    :open="open"
    title="Reference sheet"
    width="860px"
    height="min(720px, 90vh)"
    @update:open="(v: boolean) => emit('update:open', v)"
  >
    <div class="sheet">
      <div class="opts">
        <ZenToggleGroup
          v-model="which"
          :options="[
            { value: 'all', label: 'Every reference' },
            { value: 'scene', label: `Scene ${sceneIndex + 1}'s` },
          ]"
        />
        <ZenToggleGroup
          v-model="width"
          :options="[
            { value: '1024', label: '1024' },
            { value: '1536', label: '1536' },
            { value: '2048', label: '2048' },
          ]"
        />
        <ZenToggleGroup
          v-model="gutter"
          :options="[
            { value: 'light', label: 'Light', icon: 'mdi mdi-white-balance-sunny' },
            { value: 'dark', label: 'Dark', icon: 'mdi mdi-weather-night' },
          ]"
        />
        <ZenToggleGroup
          v-model="text"
          title="Text size"
          :options="[
            { value: '0.8', label: 'S', title: 'Smaller names and descriptions' },
            { value: '1', label: 'M', title: 'The usual size' },
            { value: '1.3', label: 'L', title: 'Larger names and descriptions' },
          ]"
        />
        <ZenCheckbox v-model="labels" label="Names" />
        <ZenCheckbox v-model="notes" label="Descriptions" />
        <ZenCheckbox v-model="audio" label="Audio" />
        <ZenCheckbox v-model="placeholders" label="Placeholders" />
      </div>

      <div class="preview zen-scroll">
        <img v-if="url" :src="url" alt="The reference sheet" />
        <p v-else-if="!refs.length" class="empty">No references to show.</p>
        <p v-else class="empty"><i class="mdi mdi-loading mdi-spin" /> Packing…</p>
      </div>

      <div class="row">
        <span class="soft">{{ summary }}</span>
        <span class="grow" />
        <span v-if="saved" class="soft"><i class="mdi mdi-check" /> {{ saved }}</span>
        <ZenButton sm variant="ghost" icon="mdi mdi-content-copy" :disabled="!blob" @click="copy">{{
          copied ? "Copied" : "Copy"
        }}</ZenButton>
        <ZenButton
          sm
          variant="ghost"
          icon="mdi mdi-tray-arrow-up"
          title="Save it into ComfyUI's input folder (input/h3studio), to load or use as a picture"
          :disabled="!blob"
          @click="save"
          >Save to inputs</ZenButton
        >
        <ZenButton sm variant="primary" icon="mdi mdi-download" :disabled="!blob" @click="download"
          >Download PNG</ZenButton
        >
      </div>
    </div>
  </ZenModal>
</template>

<script setup lang="ts">
// The reference sheet dialog: the project's references packed onto one board (lib/h3sheet.ts),
// previewed live as the options change, and saved out as a PNG.
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { ZenButton, ZenCheckbox, ZenModal, ZenToggleGroup } from "@nynxz/zenkit-ui";
import { refInScene, type Project } from "@/lib/h3studio";
import { drawSheet, sheetBlob, sheetRefs } from "@/lib/h3sheet";
import { uploadOrReuse } from "@/framework";

const props = defineProps<{ project: Project; open: boolean; sceneIndex: number }>();
const emit = defineEmits<{ "update:open": [open: boolean] }>();

const which = ref<"all" | "scene">("all");
const width = ref("1536");
const gutter = ref<"light" | "dark">("light");
const labels = ref(true);
const notes = ref(true);
const text = ref("1");
const audio = ref(true);
const placeholders = ref(true);

const refs = computed(() => {
  const scene = props.project.scenes[props.sceneIndex];
  const all =
    which.value === "scene" && scene
      ? sheetRefs(props.project, scene.id, (r) => refInScene(props.project, r, scene))
      : sheetRefs(props.project);
  return all.filter(
    (r) => (audio.value || r.kind !== "audio") && (placeholders.value || r.media),
  );
});

const blob = ref<Blob | null>(null);
const saved = ref("");
const url = ref("");
const size = ref("");
let drawing = 0;
async function redraw() {
  const mine = ++drawing;
  if (!props.open || !refs.value.length) {
    setPreview(null);
    return;
  }
  const canvas = await drawSheet({
    width: Number(width.value),
    refs: refs.value,
    labels: labels.value,
    notes: notes.value,
    gutter: gutter.value,
    text: Number(text.value),
  });
  if (mine !== drawing) return;
  size.value = `${canvas.width}×${canvas.height}`;
  setPreview(await sheetBlob(canvas));
}
function setPreview(next: Blob | null) {
  if (url.value) URL.revokeObjectURL(url.value);
  blob.value = next;
  url.value = next ? URL.createObjectURL(next) : "";
  saved.value = "";
}
watch(
  () => [props.open, refs.value, width.value, gutter.value, labels.value, notes.value, text.value],
  () => void redraw(),
  { immediate: true, deep: true },
);
onBeforeUnmount(() => setPreview(null));

const summary = computed(() =>
  refs.value.length
    ? `${refs.value.length} reference${refs.value.length === 1 ? "" : "s"}${size.value ? ` · ${size.value}` : ""}`
    : "",
);
const fileName = () => `h3-reference-sheet-${which.value === "scene" ? `scene${props.sceneIndex + 1}` : "all"}.png`;

function download() {
  if (!url.value) return;
  const a = document.createElement("a");
  a.href = url.value;
  a.download = fileName();
  a.click();
}
const copied = ref(false);
async function copy() {
  if (!blob.value) return;
  try {
    await navigator.clipboard.write([new ClipboardItem({ "image/png": blob.value })]);
    copied.value = true;
    setTimeout(() => (copied.value = false), 1500);
  } catch {
    copied.value = false;
  }
}
async function save() {
  if (!blob.value) return;
  saved.value = await uploadOrReuse(new File([blob.value], fileName(), { type: "image/png" }), "h3studio");
}
</script>

<style scoped>
.sheet {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
  min-height: 0;
  box-sizing: border-box;
  padding: 2px 2px 6px;
}
.opts {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
}
.preview {
  display: flex;
  flex: 1 1 0;
  align-items: flex-start;
  justify-content: center;
  min-height: 0;
  overflow: auto;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: var(--zen-radius, 8px);
  background: repeating-conic-gradient(#0000 0 25%, #8881 0 50%) 0 0 / 16px 16px;
}
.preview img {
  display: block;
  max-width: 100%;
  height: auto;
}
.empty {
  margin: auto;
  color: var(--zen-muted, #9aa0aa);
  font-size: 12px;
}
.row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.grow {
  flex: 1;
}
.soft {
  color: var(--zen-muted, #9aa0aa);
  font-size: 11px;
}
</style>
