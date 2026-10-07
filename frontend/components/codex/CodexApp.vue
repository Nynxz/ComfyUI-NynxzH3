<template>
  <div ref="rootEl" class="codex" @keydown="onKey">
    <ZenPeek />
    <header class="top">
      <i class="mdi mdi-book-open-page-variant-outline logo" />
      <ZenSelect
        v-if="shows.length"
        class="showpick"
        size="sm"
        :model-value="current?.show.id ?? ''"
        :options="showOptions"
        placeholder="Pick a show"
        @update:model-value="openShow"
      />
      <ZenIconButton icon="mdi mdi-plus" size="sm" title="New show" @click="creating = true" />
      <ZenIconButton
        v-if="current"
        icon="mdi mdi-undo"
        size="sm"
        title="Undo (Ctrl+Z)"
        :disabled="!current.state.canUndo"
        @click="current.undo()"
      />
      <ZenIconButton
        v-if="current"
        icon="mdi mdi-redo"
        size="sm"
        title="Redo (Ctrl+Shift+Z)"
        :disabled="!current.state.canRedo"
        @click="current.redo()"
      />
      <span v-if="current" class="status" :class="{ bad: current.state.error }">
        {{ current.state.error ? "Not saved" : current.state.saving ? "Saving…" : "Saved" }}
      </span>
      <span class="grow" />
      <ZenInput v-if="current" v-model="query" sm class="search" placeholder="Search" />
      <ZenButton v-if="current" size="sm" variant="primary" icon="mdi mdi-plus" @click="onNew">
        {{ newLabel }}
      </ZenButton>
    </header>

    <div v-if="creating || (!current && !loading)" class="start">
      <ZenEmpty
        :title="shows.length ? 'New show' : 'Start a show'"
        icon="mdi mdi-book-open-page-variant-outline"
      >
        Everything a show is made of — characters, places, props, looks and sounds, how they relate,
        and its episodes — kept once and used everywhere.
        <template #actions>
          <form class="newshow" @submit.prevent="create">
            <ZenInput v-model="newName" placeholder="Show name" />
            <ZenButton variant="primary" :disabled="!newName.trim()" @click="create"
              >Create</ZenButton
            >
            <ZenButton v-if="current" @click="creating = false">Cancel</ZenButton>
          </form>
        </template>
      </ZenEmpty>
    </div>

    <ZenSplit
      v-else-if="current"
      class="body"
      gutter="gap"
      :panes="[{ size: 196, min: 150, max: 300, collapsible: true }, { min: 360 }]"
    >
      <template #pane-0>
        <nav class="nav panel zen-scroll" aria-label="Codex">
          <span class="navhead">Show</span>
          <button
            v-for="p in SHOW_PAGES"
            :key="p.id"
            type="button"
            class="sec"
            :class="{ on: p.id === page }"
            @click="go(p.id)"
          >
            <i class="mdi" :class="p.icon" />
            <span class="lbl">{{ p.label }}</span>
            <span v-if="p.id === 'episodes'" class="count">{{ current.show.episodes.length }}</span>
          </button>

          <span class="navhead">Codex</span>
          <button
            v-for="s in sections"
            :key="s.id"
            type="button"
            class="sec"
            :class="{ on: s.id === page, drop: s.id === 'all' && overTarget === '' }"
            :title="s.id === 'all' ? 'Drop here to take things out of their folder' : undefined"
            @click="go(s.id)"
            @dragover="s.id === 'all' && onDragOver('', $event)"
            @dragleave="overTarget = null"
            @drop="s.id === 'all' && onDrop('', $event)"
          >
            <i class="mdi" :class="s.icon" :style="{ color: s.color }" />
            <span class="lbl">{{ s.label }}</span>
            <span class="count">{{ s.count }}</span>
          </button>

          <div class="navhead row">
            <span>Folders</span>
            <ZenIconButton
              icon="mdi mdi-folder-plus-outline"
              size="sm"
              :title="folderPage ? `New folder in ${nameOf(folderPage)}` : 'New folder'"
              @click="newFolder(folderPage ?? '')"
            />
          </div>
          <div
            v-for="f in folderRows"
            :key="f.path"
            class="sec folder"
            :class="{
              on: page === `f:${f.path}`,
              drop: overTarget === f.path,
              dragging: drag?.folder === f.path,
            }"
            :style="{ paddingLeft: `${8 + f.depth * 14}px` }"
            role="button"
            tabindex="0"
            draggable="true"
            :title="f.path"
            @click="go(`f:${f.path}`)"
            @keydown.enter.self="go(`f:${f.path}`)"
            @contextmenu.prevent="folderMenuFor(f.path, $event)"
            @dragstart="startDrag({ folder: f.path }, $event)"
            @dragend="endDrag"
            @dragover="onDragOver(f.path, $event)"
            @dragleave="overTarget = null"
            @drop="onDrop(f.path, $event)"
          >
            <button
              v-if="f.hasChildren"
              type="button"
              class="chev"
              :aria-label="f.open ? 'Collapse' : 'Expand'"
              @click.stop="toggleOpen(f.path)"
            >
              <i class="mdi" :class="f.open ? 'mdi-chevron-down' : 'mdi-chevron-right'" />
            </button>
            <span v-else class="chev" />
            <i
              class="mdi"
              :class="page === `f:${f.path}` ? 'mdi-folder-open-outline' : 'mdi-folder-outline'"
            />
            <input
              v-if="renaming === f.path"
              v-focus
              class="rename"
              :value="nameOf(f.path)"
              aria-label="Folder name"
              @click.stop
              @keydown.enter.stop="($event.target as HTMLInputElement).blur()"
              @keydown.escape.stop="renaming = null"
              @blur="finishRename(f.path, ($event.target as HTMLInputElement).value)"
            />
            <span v-else class="lbl">{{ nameOf(f.path) }}</span>
            <span class="count">{{ f.count }}</span>
          </div>
          <p v-if="!current.show.folders.length" class="hint">
            Folders are yours to arrange: make one, then drag cards onto it.
          </p>
        </nav>
      </template>

      <template #pane-1>
        <CodexOverview v-if="page === 'overview'" :show="current.show" @go="go" />
        <CodexEpisodes
          v-else-if="page === 'episodes'"
          v-model:selected="episodeId"
          :show="current.show"
        />
        <ZenSplit
          v-else
          class="work"
          gutter="gap"
          :panes="[{ min: 260 }, { size: 360, min: 300, max: 640 }]"
        >
          <template #pane-0>
            <CodexMap v-if="page === 'map'" v-model:selected="selectedId" :show="current.show" />
            <div
              v-else
              class="list panel"
              :class="{ mediaover: mediaOver }"
              @dragover="onListDragOver"
              @dragleave="mediaOver = false"
              @drop="onListDrop"
            >
              <div class="listhead">
                <div class="crumbs">
                  <template v-if="folderPage !== null">
                    <button type="button" class="crumb" @click="go('all')">Everything</button>
                    <template v-for="c in crumbs" :key="c.path">
                      <i class="mdi mdi-chevron-right" />
                      <button type="button" class="crumb" @click="go(`f:${c.path}`)">
                        {{ c.name }}
                      </button>
                    </template>
                  </template>
                  <b v-else>{{ listTitle }}</b>
                </div>
                <span class="grow" />
                <ZenToggleGroup v-model="layout.mode" size="sm" :options="MODES" />
                <ZenToggleGroup
                  v-if="layout.mode === 'grid'"
                  v-model="layout.size"
                  size="sm"
                  :options="SIZES"
                />
              </div>
              <span v-if="listHint" class="soft hintline">{{ listHint }}</span>

              <div class="items zen-scroll" :class="[layout.mode, `size-${layout.size}`]">
                <button
                  v-for="sub in subfolders"
                  :key="sub"
                  type="button"
                  class="item folder"
                  :class="{ drop: overTarget === sub }"
                  draggable="true"
                  :title="`Open ${nameOf(sub)}`"
                  @click="go(`f:${sub}`)"
                  @contextmenu.prevent="folderMenuFor(sub, $event)"
                  @dragstart="startDrag({ folder: sub }, $event)"
                  @dragend="endDrag"
                  @dragover.stop="onDragOver(sub, $event)"
                  @dragleave="overTarget = null"
                  @drop.stop="onDrop(sub, $event)"
                >
                  <span class="thumb fthumb"><i class="mdi mdi-folder" /></span>
                  <span class="text">
                    <span class="cname">{{ nameOf(sub) }}</span>
                    <span class="cmeta">{{ countIn(current.show, sub) }} inside</span>
                  </span>
                </button>
                <button
                  v-for="e in visible"
                  :key="e.id"
                  type="button"
                  class="item"
                  :class="{ on: e.id === selectedId, dragging: drag?.entry === e.id }"
                  :style="{ '--c': KINDS[e.kind].color }"
                  draggable="true"
                  :title="e.name"
                  @click="selectedId = e.id"
                  @dragstart="startDrag({ entry: e.id }, $event)"
                  @dragend="endDrag"
                >
                  <span class="thumb">
                    <MediaThumb :media="coverOf(e)" :badge="false" :label="e.name" />
                    <span v-if="e.variants.length && layout.mode === 'grid'" class="vars">
                      +{{ e.variants.length }}
                    </span>
                  </span>
                  <span class="text">
                    <span class="cname">{{ e.name }}</span>
                    <span class="cmeta">
                      <i class="mdi" :class="KINDS[e.kind].icon" />
                      <span class="handle">{{ mentionOf(e) }}</span>
                    </span>
                  </span>
                  <span v-if="layout.mode === 'list'" class="lcol">{{ e.folder || "—" }}</span>
                  <span v-if="layout.mode === 'list'" class="lcol narrow">
                    <template v-if="e.links.length"
                      ><i class="mdi mdi-link-variant" />{{ e.links.length }}</template
                    >
                  </span>
                </button>
                <button type="button" class="item new" @click="onNew">
                  <span class="thumb fthumb"><i class="mdi mdi-plus" /></span>
                  <span class="text"
                    ><span class="cname">{{ newLabel }}</span></span
                  >
                </button>
              </div>
              <div v-if="query && !visible.length" class="none">
                <span class="soft">Nothing matches “{{ query }}”.</span>
                <ZenButton size="sm" icon="mdi mdi-plus" @click="createFromQuery">
                  Make {{ query.trim() }}
                  {{ page in KINDS ? `(${KINDS[page as EntryKind].label.toLowerCase()})` : "" }}
                </ZenButton>
              </div>
              <div v-if="mediaOver" class="dropmask">
                <i class="mdi mdi-tray-arrow-down" />
                Drop pictures to make a {{ dropKindLabel }} from each
              </div>
            </div>
          </template>
          <template #pane-1>
            <div class="detail panel">
              <CodexEntry
                v-if="selected"
                :key="selected.id"
                :entry="selected"
                :show="current.show"
                @open="selectedId = $event"
                @remove="remove(selected.id)"
                @duplicate="duplicate(selected)"
              />
              <ZenEmpty
                v-else-if="selectedEpisode"
                :title="episodeName(selectedEpisode)"
                icon="mdi mdi-filmstrip-box-multiple"
              >
                {{ selectedEpisode.logline || "No logline yet." }}
                <template #actions>
                  <ZenButton @click="openEpisode(selectedEpisode.id)">Open the episode</ZenButton>
                </template>
              </ZenEmpty>
              <ZenEmpty v-else title="Nothing selected" icon="mdi mdi-cursor-default-click-outline">
                Pick something, or make something new.
              </ZenEmpty>
            </div>
          </template>
        </ZenSplit>
      </template>
    </ZenSplit>
    <ZenContextMenu ref="kindMenu" :items="kindItems" />
    <ZenContextMenu ref="folderMenu" :items="folderItems" />
    <div v-if="toast" class="toast" role="status">
      <span>{{ toast.text }}</span>
      <button type="button" @click="undoToast">Undo</button>
    </div>
  </div>
</template>

<script setup lang="ts">
// The Codex panel: a show's own pages (overview, episodes, a map of how everything relates), its
// entries — characters, places, props, looks and sounds — by kind or in folders you arrange by
// dragging, as a grid or a list. Opens as a ZenKit panel from the taskbar, or from ComfyUI's
// sidebar without ZenKit (lib/codexOpen.ts).
import {
  computed,
  nextTick,
  onBeforeUnmount,
  reactive,
  ref,
  shallowRef,
  watch,
  type Directive,
} from "vue";
import {
  ZenButton,
  ZenContextMenu,
  ZenEmpty,
  ZenIconButton,
  ZenInput,
  ZenPeek,
  ZenSelect,
  ZenSplit,
  ZenToggleGroup,
  type ContextMenuItem,
} from "@nynxz/zenkit-ui";
import {
  KIND_ORDER,
  KINDS,
  coverOf,
  episodeName,
  freeHandle,
  handleOf,
  mentionOf,
  newEntry,
  newEpisode,
  removeEntry,
  uid,
  uploadsOf,
  type Entry,
  type EntryKind,
} from "@/lib/codex";
import {
  addFolder,
  childrenOf,
  countIn,
  deleteFolder,
  moveFolder,
  nameOf,
  renameFolder,
} from "@/lib/codexFolders";
import { createShow, listShows, loadShow, useShow, type ShowSummary } from "@/lib/codexStore";
import { hasMediaDrop, mediaKind, readMediaDrop, uploadOrReuse } from "@/framework";
import CodexEntry from "./CodexEntry.vue";
import CodexEpisodes from "./CodexEpisodes.vue";
import CodexMap from "./CodexMap.vue";
import CodexOverview from "./CodexOverview.vue";
import MediaThumb from "@/components/h3studio/MediaThumb.vue";

const vFocus: Directive<HTMLInputElement> = {
  mounted: (el) => {
    el.focus();
    el.select();
  },
};

const store = {
  get(key: string): string | null {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set(key: string, value: string) {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* not remembered */
    }
  },
};

const SHOW_PAGES = [
  { id: "overview", label: "Overview", icon: "mdi mdi-text-box-outline" },
  { id: "episodes", label: "Episodes", icon: "mdi mdi-filmstrip-box-multiple" },
  { id: "map", label: "Map", icon: "mdi mdi-graph-outline" },
];
const MODES = [
  { value: "grid", label: "", icon: "mdi mdi-view-grid-outline", title: "Cards" },
  { value: "list", label: "", icon: "mdi mdi-view-list-outline", title: "List" },
];
const SIZES = [
  { value: "s", label: "S" },
  { value: "m", label: "M" },
  { value: "l", label: "L" },
];

/** "overview" | "episodes" | "map" | "all" | an entry kind | "f:<folder path>" */
const page = ref("all");
const shows = ref<ShowSummary[]>([]);
const current = shallowRef<ReturnType<typeof useShow> | null>(null);
const loading = ref(true);
const creating = ref(false);
const newName = ref("");
const selectedId = ref("");
const episodeId = ref("");
const query = ref("");

const layout = reactive({ mode: "grid", size: "m" });
try {
  Object.assign(layout, JSON.parse(store.get("nynxz.codex.layout") ?? "{}"));
} catch {
  /* defaults */
}
watch(layout, () => store.set("nynxz.codex.layout", JSON.stringify(layout)));

const showOptions = computed(() => shows.value.map((s) => ({ value: s.id, label: s.name })));
const folderPage = computed(() => (page.value.startsWith("f:") ? page.value.slice(2) : null));
const isList = computed(
  () => page.value === "all" || page.value in KINDS || folderPage.value !== null,
);
const go = (p: string) => (page.value = p);
// Searching from a page with no list (the overview, episodes, the map) shows the results in
// Everything.
watch(query, (q) => {
  if (q && !isList.value) page.value = "all";
});

async function openShow(id: string) {
  const loaded = await loadShow(id);
  if (!loaded) return;
  current.value?.stop();
  current.value = useShow(loaded);
  selectedId.value = loaded.show.entries[0]?.id ?? "";
  episodeId.value = "";
  creating.value = false;
  if (page.value.startsWith("f:")) page.value = "all";
  store.set("nynxz.codex.last", id);
}
async function refresh() {
  shows.value = await listShows();
}
async function create() {
  const name = newName.value.trim();
  if (!name) return;
  const show = await createShow(name);
  newName.value = "";
  await refresh();
  await openShow(show.id);
  page.value = "overview";
}
void (async () => {
  await refresh();
  const last = store.get("nynxz.codex.last");
  const first = shows.value.find((s) => s.id === last) ?? shows.value[0];
  if (first) await openShow(first.id);
  loading.value = false;
})();
onBeforeUnmount(() => current.value?.stop());

const entries = computed(() => current.value?.show.entries ?? []);
const sections = computed(() => [
  {
    id: "all",
    label: "Everything",
    icon: "mdi mdi-view-grid-outline",
    color: undefined,
    count: entries.value.length,
  },
  ...KIND_ORDER.map((k) => ({
    id: k as string,
    label: KINDS[k].plural,
    icon: KINDS[k].icon,
    color: KINDS[k].color,
    count: entries.value.filter((e) => e.kind === k).length,
  })),
]);

// --- folders -------------------------------------------------------------------------------------
const closed = reactive(
  new Set<string>(JSON.parse(store.get("nynxz.codex.closed") ?? "[]") as string[]),
);
const toggleOpen = (path: string) => {
  if (closed.has(path)) closed.delete(path);
  else closed.add(path);
  store.set("nynxz.codex.closed", JSON.stringify([...closed]));
};
const folderRows = computed(() => {
  const show = current.value?.show;
  if (!show) return [];
  const rows: {
    path: string;
    depth: number;
    hasChildren: boolean;
    open: boolean;
    count: number;
  }[] = [];
  const walk = (parent: string, depth: number) => {
    for (const path of childrenOf(show, parent)) {
      const kids = childrenOf(show, path).length > 0;
      const open = !closed.has(path);
      rows.push({ path, depth, hasChildren: kids, open, count: countIn(show, path) });
      if (kids && open) walk(path, depth + 1);
    }
  };
  walk("", 0);
  return rows;
});
const subfolders = computed(() =>
  current.value && folderPage.value !== null && !query.value
    ? childrenOf(current.value.show, folderPage.value)
    : [],
);
// A folder that's gone (renamed, moved, deleted) takes its page with it.
watch(
  () => current.value?.show.folders.slice(),
  (folders) => {
    if (folderPage.value !== null && folders && !folders.includes(folderPage.value))
      page.value = "all";
  },
);
const crumbs = computed(() => {
  const parts = (folderPage.value ?? "").split("/").filter(Boolean);
  return parts.map((name, i) => ({ name, path: parts.slice(0, i + 1).join("/") }));
});

const renaming = ref<string | null>(null);
function newFolder(parent: string) {
  if (!current.value) return;
  const path = addFolder(current.value.show, parent);
  if (parent) closed.delete(parent);
  renaming.value = path;
}
function finishRename(path: string, name: string) {
  if (renaming.value !== path || !current.value) return;
  renaming.value = null;
  const to = renameFolder(current.value.show, path, name);
  if (page.value === `f:${path}`) page.value = `f:${to}`;
}
const folderMenu = ref<InstanceType<typeof ZenContextMenu> | null>(null);
const menuFolder = ref("");
const folderItems = computed<ContextMenuItem[]>(() => [
  { label: "Open", icon: "mdi mdi-folder-open-outline", run: () => go(`f:${menuFolder.value}`) },
  {
    label: "Rename",
    icon: "mdi mdi-rename-outline",
    run: () => (renaming.value = menuFolder.value),
  },
  {
    label: "New folder inside",
    icon: "mdi mdi-folder-plus-outline",
    run: () => newFolder(menuFolder.value),
  },
  "-",
  {
    label: "Delete folder",
    icon: "mdi mdi-folder-remove-outline",
    hint: "what's inside moves up",
    danger: true,
    run: () => {
      if (!current.value) return;
      const path = menuFolder.value;
      deleteFolder(current.value.show, path);
      if (page.value === `f:${path}` || page.value.startsWith(`f:${path}/`)) page.value = "all";
    },
  },
]);
function folderMenuFor(path: string, e: MouseEvent) {
  menuFolder.value = path;
  folderMenu.value?.show(e);
}

// --- drag and drop: cards and folders onto folders -------------------------------------------------
const drag = ref<{ entry?: string; folder?: string } | null>(null);
const overTarget = ref<string | null>(null);
function startDrag(what: { entry?: string; folder?: string }, e: DragEvent) {
  drag.value = what;
  e.dataTransfer?.setData("application/x-nynxz-codex", JSON.stringify(what));
  if (e.dataTransfer) e.dataTransfer.effectAllowed = "move";
}
function endDrag() {
  drag.value = null;
  overTarget.value = null;
}
function onDragOver(target: string, e: DragEvent) {
  const d = drag.value;
  if (!d) return;
  if (d.folder !== undefined && (target === d.folder || target.startsWith(`${d.folder}/`))) return;
  e.preventDefault();
  if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
  overTarget.value = target;
}
function onDrop(target: string, e: DragEvent) {
  const d = drag.value;
  const show = current.value?.show;
  if (!d || !show) return;
  e.preventDefault();
  if (d.entry) {
    const entry = show.entries.find((x) => x.id === d.entry);
    if (entry) entry.folder = target;
  } else if (d.folder !== undefined) {
    const to = moveFolder(show, d.folder, target);
    if (page.value === `f:${d.folder}`) page.value = `f:${to}`;
  }
  endDrag();
}

// --- the list --------------------------------------------------------------------------------------
const listTitle = computed(() =>
  page.value === "all"
    ? "Everything"
    : page.value in KINDS
      ? KINDS[page.value as EntryKind].plural
      : "",
);
const listHint = computed(() =>
  folderPage.value !== null
    ? ""
    : page.value === "all"
      ? "Who, where, and how it looks."
      : page.value in KINDS
        ? KINDS[page.value as EntryKind].hint
        : "",
);
const visible = computed(() => {
  const words = query.value.toLowerCase().split(/\s+/).filter(Boolean);
  const folder = folderPage.value;
  return entries.value
    .filter((e) =>
      folder !== null
        ? query.value
          ? e.folder === folder || e.folder.startsWith(`${folder}/`)
          : e.folder === folder
        : page.value === "all" || e.kind === page.value,
    )
    .filter((e) => {
      const hay = `${e.name} ${e.handle} ${e.tags.join(" ")} ${e.prompt}`.toLowerCase();
      return words.every((w) => hay.includes(w));
    })
    .sort(
      (a, b) =>
        KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind) || a.name.localeCompare(b.name),
    );
});
const selected = computed(() => entries.value.find((e) => e.id === selectedId.value));
const selectedEpisode = computed(() =>
  current.value?.show.episodes.find((e) => e.id === selectedId.value),
);

// --- making things ---------------------------------------------------------------------------------
const newLabel = computed(() =>
  page.value === "episodes"
    ? "New episode"
    : page.value in KINDS
      ? `New ${KINDS[page.value as EntryKind].label.toLowerCase()}`
      : "New entry",
);
const kindMenu = ref<InstanceType<typeof ZenContextMenu> | null>(null);
const kindItems = computed<ContextMenuItem[]>(() =>
  KIND_ORDER.map((k) => ({ label: KINDS[k].label, icon: KINDS[k].icon, run: () => add(k) })),
);
function onNew(e: MouseEvent) {
  if (page.value === "episodes") {
    if (!current.value) return;
    const ep = newEpisode(current.value.show);
    current.value.show.episodes.push(ep);
    episodeId.value = ep.id;
  } else if (page.value in KINDS) add(page.value as EntryKind);
  else kindMenu.value?.show(e);
}
function add(kind: EntryKind, name = "", focus = true): Entry | undefined {
  const show = current.value?.show;
  if (!show) return;
  const entry = newEntry(kind, name);
  entry.handle = freeHandle(show, entry.handle);
  entry.folder = folderPage.value ?? "";
  show.entries.push(entry);
  selectedId.value = entry.id;
  if (page.value in KINDS && page.value !== kind) page.value = kind;
  // A new entry is named first: the name is ready to type over.
  if (focus)
    void nextTick(() => {
      const input = rootEl.value?.querySelector<HTMLInputElement>(".entry input.name");
      input?.focus();
      input?.select();
    });
  return entry;
}
const dropKind = computed<EntryKind>(() =>
  page.value in KINDS ? (page.value as EntryKind) : "character",
);
const dropKindLabel = computed(() => KINDS[dropKind.value].label.toLowerCase());
function createFromQuery() {
  const name = query.value.trim();
  if (!name) return;
  query.value = "";
  add(dropKind.value, name);
}

// --- deleting, with a way back -------------------------------------------------------------------
const toast = ref<{ text: string } | null>(null);
let toastTimer = 0;
function remove(id: string) {
  if (!current.value) return;
  const list = visible.value;
  const i = list.findIndex((e) => e.id === id);
  const name = current.value.show.entries.find((e) => e.id === id)?.name ?? "it";
  removeEntry(current.value.show, id);
  selectedId.value = list.filter((e) => e.id !== id)[Math.max(0, i - 1)]?.id ?? "";
  toast.value = { text: `Deleted ${name}` };
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => (toast.value = null), 6000);
}
function undoToast() {
  current.value?.undo();
  toast.value = null;
}

// --- keys: undo and redo, and Delete for the selected card -----------------------------------------
const rootEl = ref<HTMLElement | null>(null);
const typing = (t: EventTarget | null) =>
  t instanceof HTMLElement && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
function onKey(e: KeyboardEvent) {
  if (!current.value || typing(e.target)) return;
  const mod = e.ctrlKey || e.metaKey;
  const key = e.key.toLowerCase();
  if (mod && key === "z") {
    e.preventDefault();
    e.stopPropagation();
    if (e.shiftKey) current.value.redo();
    else current.value.undo();
  } else if (mod && key === "y") {
    e.preventDefault();
    e.stopPropagation();
    current.value.redo();
  } else if ((e.key === "Delete" || e.key === "Backspace") && selected.value && isList.value) {
    e.preventDefault();
    e.stopPropagation();
    remove(selected.value.id);
  }
}

// --- pictures dropped onto the list: an entry from each ------------------------------------------
const mediaOver = ref(false);
function onListDragOver(e: DragEvent) {
  if (drag.value) {
    if (folderPage.value !== null) onDragOver(folderPage.value, e);
    return;
  }
  if (!hasMediaDrop(e)) return;
  e.preventDefault();
  mediaOver.value = true;
}
async function onListDrop(e: DragEvent) {
  if (drag.value) {
    if (folderPage.value !== null) onDrop(folderPage.value, e);
    return;
  }
  if (!hasMediaDrop(e) || !current.value) return;
  e.preventDefault();
  mediaOver.value = false;
  const media = await readMediaDrop(e, uploadsOf(current.value.show.id), uploadOrReuse);
  let last: Entry | undefined;
  for (const m of media) {
    const file = m.split("/").pop() ?? "";
    const name = file
      .replace(/\.[^.]+$/, "")
      .replace(/[_-]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    last = add(mediaKind(m) === "audio" ? "sound" : dropKind.value, name, false);
    if (last) last.pictures.push({ media: m, label: "" });
  }
  if (last) selectedId.value = last.id;
}
function duplicate(e: Entry) {
  const show = current.value?.show;
  if (!show) return;
  const copy: Entry = {
    ...(JSON.parse(JSON.stringify(e)) as Entry),
    id: uid(),
    name: `${e.name} copy`,
    handle: freeHandle(show, handleOf(`${e.handle} copy`)),
    updated: Date.now(),
  };
  show.entries.push(copy);
  selectedId.value = copy.id;
}
function openEpisode(id: string) {
  episodeId.value = id;
  page.value = "episodes";
}
</script>

<style scoped>
.codex {
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  height: 100%;
  min-height: 0;
  padding: 8px;
  gap: 8px;
  background: var(--zen-bg, var(--comfy-menu-bg, #18181c));
  color: var(--zen-text, #e5e5ea);
  font-size: 12.5px;
}
.top {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.logo {
  color: var(--zen-accent, #6366f1);
  font-size: 18px;
}
.showpick {
  min-width: 160px;
  max-width: 260px;
}
.status {
  color: var(--zen-muted, #9aa0aa);
  font-size: 11px;
}
.status.bad {
  color: var(--zen-danger, #f87171);
}
.grow {
  flex: 1;
}
.search {
  width: 180px;
}
.start {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
}
.newshow {
  display: flex;
  gap: 6px;
}
.body,
.work {
  flex: 1;
  height: 100%;
  min-height: 0;
}
.panel {
  box-sizing: border-box;
  height: 100%;
  min-height: 0;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: var(--zen-radius, 8px);
  background: var(--zen-surface, #202026);
}
.nav {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 6px;
  overflow-y: auto;
}
.navhead {
  padding: 10px 8px 4px;
  color: var(--zen-muted, #9aa0aa);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.navhead:first-child {
  padding-top: 2px;
}
.navhead.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 6px;
  padding-bottom: 0;
}
.sec {
  display: flex;
  flex: none;
  align-items: center;
  gap: 7px;
  box-sizing: border-box;
  height: 30px;
  min-width: 0;
  padding: 0 8px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--zen-text, #e5e5ea);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.sec:hover {
  background: color-mix(in srgb, var(--zen-text, #e5e5ea) 6%, transparent);
}
.sec.on {
  background: color-mix(in srgb, var(--zen-accent, #6366f1) 20%, transparent);
  font-weight: 600;
}
.sec.drop {
  border-color: var(--zen-accent, #6366f1);
  border-style: dashed;
  background: color-mix(in srgb, var(--zen-accent, #6366f1) 12%, transparent);
}
.sec.dragging {
  opacity: 0.45;
}
.lbl {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.count {
  flex: none;
  color: var(--zen-muted, #9aa0aa);
  font-size: 11px;
}
.chev {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 14px;
  padding: 0;
  border: 0;
  background: none;
  color: var(--zen-muted, #9aa0aa);
  cursor: pointer;
}
.rename {
  flex: 1;
  min-width: 0;
  height: 22px;
  padding: 0 4px;
  border: 1px solid var(--zen-accent, #6366f1);
  border-radius: 4px;
  outline: 0;
  background: var(--zen-field-bg, var(--zen-input, #15151a));
  color: var(--zen-text, #e5e5ea);
  font: inherit;
}
.hint {
  margin: 4px 8px;
  color: var(--zen-muted, #9aa0aa);
  font-size: 11px;
  line-height: 1.4;
}
.list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px;
}
.listhead {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.listhead b {
  font-size: 14px;
}
.crumbs {
  display: flex;
  align-items: center;
  gap: 2px;
  min-width: 0;
  overflow: hidden;
  color: var(--zen-muted, #9aa0aa);
}
.crumb {
  padding: 2px 4px;
  overflow: hidden;
  border: 0;
  border-radius: 4px;
  background: none;
  color: var(--zen-text, #e5e5ea);
  font: inherit;
  font-weight: 600;
  white-space: nowrap;
  text-overflow: ellipsis;
  cursor: pointer;
}
.crumb:hover {
  background: color-mix(in srgb, var(--zen-text, #e5e5ea) 8%, transparent);
}
.soft {
  color: var(--zen-muted, #9aa0aa);
}
.hintline {
  margin-top: -2px;
}

/* --- items: one fixed-size card each in the grid, one row each in the list --- */
.items {
  --w: 148px;
  --h: 111px;
  display: grid;
  flex: 1;
  align-content: start;
  gap: 10px;
  min-height: 0;
  overflow-y: auto;
  padding: 2px;
}
.items.size-s {
  --w: 112px;
  --h: 84px;
}
.items.size-l {
  --w: 200px;
  --h: 150px;
}
.items.grid {
  grid-template-columns: repeat(auto-fill, var(--w));
  grid-auto-rows: calc(var(--h) + 44px);
}
.items.list {
  grid-template-columns: minmax(0, 1fr);
  grid-auto-rows: 44px;
  gap: 2px;
}
.item {
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  min-width: 0;
  padding: 0;
  overflow: hidden;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: var(--zen-radius, 8px);
  background: var(--zen-field-bg, var(--zen-input, #15151a));
  color: var(--zen-text, #e5e5ea);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.item:hover {
  border-color: color-mix(in srgb, var(--zen-accent, #6366f1) 50%, var(--zen-border, #34343c));
}
.item.on {
  border-color: var(--zen-accent, #6366f1);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--zen-accent, #6366f1) 35%, transparent);
}
.item.dragging {
  opacity: 0.45;
}
.item.drop {
  border-style: dashed;
  border-color: var(--zen-accent, #6366f1);
  background: color-mix(in srgb, var(--zen-accent, #6366f1) 12%, transparent);
}
.thumb {
  position: relative;
  flex: none;
  height: var(--h);
  border-bottom: 2px solid var(--c, transparent);
  background: var(--zen-media-bg, #111);
}
.thumb :deep(.mt) {
  width: 100%;
  height: 100%;
}
.fthumb {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--zen-muted, #9aa0aa);
  font-size: 30px;
}
.item.folder .fthumb {
  color: color-mix(in srgb, var(--zen-accent, #6366f1) 70%, var(--zen-text, #e5e5ea));
}
.item.new {
  border-style: dashed;
  background: transparent;
}
.item.new .fthumb {
  background: transparent;
  font-size: 24px;
}
.text {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
  min-width: 0;
  height: 42px;
  padding: 0 8px;
}
.cname {
  overflow: hidden;
  font-weight: 600;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.cmeta {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  overflow: hidden;
  color: var(--zen-muted, #9aa0aa);
  font-size: 11px;
  white-space: nowrap;
}
.cmeta > .mdi {
  flex: none;
  color: var(--c);
}
.handle {
  overflow: hidden;
  text-overflow: ellipsis;
}
.vars {
  position: absolute;
  right: 5px;
  bottom: 5px;
  padding: 1px 6px;
  border-radius: 999px;
  background: rgb(0 0 0 / 0.6);
  color: #fff;
  font-size: 10px;
}
/* list rows: a small square thumb, then the columns */
.items.list .item {
  flex-direction: row;
  align-items: center;
  border-radius: 6px;
}
.items.list .thumb {
  width: 42px;
  height: 100%;
  border-bottom: 0;
  border-right: 2px solid var(--c, transparent);
}
.items.list .fthumb {
  font-size: 20px;
}
.items.list .text {
  flex: 1;
}
.lcol {
  flex: 0 0 140px;
  min-width: 0;
  padding-right: 10px;
  overflow: hidden;
  color: var(--zen-muted, #9aa0aa);
  font-size: 11.5px;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.lcol.narrow {
  flex-basis: 42px;
}
.none {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.list {
  position: relative;
}
.list.mediaover {
  border-color: var(--zen-accent, #6366f1);
}
.dropmask {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-radius: inherit;
  background: color-mix(in srgb, var(--zen-accent, #6366f1) 22%, transparent);
  color: #fff;
  font-weight: 600;
  pointer-events: none;
}
.codex {
  position: relative;
}
.toast {
  position: absolute;
  bottom: 16px;
  left: 50%;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 10px 8px 14px;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: var(--zen-radius, 8px);
  background: var(--zen-surface, #202026);
  box-shadow: var(--zen-shadow-pop, 0 8px 24px rgb(0 0 0 / 0.4));
  transform: translateX(-50%);
}
.toast button {
  padding: 4px 10px;
  border: 0;
  border-radius: 6px;
  background: color-mix(in srgb, var(--zen-accent, #6366f1) 25%, transparent);
  color: var(--zen-text, #e5e5ea);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}
.detail {
  overflow: hidden;
}
</style>
