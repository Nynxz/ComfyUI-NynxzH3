<template>
  <span class="vec">
    <label v-for="(axis, i) in AXES" :key="axis" :title="axis">
      <span class="ax">{{ axis }}</span>
      <ZenNumber
        :model-value="modelValue[i] ?? 0"
        size="sm"
        :step="step"
        :precision="2"
        @update:model-value="set(i, $event)"
      />
    </label>
  </span>
</template>

<script setup lang="ts">
// Three numbers for a point, a size or a direction: x, y, z.
import { ZenNumber } from "@nynxz/zenkit-ui";
import type { Vec } from "@/lib/greybox";

const props = withDefaults(defineProps<{ modelValue: Vec; step?: number }>(), { step: 0.05 });
const emit = defineEmits<{ "update:modelValue": [Vec] }>();
const AXES = ["x", "y", "z"];
function set(i: number, v: number) {
  const next = [...props.modelValue] as Vec;
  next[i] = v;
  emit("update:modelValue", next);
}
</script>

<style scoped>
.vec {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 4px;
  min-width: 0;
}
label {
  display: flex;
  align-items: center;
  gap: 3px;
  min-width: 0;
}
.ax {
  color: var(--h3-muted, #9aa0aa);
  font-size: 10.5px;
}
</style>
