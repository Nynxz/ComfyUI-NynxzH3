<template>
  <div
    class="mt"
    :class="media ? kind : 'proxy'"
    :data-peek="media ? full : undefined"
    :data-peek-kind="media ? kind : undefined"
    :data-peek-label="label || undefined"
  >
    <div
      v-if="!media"
      class="placeholder"
      :title="label ? `@${label} has no picture yet` : 'No picture yet'"
    >
      <span v-if="label">{{ label.charAt(0).toUpperCase() }}</span>
      <i v-else class="mdi mdi-image-plus-outline" />
    </div>
    <video v-else-if="kind === 'video' && play" :src="full" muted playsinline autoplay loop />
    <img
      v-else-if="kind !== 'audio'"
      :src="failed ? full : thumb || full"
      alt=""
      draggable="false"
      loading="lazy"
      decoding="async"
      @error="failed = true"
    />
    <div v-else class="wave">
      <i class="mdi mdi-waveform" />
    </div>
    <span v-if="kind !== 'image' && badge" class="kind"
      ><i class="mdi" :class="kind === 'video' ? 'mdi-video-outline' : 'mdi-music-note'"
    /></span>
  </div>
</template>

<script setup lang="ts">
// A thumbnail for any media ref: a small cached picture (a video's first frame for videos), or a
// waveform tile for audio. `play` shows a video playing instead — the full file, so only where it
// is worth it (a hover preview). URLs are stable, so a re-render never re-downloads anything.
import { computed, ref, watch } from "vue";
import { mediaKind } from "@/framework";
import { stableUrl, thumbUrl } from "@/lib/h3studio";

const props = withDefaults(
  defineProps<{
    media: string;
    badge?: boolean;
    play?: boolean;
    /** A proxy (no media yet) shows its name's initial. */
    label?: string;
  }>(),
  { badge: true, play: false, label: "" },
);
const kind = computed(() => mediaKind(props.media));
const full = computed(() => stableUrl(props.media));
const thumb = computed(() => thumbUrl(props.media));
/** The thumbnail route couldn't make one (an odd file): show the file itself. */
const failed = ref(false);
watch(
  () => props.media,
  () => (failed.value = false),
);
</script>

<style scoped>
.mt {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: #0b0b0e;
}
.mt img,
.mt video {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
  pointer-events: none;
}
.placeholder {
  display: grid;
  place-items: center;
  width: 100%;
  height: 100%;
  box-sizing: border-box;
  border: 1.5px dashed color-mix(in srgb, var(--h3-text, #e5e5ea) 35%, transparent);
  border-radius: inherit;
  background: color-mix(in srgb, var(--h3-accent, #6366f1) 10%, var(--h3-bg, #18181c));
  color: var(--h3-muted, #9aa0aa);
  font-size: 18px;
  font-weight: 600;
}
.wave {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  background: linear-gradient(135deg, #2b3a55, #1d2436);
  color: #9db7ff;
  font-size: 22px;
}
.kind {
  position: absolute;
  right: 3px;
  bottom: 3px;
  display: grid;
  place-items: center;
  width: 16px;
  height: 16px;
  border-radius: 4px;
  background: rgb(0 0 0 / 65%);
  color: #fff;
  font-size: 11px;
}
</style>
