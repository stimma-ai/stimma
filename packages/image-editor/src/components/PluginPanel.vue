<script setup lang="ts">
import { computed } from 'vue';
import type { StimmaPlugin, EditorContext } from '@/types/plugins';

const props = defineProps<{
  plugin: StimmaPlugin | undefined;
  editorContext: EditorContext;
}>();

const controlsComponent = computed(() => props.plugin?.controls);
</script>

<template>
  <div
    v-if="plugin"
    class="stimma-editor__panel stimma-panel"
    :id="`panel-${plugin.id}`"
    role="tabpanel"
    :aria-labelledby="`tab-${plugin.id}`"
  >
    <component
      v-if="controlsComponent"
      :is="controlsComponent"
      :editor="editorContext"
    />
  </div>
</template>
