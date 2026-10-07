<template>
  <span class="ref">
    <input
      :value="text"
      :list="listId"
      spellcheck="false"
      :placeholder="placeholder"
      @change="commit(($event.target as HTMLInputElement).value)"
      @keydown.enter="($event.target as HTMLInputElement).blur()"
    />
    <datalist :id="listId">
      <option v-for="o in options" :key="o" :value="o" />
    </datalist>
  </span>
</template>

<script setup lang="ts">
// Where something is or looks: a point ("1.2, 0, -3"), a mark's name, an actor ("@ren"), or —
// for a camera — a set camera's name. Typed; the list offers the names that exist.
import { computed, useId } from "vue";
import { isVec, type Ref } from "@/lib/greybox";

const props = defineProps<{
  modelValue: Ref | undefined;
  options: string[];
  placeholder?: string;
}>();
const emit = defineEmits<{ "update:modelValue": [Ref | null] }>();
const listId = `gbref-${useId()}`;
const text = computed(() =>
  props.modelValue === undefined
    ? ""
    : isVec(props.modelValue)
      ? props.modelValue.map((v) => +v.toFixed(3)).join(", ")
      : props.modelValue,
);
function commit(raw: string) {
  const v = raw.trim();
  if (!v) return emit("update:modelValue", null);
  const nums = v.split(/[\s,]+/).map(Number);
  if (nums.length === 3 && nums.every((n) => Number.isFinite(n)))
    return emit("update:modelValue", nums as [number, number, number]);
  emit("update:modelValue", v);
}
</script>

<style scoped>
.ref {
  display: flex;
  min-width: 0;
}
input {
  flex: 1;
  min-width: 0;
  height: var(--zen-control-h-sm, 24px);
  padding: 0 7px;
  border: 1px solid var(--h3-line, #34343c);
  border-radius: 5px;
  background: var(--h3-field, #15151a);
  color: var(--h3-text, #e5e5ea);
  font: inherit;
  font-size: 12px;
}
input:focus {
  border-color: var(--zen-accent, #6366f1);
  outline: 0;
}
</style>
