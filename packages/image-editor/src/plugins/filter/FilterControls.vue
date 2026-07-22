<script setup lang="ts">
import { ref, watch, onMounted } from 'vue';
import type { EditorContext } from '@/types/plugins';
import { FILTER_CATEGORIES, DEFAULT_FILTERS, FILTER_MATRICES } from '@/constants';
import { applyColorMatrix } from '@/utils/colorMatrix';
import { Slider } from '@/components/common';

const props = defineProps<{
  editor: EditorContext;
}>();

// Single selected filter (can be color filter or retro effect)
const selectedFilter = ref<string>(props.editor.state.filter ?? 'none');
const thumbnails = ref<Record<string, string>>({});

// Effect values
const halftone = ref(props.editor.state.halftone ?? 0);
const vhs = ref(props.editor.state.vhs ?? 0);
const glitch = ref(props.editor.state.glitch ?? 0);
const glitchBlockSize = ref(props.editor.state.glitchBlockSize ?? 16);

// Determine initial selection on mount
onMounted(() => {
  if (halftone.value > 0) selectedFilter.value = 'retro-halftone';
  else if (vhs.value > 0) selectedFilter.value = 'retro-vhs';
  else if (glitch.value > 0) selectedFilter.value = 'retro-glitch';
});

// Retro filter definitions (no "None" - uses main None)
const retroFilters = [
  { id: 'retro-halftone', label: 'Halftone' },
  { id: 'retro-vhs', label: 'VHS' },
  { id: 'retro-glitch', label: 'Glitch' },
];

// Check if selected filter is a retro effect
function isRetroFilter(id: string): boolean {
  return id.startsWith('retro-');
}

// Generate filter thumbnails from the source image
async function generateThumbnails() {
  const img = props.editor.getImageElement();
  if (!img) return;

  const thumbSize = 60;
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  // Calculate thumbnail dimensions maintaining aspect ratio
  const scale = thumbSize / Math.max(img.width, img.height);
  canvas.width = Math.round(img.width * scale);
  canvas.height = Math.round(img.height * scale);

  for (const filter of DEFAULT_FILTERS) {
    // Draw scaled image
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

    // Apply filter matrix
    if (filter.id !== 'none') {
      const matrix = FILTER_MATRICES[filter.id];
      if (matrix) {
        const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
        applyColorMatrix(imageData, matrix);
        ctx.putImageData(imageData, 0, 0);
      }
    }

    // Store as data URL
    thumbnails.value[filter.id] = canvas.toDataURL('image/jpeg', 0.7);
  }

  // Generate retro filter thumbnails (just use base image)
  for (const retro of retroFilters) {
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    thumbnails.value[retro.id] = canvas.toDataURL('image/jpeg', 0.7);
  }
}

function selectFilter(filterId: string) {
  // If clicking the already selected filter, deselect it (go to none)
  if (selectedFilter.value === filterId && filterId !== 'none') {
    filterId = 'none';
  }

  selectedFilter.value = filterId;

  // Clear all retro effects
  halftone.value = 0;
  vhs.value = 0;
  glitch.value = 0;
  glitchBlockSize.value = 16;

  if (isRetroFilter(filterId)) {
    // It's a retro filter - clear color filter and set effect
    props.editor.updateState({ filter: null });

    if (filterId === 'retro-halftone') halftone.value = 50;
    else if (filterId === 'retro-vhs') vhs.value = 50;
    else if (filterId === 'retro-glitch') glitch.value = 50;

    updateEffects();
  } else {
    // It's a color filter - clear retro effects
    updateEffects(); // Clear retro effects first
    props.editor.updateState({ filter: filterId === 'none' ? null : filterId });
    props.editor.pushHistory(`Apply ${filterId} filter`);
  }
}

let updateTimeout: number | null = null;
function updateEffects() {
  if (updateTimeout) {
    clearTimeout(updateTimeout);
  }
  updateTimeout = window.setTimeout(() => {
    props.editor.updateState({
      halftone: halftone.value,
      halftoneAngle: 0,
      vhs: vhs.value,
      glitch: glitch.value,
      glitchBlockSize: glitchBlockSize.value,
      ditherEnabled: false,
    });
    if (isRetroFilter(selectedFilter.value)) {
      props.editor.pushHistory('Retro effect');
    }
    updateTimeout = null;
  }, 100);
}

// Watch effect values for live updates
watch([halftone, vhs, glitch, glitchBlockSize], updateEffects);

// Generate thumbnails when image loads
onMounted(() => {
  generateThumbnails();
});

// Regenerate if image changes
watch(() => props.editor.getImageElement(), () => {
  generateThumbnails();
});
</script>

<template>
  <div class="stimma-filter-controls">
    <!-- Color Filters -->
    <div
      v-for="category in FILTER_CATEGORIES"
      :key="category.id"
      class="stimma-filter-controls__category"
    >
      <div v-if="category.label" class="stimma-filter-controls__category-title">
        {{ category.label }}
      </div>
      <div class="stimma-filter-controls__grid">
        <button
          v-for="filter in category.filters"
          :key="filter.id"
          class="stimma-filter-controls__item"
          :class="{ 'stimma-filter-controls__item--active': selectedFilter === filter.id }"
          @click="selectFilter(filter.id)"
        >
          <div class="stimma-filter-controls__thumb">
            <img
              v-if="thumbnails[filter.id]"
              :src="thumbnails[filter.id]"
              :alt="filter.label"
            />
            <div v-else class="stimma-filter-controls__placeholder" />
          </div>
          <span class="stimma-filter-controls__label">{{ filter.label }}</span>
        </button>
      </div>
    </div>

    <!-- Retro Filters -->
    <div class="stimma-filter-controls__category">
      <div class="stimma-filter-controls__category-title">Retro</div>
      <div class="stimma-filter-controls__grid">
        <button
          v-for="retro in retroFilters"
          :key="retro.id"
          class="stimma-filter-controls__item"
          :class="{ 'stimma-filter-controls__item--active': selectedFilter === retro.id }"
          @click="selectFilter(retro.id)"
        >
          <div class="stimma-filter-controls__thumb">
            <img
              v-if="thumbnails[retro.id]"
              :src="thumbnails[retro.id]"
              :alt="retro.label"
            />
            <div v-else class="stimma-filter-controls__placeholder" />
          </div>
          <span class="stimma-filter-controls__label">{{ retro.label }}</span>
        </button>
      </div>

      <!-- Settings for selected retro effect -->
      <div v-if="isRetroFilter(selectedFilter)" class="stimma-filter-controls__settings">
        <!-- Halftone settings -->
        <template v-if="selectedFilter === 'retro-halftone'">
          <div class="stimma-panel__row">
            <span class="stimma-panel__label">Intensity</span>
            <Slider v-model="halftone" :min="0" :max="100" />
          </div>
        </template>

        <!-- VHS settings -->
        <template v-if="selectedFilter === 'retro-vhs'">
          <div class="stimma-panel__row">
            <span class="stimma-panel__label">Intensity</span>
            <Slider v-model="vhs" :min="0" :max="100" />
          </div>
        </template>

        <!-- Glitch settings -->
        <template v-if="selectedFilter === 'retro-glitch'">
          <div class="stimma-panel__row">
            <span class="stimma-panel__label">Intensity</span>
            <Slider v-model="glitch" :min="0" :max="100" />
          </div>
          <div class="stimma-panel__row">
            <span class="stimma-panel__label">Block Size</span>
            <Slider v-model="glitchBlockSize" :min="8" :max="64" />
          </div>
        </template>

      </div>
    </div>
  </div>
</template>

<style scoped>
.stimma-filter-controls__category {
  margin-bottom: var(--stimma-spacing-md);
}

.stimma-filter-controls__category:last-child {
  margin-bottom: 0;
}

.stimma-filter-controls__category-title {
  font-size: var(--stimma-font-size-xs);
  font-weight: 600;
  color: rgb(var(--stimma-color-foreground) / 0.5);
  margin-bottom: var(--stimma-spacing-xs);
  padding: 0 var(--stimma-spacing-xs);
}

.stimma-filter-controls__grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--stimma-spacing-sm);
}

.stimma-filter-controls__item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--stimma-spacing-xs);
  padding: var(--stimma-spacing-xs);
  border-radius: var(--stimma-border-radius);
  background: transparent;
  border: 2px solid transparent;
  cursor: pointer;
  transition: all var(--stimma-transition-duration);
}

.stimma-filter-controls__item:hover {
  background-color: rgb(var(--stimma-color-foreground) / 0.05);
}

.stimma-filter-controls__item--active {
  border-color: rgb(var(--stimma-color-primary));
  background-color: rgb(var(--stimma-color-primary) / 0.1);
}

.stimma-filter-controls__thumb {
  width: 60px;
  height: 60px;
  border-radius: var(--stimma-border-radius-sm);
  overflow: hidden;
  background-color: rgb(var(--stimma-color-foreground) / 0.1);
}

.stimma-filter-controls__thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.stimma-filter-controls__placeholder {
  width: 100%;
  height: 100%;
  background: linear-gradient(135deg,
    rgb(var(--stimma-color-foreground) / 0.1) 0%,
    rgb(var(--stimma-color-foreground) / 0.05) 100%
  );
}

.stimma-filter-controls__label {
  font-size: var(--stimma-font-size-xs, 11px);
  color: rgb(var(--stimma-color-secondary));
  text-align: center;
}

.stimma-filter-controls__item--active .stimma-filter-controls__label {
  color: rgb(var(--stimma-color-primary));
  font-weight: 500;
}

/* Settings panel below grid */
.stimma-filter-controls__settings {
  margin-top: var(--stimma-spacing-sm);
  padding-top: var(--stimma-spacing-sm);
  border-top: 1px solid rgb(var(--stimma-color-foreground) / 0.1);
}
</style>
