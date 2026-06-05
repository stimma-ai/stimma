<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, inject } from 'vue';
import type { Ref } from 'vue';
import Icon from '@/components/icons/Icon.vue';

// Inject dark theme state from parent editor
const isDarkTheme = inject<Ref<boolean>>('stimmaThemeIsDark', ref(false));

interface RGBAColor {
  r: number;
  g: number;
  b: number;
  a?: number;
}

const props = withDefaults(
  defineProps<{
    modelValue: RGBAColor | null;
    allowNull?: boolean;
    imagePalette?: RGBAColor[];
  }>(),
  {
    allowNull: false,
  }
);

const emit = defineEmits<{
  (e: 'update:modelValue', color: RGBAColor | null): void;
}>();

// Static quick access colors (10 colors - first row + 2)
const staticQuickColors: RGBAColor[] = [
  { r: 0, g: 0, b: 0, a: 1 },       // Black
  { r: 255, g: 59, b: 48, a: 1 },   // Red
  { r: 255, g: 149, b: 0, a: 1 },   // Orange
  { r: 255, g: 204, b: 0, a: 1 },   // Yellow
  { r: 52, g: 199, b: 89, a: 1 },   // Green
  { r: 0, g: 199, b: 190, a: 1 },   // Teal
  { r: 0, g: 122, b: 255, a: 1 },   // Blue
  { r: 175, g: 82, b: 222, a: 1 },  // Purple
  { r: 255, g: 105, b: 180, a: 1 },  // Pink
  { r: 255, g: 255, b: 255, a: 1 }, // White
];

// Compute image palette colors limited to fill exactly 2 rows of 8 (16 total)
const limitedImagePalette = computed(() => {
  if (!props.imagePalette || props.imagePalette.length === 0) return [];
  const fixedCount = staticQuickColors.length + (props.allowNull ? 1 : 0);
  const maxImageColors = 16 - fixedCount;
  return props.imagePalette.slice(0, maxImageColors);
});

// Modal preset colors (bottom of modal)
const modalPresets: RGBAColor[] = [
  { r: 0, g: 0, b: 0, a: 1 },
  { r: 0, g: 122, b: 255, a: 1 },
  { r: 52, g: 199, b: 89, a: 1 },
  { r: 255, g: 204, b: 0, a: 1 },
  { r: 255, g: 59, b: 48, a: 1 },
];

// Grid colors - organized like iOS
const gridColors = computed(() => {
  const colors: RGBAColor[] = [];

  // Grayscale row (12 shades)
  for (let i = 0; i < 12; i++) {
    const v = Math.round((1 - i / 11) * 255);
    colors.push({ r: v, g: v, b: v, a: 1 });
  }

  // Color rows - 12 hues, 7 saturation/brightness variations
  const hues = [200, 220, 260, 280, 320, 350, 10, 30, 45, 60, 90, 160];
  const variations = [
    { s: 100, l: 35 },
    { s: 100, l: 45 },
    { s: 100, l: 55 },
    { s: 80, l: 60 },
    { s: 60, l: 70 },
    { s: 40, l: 80 },
    { s: 20, l: 90 },
  ];

  for (const v of variations) {
    for (const h of hues) {
      colors.push(hslToRgb(h, v.s, v.l));
    }
  }

  return colors;
});

// Modal state
const showModal = ref(false);
const activeTab = ref<'grid' | 'spectrum' | 'sliders'>('grid');

// Internal color state for modal editing
const editColor = ref<RGBAColor>({ r: 255, g: 255, b: 255, a: 1 });
const editOpacity = ref(100);

// Spectrum picker state
const spectrumRef = ref<HTMLElement | null>(null);
const isDraggingSpectrum = ref(false);
const spectrumX = ref(0);
const spectrumY = ref(0);

// Opacity slider state
const opacityRef = ref<HTMLElement | null>(null);
const isDraggingOpacity = ref(false);

// RGB slider state
const isDraggingRed = ref(false);
const isDraggingGreen = ref(false);
const isDraggingBlue = ref(false);
const redSliderRef = ref<HTMLElement | null>(null);
const greenSliderRef = ref<HTMLElement | null>(null);
const blueSliderRef = ref<HTMLElement | null>(null);

// Hex input
const hexInput = ref('');

// Eyedropper support
const eyeDropperSupported = ref(false);
onMounted(() => {
  eyeDropperSupported.value = 'EyeDropper' in window;
});

// Color conversions
function hslToRgb(h: number, s: number, l: number): RGBAColor {
  s /= 100;
  l /= 100;
  const a_ = s * Math.min(l, 1 - l);
  const f = (n: number) => {
    const k = (n + h / 30) % 12;
    return l - a_ * Math.max(Math.min(k - 3, 9 - k, 1), -1);
  };
  return {
    r: Math.round(f(0) * 255),
    g: Math.round(f(8) * 255),
    b: Math.round(f(4) * 255),
    a: 1,
  };
}

function rgbToHex(color: RGBAColor): string {
  const r = color.r.toString(16).padStart(2, '0');
  const g = color.g.toString(16).padStart(2, '0');
  const b = color.b.toString(16).padStart(2, '0');
  return `${r}${g}${b}`.toUpperCase();
}

function hexToRgb(hex: string): RGBAColor | null {
  const clean = hex.replace('#', '');
  if (clean.length !== 6) return null;
  const result = /^([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(clean);
  if (!result) return null;
  return {
    r: parseInt(result[1], 16),
    g: parseInt(result[2], 16),
    b: parseInt(result[3], 16),
    a: 1,
  };
}

function rgbToHsl(color: RGBAColor): { h: number; s: number; l: number } {
  const r = color.r / 255;
  const g = color.g / 255;
  const b = color.b / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  let h = 0;
  let s = 0;
  const l = (max + min) / 2;

  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r: h = ((g - b) / d + (g < b ? 6 : 0)) / 6; break;
      case g: h = ((b - r) / d + 2) / 6; break;
      case b: h = ((r - g) / d + 4) / 6; break;
    }
  }

  return { h: h * 360, s: s * 100, l: l * 100 };
}

// Color to CSS
function colorToCss(color: RGBAColor, opacity?: number): string {
  const a = opacity !== undefined ? opacity / 100 : (color.a ?? 1);
  return `rgba(${color.r}, ${color.g}, ${color.b}, ${a})`;
}

// Check if color matches
function isActiveQuick(color: RGBAColor): boolean {
  if (!props.modelValue) return false;
  return (
    props.modelValue.r === color.r &&
    props.modelValue.g === color.g &&
    props.modelValue.b === color.b
  );
}

// Select color directly
function selectColor(color: RGBAColor) {
  emit('update:modelValue', { ...color, a: (props.modelValue?.a ?? 1) });
}

// Open modal
function openModal() {
  if (props.modelValue) {
    editColor.value = { ...props.modelValue };
    editOpacity.value = Math.round((props.modelValue.a ?? 1) * 100);
    hexInput.value = rgbToHex(props.modelValue);
    // Set spectrum position
    const hsl = rgbToHsl(props.modelValue);
    spectrumX.value = hsl.h / 360;
    spectrumY.value = 1 - (hsl.l / 100);
  } else {
    editColor.value = { r: 255, g: 255, b: 255, a: 1 };
    editOpacity.value = 100;
    hexInput.value = 'FFFFFF';
    spectrumX.value = 0;
    spectrumY.value = 0;
  }
  showModal.value = true;
}

// Close modal and apply
function closeModal() {
  showModal.value = false;
  applyColor();
}

// Apply current edit color
function applyColor() {
  emit('update:modelValue', { ...editColor.value, a: editOpacity.value / 100 });
}

// Select from grid
function selectGridColor(color: RGBAColor) {
  editColor.value = { ...color };
  hexInput.value = rgbToHex(color);
  applyColor();
}

// Select from modal presets
function selectModalPreset(color: RGBAColor) {
  editColor.value = { ...color };
  hexInput.value = rgbToHex(color);
  applyColor();
}

// Spectrum handlers
function updateFromSpectrum(x: number, y: number) {
  if (!spectrumRef.value) return;
  const rect = spectrumRef.value.getBoundingClientRect();
  spectrumX.value = Math.max(0, Math.min(1, (x - rect.left) / rect.width));
  spectrumY.value = Math.max(0, Math.min(1, (y - rect.top) / rect.height));

  // Convert position to color
  // X = hue (0-360), Y = white at top, saturated in middle, black at bottom
  const h = spectrumX.value * 360;
  const l = 100 - spectrumY.value * 100;
  const s = spectrumY.value < 0.5 ? spectrumY.value * 2 * 100 : (1 - (spectrumY.value - 0.5) * 2) * 100;

  editColor.value = hslToRgb(h, Math.max(0, s), l);
  hexInput.value = rgbToHex(editColor.value);
  applyColor();
}

function handleSpectrumDown(e: MouseEvent) {
  isDraggingSpectrum.value = true;
  updateFromSpectrum(e.clientX, e.clientY);
}

// Opacity handlers
function updateFromOpacity(x: number) {
  if (!opacityRef.value) return;
  const rect = opacityRef.value.getBoundingClientRect();
  editOpacity.value = Math.round(Math.max(0, Math.min(100, ((x - rect.left) / rect.width) * 100)));
  applyColor();
}

function handleOpacityDown(e: MouseEvent) {
  isDraggingOpacity.value = true;
  updateFromOpacity(e.clientX);
}

// RGB slider handlers
function updateRed(x: number) {
  if (!redSliderRef.value) return;
  const rect = redSliderRef.value.getBoundingClientRect();
  editColor.value.r = Math.round(Math.max(0, Math.min(255, ((x - rect.left) / rect.width) * 255)));
  hexInput.value = rgbToHex(editColor.value);
  applyColor();
}

function updateGreen(x: number) {
  if (!greenSliderRef.value) return;
  const rect = greenSliderRef.value.getBoundingClientRect();
  editColor.value.g = Math.round(Math.max(0, Math.min(255, ((x - rect.left) / rect.width) * 255)));
  hexInput.value = rgbToHex(editColor.value);
  applyColor();
}

function updateBlue(x: number) {
  if (!blueSliderRef.value) return;
  const rect = blueSliderRef.value.getBoundingClientRect();
  editColor.value.b = Math.round(Math.max(0, Math.min(255, ((x - rect.left) / rect.width) * 255)));
  hexInput.value = rgbToHex(editColor.value);
  applyColor();
}

function handleRedDown(e: MouseEvent) { isDraggingRed.value = true; updateRed(e.clientX); }
function handleGreenDown(e: MouseEvent) { isDraggingGreen.value = true; updateGreen(e.clientX); }
function handleBlueDown(e: MouseEvent) { isDraggingBlue.value = true; updateBlue(e.clientX); }

// Hex input
function handleHexChange() {
  const color = hexToRgb(hexInput.value);
  if (color) {
    editColor.value = color;
    applyColor();
  }
}

// Eyedropper
async function openEyeDropper() {
  showModal.value = false;

  if (!eyeDropperSupported.value) return;

  try {
    // @ts-ignore
    const eyeDropper = new EyeDropper();
    const result = await eyeDropper.open();
    const color = hexToRgb(result.sRGBHex.replace('#', ''));
    if (color) {
      emit('update:modelValue', { ...color, a: editOpacity.value / 100 });
    }
  } catch {
    // User cancelled
  }
}

// No fill
function selectNoFill() {
  emit('update:modelValue', null);
}

// Global mouse handlers
function handleMouseMove(e: MouseEvent) {
  if (isDraggingSpectrum.value) updateFromSpectrum(e.clientX, e.clientY);
  if (isDraggingOpacity.value) updateFromOpacity(e.clientX);
  if (isDraggingRed.value) updateRed(e.clientX);
  if (isDraggingGreen.value) updateGreen(e.clientX);
  if (isDraggingBlue.value) updateBlue(e.clientX);
}

function handleMouseUp() {
  isDraggingSpectrum.value = false;
  isDraggingOpacity.value = false;
  isDraggingRed.value = false;
  isDraggingGreen.value = false;
  isDraggingBlue.value = false;
}

onMounted(() => {
  document.addEventListener('mousemove', handleMouseMove);
  document.addEventListener('mouseup', handleMouseUp);
});

onUnmounted(() => {
  document.removeEventListener('mousemove', handleMouseMove);
  document.removeEventListener('mouseup', handleMouseUp);
});

// Computed styles
const spectrumPos = computed(() => ({
  left: `${spectrumX.value * 100}%`,
  top: `${spectrumY.value * 100}%`,
}));

const opacityPos = computed(() => ({
  left: `${editOpacity.value}%`,
}));

const redSliderBg = computed(() => {
  const { g, b } = editColor.value;
  return `linear-gradient(to right, rgb(0,${g},${b}), rgb(255,${g},${b}))`;
});

const greenSliderBg = computed(() => {
  const { r, b } = editColor.value;
  return `linear-gradient(to right, rgb(${r},0,${b}), rgb(${r},255,${b}))`;
});

const blueSliderBg = computed(() => {
  const { r, g } = editColor.value;
  return `linear-gradient(to right, rgb(${r},${g},0), rgb(${r},${g},255))`;
});

const opacityBg = computed(() => {
  const { r, g, b } = editColor.value;
  return `linear-gradient(to right, rgba(${r},${g},${b},0), rgb(${r},${g},${b}))`;
});

// Expose methods for external use
defineExpose({
  openModal,
  closeModal,
});
</script>

<template>
  <div class="stimma-color-picker">
    <!-- Preview bar row -->
    <div class="stimma-color-picker__preview-row">
      <button
        class="stimma-color-picker__preview"
        :style="modelValue ? { backgroundColor: colorToCss(modelValue) } : {}"
        :class="{ 'stimma-color-picker__preview--none': !modelValue }"
        title="More colors"
        @click="openModal"
      />
    </div>

    <!-- Swatch grid -->
    <div class="stimma-color-picker__grid">
      <!-- No fill option -->
      <button
        v-if="allowNull"
        class="stimma-color-picker__swatch stimma-color-picker__swatch--none"
        :class="{ 'stimma-color-picker__swatch--active': modelValue === null }"
        title="No fill"
        @click="selectNoFill"
      />

      <!-- Static colors -->
      <button
        v-for="(color, i) in staticQuickColors"
        :key="'static-' + i"
        class="stimma-color-picker__swatch"
        :class="{ 'stimma-color-picker__swatch--active': isActiveQuick(color) }"
        :style="{ backgroundColor: colorToCss(color) }"
        @click="selectColor(color)"
      />

      <!-- Image palette colors -->
      <template v-if="limitedImagePalette.length > 0">
        <button
          v-for="(color, i) in limitedImagePalette"
          :key="'palette-' + i"
          class="stimma-color-picker__swatch stimma-color-picker__swatch--palette"
          :class="{ 'stimma-color-picker__swatch--active': isActiveQuick(color) }"
          :style="{ backgroundColor: colorToCss(color) }"
          :title="'From image'"
          @click="selectColor(color)"
        />
      </template>
    </div>

    <!-- Modal -->
    <Teleport to="body">
      <div
        v-if="showModal"
        class="stimma-color-modal__backdrop"
        :class="{ 'stimma-editor--dark': isDarkTheme }"
        @click="closeModal"
      >
        <div class="stimma-color-modal" @click.stop>
          <!-- Header -->
          <div class="stimma-color-modal__header">
            <button
              v-if="eyeDropperSupported"
              class="stimma-color-modal__eyedropper"
              title="Pick from screen"
              @click="openEyeDropper"
            >
              <Icon name="eyeDropper" :size="20" />
            </button>
            <span v-else />
            <span class="stimma-color-modal__title">Colors</span>
            <button class="stimma-color-modal__close" @click="closeModal">
              <Icon name="close" :size="20" />
            </button>
          </div>

          <!-- Tabs -->
          <div class="stimma-color-modal__tabs">
            <button
              class="stimma-color-modal__tab"
              :class="{ 'stimma-color-modal__tab--active': activeTab === 'grid' }"
              @click="activeTab = 'grid'"
            >
              Grid
            </button>
            <button
              class="stimma-color-modal__tab"
              :class="{ 'stimma-color-modal__tab--active': activeTab === 'spectrum' }"
              @click="activeTab = 'spectrum'"
            >
              Spectrum
            </button>
            <button
              class="stimma-color-modal__tab"
              :class="{ 'stimma-color-modal__tab--active': activeTab === 'sliders' }"
              @click="activeTab = 'sliders'"
            >
              Sliders
            </button>
          </div>

          <!-- Tab content -->
          <div class="stimma-color-modal__content">
            <!-- Grid -->
            <div v-if="activeTab === 'grid'" class="stimma-color-modal__grid">
              <button
                v-for="(color, i) in gridColors"
                :key="i"
                class="stimma-color-modal__grid-cell"
                :style="{ backgroundColor: colorToCss(color) }"
                @click="selectGridColor(color)"
              />
            </div>

            <!-- Spectrum -->
            <div v-if="activeTab === 'spectrum'" class="stimma-color-modal__spectrum-wrap">
              <div
                ref="spectrumRef"
                class="stimma-color-modal__spectrum"
                @mousedown="handleSpectrumDown"
              >
                <div class="stimma-color-modal__spectrum-handle" :style="spectrumPos" />
              </div>
            </div>

            <!-- Sliders -->
            <div v-if="activeTab === 'sliders'" class="stimma-color-modal__sliders">
              <div class="stimma-color-modal__slider-group">
                <label class="stimma-color-modal__slider-label">RED</label>
                <div class="stimma-color-modal__slider-row">
                  <div
                    ref="redSliderRef"
                    class="stimma-color-modal__slider-track"
                    :style="{ background: redSliderBg }"
                    @mousedown="handleRedDown"
                  >
                    <div
                      class="stimma-color-modal__slider-handle"
                      :style="{ left: `${(editColor.r / 255) * 100}%` }"
                    />
                  </div>
                  <span class="stimma-color-modal__slider-value">{{ editColor.r }}</span>
                </div>
              </div>

              <div class="stimma-color-modal__slider-group">
                <label class="stimma-color-modal__slider-label">GREEN</label>
                <div class="stimma-color-modal__slider-row">
                  <div
                    ref="greenSliderRef"
                    class="stimma-color-modal__slider-track"
                    :style="{ background: greenSliderBg }"
                    @mousedown="handleGreenDown"
                  >
                    <div
                      class="stimma-color-modal__slider-handle"
                      :style="{ left: `${(editColor.g / 255) * 100}%` }"
                    />
                  </div>
                  <span class="stimma-color-modal__slider-value">{{ editColor.g }}</span>
                </div>
              </div>

              <div class="stimma-color-modal__slider-group">
                <label class="stimma-color-modal__slider-label">BLUE</label>
                <div class="stimma-color-modal__slider-row">
                  <div
                    ref="blueSliderRef"
                    class="stimma-color-modal__slider-track"
                    :style="{ background: blueSliderBg }"
                    @mousedown="handleBlueDown"
                  >
                    <div
                      class="stimma-color-modal__slider-handle"
                      :style="{ left: `${(editColor.b / 255) * 100}%` }"
                    />
                  </div>
                  <span class="stimma-color-modal__slider-value">{{ editColor.b }}</span>
                </div>
              </div>

              <div class="stimma-color-modal__hex-row">
                <span class="stimma-color-modal__hex-label">Hex Color #</span>
                <input
                  v-model="hexInput"
                  class="stimma-color-modal__hex-input"
                  maxlength="6"
                  @change="handleHexChange"
                  @keyup.enter="handleHexChange"
                />
              </div>
            </div>
          </div>

          <!-- Opacity -->
          <div class="stimma-color-modal__opacity-section">
            <label class="stimma-color-modal__slider-label">OPACITY</label>
            <div class="stimma-color-modal__slider-row">
              <div
                ref="opacityRef"
                class="stimma-color-modal__slider-track stimma-color-modal__slider-track--opacity"
                @mousedown="handleOpacityDown"
              >
                <div class="stimma-color-modal__opacity-gradient" :style="{ background: opacityBg }" />
                <div class="stimma-color-modal__slider-handle" :style="opacityPos" />
              </div>
              <span class="stimma-color-modal__slider-value">{{ editOpacity }} %</span>
            </div>
          </div>

          <!-- Bottom presets -->
          <div class="stimma-color-modal__presets">
            <div
              class="stimma-color-modal__preview"
              :style="{ backgroundColor: colorToCss(editColor, editOpacity) }"
            />
            <button
              v-for="(color, i) in modalPresets"
              :key="i"
              class="stimma-color-modal__preset"
              :style="{ backgroundColor: colorToCss(color) }"
              @click="selectModalPreset(color)"
            />
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
/* Preview row - centered over grid with 2 swatch padding on each side */
.stimma-color-picker__preview-row {
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 8px;
}

.stimma-color-picker__preview {
  /* 4 swatches wide + 3 gaps */
  width: calc(4 * 26px + 3 * 4px);
  height: 36px;
  border-radius: 6px;
  border: none;
  cursor: pointer;
  transition: transform 0.1s, box-shadow 0.1s;
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.15), 0 0 0 1px rgba(255, 255, 255, 0.1);
}

.stimma-color-picker__preview:hover {
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.2), 0 0 0 1px rgba(255, 255, 255, 0.15), 0 2px 4px rgba(0, 0, 0, 0.2);
}

.stimma-color-picker__preview--none {
  background-color: #fff;
  background-image:
    linear-gradient(45deg, #ccc 25%, transparent 25%),
    linear-gradient(-45deg, #ccc 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, #ccc 75%),
    linear-gradient(-45deg, transparent 75%, #ccc 75%);
  background-size: 10px 10px;
  background-position: 0 0, 0 5px, 5px -5px, -5px 0px;
}

/* Swatch grid - 8 columns */
.stimma-color-picker__grid {
  display: grid;
  grid-template-columns: repeat(8, 26px);
  gap: 4px;
}

.stimma-color-picker__swatch {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  border: none;
  cursor: pointer;
  transition: transform 0.1s, box-shadow 0.1s;
  padding: 0;
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.15), 0 0 0 1px rgba(255, 255, 255, 0.1);
}

.stimma-color-picker__swatch:hover {
  transform: scale(1.1);
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.2), 0 0 0 1px rgba(255, 255, 255, 0.15), 0 2px 4px rgba(0, 0, 0, 0.2);
}

.stimma-color-picker__swatch--active {
  transform: scale(1.1);
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.15), 0 0 0 2px rgb(var(--stimma-color-primary)), 0 0 0 4px rgba(var(--stimma-color-primary), 0.3);
}

.stimma-color-picker__swatch--none {
  background-color: #fff;
  background-image:
    linear-gradient(45deg, #ccc 25%, transparent 25%),
    linear-gradient(-45deg, #ccc 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, #ccc 75%),
    linear-gradient(-45deg, transparent 75%, #ccc 75%);
  background-size: 8px 8px;
  background-position: 0 0, 0 4px, 4px -4px, -4px 0px;
}

.stimma-color-picker__swatch--palette {
  border-radius: 50%;
}

/* Modal */
.stimma-color-modal__backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
}

.stimma-color-modal {
  width: 300px;
  background: rgb(var(--stimma-color-background));
  color: rgb(var(--stimma-color-foreground));
  border-radius: 16px;
  padding: 16px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
}

.stimma-color-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.stimma-color-modal__eyedropper,
.stimma-color-modal__close {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: rgba(var(--stimma-color-foreground), 0.7);
  cursor: pointer;
  border-radius: 6px;
}

.stimma-color-modal__eyedropper:hover,
.stimma-color-modal__close:hover {
  background: rgba(var(--stimma-color-foreground), 0.1);
}

.stimma-color-modal__title {
  font-weight: 600;
  font-size: 16px;
}

/* Tabs */
.stimma-color-modal__tabs {
  display: flex;
  background: rgba(var(--stimma-color-foreground), 0.08);
  border-radius: 8px;
  padding: 3px;
  margin-bottom: 12px;
}

.stimma-color-modal__tab {
  flex: 1;
  padding: 6px 12px;
  border: none;
  background: transparent;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  color: rgba(var(--stimma-color-foreground), 0.6);
  cursor: pointer;
  transition: all 0.15s;
}

.stimma-color-modal__tab--active {
  background: rgb(var(--stimma-color-background));
  color: rgb(var(--stimma-color-foreground));
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

/* Content */
.stimma-color-modal__content {
  min-height: 200px;
  margin-bottom: 16px;
}

/* Grid */
.stimma-color-modal__grid {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: 2px;
}

.stimma-color-modal__grid-cell {
  aspect-ratio: 1;
  border: none;
  cursor: pointer;
  transition: transform 0.1s;
}

.stimma-color-modal__grid-cell:hover {
  transform: scale(1.2);
  z-index: 1;
  position: relative;
}

/* Spectrum */
.stimma-color-modal__spectrum-wrap {
  height: 200px;
}

.stimma-color-modal__spectrum {
  width: 100%;
  height: 100%;
  border-radius: 8px;
  cursor: crosshair;
  position: relative;
  background:
    linear-gradient(to bottom, white 0%, transparent 50%, black 100%),
    linear-gradient(to right,
      hsl(0, 100%, 50%),
      hsl(60, 100%, 50%),
      hsl(120, 100%, 50%),
      hsl(180, 100%, 50%),
      hsl(240, 100%, 50%),
      hsl(300, 100%, 50%),
      hsl(360, 100%, 50%)
    );
}

.stimma-color-modal__spectrum-handle {
  position: absolute;
  width: 20px;
  height: 20px;
  border: 3px solid white;
  border-radius: 50%;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.3), 0 2px 4px rgba(0, 0, 0, 0.3);
  transform: translate(-50%, -50%);
  pointer-events: none;
}

/* Sliders */
.stimma-color-modal__sliders {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.stimma-color-modal__slider-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.stimma-color-modal__slider-label {
  font-size: 11px;
  font-weight: 600;
  color: rgba(var(--stimma-color-foreground), 0.5);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.stimma-color-modal__slider-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.stimma-color-modal__slider-track {
  flex: 1;
  height: 28px;
  border-radius: 14px;
  position: relative;
  cursor: pointer;
}

.stimma-color-modal__slider-track--opacity {
  background: repeating-conic-gradient(
    rgba(var(--stimma-color-foreground), 0.15) 0% 25%,
    rgba(var(--stimma-color-foreground), 0.05) 0% 50%
  ) 50% / 12px 12px;
}

.stimma-color-modal__opacity-gradient {
  position: absolute;
  inset: 0;
  border-radius: 14px;
}

.stimma-color-modal__slider-handle {
  position: absolute;
  top: 50%;
  width: 24px;
  height: 24px;
  border: 3px solid white;
  border-radius: 50%;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.15), 0 2px 4px rgba(0, 0, 0, 0.2);
  transform: translate(-50%, -50%);
  pointer-events: none;
  background: transparent;
}

.stimma-color-modal__slider-value {
  min-width: 48px;
  padding: 6px 10px;
  background: rgba(var(--stimma-color-foreground), 0.1);
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  text-align: center;
  color: rgb(var(--stimma-color-foreground));
}

.stimma-color-modal__hex-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}

.stimma-color-modal__hex-label {
  font-size: 13px;
  color: rgba(var(--stimma-color-foreground), 0.6);
}

.stimma-color-modal__hex-input {
  width: 80px;
  padding: 6px 10px;
  background: rgba(var(--stimma-color-foreground), 0.1);
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  font-family: monospace;
  text-align: center;
  text-transform: uppercase;
  color: rgb(var(--stimma-color-foreground));
}

.stimma-color-modal__hex-input:focus {
  outline: none;
  box-shadow: 0 0 0 2px rgb(var(--stimma-color-primary));
}

/* Opacity section */
.stimma-color-modal__opacity-section {
  padding-top: 16px;
  border-top: 1px solid rgba(var(--stimma-color-foreground), 0.1);
  margin-bottom: 16px;
}

/* Presets */
.stimma-color-modal__presets {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 16px;
  border-top: 1px solid rgba(var(--stimma-color-foreground), 0.1);
}

.stimma-color-modal__preview {
  width: 48px;
  height: 48px;
  border-radius: 8px;
  border: 2px solid rgba(var(--stimma-color-foreground), 0.15);
}

.stimma-color-modal__preset {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: none;
  cursor: pointer;
  transition: transform 0.1s;
}

.stimma-color-modal__preset:hover {
  transform: scale(1.05);
}
</style>
