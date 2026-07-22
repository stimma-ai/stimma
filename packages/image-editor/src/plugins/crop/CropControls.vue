<script setup lang="ts">
import { ref, watch, onMounted } from 'vue';
import type { EditorContext } from '@/types/plugins';
import { DEFAULT_ASPECT_RATIOS } from '@/constants';
import { Slider } from '@/components/common';
import Icon from '@/components/icons/Icon.vue';

const props = defineProps<{
  editor: EditorContext;
}>();

// Local state
const rotation = ref(0); // in degrees, -45 to 45

// Aspect ratio options
const aspectRatios = DEFAULT_ASPECT_RATIOS;
const selectedAspectRatio = ref<number | null>(null);
let isInitializing = true;

// Sync local state with actual crop state on mount
onMounted(() => {
  const cropAspect = props.editor.state.crop.aspectRatio;
  if (cropAspect === null) {
    selectedAspectRatio.value = null;
  } else {
    // Find matching preset or leave as custom (null selection but don't clear aspect)
    const match = aspectRatios.find(opt =>
      opt.value !== null && opt.value !== -1 && Math.abs(opt.value - cropAspect) < 0.01
    );
    selectedAspectRatio.value = match?.value ?? null;
  }

  // Sync rotation
  rotation.value = (props.editor.state.rotation * 180) / Math.PI;

  // Allow watcher to run after initialization
  isInitializing = false;
});


// Watchers
watch(rotation, (value) => {
  // Convert degrees to radians and update state
  const radians = (value * Math.PI) / 180;
  props.editor.updateState({ rotation: radians });
});

watch(selectedAspectRatio, (value) => {
  // Skip during initialization to avoid overwriting existing aspect ratio
  if (isInitializing) return;

  const crop = { ...props.editor.state.crop };

  if (value === null) {
    // Free crop
    crop.aspectRatio = null;
  } else if (value === -1) {
    // Original aspect ratio - account for 90° rotations
    if (props.editor.state.imageSize) {
      const { width, height } = props.editor.state.imageSize;
      const isRotated90 = props.editor.state.rotation90 === 1 || props.editor.state.rotation90 === 3;
      crop.aspectRatio = isRotated90 ? height / width : width / height;
    }
  } else {
    crop.aspectRatio = value;
    // Adjust crop to match aspect ratio
    // Note: crop.width/height are normalized (0-1), so we need to account for image aspect ratio
    // pixelWidth / pixelHeight = aspectRatio
    // (crop.width * imgW) / (crop.height * imgH) = aspectRatio
    // crop.width / crop.height = aspectRatio * (imgH / imgW)
    if (props.editor.state.imageSize) {
      const { width: imgW, height: imgH } = props.editor.state.imageSize;
      const imageAR = imgW / imgH;
      const normalizedAR = value / imageAR; // Convert pixel AR to normalized AR

      const currentNormalizedRatio = crop.width / crop.height;
      if (currentNormalizedRatio > normalizedAR) {
        // Too wide, reduce width
        crop.width = crop.height * normalizedAR;
      } else {
        // Too tall, reduce height
        crop.height = crop.width / normalizedAR;
      }
    }
  }

  props.editor.updateState({ crop });
  props.editor.pushHistory('Change aspect ratio');
});

// Methods
function handleRotateLeft() {
  const state = props.editor.state;
  const newRotation90 = ((state.rotation90 - 1 + 4) % 4) as 0 | 1 | 2 | 3;
  props.editor.updateState({ rotation90: newRotation90 });
  props.editor.pushHistory('Rotate left');
}

function handleRotateRight() {
  const state = props.editor.state;
  const newRotation90 = ((state.rotation90 + 1) % 4) as 0 | 1 | 2 | 3;
  props.editor.updateState({ rotation90: newRotation90 });
  props.editor.pushHistory('Rotate right');
}

function handleFlipHorizontal() {
  const state = props.editor.state;
  props.editor.updateState({ flipX: !state.flipX });
  props.editor.pushHistory('Flip horizontal');
}

function handleFlipVertical() {
  const state = props.editor.state;
  props.editor.updateState({ flipY: !state.flipY });
  props.editor.pushHistory('Flip vertical');
}

function handleReset() {
  rotation.value = 0;
  selectedAspectRatio.value = null;
  props.editor.updateState({
    crop: {
      x: 0.5,
      y: 0.5,
      width: 1,
      height: 1,
      aspectRatio: null,
    },
    rotation: 0,
    rotation90: 0,
    flipX: false,
    flipY: false,
  });
  props.editor.pushHistory('Revert crop');
}
</script>

<template>
  <div class="stimma-crop-controls">
    <!-- Aspect Ratio -->
    <div class="stimma-panel__section">
      <div class="stimma-panel__section-title">Aspect Ratio</div>
      <div class="stimma-crop-controls__ratios">
        <button
          v-for="option in aspectRatios"
          :key="option.label"
          class="stimma-crop-controls__ratio-btn"
          :class="{ 'stimma-crop-controls__ratio-btn--active': selectedAspectRatio === option.value }"
          @click="selectedAspectRatio = option.value"
        >
          {{ option.label }}
        </button>
      </div>
    </div>

    <!-- Rotation -->
    <div class="stimma-panel__section">
      <div class="stimma-panel__section-title">Rotation</div>
      <div class="stimma-panel__row">
        <Slider
          v-model="rotation"
          :min="-45"
          :max="45"
          :step="0.1"
          :format-value="(v) => `${v.toFixed(1)}°`"
        />
      </div>
    </div>

    <!-- Transform buttons -->
    <div class="stimma-panel__section">
      <div class="stimma-panel__section-title">Transform</div>
      <div class="stimma-crop-controls__transforms">
        <button
          class="stimma-crop-controls__transform-btn"
          title="Rotate left 90°"
          @click="handleRotateLeft"
        >
          <Icon name="rotateLeft" />
        </button>
        <button
          class="stimma-crop-controls__transform-btn"
          title="Rotate right 90°"
          @click="handleRotateRight"
        >
          <Icon name="rotateRight" />
        </button>
        <button
          class="stimma-crop-controls__transform-btn"
          :class="{ 'stimma-crop-controls__transform-btn--active': editor.state.flipX }"
          title="Flip horizontal"
          @click="handleFlipHorizontal"
        >
          <Icon name="flipHorizontal" />
        </button>
        <button
          class="stimma-crop-controls__transform-btn"
          :class="{ 'stimma-crop-controls__transform-btn--active': editor.state.flipY }"
          title="Flip vertical"
          @click="handleFlipVertical"
        >
          <Icon name="flipVertical" />
        </button>
      </div>
    </div>

    <!-- Revert button -->
    <div class="stimma-panel__section stimma-crop-controls__revert-section">
      <button class="stimma-button stimma-button--default" @click="handleReset">
        Revert
      </button>
    </div>
  </div>
</template>

<style scoped>
.stimma-crop-controls__ratios {
  display: flex;
  flex-wrap: wrap;
  gap: var(--stimma-spacing-xs);
}

.stimma-crop-controls__ratio-btn {
  padding: var(--stimma-spacing-xs) var(--stimma-spacing-sm);
  border-radius: var(--stimma-border-radius-sm);
  font-size: var(--stimma-font-size-sm);
  background-color: rgb(var(--stimma-color-foreground) / 0.05);
  transition: all var(--stimma-transition-duration);
}

.stimma-crop-controls__ratio-btn:hover {
  background-color: rgb(var(--stimma-color-foreground) / 0.1);
}

.stimma-crop-controls__ratio-btn--active {
  background-color: rgb(var(--stimma-color-primary));
  color: white;
}

.stimma-crop-controls__transforms {
  display: flex;
  gap: var(--stimma-spacing-xs);
}

.stimma-crop-controls__transform-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: var(--stimma-border-radius);
  background-color: rgb(var(--stimma-color-foreground) / 0.05);
  transition: all var(--stimma-transition-duration);
}

.stimma-crop-controls__transform-btn:hover {
  background-color: rgb(var(--stimma-color-foreground) / 0.1);
}

.stimma-crop-controls__transform-btn--active {
  background-color: rgb(var(--stimma-color-primary) / 0.2);
  color: rgb(var(--stimma-color-primary));
}

.stimma-crop-controls__revert-section {
  display: flex;
  justify-content: center;
}
</style>
