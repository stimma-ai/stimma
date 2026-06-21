<script setup lang="ts">
import { computed } from 'vue';

const props = withDefaults(
  defineProps<{
    modelValue: number;
    min?: number;
    max?: number;
    step?: number;
    showValue?: boolean;
    formatValue?: (value: number) => string;
  }>(),
  {
    min: 0,
    max: 100,
    step: 1,
    showValue: true,
    formatValue: (v: number) => String(Math.round(v)),
  }
);

const emit = defineEmits<{
  (e: 'update:modelValue', value: number): void;
}>();

const displayValue = computed(() => {
  return props.formatValue(props.modelValue);
});

// Percentage for fill
const fillPercent = computed(() => {
  return ((props.modelValue - props.min) / (props.max - props.min)) * 100;
});

function handleInput(event: Event) {
  const target = event.target as HTMLInputElement;
  emit('update:modelValue', parseFloat(target.value));
}
</script>

<template>
  <div class="stimma-slider">
    <div class="stimma-slider__track">
      <div class="stimma-slider__fill" :style="{ width: fillPercent + '%' }" />
      <input
        type="range"
        class="stimma-slider__input"
        :value="modelValue"
        :min="min"
        :max="max"
        :step="step"
        @input="handleInput"
      />
    </div>
    <span v-if="showValue" class="stimma-slider__value">
      {{ displayValue }}
    </span>
  </div>
</template>

<style scoped>
.stimma-slider {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
}

.stimma-slider__track {
  flex: 1;
  height: 6px;
  background: rgba(var(--stimma-color-foreground), 0.15);
  border-radius: var(--stimma-border-radius-round);
  position: relative;
}

.stimma-slider__fill {
  position: absolute;
  left: 0;
  top: 0;
  height: 100%;
  background: rgb(var(--stimma-color-primary));
  border-radius: var(--stimma-border-radius-round);
  pointer-events: none;
}

.stimma-slider__input {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  -webkit-appearance: none;
  appearance: none;
  background: transparent;
  cursor: pointer;
  margin: 0;
}

.stimma-slider__input::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 14px;
  height: 14px;
  background: white;
  border-radius: 50%;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
  cursor: pointer;
}

.stimma-slider__input::-moz-range-thumb {
  width: 14px;
  height: 14px;
  background: white;
  border: none;
  border-radius: 50%;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
  cursor: pointer;
}

.stimma-slider__value {
  flex: 0 0 auto;
  min-width: 32px;
  text-align: right;
  font-size: 12px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  color: rgba(var(--stimma-color-foreground), 0.6);
}
</style>
