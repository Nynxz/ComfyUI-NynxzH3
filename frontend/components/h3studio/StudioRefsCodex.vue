<template>
  <ZenPopover placement="bottom-start">
    <template #trigger="{ toggle }">
      <ZenButton
        sm
        icon="mdi mdi-book-open-page-variant-outline"
        title="Fill the references from the Codex by name, or start Codex entries from placeholders"
        @click="open(toggle)"
      >
        Fill from Codex
      </ZenButton>
    </template>
    <div class="pop">
      <p v-if="!shows.length && !loading" class="soft">Make a show in the Codex first.</p>
      <template v-else>
        <ZenSelect
          v-model="showId"
          size="sm"
          :options="shows.map((s) => ({ value: s.id, label: s.name }))"
        />
        <p v-if="loading" class="soft">Looking…</p>
        <template v-else-if="show">
          <section>
            <h4>In the Codex · {{ found.matches.length }}</h4>
            <p v-if="!found.matches.length" class="soft">
              No reference here has the name of an entry in {{ show.name }}.
            </p>
            <div v-for="m in found.matches" :key="m.ref.id" class="row">
              <span class="mention">@{{ m.ref.name }}</span>
              <i class="mdi mdi-arrow-right soft" />
              <span class="grow ellipsis">{{ m.entry.name }}</span>
              <span class="kind">{{ KINDS[m.entry.kind].label }}</span>
              <i
                v-if="m.linked"
                class="mdi mdi-link-variant soft"
                title="Tied to this entry: filling brings its latest picture and description"
              />
            </div>
            <ZenButton
              v-if="found.matches.length"
              sm
              variant="primary"
              icon="mdi mdi-download-outline"
              @click="fill"
            >
              Fill from the Codex
            </ZenButton>
          </section>
          <section v-if="found.missing.length">
            <h4>Not in the Codex · {{ found.missing.length }}</h4>
            <div v-for="r in found.missing" :key="r.id" class="row">
              <span class="mention grow ellipsis" :title="r.note">@{{ r.name }}</span>
              <ZenSelect
                class="kindpick"
                size="sm"
                :model-value="kinds[r.id] ?? guess(r)"
                :options="KIND_OPTIONS"
                @update:model-value="(v: string) => (kinds[r.id] = v)"
              />
            </div>
            <ZenButton
              sm
              icon="mdi mdi-book-plus-outline"
              :disabled="!toAdd.length || busy"
              @click="add"
            >
              Add {{ toAdd.length }} to {{ show.name }}
            </ZenButton>
          </section>
          <p v-if="message" class="msg">{{ message }}</p>
        </template>
      </template>
    </div>
  </ZenPopover>
</template>

<script setup lang="ts">
// The references against a Codex show: a script's @ren is the show's Ren. Fill brings the
// entries' pictures, descriptions, voices and LoRAs in; placeholders the show doesn't have yet can
// start entries there. Either way the reference stays tied to its entry for the next fill.
import { computed, reactive, ref, shallowRef, watch } from "vue";
import { ZenButton, ZenPopover, ZenSelect } from "@nynxz/zenkit-ui";
import { KIND_ORDER, KINDS, type EntryKind, type Show } from "@/lib/codex";
import { linkOf } from "@/lib/codexFilms";
import { listShows, liveShows, loadShow, type ShowSummary } from "@/lib/codexStore";
import { addToCodex, fillFromCodex, matchRefs } from "@/lib/codexStudio";
import type { Project, Ref } from "@/lib/h3studio";

const props = defineProps<{ project: Project }>();

const SKIP = "skip";
const KIND_OPTIONS = [
  ...KIND_ORDER.map((k) => ({ value: k, label: KINDS[k].label })),
  { value: SKIP, label: "Leave out" },
];

const shows = ref<ShowSummary[]>([]);
const showId = ref("");
const show = shallowRef<Show | null>(null);
const loading = ref(false);
const busy = ref(false);
const message = ref("");
const kinds = reactive<Record<string, string>>({});
/** Bumped after a fill or an add, so the lists are worked out again. */
const tick = ref(0);

const found = computed(() => {
  void tick.value;
  return show.value ? matchRefs(props.project, show.value) : { matches: [], missing: [] };
});
/** A placeholder whose voice is in the cast is someone; anything else is a thing until told. */
const guess = (r: Ref): EntryKind =>
  props.project.cast?.some((v) => v.ref === r.id)
    ? "character"
    : r.kind === "audio"
      ? "sound"
      : "prop";
const toAdd = computed(() =>
  found.value.missing
    .map((r) => ({ ref: r, kind: (kinds[r.id] ?? guess(r)) as EntryKind | typeof SKIP }))
    .filter((x): x is { ref: Ref; kind: EntryKind } => x.kind !== SKIP),
);

async function open(toggle: () => void) {
  toggle();
  message.value = "";
  loading.value = true;
  shows.value = await listShows();
  const linked = linkOf(props.project)?.show;
  if (!shows.value.some((s) => s.id === showId.value))
    showId.value = shows.value.find((s) => s.id === linked)?.id ?? shows.value[0]?.id ?? "";
  await load();
}
async function load() {
  loading.value = true;
  show.value = showId.value
    ? (liveShows.get(showId.value)?.show ?? (await loadShow(showId.value))?.show ?? null)
    : null;
  loading.value = false;
  tick.value++;
}
watch(showId, (id, before) => {
  if (before !== undefined && id !== before) void load();
});

function fill() {
  if (!show.value) return;
  const changed = fillFromCodex(props.project, show.value);
  message.value = changed.length
    ? `Filled ${changed.join(", ")} from ${show.value.name}.`
    : "Everything is already up to date.";
  tick.value++;
}
async function add() {
  if (!show.value || !toAdd.value.length) return;
  busy.value = true;
  try {
    const n = await addToCodex(props.project, showId.value, toAdd.value);
    await load();
    message.value = `Added ${n} entr${n === 1 ? "y" : "ies"} to ${show.value?.name}. Give them pictures in the Codex, then fill.`;
  } catch (e) {
    message.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}
</script>

<style scoped>
.pop {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 300px;
  max-height: 460px;
  padding: 10px;
  overflow-y: auto;
  color: var(--zen-text, #e5e5ea);
  font-size: 12px;
}
section {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
h4 {
  margin: 4px 0 2px;
  color: var(--zen-muted, #9aa0aa);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 24px;
}
.mention {
  font-family: ui-monospace, monospace;
}
.kind {
  color: var(--zen-muted, #9aa0aa);
  font-size: 10.5px;
}
.kindpick {
  width: 110px;
}
.grow {
  flex: 1;
  min-width: 0;
}
.ellipsis {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.soft {
  margin: 0;
  color: var(--zen-muted, #9aa0aa);
}
.msg {
  margin: 0;
  color: var(--zen-text, #e5e5ea);
}
</style>
