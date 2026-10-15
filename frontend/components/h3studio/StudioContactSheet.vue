<template>
  <ZenModal
    :open="target !== null"
    title="Contact sheet"
    width="900px"
    height="min(760px, 90vh)"
    @update:open="(v: boolean) => !v && emit('close')"
  >
    <div class="sheet">
      <div class="opts">
        <ZenToggleGroup
          v-model="count"
          title="Frames"
          :options="COUNTS.map((n) => ({ value: String(n), label: `${n} frames` }))"
        />
        <ZenToggleGroup
          v-model="columns"
          title="Across"
          :options="[
            { value: '3', label: '3 across' },
            { value: '4', label: '4 across' },
            { value: '6', label: '6 across' },
          ]"
        />
      </div>

      <div class="preview zen-scroll">
        <img
          v-if="made"
          :src="src"
          alt="Frames evenly through the render"
          draggable="true"
          title="Drag it into a chat, a folder or a node"
          @dragstart="carryMedia($event, made.ref)"
        />
        <p v-else-if="problem" class="empty bad">
          <i class="mdi mdi-alert-outline" /> {{ problem }}
        </p>
        <p v-else class="empty"><i class="mdi mdi-loading mdi-spin" /> Cutting frames…</p>
      </div>

      <div class="row">
        <span class="soft">{{ summary }}</span>
        <span class="grow" />
        <ZenButton
          sm
          variant="ghost"
          icon="mdi mdi-folder-outline"
          title="The file's place on this computer, for an agent to read"
          :disabled="!made"
          @click="copyText(made!.path, 'path')"
          >{{ copied === "path" ? "Copied" : "Copy path" }}</ZenButton
        >
        <ZenButton
          sm
          variant="ghost"
          icon="mdi mdi-content-copy"
          :disabled="!made"
          @click="copyImage"
          >{{ copied === "image" ? "Copied" : "Copy image" }}</ZenButton
        >
        <ZenButton sm variant="primary" icon="mdi mdi-download" :disabled="!made" @click="download"
          >Download PNG</ZenButton
        >
      </div>
    </div>
  </ZenModal>
</template>

<script setup lang="ts">
// A render's contact sheet (lib/h3contact.ts): frames evenly through the clip in a grid, marked with
// their time and shot. Dragged out, copied or downloaded, it's a scene at a glance for a chat or an
// agent; agents running here can read it from its path.
import { computed, ref, watch } from "vue";
import { ZenButton, ZenModal, ZenToggleGroup } from "@nynxz/zenkit-ui";
import { contactSheet, type ContactRequest, type ContactSheet } from "@/lib/h3contact";
import { carryMedia } from "@/lib/dragOut";
import { stableUrl } from "@/lib/h3studio";

const props = defineProps<{ target: ContactRequest | null }>();
const emit = defineEmits<{ close: [] }>();

const COUNTS = [8, 12, 16, 24];
const count = ref("12");
const columns = ref("4");
const made = ref<ContactSheet | null>(null);
// The same layout of a clip keeps its file name, remade when the clip is newer: a fresh address
// each time, so the browser doesn't show the sheet it had before.
const src = computed(() => {
  if (!made.value) return "";
  const url = stableUrl(made.value.ref);
  return `${url}${url.includes("?") ? "&" : "?"}v=${asked}`;
});
const problem = ref("");

let asked = 0;
async function make() {
  const mine = ++asked;
  made.value = null;
  problem.value = "";
  if (!props.target) return;
  try {
    const sheet = await contactSheet({
      ...props.target,
      count: Number(count.value),
      columns: Number(columns.value),
    });
    if (mine === asked) made.value = sheet;
  } catch (e) {
    if (mine === asked) problem.value = (e as Error).message;
  }
}
watch(
  () => [props.target, count.value, columns.value],
  () => void make(),
  { immediate: true },
);

const summary = computed(() =>
  made.value
    ? `${made.value.frames.length} frames of ${made.value.seconds.toFixed(1)} s, one every ` +
      `${(made.value.seconds / made.value.frames.length).toFixed(2)} s`
    : "",
);

function download() {
  if (!made.value) return;
  const a = document.createElement("a");
  a.href = stableUrl(made.value.ref);
  a.download = made.value.ref.split("/").pop() ?? "contact-sheet.png";
  a.click();
}
const copied = ref<"" | "image" | "path">("");
function flash(what: "image" | "path") {
  copied.value = what;
  setTimeout(() => (copied.value = ""), 1500);
}
async function copyText(text: string, what: "path") {
  await navigator.clipboard.writeText(text);
  flash(what);
}
async function copyImage() {
  if (!made.value) return;
  try {
    const blob = await (await fetch(stableUrl(made.value.ref))).blob();
    await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
    flash("image");
  } catch {
    copied.value = "";
  }
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
  background: color-mix(in srgb, var(--zen-text, #e5e5ea) 9%, var(--zen-bg, #18181c));
}
.preview img {
  display: block;
  max-width: 100%;
  height: auto;
  cursor: grab;
}
.empty {
  margin: auto;
  color: var(--zen-muted, #9aa0aa);
  font-size: 12px;
}
.empty.bad {
  color: var(--zen-danger, #e5767a);
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
