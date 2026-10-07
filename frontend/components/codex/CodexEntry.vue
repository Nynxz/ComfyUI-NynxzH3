<template>
  <div class="entry zen-scroll">
    <section
      class="pics"
      :class="{ dropping }"
      @dragover="onDragOver"
      @dragleave="dropping = false"
      @drop="onDrop"
    >
      <div class="cover" :title="cover ? 'The picture that stands for it' : 'Drop pictures here'">
        <MediaThumb :media="cover" :badge="false" :label="doc.name" />
        <audio
          v-if="coverIsAudio"
          class="player"
          :src="mediaRefUrl(cover)"
          controls
          preload="none"
        />
        <div v-if="dropping" class="dropmask"><i class="mdi mdi-tray-arrow-down" />Drop to add</div>
      </div>
      <div class="strip">
        <div
          v-for="(p, i) in pictures"
          :key="p.media + i"
          class="pic"
          :class="{ on: p.media === cover }"
          :title="p.media === cover ? 'Cover' : 'Click to make this the cover'"
          @click="setCover(p.media)"
        >
          <MediaThumb :media="p.media" :badge="false" />
          <button
            type="button"
            class="x"
            title="Remove"
            aria-label="Remove picture"
            @click.stop="removePicture(i)"
          >
            <i class="mdi mdi-close" />
          </button>
        </div>
        <button
          type="button"
          class="pic add"
          title="Add pictures"
          aria-label="Add pictures"
          @click="pick"
        >
          <i class="mdi mdi-plus" />
        </button>
      </div>
      <p v-if="variant" class="soft small">
        Pictures for <b>{{ variant.name }}</b
        >. <button type="button" class="linkbtn" @click="variantId = ''">Show the main ones</button>
      </p>
    </section>

    <section class="head">
      <input
        :value="doc.name"
        class="name"
        aria-label="Name"
        @input="setName(($event.target as HTMLInputElement).value)"
        @change="touch"
      />
      <div class="row">
        <span class="mention" :title="`Write ${mention} in a shot to use it`">{{ mention }}</span>
        <ZenSelect
          size="sm"
          :model-value="doc.kind"
          :options="kindOptions"
          @update:model-value="setKind"
        />
      </div>
      <ZenField
        label="Mention as"
        stack
        hint="What you write in a shot. Letters, numbers and dashes."
      >
        <ZenInput sm :model-value="doc.handle" @update:model-value="setHandle(String($event))" />
      </ZenField>
    </section>

    <section class="card">
      <h4>In prompts</h4>
      <ZenInput
        v-model="doc.prompt"
        type="textarea"
        :rows="3"
        :placeholder="PROMPT_HINT[doc.kind]"
        @change="touch"
      />
      <p class="soft small">
        What a shot gets when it mentions {{ mention
        }}<template v-if="variant">, plus {{ variant.name }}'s words</template>.
      </p>
    </section>

    <section v-if="doc.kind === 'character'" class="block">
      <h4>Who they are</h4>
      <ZenInput
        v-model="doc.about"
        type="textarea"
        :rows="2"
        placeholder="A line or two for you — not sent to the model."
      />
    </section>

    <section class="block">
      <h4>{{ kind.variants }}</h4>
      <div class="chips">
        <button type="button" class="chip" :class="{ on: !variantId }" @click="variantId = ''">
          Main
        </button>
        <button
          v-for="v in doc.variants"
          :key="v.id"
          type="button"
          class="chip"
          :class="{ on: v.id === variantId }"
          @click="variantId = v.id"
        >
          {{ v.name }}
        </button>
        <button
          type="button"
          class="chip add"
          :title="`Add to ${kind.variants.toLowerCase()}`"
          @click="addVariant"
        >
          <i class="mdi mdi-plus" />
        </button>
      </div>
      <div v-if="variant" class="variant">
        <ZenField label="Name">
          <ZenInput v-model="variant.name" sm />
        </ZenField>
        <ZenInput
          v-model="variant.prompt"
          type="textarea"
          :rows="2"
          :placeholder="VARIANT_HINT[doc.kind]"
        />
        <ZenButton size="sm" icon="mdi mdi-delete-outline" @click="removeVariant"
          >Remove {{ variant.name }}</ZenButton
        >
      </div>
    </section>

    <template v-if="doc.kind === 'character'">
      <section class="block">
        <h4>Voice</h4>
        <ZenSelect
          size="sm"
          :model-value="voiceLink"
          :options="voiceOptions"
          @update:model-value="setVoiceLink"
        />
        <ZenInput
          v-model="doc.voice.description"
          type="textarea"
          :rows="2"
          placeholder="How they sound, e.g. a low, dry voice, unhurried"
        />
        <ZenField label="Language">
          <ZenInput v-model="doc.voice.language" sm />
        </ZenField>
      </section>

      <section class="block">
        <h4>LoRAs</h4>
        <div v-for="(l, i) in doc.loras" :key="l.name + i" class="lora">
          <i class="mdi mdi-puzzle-outline" />
          <span class="lname" :title="l.name">{{ shortName(l.name) }}</span>
          <ZenNumber
            v-model="l.strength"
            size="sm"
            :min="-2"
            :max="2"
            :step="0.05"
            :precision="2"
          />
          <ZenIconButton
            icon="mdi mdi-close"
            size="sm"
            title="Remove"
            @click="doc.loras.splice(i, 1)"
          />
        </div>
        <ZenButton size="sm" icon="mdi mdi-plus" @click="loraOpen = true">Add a LoRA</ZenButton>
      </section>
    </template>

    <section class="block">
      <h4>Links</h4>
      <div v-for="l in links" :key="l.key" class="link">
        <i
          class="mdi"
          :class="KINDS[l.entry.kind].icon"
          :style="{ color: KINDS[l.entry.kind].color }"
        />
        <input
          v-if="l.out"
          class="llabel"
          :value="l.label"
          :list="`codex-labels-${l.entry.kind}`"
          placeholder="how they relate"
          aria-label="How they relate"
          @change="setLabel(l.entry.id, ($event.target as HTMLInputElement).value)"
        />
        <span v-else class="llabel from">{{ l.label || "linked" }} ←</span>
        <button
          type="button"
          class="lname-btn"
          :title="`Open ${l.entry.name}`"
          @click="emit('open', l.entry.id)"
        >
          {{ l.entry.name }}
        </button>
        <ZenIconButton icon="mdi mdi-close" size="sm" title="Remove link" @click="unlink(l)" />
      </div>
      <ZenSelect
        v-if="linkable.length"
        size="sm"
        model-value=""
        placeholder="Link to…"
        :options="linkable"
        @update:model-value="link"
      />
      <datalist v-for="k in KIND_ORDER" :id="`codex-labels-${k}`" :key="k">
        <option v-for="o in LINK_LABELS[k]" :key="o" :value="o" />
      </datalist>
    </section>

    <section class="block">
      <h4>Tags</h4>
      <ZenInput
        sm
        :model-value="doc.tags.join(', ')"
        placeholder="lead, interior, episode 1…"
        @update:model-value="
          doc.tags = String($event)
            .split(',')
            .map((t) => t.trim())
            .filter(Boolean)
        "
      />
    </section>

    <section class="block">
      <h4>Notes</h4>
      <ZenInput
        v-model="doc.notes"
        type="textarea"
        :rows="3"
        placeholder="Anything worth remembering."
      />
    </section>

    <section class="actions">
      <template v-if="studios.length">
        <ZenSelect
          v-if="studios.length > 1"
          size="sm"
          class="studiopick"
          :model-value="studioId"
          :options="studios.map((s) => ({ value: s.id, label: s.label }))"
          @update:model-value="studioId = $event"
        />
        <ZenButton variant="primary" icon="mdi mdi-movie-open-plus-outline" @click="sendToStudio">
          {{ doc.kind === "character" ? "Add to H3 Studio cast" : "Add to H3 Studio" }}
        </ZenButton>
      </template>
      <p v-else class="soft small">Add an H3 Studio to the workflow to use this in a film.</p>
      <p v-if="sent" class="sent"><i class="mdi mdi-check" /> {{ sent }}</p>
      <div class="row">
        <ZenButton size="sm" icon="mdi mdi-content-copy" @click="emit('duplicate')"
          >Duplicate</ZenButton
        >
        <ZenButton size="sm" icon="mdi mdi-delete-outline" @click="emit('remove')"
          >Delete</ZenButton
        >
      </div>
    </section>

    <LoraBrowser v-model:open="loraOpen" @pick="addLora" />
    <ZenMediaPicker
      :open="pickerOpen"
      :library="mediaLibrary"
      :kinds="doc.kind === 'sound' ? ['audio', 'video'] : ['image', 'video']"
      multiple
      title="Add pictures"
      confirm-label="Add"
      :subfolder="uploads"
      @update:open="pickerOpen = $event"
      @pick="addPictures"
    />
  </div>
</template>

<script setup lang="ts">
// One Codex entry, edited in place: its pictures (and a cover), the line shots get when they
// mention it, its variants (a character's wardrobe, a place's times of day), and for a character
// their voice and LoRAs. "Add to H3 Studio" puts it into a studio in the open workflow.
import { computed, onBeforeUnmount, ref, watch } from "vue";
import {
  LoraBrowser,
  ZenButton,
  ZenField,
  ZenIconButton,
  ZenInput,
  ZenMediaPicker,
  ZenNumber,
  ZenSelect,
} from "@nynxz/zenkit-ui";
import {
  hasMediaDrop,
  mediaKind,
  mediaLibrary,
  mediaRefUrl,
  readMediaDrop,
  uploadOrReuse,
} from "@/framework";
import {
  KIND_ORDER,
  KINDS,
  LINK_LABELS,
  coverOf,
  freeHandle,
  handleOf,
  linksOf,
  mentionOf,
  newVariant,
  uploadsOf,
  type Entry,
  type EntryKind,
  type Show,
} from "@/lib/codex";
import { addToStudio, studiosInGraph, type StudioTarget } from "@/lib/codexStudio";
import MediaThumb from "@/components/h3studio/MediaThumb.vue";

const props = defineProps<{ entry: Entry; show: Show }>();
const emit = defineEmits<{ remove: []; duplicate: []; open: [id: string] }>();
/** The entry, shared with the list and edited in place. */
const doc = computed(() => props.entry);

const PROMPT_HINT: Record<EntryKind, string> = {
  character: "a woman in her mid-30s with cropped dark hair, a grey knit cardigan…",
  place: "a cramped radio booth at night, foam panels, a red ON AIR lamp…",
  prop: "a red rotary phone with a cracked receiver",
  look: "shot on 16mm film, sodium-orange light, deep blacks, soft halation",
  sound: "a low, dry female voice, unhurried, late-night radio warmth",
};
const VARIANT_HINT: Record<EntryKind, string> = {
  character: "What changes: in a long yellow rain coat, hood down",
  place: "What changes: at dawn, grey-blue light, lamps off",
  prop: "What changes: off the hook, receiver on the desk",
  look: "What changes: bleached, nearly black and white",
  sound: "What changes: whispered, close to the mic",
};

const kind = computed(() => KINDS[doc.value.kind]);
const kindOptions = KIND_ORDER.map((k) => ({
  value: k,
  label: KINDS[k].label,
  icon: KINDS[k].icon,
}));
const mention = computed(() => mentionOf(doc.value));
const uploads = computed(() => uploadsOf(props.show.id));
/** The show, for links: edited in place when a link from another entry is removed. */
const showDoc = computed(() => props.show);

const variantId = ref("");
watch(
  () => doc.value.id,
  () => (variantId.value = ""),
);
const variant = computed(() => doc.value.variants.find((v) => v.id === variantId.value));
const pictures = computed(() => (variant.value ? variant.value.pictures : doc.value.pictures));
const cover = computed(() =>
  variant.value ? variant.value.pictures[0]?.media || coverOf(doc.value) : coverOf(doc.value),
);

const touch = () => (doc.value.updated = Date.now());

function setKind(k: string) {
  doc.value.kind = k as EntryKind;
  touch();
}
/** The handle follows the name until it's set by hand. */
function setName(name: string) {
  const following =
    doc.value.handle === freeHandle(showDoc.value, handleOf(doc.value.name), doc.value.id);
  doc.value.name = name;
  if (following) doc.value.handle = freeHandle(showDoc.value, handleOf(name), doc.value.id);
}
function setHandle(v: string) {
  doc.value.handle = freeHandle(showDoc.value, handleOf(v), doc.value.id);
}

function addPictures(media: string[]) {
  const list = pictures.value;
  for (const m of media) if (!list.some((p) => p.media === m)) list.push({ media: m, label: "" });
  touch();
}
function removePicture(i: number) {
  const [gone] = pictures.value.splice(i, 1);
  if (gone && doc.value.cover === gone.media) doc.value.cover = "";
  touch();
}
function setCover(media: string) {
  if (variant.value) {
    const list = variant.value.pictures;
    const i = list.findIndex((p) => p.media === media);
    if (i > 0) list.unshift(...list.splice(i, 1));
  } else doc.value.cover = media;
  touch();
}

const pickerOpen = ref(false);
const pick = () => (pickerOpen.value = true);
const dropping = ref(false);
function onDragOver(e: DragEvent) {
  if (!hasMediaDrop(e)) return;
  e.preventDefault();
  dropping.value = true;
}
async function onDrop(e: DragEvent) {
  if (!hasMediaDrop(e)) return;
  e.preventDefault();
  dropping.value = false;
  addPictures(await readMediaDrop(e, uploads.value, uploadOrReuse));
}

function addVariant() {
  const v = newVariant(
    `${kind.value.variants === "Wardrobe" ? "Outfit" : "Variant"} ${doc.value.variants.length + 1}`,
  );
  doc.value.variants.push(v);
  variantId.value = v.id;
  touch();
}
function removeVariant() {
  const i = doc.value.variants.findIndex((v) => v.id === variantId.value);
  if (i >= 0) doc.value.variants.splice(i, 1);
  variantId.value = "";
  touch();
}

const loraOpen = ref(false);
const shortName = (name: string) =>
  name
    .split(/[\\/]/)
    .pop()!
    .replace(/\.safetensors$/, "");
function addLora(name: string) {
  loraOpen.value = false;
  if (!doc.value.loras.some((l) => l.name === name)) doc.value.loras.push({ name, strength: 1 });
  touch();
}

const studios = ref<StudioTarget[]>(studiosInGraph());
const studioId = ref(studios.value[0]?.id ?? "");
const scan = () => {
  studios.value = studiosInGraph();
  if (!studios.value.some((s) => s.id === studioId.value))
    studioId.value = studios.value[0]?.id ?? "";
};
const timer = window.setInterval(scan, 1500);
onBeforeUnmount(() => window.clearInterval(timer));

const coverIsAudio = computed(() => !!cover.value && mediaKind(cover.value) === "audio");

// --- links ---------------------------------------------------------------------------------------
const links = computed(() =>
  linksOf(showDoc.value, doc.value.id).map((l, i) => ({
    ...l,
    key: `${l.out ? "o" : "i"}${l.entry.id}${i}`,
  })),
);
const linkable = computed(() =>
  KIND_ORDER.flatMap((k) =>
    showDoc.value.entries
      .filter(
        (e) => e.kind === k && e.id !== doc.value.id && !doc.value.links.some((l) => l.to === e.id),
      )
      .map((e) => ({ value: e.id, label: e.name, icon: KINDS[k].icon })),
  ),
);
function link(id: string) {
  const to = showDoc.value.entries.find((e) => e.id === id);
  if (!to) return;
  doc.value.links.push({ to: id, label: LINK_LABELS[to.kind][0] ?? "" });
  touch();
}
function setLabel(to: string, label: string) {
  const l = doc.value.links.find((x) => x.to === to);
  if (l) l.label = label.trim();
}
function unlink(l: { entry: Entry; out: boolean }) {
  if (l.out) doc.value.links = doc.value.links.filter((x) => x.to !== l.entry.id);
  else l.entry.links = l.entry.links.filter((x) => x.to !== doc.value.id);
  touch();
}

// A character's voice is a link to a sound, labelled "voice".
const voiceLink = computed(() => doc.value.links.find((l) => l.label === "voice")?.to ?? "");
const voiceOptions = computed(() => [
  { value: "", label: "No voice clip — described in words" },
  ...showDoc.value.entries
    .filter((e) => e.kind === "sound")
    .map((e) => ({ value: e.id, label: e.name, icon: KINDS.sound.icon })),
]);
function setVoiceLink(id: string) {
  doc.value.links = doc.value.links.filter((l) => l.label !== "voice");
  if (id) doc.value.links.push({ to: id, label: "voice" });
  touch();
}

const sent = ref("");
function sendToStudio() {
  const target = studios.value.find((s) => s.id === studioId.value);
  if (!target) return;
  const used = addToStudio(target.project, doc.value, showDoc.value, variantId.value || undefined);
  sent.value = `In ${target.label.split(" — ")[0]} as ${used}`;
}
watch(
  () => doc.value.id,
  () => (sent.value = ""),
);
</script>

<style scoped>
.entry {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
  overflow-x: hidden;
  box-sizing: border-box;
  height: 100%;
  overflow-y: auto;
  padding: 14px;
}
h4 {
  margin: 0 0 6px;
  color: var(--zen-muted, #9aa0aa);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.soft {
  color: var(--zen-muted, #9aa0aa);
}
.small {
  margin: 4px 0 0;
  font-size: 11px;
}
.pics {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.cover {
  position: relative;
  overflow: hidden;
  height: 200px;
  flex: none;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: var(--zen-radius, 8px);
  background: var(--zen-media-bg, #111);
}
.cover :deep(.mt) {
  width: 100%;
  height: 100%;
}
.dropmask {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  background: color-mix(in srgb, var(--zen-accent, #6366f1) 30%, transparent);
  color: #fff;
  font-weight: 600;
}
.pics.dropping .cover {
  border-color: var(--zen-accent, #6366f1);
}
.strip {
  display: grid;
  grid-template-columns: repeat(auto-fill, 56px);
  gap: 6px;
}
.pic {
  position: relative;
  overflow: hidden;
  aspect-ratio: 1;
  padding: 0;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: 6px;
  background: var(--zen-media-bg, #111);
  cursor: pointer;
}
.pic :deep(.mt) {
  width: 100%;
  height: 100%;
}
.pic.on {
  border-color: var(--zen-accent, #6366f1);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--zen-accent, #6366f1) 35%, transparent);
}
.pic.add {
  display: flex;
  align-items: center;
  justify-content: center;
  border-style: dashed;
  background: transparent;
  color: var(--zen-muted, #9aa0aa);
  font-size: 18px;
}
.x {
  position: absolute;
  top: 2px;
  right: 2px;
  display: none;
  width: 18px;
  height: 18px;
  padding: 0;
  border: 0;
  border-radius: 4px;
  background: rgb(0 0 0 / 0.65);
  color: #fff;
  cursor: pointer;
}
.pic:hover .x {
  display: block;
}
.head {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.name {
  width: 100%;
  padding: 2px 0;
  border: 0;
  border-bottom: 1px solid transparent;
  outline: 0;
  background: transparent;
  color: var(--zen-text, #e5e5ea);
  font: inherit;
  font-size: 18px;
  font-weight: 600;
}
.name:focus {
  border-bottom-color: var(--zen-accent, #6366f1);
}
.row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.mention {
  flex: 1 1 120px;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  color: color-mix(in srgb, var(--zen-accent, #6366f1) 55%, var(--zen-text, #e5e5ea));
  font-family: ui-monospace, monospace;
  font-size: 12px;
}
.card {
  padding: 10px;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: var(--zen-radius, 8px);
  background: var(--zen-surface, #202026);
}
.block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chip {
  height: var(--zen-control-h-sm, 24px);
  padding: 0 10px;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: 999px;
  background: transparent;
  color: var(--zen-text, #e5e5ea);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}
.chip.on {
  border-color: var(--zen-accent, #6366f1);
  background: color-mix(in srgb, var(--zen-accent, #6366f1) 18%, transparent);
}
.chip.add {
  color: var(--zen-muted, #9aa0aa);
  border-style: dashed;
}
.variant {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: var(--zen-radius, 8px);
}
.lora {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.lname {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: auto;
  padding-top: 8px;
  border-top: 1px solid var(--zen-border, #34343c);
}
.link {
  display: grid;
  grid-template-columns: auto minmax(0, 40%) minmax(0, 1fr) auto;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.llabel {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  height: var(--zen-control-h-sm, 24px);
  padding: 0 6px;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: 5px;
  background: var(--zen-field-bg, var(--zen-input, #15151a));
  color: var(--zen-text, #e5e5ea);
  font: inherit;
  font-size: 12px;
}
.llabel.from {
  display: flex;
  align-items: center;
  border-style: dashed;
  color: var(--zen-muted, #9aa0aa);
}
.lname-btn {
  flex: 1;
  min-width: 0;
  padding: 0;
  overflow: hidden;
  border: 0;
  background: none;
  color: var(--zen-text, #e5e5ea);
  font: inherit;
  font-weight: 600;
  text-align: left;
  white-space: nowrap;
  text-overflow: ellipsis;
  cursor: pointer;
}
.lname-btn:hover {
  text-decoration: underline;
}
.player {
  position: absolute;
  right: 8px;
  bottom: 8px;
  left: 8px;
  height: 32px;
}
.studiopick {
  width: 100%;
}
.sent {
  margin: 0;
  color: var(--zen-success, #4ade80);
  font-size: 12px;
}
.linkbtn {
  padding: 0;
  border: 0;
  background: none;
  color: var(--zen-accent-text, #a5aaff);
  font: inherit;
  cursor: pointer;
  text-decoration: underline;
}
</style>
