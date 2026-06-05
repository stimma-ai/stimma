<script setup lang="ts">
import { ref, watch } from 'vue';
import type { EditorContext } from '@/types/plugins';
import { Slider } from '@/components/common';

const props = defineProps<{
  editor: EditorContext;
}>();

// Local state for sliders
const blur = ref(props.editor.state.blur ?? 0);
const sharpen = ref(props.editor.state.sharpen ?? 0);
const noise = ref(props.editor.state.noise ?? 0);
const glow = ref(props.editor.state.glow ?? 0);
const pixelate = ref(props.editor.state.pixelate ?? 0);
const chromaticAberration = ref(props.editor.state.chromaticAberration ?? 0);
const motionBlur = ref(props.editor.state.motionBlur ?? 0);
const motionBlurAngle = ref(props.editor.state.motionBlurAngle ?? 0);
const vignette = ref(props.editor.state.vignette ?? 0);
const clarity = ref(props.editor.state.clarity ?? 0);

// Debounced update
let updateTimeout: number | null = null;

function updateState() {
  if (updateTimeout) {
    clearTimeout(updateTimeout);
  }
  updateTimeout = window.setTimeout(() => {
    props.editor.updateState({
      blur: blur.value,
      sharpen: sharpen.value,
      noise: noise.value,
      glow: glow.value,
      pixelate: pixelate.value,
      chromaticAberration: chromaticAberration.value,
      motionBlur: motionBlur.value,
      motionBlurAngle: motionBlurAngle.value,
      vignette: vignette.value,
      clarity: clarity.value,
    });
    props.editor.pushHistory('Adjust effects');
    updateTimeout = null;
  }, 100);
}

// Watch all adjustments
watch([blur, sharpen, noise, glow, pixelate, chromaticAberration, motionBlur, motionBlurAngle, vignette, clarity], updateState);

function handleReset() {
  blur.value = 0;
  sharpen.value = 0;
  noise.value = 0;
  glow.value = 0;
  pixelate.value = 0;
  chromaticAberration.value = 0;
  motionBlur.value = 0;
  motionBlurAngle.value = 0;
  vignette.value = 0;
  clarity.value = 0;

  props.editor.updateState({
    blur: 0,
    sharpen: 0,
    noise: 0,
    glow: 0,
    pixelate: 0,
    chromaticAberration: 0,
    motionBlur: 0,
    motionBlurAngle: 0,
    vignette: 0,
    clarity: 0,
  });
  props.editor.pushHistory('Reset effects');
}
</script>

<template>
  <div class="stimma-effects-controls">
    <!-- Blur & Sharpen -->
    <div class="stimma-panel__section">
      <div class="stimma-panel__section-title">Focus</div>

      <div class="stimma-panel__row">
        <span class="stimma-panel__label">Blur</span>
        <Slider v-model="blur" :min="0" :max="50" />
      </div>

      <div class="stimma-panel__row">
        <span class="stimma-panel__label">Sharpen</span>
        <Slider v-model="sharpen" :min="0" :max="100" />
      </div>

      <div class="stimma-panel__row">
        <span class="stimma-panel__label">Clarity</span>
        <Slider v-model="clarity" :min="-100" :max="100" />
      </div>
    </div>

    <!-- Motion Blur -->
    <div class="stimma-panel__section">
      <div class="stimma-panel__section-title">Motion</div>

      <div class="stimma-panel__row">
        <span class="stimma-panel__label">Motion Blur</span>
        <Slider v-model="motionBlur" :min="0" :max="50" />
      </div>

      <div class="stimma-panel__row">
        <span class="stimma-panel__label">Direction</span>
        <Slider v-model="motionBlurAngle" :min="-180" :max="180" :format-value="(v) => `${v}°`" />
      </div>
    </div>

    <!-- Creative Effects -->
    <div class="stimma-panel__section">
      <div class="stimma-panel__section-title">Creative</div>

      <div class="stimma-panel__row">
        <span class="stimma-panel__label">Glow</span>
        <Slider v-model="glow" :min="0" :max="100" />
      </div>

      <div class="stimma-panel__row">
        <span class="stimma-panel__label">Noise</span>
        <Slider v-model="noise" :min="0" :max="100" />
      </div>

      <div class="stimma-panel__row">
        <span class="stimma-panel__label">Pixelate</span>
        <Slider v-model="pixelate" :min="0" :max="100" />
      </div>

      <div class="stimma-panel__row">
        <span class="stimma-panel__label">Chromatic</span>
        <Slider v-model="chromaticAberration" :min="0" :max="50" />
      </div>

      <div class="stimma-panel__row">
        <span class="stimma-panel__label">Vignette</span>
        <Slider v-model="vignette" :min="0" :max="100" />
      </div>
    </div>

    <div class="stimma-panel__section">
      <button class="stimma-button stimma-button--default stimma-button--full" @click="handleReset">
        Reset All
      </button>
    </div>
  </div>
</template>
