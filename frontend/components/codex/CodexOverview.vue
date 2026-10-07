<template>
  <div class="overview zen-scroll">
    <div class="col">
      <input v-model="doc.name" class="title" aria-label="Show name" />
      <ZenInput
        v-model="doc.logline"
        type="textarea"
        :rows="2"
        placeholder="The show in a sentence: who wants what, and what's in the way."
      />

      <div class="stats">
        <button
          v-for="s in stats"
          :key="s.id"
          type="button"
          class="stat"
          :style="{ '--c': s.color }"
          @click="emit('go', s.id)"
        >
          <i class="mdi" :class="s.icon" />
          <b>{{ s.count }}</b>
          <span>{{ s.label }}</span>
        </button>
      </div>

      <section>
        <h4>Show notes</h4>
        <ZenInput
          v-model="doc.notes"
          type="textarea"
          :rows="12"
          placeholder="The rules the whole show follows — tone, what we never show, running jokes, how episodes end…"
        />
      </section>

      <section class="context">
        <div class="ctxhead">
          <div>
            <h4>As context</h4>
            <p class="soft">
              The whole Codex as plain text — every entry, how they relate, the episodes — for a
              writing agent or a chat.
            </p>
          </div>
          <ZenButton icon="mdi mdi-content-copy" @click="copy">{{
            copied ? "Copied" : "Copy"
          }}</ZenButton>
        </div>
        <pre class="ctx zen-scroll">{{ context }}</pre>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
// A show's own page: its name, its logline, the notes the whole show follows, what's in it at a
// glance, and all of it as plain text for a writing agent.
import { computed, ref } from "vue";
import { ZenButton, ZenInput } from "@nynxz/zenkit-ui";
import { EPISODE_COLOR, KIND_ORDER, KINDS, showContext, type Show } from "@/lib/codex";

const props = defineProps<{ show: Show }>();
const emit = defineEmits<{ go: [page: string] }>();
/** The show, edited in place. */
const doc = computed(() => props.show);

const stats = computed(() => [
  {
    id: "episodes",
    label: "Episodes",
    icon: "mdi mdi-filmstrip-box-multiple",
    color: EPISODE_COLOR,
    count: doc.value.episodes.length,
  },
  ...KIND_ORDER.map((k) => ({
    id: k as string,
    label: KINDS[k].plural,
    icon: KINDS[k].icon,
    color: KINDS[k].color,
    count: doc.value.entries.filter((e) => e.kind === k).length,
  })),
]);

const context = computed(() => showContext(doc.value));
const copied = ref(false);
async function copy() {
  try {
    await navigator.clipboard.writeText(context.value);
    copied.value = true;
    window.setTimeout(() => (copied.value = false), 1500);
  } catch {
    /* the clipboard is unavailable; the text is on screen to select */
  }
}
</script>

<style scoped>
.overview {
  box-sizing: border-box;
  height: 100%;
  overflow-y: auto;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: var(--zen-radius, 8px);
  background: var(--zen-surface, #202026);
}
.col {
  display: flex;
  flex-direction: column;
  gap: 16px;
  box-sizing: border-box;
  max-width: 820px;
  margin: 0 auto;
  padding: 22px 20px 28px;
}
.title {
  width: 100%;
  padding: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--zen-text, #e5e5ea);
  font: inherit;
  font-size: 24px;
  font-weight: 700;
}
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
  gap: 8px;
}
.stat {
  display: grid;
  grid-template-columns: auto 1fr;
  align-items: center;
  gap: 2px 8px;
  padding: 10px 12px;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: var(--zen-radius, 8px);
  background: var(--zen-field-bg, var(--zen-input, #15151a));
  color: var(--zen-text, #e5e5ea);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.stat:hover {
  border-color: var(--c);
}
.stat .mdi {
  grid-row: span 2;
  color: var(--c);
  font-size: 20px;
}
.stat b {
  font-size: 17px;
}
.stat span {
  color: var(--zen-muted, #9aa0aa);
  font-size: 11px;
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
  margin: 0;
  color: var(--zen-muted, #9aa0aa);
  font-size: 11.5px;
}
.ctxhead {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}
.ctx {
  max-height: 260px;
  margin: 0;
  padding: 10px 12px;
  overflow: auto;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: var(--zen-radius, 8px);
  background: var(--zen-field-bg, var(--zen-input, #15151a));
  color: var(--zen-text, #e5e5ea);
  font-size: 11.5px;
  line-height: 1.5;
  white-space: pre-wrap;
}
</style>
