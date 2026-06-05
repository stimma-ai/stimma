<script setup lang="ts">
import { ref, watch } from 'vue';
import type { EditorContext } from '@/types/plugins';
import { Slider } from '@/components/common';

const props = defineProps<{
  editor: EditorContext;
}>();

// Local state for sliders
const brightness = ref(props.editor.state.brightness ?? 0);
const contrast = ref(props.editor.state.contrast ?? 0);
const saturation = ref(props.editor.state.saturation ?? 0);
const exposure = ref(props.editor.state.exposure ?? 0);
const temperature = ref(props.editor.state.temperature ?? 0);
const gamma = ref(props.editor.state.gamma ?? 1);

// Debounced update
let updateTimeout: number | null = null;

function updateState() {
  if (updateTimeout) {
    clearTimeout(updateTimeout);
  }
  updateTimeout = window.setTimeout(() => {
    props.editor.updateState({
      brightness: brightness.value,
      contrast: contrast.value,
      saturation: saturation.value,
      exposure: exposure.value,
      temperature: temperature.value,
      gamma: gamma.value,
    });
    props.editor.pushHistory('Adjust colors');
    updateTimeout = null;
  }, 100);
}

// Watch all adjustments
watch([brightness, contrast, saturation, exposure, temperature, gamma], updateState);

/**
 * Analyze source image and return histogram data
 */
function analyzeImage(): { r: number[]; g: number[]; b: number[]; avg: number; minR: number; maxR: number; minG: number; maxG: number; minB: number; maxB: number } | null {
  const img = props.editor.getImageElement();
  if (!img) return null;

  // Create temp canvas to read pixels
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;

  // Use smaller size for faster analysis
  const maxSize = 256;
  const scale = Math.min(1, maxSize / Math.max(img.width, img.height));
  canvas.width = Math.floor(img.width * scale);
  canvas.height = Math.floor(img.height * scale);

  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const data = imageData.data;

  // Build histograms
  const histR = new Array(256).fill(0);
  const histG = new Array(256).fill(0);
  const histB = new Array(256).fill(0);
  let totalBrightness = 0;

  for (let i = 0; i < data.length; i += 4) {
    const r = data[i];
    const g = data[i + 1];
    const b = data[i + 2];
    histR[r]++;
    histG[g]++;
    histB[b]++;
    totalBrightness += (r + g + b) / 3;
  }

  const pixelCount = data.length / 4;
  const avg = totalBrightness / pixelCount;

  // Find min/max with 0.5% threshold to ignore outliers
  const threshold = pixelCount * 0.005;
  let minR = 0, maxR = 255, minG = 0, maxG = 255, minB = 0, maxB = 255;
  let countR = 0, countG = 0, countB = 0;

  for (let i = 0; i < 256; i++) {
    countR += histR[i];
    if (countR > threshold) { minR = i; break; }
  }
  for (let i = 255; i >= 0; i--) {
    countR += histR[i];
    if (countR > threshold) { maxR = i; break; }
  }
  countR = 0;
  for (let i = 0; i < 256; i++) {
    countG += histG[i];
    if (countG > threshold) { minG = i; break; }
  }
  for (let i = 255; i >= 0; i--) {
    countG += histG[i];
    if (countG > threshold) { maxG = i; break; }
  }
  countG = 0;
  for (let i = 0; i < 256; i++) {
    countB += histB[i];
    if (countB > threshold) { minB = i; break; }
  }
  for (let i = 255; i >= 0; i--) {
    countB += histB[i];
    if (countB > threshold) { maxB = i; break; }
  }

  return { r: histR, g: histG, b: histB, avg, minR, maxR, minG, maxG, minB, maxB };
}

function handleAutoContrast() {
  const analysis = analyzeImage();
  if (!analysis) return;

  // Auto contrast: stretch histogram to full range
  const range = Math.max(analysis.maxR - analysis.minR, analysis.maxG - analysis.minG, analysis.maxB - analysis.minB);
  const contrastBoost = Math.round(((255 - range) / 255) * 50);

  contrast.value = Math.min(50, contrastBoost);
  props.editor.updateState({ contrast: contrast.value });
  props.editor.pushHistory('Auto Contrast');
}

function handleAutoLevels() {
  const analysis = analyzeImage();
  if (!analysis) return;

  // Auto levels: adjust brightness and contrast based on histogram
  const midpoint = 127.5;
  const brightnessAdjust = Math.round((midpoint - analysis.avg) / 2.55);

  // Calculate contrast from dynamic range
  const avgMin = (analysis.minR + analysis.minG + analysis.minB) / 3;
  const avgMax = (analysis.maxR + analysis.maxG + analysis.maxB) / 3;
  const range = avgMax - avgMin;
  const contrastAdjust = Math.round(((255 - range) / 255) * 30);

  brightness.value = Math.max(-50, Math.min(50, brightnessAdjust));
  contrast.value = Math.max(0, Math.min(50, contrastAdjust));

  props.editor.updateState({
    brightness: brightness.value,
    contrast: contrast.value,
  });
  props.editor.pushHistory('Auto Levels');
}

function handleAutoWhiteBalance() {
  const analysis = analyzeImage();
  if (!analysis) return;

  // Simple white balance: adjust temperature based on R/B ratio
  const avgR = analysis.r.reduce((sum, count, val) => sum + count * val, 0) / analysis.r.reduce((a, b) => a + b, 0);
  const avgB = analysis.b.reduce((sum, count, val) => sum + count * val, 0) / analysis.b.reduce((a, b) => a + b, 0);

  // If image is too blue, warm it up (positive temp); if too red, cool it down
  const tempAdjust = Math.round((avgB - avgR) / 2.55 * 0.5);

  temperature.value = Math.max(-50, Math.min(50, tempAdjust));
  props.editor.updateState({ temperature: temperature.value });
  props.editor.pushHistory('Auto White Balance');
}

function handleReset() {
  brightness.value = 0;
  contrast.value = 0;
  saturation.value = 0;
  exposure.value = 0;
  temperature.value = 0;
  gamma.value = 1;

  props.editor.updateState({
    brightness: 0,
    contrast: 0,
    saturation: 0,
    exposure: 0,
    temperature: 0,
    gamma: 1,
  });
  props.editor.pushHistory('Revert adjustments');
}
</script>

<template>
  <div class="stimma-finetune-controls">
    <!-- Actions -->
    <div class="stimma-panel__section">
      <div class="stimma-panel__section-title">Actions</div>
      <div class="stimma-finetune-controls__actions">
        <button class="stimma-finetune-controls__action-btn" @click="handleAutoLevels">
          Auto Levels
        </button>
        <button class="stimma-finetune-controls__action-btn" @click="handleAutoContrast">
          Auto Contrast
        </button>
        <button class="stimma-finetune-controls__action-btn" @click="handleAutoWhiteBalance">
          Auto Balance
        </button>
        <button class="stimma-finetune-controls__action-btn" @click="handleReset">
          Revert
        </button>
      </div>
    </div>

    <!-- Sliders -->
    <div class="stimma-panel__section">
      <div class="stimma-panel__section-title">Adjustments</div>

      <div class="stimma-panel__row">
        <span class="stimma-panel__label">Brightness</span>
        <Slider v-model="brightness" :min="-100" :max="100" />
      </div>

      <div class="stimma-panel__row">
        <span class="stimma-panel__label">Contrast</span>
        <Slider v-model="contrast" :min="-100" :max="100" />
      </div>

      <div class="stimma-panel__row">
        <span class="stimma-panel__label">Saturation</span>
        <Slider v-model="saturation" :min="-100" :max="100" />
      </div>

      <div class="stimma-panel__row">
        <span class="stimma-panel__label">Exposure</span>
        <Slider v-model="exposure" :min="-100" :max="100" />
      </div>

      <div class="stimma-panel__row">
        <span class="stimma-panel__label">Temperature</span>
        <Slider v-model="temperature" :min="-100" :max="100" />
      </div>

      <div class="stimma-panel__row">
        <span class="stimma-panel__label">Gamma</span>
        <Slider v-model="gamma" :min="0.2" :max="2.2" :step="0.1" :format-value="(v) => v.toFixed(1)" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.stimma-finetune-controls__actions {
  display: flex;
  flex-direction: column;
  gap: var(--stimma-spacing-xs);
}

.stimma-finetune-controls__action-btn {
  padding: var(--stimma-spacing-xs) var(--stimma-spacing-sm);
  border-radius: var(--stimma-border-radius-sm);
  font-size: var(--stimma-font-size-sm);
  background-color: rgba(var(--stimma-color-foreground), 0.05);
  border: 1px solid transparent;
  cursor: pointer;
  transition: all var(--stimma-transition-duration);
  text-align: center;
}

.stimma-finetune-controls__action-btn:hover {
  background-color: rgba(var(--stimma-color-foreground), 0.1);
  border-color: rgba(var(--stimma-color-foreground), 0.1);
}

.stimma-finetune-controls__action-btn:active {
  background-color: rgba(var(--stimma-color-primary), 0.2);
}
</style>
