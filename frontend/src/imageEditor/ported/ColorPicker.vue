<script setup lang="ts">
/**
 * The editor's color picker, rebuilt to the Variant-A mock
 * (plans/COLOR_PICKER_MOCK.html): the color IS the header — well, opacity %,
 * eyedropper — over Grid/Spectrum/Manual tabs, a slim opacity row, and
 * exactly two swatch rows: "From this image" (the extracted palette) and
 * "Recent" (self-filling). The preset cartoon palettes are gone. The Manual
 * tab holds every way of NAMING a color rather than pointing at one: the hex
 * field and the RGB sliders with editable channel numbers.
 *
 * The grid is generated in OKLCH — perceptual lightness/chroma steps — so
 * every row keeps a visible difference; the old HSL ramp collapsed its light
 * rows into an indistinguishable field of near-whites.
 */
import { ref, computed, watch, onMounted, onUnmounted } from 'vue';
import { makeProfileKey } from '../../utils/storageKeys';

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
    /** Kept for call-site compatibility; the picker is always the panel now. */
    embedded?: boolean;
  }>(),
  {
    allowNull: false,
  }
);

const emit = defineEmits<{
  (e: 'update:modelValue', color: RGBAColor | null): void;
}>();

// -- color math --------------------------------------------------------------

function rgbToHex(color: RGBAColor): string {
  const r = color.r.toString(16).padStart(2, '0');
  const g = color.g.toString(16).padStart(2, '0');
  const b = color.b.toString(16).padStart(2, '0');
  return `${r}${g}${b}`.toUpperCase();
}

function hexToRgb(hex: string): RGBAColor | null {
  const clean = hex.replace('#', '');
  const result = /^([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(clean);
  if (!result) return null;
  return {
    r: parseInt(result[1], 16),
    g: parseInt(result[2], 16),
    b: parseInt(result[3], 16),
    a: 1,
  };
}

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

/** OKLCH → sRGB, gamut-clamped. Standard Björn Ottosson OKLab math. */
function oklchToRgb(L: number, C: number, H: number): RGBAColor {
  const hr = (H * Math.PI) / 180;
  const a = C * Math.cos(hr);
  const b = C * Math.sin(hr);
  const l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s_ = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const lin = [
    4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
    -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
    -0.0041960863 * l_ - 0.7034186147 * m_ + 1.707614701 * s_,
  ].map(c => {
    c = Math.min(1, Math.max(0, c));
    return c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055;
  });
  return {
    r: Math.round(lin[0] * 255),
    g: Math.round(lin[1] * 255),
    b: Math.round(lin[2] * 255),
    a: 1,
  };
}

function colorToCss(color: RGBAColor, opacity?: number): string {
  const a = opacity !== undefined ? opacity / 100 : (color.a ?? 1);
  return `rgba(${color.r}, ${color.g}, ${color.b}, ${a})`;
}

// -- state -------------------------------------------------------------------

const TAB_KEY = () => makeProfileKey('imageEditor', 'colorPicker', 'tab');
const RECENTS_KEY = () => makeProfileKey('imageEditor', 'colorPicker', 'recents');

const activeTab = ref<'grid' | 'spectrum' | 'sliders'>('grid');
const editColor = ref<RGBAColor>({ r: 255, g: 255, b: 255, a: 1 });
const editOpacity = ref(100);
const hexInput = ref('FFFFFF');
const recents = ref<string[]>([]);
const spectrumX = ref(0);
const spectrumY = ref(0);

/** Sync from the outside in — the parent may set the color elsewhere. */
watch(
  () => props.modelValue,
  value => {
    if (!value) return;
    // Our own emits echo back through this prop; re-deriving the spectrum
    // position from them would fight the drag in progress. Only real external
    // changes sync in.
    if (
      value.r === editColor.value.r &&
      value.g === editColor.value.g &&
      value.b === editColor.value.b &&
      Math.round((value.a ?? 1) * 100) === editOpacity.value
    ) return;
    editColor.value = { r: value.r, g: value.g, b: value.b };
    editOpacity.value = Math.round((value.a ?? 1) * 100);
    hexInput.value = rgbToHex(value);
    const hsl = rgbToHsl(value);
    spectrumX.value = hsl.h / 360;
    spectrumY.value = 1 - hsl.l / 100;
  },
  { immediate: true }
);

function applyColor() {
  emit('update:modelValue', { ...editColor.value, a: editOpacity.value / 100 });
}

function setColor(color: RGBAColor) {
  editColor.value = { r: color.r, g: color.g, b: color.b };
  hexInput.value = rgbToHex(color);
  applyColor();
}

/**
 * Recents fill themselves from COMMITTED picks — a click, a released drag, an
 * entered hex — never from every drag tick, or one spectrum swipe would flood
 * all twelve slots with its trail.
 */
const RECENTS_MAX = 12;
function pushRecent(color: RGBAColor) {
  const hex = rgbToHex(color);
  recents.value = [hex, ...recents.value.filter(h => h !== hex)].slice(0, RECENTS_MAX);
  try {
    localStorage.setItem(RECENTS_KEY(), JSON.stringify(recents.value));
  } catch { /* storage full or unavailable — recents just don't persist */ }
}

function isCurrent(color: RGBAColor): boolean {
  return (
    !!props.modelValue &&
    editColor.value.r === color.r &&
    editColor.value.g === color.g &&
    editColor.value.b === color.b
  );
}

// -- grid --------------------------------------------------------------------

/**
 * A neutral ramp, then 12 hues × 6 OKLCH tones. The chroma curve peaks in the
 * mid rows and eases off at both ends, which is what keeps the light rows
 * legible as colors rather than a field of white.
 */
const gridColors = computed<RGBAColor[]>(() => {
  const colors: RGBAColor[] = [];
  for (let i = 0; i < 12; i++) {
    colors.push(oklchToRgb(0.98 - (i * 0.78) / 11, 0, 0));
  }
  const tones = [
    { l: 0.85, c: 0.09 }, { l: 0.76, c: 0.13 }, { l: 0.66, c: 0.17 },
    { l: 0.56, c: 0.19 }, { l: 0.46, c: 0.16 }, { l: 0.35, c: 0.11 },
  ];
  for (const tone of tones) {
    for (let h = 0; h < 12; h++) {
      colors.push(oklchToRgb(tone.l, tone.c, 15 + h * 30));
    }
  }
  return colors;
});

const imageChips = computed(() => (props.imagePalette ?? []).slice(0, RECENTS_MAX));

function pickChip(color: RGBAColor) {
  setColor(color);
  pushRecent(color);
}

function selectNoFill() {
  emit('update:modelValue', null);
}

// -- spectrum ----------------------------------------------------------------

const spectrumRef = ref<HTMLElement | null>(null);
const isDraggingSpectrum = ref(false);

function updateFromSpectrum(x: number, y: number) {
  if (!spectrumRef.value) return;
  const rect = spectrumRef.value.getBoundingClientRect();
  spectrumX.value = Math.max(0, Math.min(1, (x - rect.left) / rect.width));
  spectrumY.value = Math.max(0, Math.min(1, (y - rect.top) / rect.height));
  const h = spectrumX.value * 360;
  const l = 100 - spectrumY.value * 100;
  const s = spectrumY.value < 0.5 ? spectrumY.value * 2 * 100 : (1 - (spectrumY.value - 0.5) * 2) * 100;
  editColor.value = hslToRgb(h, Math.max(0, s), l);
  hexInput.value = rgbToHex(editColor.value);
  applyColor();
}

function handleSpectrumDown(e: PointerEvent) {
  if (!beginDrag(e)) return;
  isDraggingSpectrum.value = true;
  updateFromSpectrum(e.clientX, e.clientY);
}

const spectrumPos = computed(() => ({
  left: `${spectrumX.value * 100}%`,
  top: `${spectrumY.value * 100}%`,
}));

// -- rgb sliders -------------------------------------------------------------

const channelRefs = {
  r: ref<HTMLElement | null>(null),
  g: ref<HTMLElement | null>(null),
  b: ref<HTMLElement | null>(null),
};
const draggingChannel = ref<null | 'r' | 'g' | 'b'>(null);

function updateChannel(channel: 'r' | 'g' | 'b', x: number) {
  const el = channelRefs[channel].value;
  if (!el) return;
  const rect = el.getBoundingClientRect();
  editColor.value[channel] = Math.round(
    Math.max(0, Math.min(255, ((x - rect.left) / rect.width) * 255))
  );
  hexInput.value = rgbToHex(editColor.value);
  applyColor();
}

const channelBg = computed(() => {
  const { r, g, b } = editColor.value;
  return {
    r: `linear-gradient(to right, rgb(0,${g},${b}), rgb(255,${g},${b}))`,
    g: `linear-gradient(to right, rgb(${r},0,${b}), rgb(${r},255,${b}))`,
    b: `linear-gradient(to right, rgb(${r},${g},0), rgb(${r},${g},255))`,
  };
});

const CHANNELS = [
  { id: 'r', label: 'R' },
  { id: 'g', label: 'G' },
  { id: 'b', label: 'B' },
] as const;

// -- opacity -----------------------------------------------------------------

const opacityRef = ref<HTMLElement | null>(null);
const isDraggingOpacity = ref(false);

function updateFromOpacity(x: number) {
  if (!opacityRef.value) return;
  const rect = opacityRef.value.getBoundingClientRect();
  editOpacity.value = Math.round(
    Math.max(0, Math.min(100, ((x - rect.left) / rect.width) * 100))
  );
  applyColor();
}

function onOpacityInput(event: Event) {
  const value = Number((event.target as HTMLInputElement).value);
  if (Number.isFinite(value)) {
    editOpacity.value = Math.max(0, Math.min(100, Math.round(value)));
    applyColor();
  }
}

const opacityBg = computed(() => {
  const { r, g, b } = editColor.value;
  return `linear-gradient(to right, rgba(${r},${g},${b},0), rgb(${r},${g},${b}))`;
});

// -- manual entry + eyedropper -------------------------------------------------

function handleHexChange() {
  const color = hexToRgb(hexInput.value);
  if (color) {
    setColor(color);
    pushRecent(color);
  } else if (props.modelValue) {
    hexInput.value = rgbToHex(props.modelValue);
  }
}

/** A typed channel value is a committed pick, like an entered hex. */
function handleChannelEntry(channel: 'r' | 'g' | 'b', raw: string) {
  const value = Number(raw);
  if (!Number.isFinite(value)) return;
  editColor.value[channel] = Math.round(Math.max(0, Math.min(255, value)));
  hexInput.value = rgbToHex(editColor.value);
  applyColor();
  pushRecent(editColor.value);
}

const eyeDropperSupported = ref(false);

async function openEyeDropper() {
  try {
    // @ts-ignore - Chromium-only API; the button hides where it is absent.
    const result = await new EyeDropper().open();
    const color = hexToRgb(result.sRGBHex);
    if (color) {
      setColor(color);
      pushRecent(color);
    }
  } catch { /* user cancelled */ }
}

let dragPointerId: number | null = null;
function beginDrag(event: PointerEvent): boolean {
  if (!event.isPrimary || event.button !== 0 || dragPointerId !== null) return false;
  dragPointerId = event.pointerId;
  (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
  return true;
}

// -- global drag plumbing ----------------------------------------------------

function handleMouseMove(e: PointerEvent) {
  if (e.pointerId !== dragPointerId) return;
  if (isDraggingSpectrum.value) updateFromSpectrum(e.clientX, e.clientY);
  if (isDraggingOpacity.value) updateFromOpacity(e.clientX);
  if (draggingChannel.value) updateChannel(draggingChannel.value, e.clientX);
}

function handleMouseUp(e: PointerEvent) {
  if (e.pointerId !== dragPointerId) return;
  dragPointerId = null;
  // A released drag is a committed pick; that is when it earns a recent slot.
  if (isDraggingSpectrum.value || draggingChannel.value) pushRecent(editColor.value);
  isDraggingSpectrum.value = false;
  isDraggingOpacity.value = false;
  draggingChannel.value = null;
}

onMounted(() => {
  eyeDropperSupported.value = 'EyeDropper' in window;
  try {
    const stored = localStorage.getItem(RECENTS_KEY());
    if (stored) recents.value = JSON.parse(stored).slice(0, RECENTS_MAX);
    const tab = localStorage.getItem(TAB_KEY());
    if (tab === 'grid' || tab === 'spectrum' || tab === 'sliders') activeTab.value = tab;
  } catch { /* fall back to defaults */ }
  document.addEventListener('pointermove', handleMouseMove);
  document.addEventListener('pointerup', handleMouseUp);
  document.addEventListener('pointercancel', handleMouseUp);
});

onUnmounted(() => {
  document.removeEventListener('pointermove', handleMouseMove);
  document.removeEventListener('pointerup', handleMouseUp);
  document.removeEventListener('pointercancel', handleMouseUp);
});

function chooseTab(tab: 'grid' | 'spectrum' | 'sliders') {
  activeTab.value = tab;
  try {
    localStorage.setItem(TAB_KEY(), tab);
  } catch { /* preference just doesn't persist */ }
}

// 'sliders' keeps its stored id so a remembered tab choice survives the rename.
const TABS = [
  { id: 'grid', label: 'Grid' },
  { id: 'spectrum', label: 'Spectrum' },
  { id: 'sliders', label: 'Manual' },
] as const;
</script>

<template>
  <div class="w-full text-content">
    <!-- The color is the header: well, hex, opacity, eyedropper. -->
    <div class="flex items-center gap-2 mb-2.5">
      <div
        class="w-9 h-7 shrink-0 rounded border border-edge-strong"
        :style="{
          background: modelValue
            ? `linear-gradient(${colorToCss(editColor, editOpacity)}, ${colorToCss(editColor, editOpacity)}),
               repeating-conic-gradient(rgba(255,255,255,.12) 0% 25%, rgba(255,255,255,.04) 0% 50%) 0 0/8px 8px`
            : 'repeating-conic-gradient(rgba(255,255,255,.12) 0% 25%, rgba(255,255,255,.04) 0% 50%) 0 0/8px 8px',
        }"
      />
      <div class="flex-1" />
      <div class="flex items-center gap-0.5 px-2 py-1 bg-surface-raised rounded-md">
        <input
          :value="editOpacity"
          type="number" min="0" max="100"
          class="w-8 bg-transparent text-xs tabular-nums text-right text-content-secondary
                 focus:outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none"
          @change="onOpacityInput"
        />
        <span class="text-xs text-content-tertiary">%</span>
      </div>
      <button
        v-if="allowNull"
        type="button"
        title="No fill"
        class="w-7 h-7 shrink-0 grid place-items-center rounded-md border
               hover:bg-overlay-subtle"
        :class="modelValue === null ? 'border-selection' : 'border-edge-subtle'"
        @click="selectNoFill"
      >
        <svg viewBox="0 0 24 24" class="w-3.5 h-3.5 text-red-400" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/></svg>
      </button>
      <button
        v-if="eyeDropperSupported"
        type="button"
        title="Pick from screen"
        class="w-7 h-7 shrink-0 grid place-items-center rounded-md text-content-secondary
               hover:text-content hover:bg-overlay-subtle"
        @click="openEyeDropper"
      >
        <svg viewBox="0 0 24 24" class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m2 22 1-1h3l9-9"/><path d="M3 21v-3l9-9"/><path d="m15 6 3.4-3.4a2.1 2.1 0 1 1 3 3L18 9l.4.4a2.1 2.1 0 1 1-3 3l-3.8-3.8a2.1 2.1 0 1 1 3-3l.4.4Z"/></svg>
      </button>
    </div>

    <!-- Mode tabs -->
    <div class="flex gap-0.5 p-0.5 mb-2.5 bg-surface-overlay rounded-lg">
      <button
        v-for="tab in TABS"
        :key="tab.id"
        type="button"
        class="flex-1 py-1 text-[11px] rounded-md transition-colors"
        :class="activeTab === tab.id
          ? 'bg-surface-raised text-content'
          : 'text-content-secondary hover:text-content'"
        @click="chooseTab(tab.id)"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- Grid -->
    <div v-if="activeTab === 'grid'" class="grid grid-cols-12 gap-0.5">
      <button
        v-for="(color, i) in gridColors"
        :key="i"
        :aria-label="rgbToHex(color)"
        type="button"
        class="aspect-square rounded-media"
        :class="isCurrent(color) ? 'outline outline-2 outline-selection outline-offset-1 relative z-[1]' : ''"
        :style="{ backgroundColor: colorToCss(color) }"
        @click="pickChip(color)"
      />
    </div>

    <!-- Spectrum -->
    <div
      v-else-if="activeTab === 'spectrum'"
      ref="spectrumRef"
      class="h-[150px] touch-none rounded-md border border-edge-subtle cursor-crosshair relative"
      :style="{
        background:
          'linear-gradient(to bottom, white 0%, transparent 50%, black 100%),' +
          'linear-gradient(to right, hsl(0,100%,50%), hsl(60,100%,50%), hsl(120,100%,50%), hsl(180,100%,50%), hsl(240,100%,50%), hsl(300,100%,50%), hsl(360,100%,50%))',
      }"
      @pointerdown="handleSpectrumDown"
    >
      <div
        class="absolute w-3 h-3 rounded-full border-2 border-white -translate-x-1/2 -translate-y-1/2 pointer-events-none
               shadow-[0_0_0_1px_rgba(0,0,0,.6)]"
        :style="spectrumPos"
      />
    </div>

    <!-- Manual: name the color instead of pointing at one — hex first, then
         the RGB sliders with typed channel values. -->
    <div v-else class="flex flex-col gap-2.5 py-1">
      <div class="flex items-center gap-1.5 px-2 py-1 bg-surface-raised rounded-md">
        <span class="text-xs text-content-tertiary">#</span>
        <input
          v-model="hexInput"
          maxlength="6"
          spellcheck="false"
          aria-label="Hex color"
          class="w-full bg-transparent text-xs tabular-nums uppercase text-content
                 focus:outline-none"
          @change="handleHexChange"
          @keyup.enter="handleHexChange"
        />
      </div>
      <div v-for="channel in CHANNELS" :key="channel.id" class="flex items-center gap-2">
        <span class="w-3 text-[11px] text-content-tertiary">{{ channel.label }}</span>
        <div
          :ref="el => (channelRefs[channel.id].value = el as HTMLElement)"
          class="flex-1 h-3 compact:h-11 touch-none rounded-full cursor-pointer relative border border-edge-subtle"
          :style="{ background: channelBg[channel.id] }"
          @pointerdown="if (beginDrag($event)) { draggingChannel = channel.id; updateChannel(channel.id, $event.clientX) }"
        >
          <div
            class="absolute top-1/2 w-3.5 h-3.5 rounded-full border-2 border-white -translate-x-1/2 -translate-y-1/2 pointer-events-none
                   shadow-[0_0_0_1px_rgba(0,0,0,.5)]"
            :style="{ left: `${(editColor[channel.id] / 255) * 100}%` }"
          />
        </div>
        <input
          :value="editColor[channel.id]"
          type="number" min="0" max="255"
          :aria-label="`${channel.label} channel`"
          class="w-10 px-1 py-0.5 bg-surface-raised rounded text-right text-[11px] tabular-nums
                 text-content-secondary focus:outline-none focus-visible:ring-2 ring-accent/60
                 [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none"
          @change="handleChannelEntry(channel.id, ($event.target as HTMLInputElement).value)"
        />
      </div>
    </div>

    <!-- Opacity -->
    <div class="flex items-center gap-2 mt-2.5">
      <span class="w-11 text-[11px] text-content-tertiary">Opacity</span>
      <div
        ref="opacityRef"
        class="flex-1 h-3 compact:h-11 touch-none rounded-full cursor-pointer relative
               [background:repeating-conic-gradient(rgba(255,255,255,.12)_0%_25%,rgba(255,255,255,.04)_0%_50%)_0_0/8px_8px]"
        @pointerdown="if (beginDrag($event)) { isDraggingOpacity = true; updateFromOpacity($event.clientX) }"
      >
        <div class="absolute inset-0 rounded-full" :style="{ background: opacityBg }" />
        <div
          class="absolute top-1/2 w-3.5 h-3.5 rounded-full border-2 border-white -translate-x-1/2 -translate-y-1/2 pointer-events-none
                 shadow-[0_0_0_1px_rgba(0,0,0,.5)]"
          :style="{ left: `${editOpacity}%` }"
        />
      </div>
      <span class="w-7 text-right text-[11px] tabular-nums text-content-secondary">
        {{ editOpacity }}
      </span>
    </div>

    <!-- Swatches: the image's own colors, then what was actually used. -->
    <template v-if="imageChips.length">
      <div class="mt-3 mb-1.5 text-[11px] text-content-tertiary">From this image</div>
      <div class="grid grid-cols-12 gap-0.5">
        <button
          v-for="(color, i) in imageChips"
          :key="'image-' + i"
          type="button"
          class="aspect-square rounded-media border border-white/[.06]"
          :class="isCurrent(color) ? 'outline outline-2 outline-selection outline-offset-1 relative z-[1]' : ''"
          :style="{ backgroundColor: colorToCss(color) }"
          @click="pickChip(color)"
        />
      </div>
    </template>

    <template v-if="recents.length">
      <div class="mt-3 mb-1.5 text-[11px] text-content-tertiary">Recent</div>
      <div class="grid grid-cols-12 gap-0.5">
        <button
          v-for="hex in recents"
          :key="'recent-' + hex"
          type="button"
          class="aspect-square rounded-media border border-white/[.06]"
          :class="hexInput === hex && modelValue ? 'outline outline-2 outline-selection outline-offset-1 relative z-[1]' : ''"
          :style="{ backgroundColor: '#' + hex }"
          @click="pickChip(hexToRgb(hex)!)"
        />
      </div>
    </template>
  </div>
</template>
