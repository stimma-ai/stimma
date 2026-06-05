<script setup lang="ts">
import { computed } from 'vue';
import Icon from './icons/Icon.vue';
import IconButton from './common/IconButton.vue';

const props = defineProps<{
  canUndo: boolean;
  canRedo: boolean;
  zoom: number;
  activePlugin?: string;
  hideAnnotationsInRetouch?: boolean;
}>();

const emit = defineEmits<{
  (e: 'undo'): void;
  (e: 'redo'): void;
  (e: 'revert'): void;
  (e: 'zoom-in'): void;
  (e: 'zoom-out'): void;
  (e: 'zoom-reset'): void;
  (e: 'toggle-annotations'): void;
}>();

const zoomPercentage = computed(() => `${Math.round(props.zoom * 100)}%`);

// Show annotations toggle only when in retouch mode
const showAnnotationsToggle = computed(() => props.activePlugin === 'retouch');
</script>

<template>
  <div class="stimma-toolbar" role="toolbar" aria-label="Editor tools">
    <!-- Left group: Revert, Undo, Redo -->
    <div class="stimma-toolbar__group stimma-toolbar__group--start">
      <IconButton
        label="Revert"
        :disabled="!canUndo"
        @click="emit('revert')"
      >
        <Icon name="revert" />
      </IconButton>

      <div class="stimma-toolbar__divider" />

      <IconButton
        label="Undo"
        :disabled="!canUndo"
        @click="emit('undo')"
      >
        <Icon name="undo" />
      </IconButton>

      <IconButton
        label="Redo"
        :disabled="!canRedo"
        @click="emit('redo')"
      >
        <Icon name="redo" />
      </IconButton>

      <!-- Annotations visibility toggle (retouch mode only) -->
      <template v-if="showAnnotationsToggle">
        <div class="stimma-toolbar__divider" />
        <button
          class="stimma-toolbar__layer-toggle"
          :class="{ 'stimma-toolbar__layer-toggle--hidden': hideAnnotationsInRetouch }"
          :title="hideAnnotationsInRetouch ? 'Show annotations' : 'Hide annotations'"
          @click="emit('toggle-annotations')"
        >
          <span class="stimma-toolbar__layer-icon">
            <Icon name="pencil" :size="16" />
          </span>
          <span class="stimma-toolbar__layer-eye">
            <Icon :name="hideAnnotationsInRetouch ? 'eyeOff' : 'eye'" :size="12" />
          </span>
        </button>
      </template>
    </div>

    <!-- Center group: Zoom controls -->
    <div class="stimma-toolbar__group stimma-toolbar__zoom">
      <IconButton label="Zoom out" @click="emit('zoom-out')">
        <Icon name="zoomOut" />
      </IconButton>

      <button
        class="stimma-toolbar__zoom-value"
        :title="'Reset zoom'"
        @click="emit('zoom-reset')"
      >
        {{ zoomPercentage }}
      </button>

      <IconButton label="Zoom in" @click="emit('zoom-in')">
        <Icon name="zoomIn" />
      </IconButton>
    </div>

    <!-- Right group: Custom controls via slot -->
    <div class="stimma-toolbar__group stimma-toolbar__group--end">
      <slot name="toolbar-end" />
    </div>
  </div>
</template>
