<script setup lang="ts">
import type { StimmaPlugin } from '@/types/plugins';

defineProps<{
  plugins: StimmaPlugin[];
  activePlugin: string;
}>();

const emit = defineEmits<{
  (e: 'select', pluginId: string): void;
}>();
</script>

<template>
  <div class="stimma-tabs" role="tablist" aria-label="Editing tools">
    <div class="stimma-tabs__list">
      <button
        v-for="plugin in plugins"
        :key="plugin.id"
        class="stimma-tabs__tab"
        :class="{ 'stimma-tabs__tab--active': activePlugin === plugin.id }"
        role="tab"
        :aria-selected="activePlugin === plugin.id"
        :aria-controls="`panel-${plugin.id}`"
        @click="emit('select', plugin.id)"
      >
        <span
          v-if="typeof plugin.icon === 'string'"
          class="stimma-tabs__icon"
          v-html="plugin.icon"
        />
        <component
          v-else
          :is="plugin.icon"
          class="stimma-tabs__icon"
        />
        <span class="stimma-tabs__label">{{ plugin.label }}</span>
      </button>
    </div>
  </div>
</template>
