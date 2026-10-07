<template>
  <div class="summary">
    <div class="card">
      <header class="head">
        <i class="mdi mdi-movie-open-star-outline" />
        <div class="title">
          <b>H3 Studio is open in a panel</b>
          <span class="meta">
            {{ project.scenes.length }} scene{{ project.scenes.length === 1 ? "" : "s" }} ·
            {{ shots }} shot{{ shots === 1 ? "" : "s" }} · {{ formatTime(total) }}
          </span>
        </div>
        <ZenButton variant="primary" icon="mdi mdi-open-in-new" @click="emit('focus')">
          Show it
        </ZenButton>
      </header>
      <div class="film">
        <div
          v-for="(s, i) in project.scenes"
          :key="s.id"
          class="seg"
          :class="{ on: i === project.active }"
          :style="{ flex: s.seconds }"
          :title="`Scene ${i + 1}${s.title ? ` · ${s.title}` : ''} · ${s.seconds.toFixed(2)}s`"
        >
          <span class="n">{{ i + 1 }}</span>
          <span v-if="s.title" class="name">{{ s.title }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// What the node shows while its studio is popped out: a card with the film at a glance (its
// scenes, to scale) and the way back to the panel.
import { computed } from "vue";
import { ZenButton } from "@nynxz/zenkit-ui";
import { formatTime, type Project } from "@/lib/h3studio";

const props = defineProps<{ project: Project }>();
const emit = defineEmits<{ focus: [] }>();
const total = computed(() => props.project.scenes.reduce((sum, s) => sum + s.seconds, 0));
const shots = computed(() => props.project.scenes.reduce((n, s) => n + s.shots.length, 0));
</script>

<style scoped>
.summary {
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  height: 100%;
  padding: 8px;
  border-radius: var(--zen-radius, 8px);
  background: var(--zen-bg, var(--comfy-menu-bg, #18181c));
  color: var(--zen-text, #e5e5ea);
  font-size: 12px;
}
.card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  box-sizing: border-box;
  width: min(100%, 560px);
  padding: 14px;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: var(--zen-radius, 8px);
  background: var(--zen-surface, #202026);
}
.head {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.head > .mdi {
  color: var(--zen-accent, #6366f1);
  font-size: 22px;
}
.title {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.title b {
  font-size: 12.5px;
}
.meta {
  color: var(--zen-muted, #9aa0aa);
  font-size: 11px;
}
.film {
  display: flex;
  gap: 3px;
  height: 34px;
}
.seg {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 22px;
  overflow: hidden;
  padding: 0 8px;
  border: 1px solid var(--zen-border, #34343c);
  border-radius: 6px;
  background: var(--zen-field-bg, var(--zen-input, #15151a));
  color: var(--zen-muted, #9aa0aa);
  font-size: 11px;
}
.seg.on {
  border-color: var(--zen-accent, #6366f1);
  background: color-mix(in srgb, var(--zen-accent, #6366f1) 16%, var(--zen-input, #15151a));
  color: var(--zen-text, #e5e5ea);
}
.n {
  font-weight: 700;
}
.name {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
</style>
