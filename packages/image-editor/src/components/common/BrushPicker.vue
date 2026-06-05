<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick, inject } from 'vue';
import type { BrushSettings, BrushPreset } from '@/types/shapes';
import type { IconName } from '@/components/icons';
import type { ComputedRef } from 'vue';

// Inject theme state
const isDarkTheme = inject<ComputedRef<boolean>>('stimmaThemeIsDark', computed(() => true));

const props = withDefaults(defineProps<{
  modelValue: BrushSettings;
  isEraser?: boolean;
  strokeColor?: { r: number; g: number; b: number; a?: number };
}>(), {
  isEraser: false,
  strokeColor: () => ({ r: 255, g: 255, b: 255, a: 1 }),
});

const emit = defineEmits<{
  (e: 'update:modelValue', settings: BrushSettings): void;
  (e: 'update:isEraser', value: boolean): void;
}>();

// Size presets: 6 sizes for each brush type
const presetSizes = [2, 5, 10, 20, 40, 80];

// Brush type base settings
const brushTypes = {
  hard: { hardness: 100, opacity: 100, flow: 100, spacing: 25, glow: 0, jitter: 0, scatter: 0 },
  soft: { hardness: 30, opacity: 100, flow: 100, spacing: 25, glow: 0, jitter: 0, scatter: 0 },
  air: { hardness: 5, opacity: 50, flow: 30, spacing: 10, glow: 0, jitter: 0, scatter: 0 },
};

// Generate presets for each type and size
const hardPresets: BrushPreset[] = presetSizes.map(size => ({
  id: `hard-${size}`,
  name: `${size}`,
  icon: 'hardRound' as IconName,
  settings: { size, ...brushTypes.hard },
}));

const softPresets: BrushPreset[] = presetSizes.map(size => ({
  id: `soft-${size}`,
  name: `${size}`,
  icon: 'softRound' as IconName,
  settings: { size, ...brushTypes.soft },
}));

const airPresets: BrushPreset[] = presetSizes.map(size => ({
  id: `air-${size}`,
  name: `${size}`,
  icon: 'airbrush' as IconName,
  settings: { size, ...brushTypes.air },
}));

// All presets combined for matching
const presets: BrushPreset[] = [...hardPresets, ...softPresets, ...airPresets];

// Current brush settings (for editing)
const editSettings = ref<BrushSettings>({ ...props.modelValue });
const activePresetId = ref<string | null>('hard-10');
const isEraser = ref(false);

// Canvas refs
const previewCanvasRef = ref<HTMLCanvasElement | null>(null);
const presetCanvasRefs = ref<Map<string, HTMLCanvasElement>>(new Map());

// Slider dragging state
const isDraggingSize = ref(false);
const isDraggingHardness = ref(false);
const isDraggingOpacity = ref(false);
const isDraggingFlow = ref(false);
const isDraggingSpacing = ref(false);
const sizeSliderRef = ref<HTMLElement | null>(null);
const hardnessSliderRef = ref<HTMLElement | null>(null);
const opacitySliderRef = ref<HTMLElement | null>(null);
const flowSliderRef = ref<HTMLElement | null>(null);
const spacingSliderRef = ref<HTMLElement | null>(null);

// Store preset canvas ref
function setPresetCanvasRef(el: HTMLCanvasElement | null, id: string) {
  if (el) {
    presetCanvasRefs.value.set(id, el);
  }
}

// Sync editSettings when modelValue changes externally
watch(() => props.modelValue, (newVal) => {
  editSettings.value = { ...newVal };
  drawMainPreview();
}, { deep: true });

// Sync isEraser when prop changes
watch(() => props.isEraser, (newVal) => {
  isEraser.value = newVal;
  if (newVal) {
    activePresetId.value = 'eraser';
  } else if (activePresetId.value === 'eraser') {
    activePresetId.value = null;
  }
}, { immediate: true });

// Watch stroke color changes to redraw preview
watch(() => props.strokeColor, () => {
  drawMainPreview();
}, { deep: true });

// Check if preset matches current settings - structural comparison
function isPresetActive(preset: BrushPreset): boolean {
  if (preset.isEraser && !isEraser.value) return false;
  if (!preset.isEraser && isEraser.value) return false;

  // Compare settings structurally
  const s = preset.settings;
  const current = editSettings.value;
  return (
    s.size === current.size &&
    s.hardness === current.hardness &&
    s.opacity === current.opacity &&
    s.flow === current.flow &&
    s.spacing === current.spacing
  );
}

// Select a preset
function selectPreset(preset: BrushPreset) {
  activePresetId.value = preset.id;
  isEraser.value = preset.isEraser ?? false;
  editSettings.value = { ...preset.settings };
  emit('update:modelValue', { ...editSettings.value });
  emit('update:isEraser', isEraser.value);
  drawMainPreview();
}

// Apply settings (called when sliders change)
function applySettings() {
  // Check if current settings match any preset
  activePresetId.value = null;
  for (const preset of presets) {
    if (preset.isEraser === isEraser.value) {
      const s = preset.settings;
      if (
        s.size === editSettings.value.size &&
        s.hardness === editSettings.value.hardness &&
        s.opacity === editSettings.value.opacity &&
        s.flow === editSettings.value.flow &&
        s.spacing === editSettings.value.spacing
      ) {
        activePresetId.value = preset.id;
        break;
      }
    }
  }
  emit('update:modelValue', { ...editSettings.value });
  drawMainPreview();
}

// Slider update handlers
function updateFromSlider(
  sliderRef: HTMLElement | null,
  x: number,
  min: number,
  max: number
): number {
  if (!sliderRef) return min;
  const rect = sliderRef.getBoundingClientRect();
  const ratio = Math.max(0, Math.min(1, (x - rect.left) / rect.width));
  return Math.round(min + ratio * (max - min));
}

function handleSizeDown(e: MouseEvent) {
  isDraggingSize.value = true;
  editSettings.value.size = updateFromSlider(sizeSliderRef.value, e.clientX, 1, 100);
  applySettings();
}

function handleHardnessDown(e: MouseEvent) {
  isDraggingHardness.value = true;
  editSettings.value.hardness = updateFromSlider(hardnessSliderRef.value, e.clientX, 0, 100);
  applySettings();
}

function handleOpacityDown(e: MouseEvent) {
  isDraggingOpacity.value = true;
  editSettings.value.opacity = updateFromSlider(opacitySliderRef.value, e.clientX, 0, 100);
  applySettings();
}

function handleFlowDown(e: MouseEvent) {
  isDraggingFlow.value = true;
  editSettings.value.flow = updateFromSlider(flowSliderRef.value, e.clientX, 0, 100);
  applySettings();
}

function handleSpacingDown(e: MouseEvent) {
  isDraggingSpacing.value = true;
  editSettings.value.spacing = updateFromSlider(spacingSliderRef.value, e.clientX, 1, 100);
  applySettings();
}

// Global mouse handlers
function handleMouseMove(e: MouseEvent) {
  if (isDraggingSize.value) {
    editSettings.value.size = updateFromSlider(sizeSliderRef.value, e.clientX, 1, 100);
    applySettings();
  }
  if (isDraggingHardness.value) {
    editSettings.value.hardness = updateFromSlider(hardnessSliderRef.value, e.clientX, 0, 100);
    applySettings();
  }
  if (isDraggingOpacity.value) {
    editSettings.value.opacity = updateFromSlider(opacitySliderRef.value, e.clientX, 0, 100);
    applySettings();
  }
  if (isDraggingFlow.value) {
    editSettings.value.flow = updateFromSlider(flowSliderRef.value, e.clientX, 0, 100);
    applySettings();
  }
  if (isDraggingSpacing.value) {
    editSettings.value.spacing = updateFromSlider(spacingSliderRef.value, e.clientX, 1, 100);
    applySettings();
  }
}

function handleMouseUp() {
  isDraggingSize.value = false;
  isDraggingHardness.value = false;
  isDraggingOpacity.value = false;
  isDraggingFlow.value = false;
  isDraggingSpacing.value = false;
}

// Theme-aware colors
const previewColors = computed(() => {
  if (isDarkTheme.value) {
    return {
      bgStart: '#2a2a2a',
      bgEnd: '#1a1a1a',
      brush: { r: 255, g: 255, b: 255 },
      presetBg: '#1e1e1e',
    };
  } else {
    return {
      bgStart: '#e8e8e8',
      bgEnd: '#d8d8d8',
      brush: { r: 40, g: 40, b: 40 },
      presetBg: '#e0e0e0',
    };
  }
});

// Draw main preview (just a single brush stamp centered)
function drawMainPreview() {
  const canvas = previewCanvasRef.value;
  if (!canvas) return;

  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const { size, hardness, opacity, flow } = editSettings.value;
  const width = canvas.width;
  const height = canvas.height;
  const colors = previewColors.value;

  // Subtle gradient background
  const bgGradient = ctx.createLinearGradient(0, 0, width, height);
  bgGradient.addColorStop(0, colors.bgStart);
  bgGradient.addColorStop(1, colors.bgEnd);
  ctx.fillStyle = bgGradient;
  ctx.fillRect(0, 0, width, height);

  // Draw brush stamp centered - scale to fit nicely
  const maxDisplaySize = Math.min(width, height) - 8;
  const displaySize = Math.min(maxDisplaySize, size * 1.2);

  drawBrushStamp(ctx, width / 2, height / 2, displaySize, hardness, opacity, flow, colors.brush);
}

// Draw preset previews
function drawPresetPreviews() {
  const colors = previewColors.value;

  for (const preset of presets) {
    const canvas = presetCanvasRefs.value.get(preset.id);
    if (!canvas) continue;

    const ctx = canvas.getContext('2d');
    if (!ctx) continue;

    const { size, hardness, opacity, flow } = preset.settings;
    const width = canvas.width;
    const height = canvas.height;

    // Theme-aware background
    ctx.fillStyle = colors.presetBg;
    ctx.fillRect(0, 0, width, height);

    // Scale brush size to fit in the small preview
    // Map size 2-80 to display size 6-18
    const displaySize = 6 + ((size - 2) / 78) * 12;

    drawBrushStamp(ctx, width / 2, height / 2, displaySize, hardness, opacity, flow, colors.brush);
  }
}

// Draw a single brush stamp
function drawBrushStamp(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  size: number,
  hardness: number,
  opacity: number,
  flow: number,
  color: { r: number; g: number; b: number }
) {
  const radius = size / 2;
  const alpha = (opacity / 100) * (flow / 100);

  // Create gradient for brush stamp
  const gradient = ctx.createRadialGradient(x, y, 0, x, y, radius);
  const hardnessPoint = Math.max(0.01, hardness / 100);

  gradient.addColorStop(0, `rgba(${color.r}, ${color.g}, ${color.b}, ${alpha})`);
  gradient.addColorStop(hardnessPoint, `rgba(${color.r}, ${color.g}, ${color.b}, ${alpha})`);
  gradient.addColorStop(1, `rgba(${color.r}, ${color.g}, ${color.b}, 0)`);

  ctx.fillStyle = gradient;
  ctx.beginPath();
  ctx.arc(x, y, radius, 0, Math.PI * 2);
  ctx.fill();
}

// Watch for settings changes to update preview
watch(editSettings, () => {
  drawMainPreview();
}, { deep: true });

// Redraw when theme changes
watch(isDarkTheme, () => {
  drawMainPreview();
  drawPresetPreviews();
});

onMounted(() => {
  document.addEventListener('mousemove', handleMouseMove);
  document.addEventListener('mouseup', handleMouseUp);
  nextTick(() => {
    drawMainPreview();
    drawPresetPreviews();
  });
});

onUnmounted(() => {
  document.removeEventListener('mousemove', handleMouseMove);
  document.removeEventListener('mouseup', handleMouseUp);
});

// Computed styles for slider positions
const sizePos = computed(() => `${((editSettings.value.size - 1) / 99) * 100}%`);
const hardnessPos = computed(() => `${editSettings.value.hardness}%`);
const opacityPos = computed(() => `${editSettings.value.opacity}%`);
const flowPos = computed(() => `${editSettings.value.flow}%`);
const spacingPos = computed(() => `${((editSettings.value.spacing - 1) / 99) * 100}%`);

// Expose isEraser for parent component
defineExpose({ isEraser });
</script>

<template>
  <div class="stimma-brush-picker">
    <!-- Brush preview (single stamp) -->
    <div class="stimma-brush-picker__preview">
      <canvas
        ref="previewCanvasRef"
        class="stimma-brush-picker__preview-canvas"
        width="80"
        height="80"
      />
    </div>

    <!-- Preset grid: 3 rows (Hard, Soft, Air) x 6 sizes with visual previews -->
    <div class="stimma-brush-picker__preset-grid">
      <div class="stimma-brush-picker__preset-row">
        <button
          v-for="preset in hardPresets"
          :key="preset.id"
          class="stimma-brush-picker__preset"
          :class="{ 'stimma-brush-picker__preset--active': isPresetActive(preset) }"
          :title="`Hard ${preset.name}px`"
          @click="selectPreset(preset)"
        >
          <canvas
            :ref="(el) => setPresetCanvasRef(el as HTMLCanvasElement, preset.id)"
            width="24"
            height="24"
          />
        </button>
      </div>
      <div class="stimma-brush-picker__preset-row">
        <button
          v-for="preset in softPresets"
          :key="preset.id"
          class="stimma-brush-picker__preset"
          :class="{ 'stimma-brush-picker__preset--active': isPresetActive(preset) }"
          :title="`Soft ${preset.name}px`"
          @click="selectPreset(preset)"
        >
          <canvas
            :ref="(el) => setPresetCanvasRef(el as HTMLCanvasElement, preset.id)"
            width="24"
            height="24"
          />
        </button>
      </div>
      <div class="stimma-brush-picker__preset-row">
        <button
          v-for="preset in airPresets"
          :key="preset.id"
          class="stimma-brush-picker__preset"
          :class="{ 'stimma-brush-picker__preset--active': isPresetActive(preset) }"
          :title="`Air ${preset.name}px`"
          @click="selectPreset(preset)"
        >
          <canvas
            :ref="(el) => setPresetCanvasRef(el as HTMLCanvasElement, preset.id)"
            width="24"
            height="24"
          />
        </button>
      </div>
    </div>

    <!-- Sliders -->
    <div class="stimma-brush-picker__sliders">
      <div class="stimma-brush-picker__slider-group">
        <div class="stimma-brush-picker__slider-header">
          <label class="stimma-brush-picker__slider-label">Size</label>
          <span class="stimma-brush-picker__slider-value">{{ editSettings.size }}px</span>
        </div>
        <div
          ref="sizeSliderRef"
          class="stimma-brush-picker__slider-track"
          @mousedown="handleSizeDown"
        >
          <div class="stimma-brush-picker__slider-fill" :style="{ width: sizePos }" />
          <div class="stimma-brush-picker__slider-handle" :style="{ left: sizePos }" />
        </div>
      </div>

      <div class="stimma-brush-picker__slider-group">
        <div class="stimma-brush-picker__slider-header">
          <label class="stimma-brush-picker__slider-label">Hardness</label>
          <span class="stimma-brush-picker__slider-value">{{ editSettings.hardness }}%</span>
        </div>
        <div
          ref="hardnessSliderRef"
          class="stimma-brush-picker__slider-track"
          @mousedown="handleHardnessDown"
        >
          <div class="stimma-brush-picker__slider-fill" :style="{ width: hardnessPos }" />
          <div class="stimma-brush-picker__slider-handle" :style="{ left: hardnessPos }" />
        </div>
      </div>

      <div class="stimma-brush-picker__slider-group">
        <div class="stimma-brush-picker__slider-header">
          <label class="stimma-brush-picker__slider-label">Opacity</label>
          <span class="stimma-brush-picker__slider-value">{{ editSettings.opacity }}%</span>
        </div>
        <div
          ref="opacitySliderRef"
          class="stimma-brush-picker__slider-track"
          @mousedown="handleOpacityDown"
        >
          <div class="stimma-brush-picker__slider-fill" :style="{ width: opacityPos }" />
          <div class="stimma-brush-picker__slider-handle" :style="{ left: opacityPos }" />
        </div>
      </div>

      <div class="stimma-brush-picker__slider-group">
        <div class="stimma-brush-picker__slider-header">
          <label class="stimma-brush-picker__slider-label">Flow</label>
          <span class="stimma-brush-picker__slider-value">{{ editSettings.flow }}%</span>
        </div>
        <div
          ref="flowSliderRef"
          class="stimma-brush-picker__slider-track"
          @mousedown="handleFlowDown"
        >
          <div class="stimma-brush-picker__slider-fill" :style="{ width: flowPos }" />
          <div class="stimma-brush-picker__slider-handle" :style="{ left: flowPos }" />
        </div>
      </div>

      <div class="stimma-brush-picker__slider-group">
        <div class="stimma-brush-picker__slider-header">
          <label class="stimma-brush-picker__slider-label">Spacing</label>
          <span class="stimma-brush-picker__slider-value">{{ editSettings.spacing }}%</span>
        </div>
        <div
          ref="spacingSliderRef"
          class="stimma-brush-picker__slider-track"
          @mousedown="handleSpacingDown"
        >
          <div class="stimma-brush-picker__slider-fill" :style="{ width: spacingPos }" />
          <div class="stimma-brush-picker__slider-handle" :style="{ left: spacingPos }" />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stimma-brush-picker {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* Main preview */
.stimma-brush-picker__preview {
  display: flex;
  justify-content: center;
  padding: 8px 0;
}

.stimma-brush-picker__preview-canvas {
  width: 80px;
  height: 80px;
  border-radius: 8px;
}

/* Preset grid */
.stimma-brush-picker__preset-grid {
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: rgba(var(--stimma-color-foreground), 0.05);
  border-radius: 6px;
  padding: 4px;
}

.stimma-brush-picker__preset-row {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 4px;
}

.stimma-brush-picker__preset {
  aspect-ratio: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  border: 2px solid transparent;
  background: transparent;
  cursor: pointer;
  transition: all 0.15s;
  padding: 0;
  overflow: hidden;
}

.stimma-brush-picker__preset canvas {
  width: 100%;
  height: 100%;
  border-radius: 2px;
}

.stimma-brush-picker__preset:hover {
  border-color: rgba(var(--stimma-color-foreground), 0.4);
}

.stimma-brush-picker__preset--active {
  border-color: rgb(var(--stimma-color-primary));
  box-shadow: 0 0 0 1px rgb(var(--stimma-color-primary));
}

/* Sliders */
.stimma-brush-picker__sliders {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.stimma-brush-picker__slider-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stimma-brush-picker__slider-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.stimma-brush-picker__slider-label {
  font-size: 12px;
  font-weight: 500;
  color: rgba(var(--stimma-color-foreground), 0.8);
}

.stimma-brush-picker__slider-value {
  font-size: 12px;
  font-weight: 500;
  color: rgba(var(--stimma-color-foreground), 0.6);
  min-width: 36px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.stimma-brush-picker__slider-track {
  height: 6px;
  background: rgba(var(--stimma-color-foreground), 0.15);
  border-radius: 3px;
  position: relative;
  cursor: pointer;
}

.stimma-brush-picker__slider-fill {
  position: absolute;
  left: 0;
  top: 0;
  height: 100%;
  background: rgb(var(--stimma-color-primary));
  border-radius: 3px;
}

.stimma-brush-picker__slider-handle {
  position: absolute;
  top: 50%;
  width: 14px;
  height: 14px;
  background: white;
  border-radius: 50%;
  transform: translate(-50%, -50%);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
  pointer-events: none;
}
</style>
