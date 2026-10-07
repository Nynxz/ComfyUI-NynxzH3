<script lang="ts">
import type { NodeDef } from "@/framework";
export { widgetOptions } from "./H3StudioLink.vue";

export const nodeDef: Omit<NodeDef, "widgets"> = {
  is: "nynxz.H3.StudioFilm",
};
</script>

<script setup lang="ts">
// H3 Studio Film's body: the same studio picker as H3 Studio Scenes.
import H3StudioLink from "./H3StudioLink.vue";
</script>

<template>
  <H3StudioLink v-bind="$attrs" />
</template>
