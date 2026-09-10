<script setup lang="ts">
/**
 * Ported from the retired editor's brush picker, restyled as a compact stack.
 *
 * The picker is one component used from two anchors: the toolbar chip
 * (ToolbarPopover) and the pen's quick popup beside the cursor
 * (CursorPopover, opened by a stylus side button). Both places get the same
 * layout: a live stroke ribbon, a flat preset grid, and full-row bar sliders
 * whose whole height is the drag target — pen-sized, not mouse-sized.
 *
 * A brush is not a property of the layer it painted, so per the placement
 * rule this hangs off the toolbar rather than living in the Edits inspector.
 */
import { ref, computed, onMounted, watch, nextTick, inject } from 'vue';
import type { BrushSettings, BrushPreset } from './geometry';
import type { ComputedRef } from 'vue';
import { BRUSH_PRESETS, settingsForPreset } from '../brush/brushPresets';
import { resolveBrushDab, seededRandom } from '../brush/brushRuntime';
import { createBrushMask } from './pixelOps';
import ToolIcon from '../components/ToolIcon.vue';
import type { BrushInputSample } from '../brush/types';

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

const presetDefinitionById = new Map(BRUSH_PRESETS.map(preset => [preset.id, preset]));
const presets: BrushPreset[] = BRUSH_PRESETS.map(definition => ({
  id: definition.id,
  name: definition.name,
  icon: definition.tip.kind,
  settings: settingsForPreset(definition),
  isEraser: definition.eraser,
}));
// Flat, category-ordered. Eleven brushes don't need six section headers —
// the stroke thumbnails and names carry it.
const visiblePresets = computed(() =>
  presets.filter(preset => !!preset.isEraser === props.isEraser));

// Current brush settings (for editing)
const editSettings = ref<BrushSettings>({ ...props.modelValue });
const activePresetId = ref<string | null>('hard-10');
const isEraser = ref(false);

// Canvas refs
const ribbonCanvasRef = ref<HTMLCanvasElement | null>(null);
const presetCanvasRefs = ref<Map<string, HTMLCanvasElement>>(new Map());

// Store preset canvas ref
function setPresetCanvasRef(el: HTMLCanvasElement | null, id: string) {
  if (el) {
    presetCanvasRefs.value.set(id, el);
  }
}

// Sync editSettings when modelValue changes externally
watch(() => props.modelValue, (newVal) => {
  editSettings.value = { ...newVal };
}, { deep: true });

// Sync isEraser when prop changes; the visible grid swaps, so its canvases
// remount and need a redraw.
watch(() => props.isEraser, (newVal) => {
  isEraser.value = newVal;
  if (newVal) {
    activePresetId.value = 'eraser';
  } else if (activePresetId.value === 'eraser') {
    activePresetId.value = null;
  }
  void nextTick(() => drawPresetPreviews());
}, { immediate: true });

// Check if preset matches current settings - structural comparison
function isPresetActive(preset: BrushPreset): boolean {
  if (preset.isEraser && !isEraser.value) return false;
  if (!preset.isEraser && isEraser.value) return false;

  if (currentPresetId() === preset.id) return true;
  // Old stored brushes have no id; compare their round-brush controls.
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

function currentPresetId(): string | undefined {
  return editSettings.value.presetId;
}

/** What the ribbon names: the preset, or the settings drifted off one. */
const ribbonLabel = computed(() => {
  const definition = editSettings.value.presetId
    ? presetDefinitionById.get(editSettings.value.presetId)
    : undefined;
  return definition ? `${definition.name} · ${definition.category}` : 'Custom brush';
});

// Select a preset. Pressure dynamics are a how-the-pen-behaves choice, not
// part of the tip, so they survive switching presets.
function selectPreset(preset: BrushPreset) {
  activePresetId.value = preset.id;
  isEraser.value = preset.isEraser ?? false;
  editSettings.value = {
    ...preset.settings,
    pressureSize: editSettings.value.pressureSize,
    pressureOpacity: editSettings.value.pressureOpacity,
  };
  emit('update:modelValue', { ...editSettings.value });
  emit('update:isEraser', isEraser.value);
}

function togglePressure(key: 'pressureSize' | 'pressureOpacity') {
  editSettings.value = { ...editSettings.value, [key]: !editSettings.value[key] };
  applySettings();
}

// Apply settings (called when sliders change)
function applySettings() {
  activePresetId.value = editSettings.value.presetId ?? null;
  emit('update:modelValue', { ...editSettings.value });
}

// Bar sliders: the whole row is the track, label and value live inside it.
type NumericBrushKey = 'size' | 'hardness' | 'opacity' | 'flow' | 'spacing';
interface SliderDef {
  key: NumericBrushKey;
  label: string;
  min: number;
  max: number;
  unit: string;
  pressureKey?: 'pressureSize' | 'pressureOpacity';
  pressureTitle?: string;
}
const SLIDERS: SliderDef[] = [
  { key: 'size', label: 'Size', min: 1, max: 100, unit: 'px',
    pressureKey: 'pressureSize', pressureTitle: 'Pen pressure controls brush size' },
  { key: 'hardness', label: 'Hardness', min: 0, max: 100, unit: '%' },
  { key: 'opacity', label: 'Opacity', min: 0, max: 100, unit: '%' },
  { key: 'flow', label: 'Flow', min: 0, max: 100, unit: '%',
    pressureKey: 'pressureOpacity', pressureTitle: 'Pen pressure controls paint flow' },
  { key: 'spacing', label: 'Spacing', min: 1, max: 100, unit: '%' },
];

function sliderFillWidth(def: SliderDef): string {
  const ratio = (editSettings.value[def.key] - def.min) / (def.max - def.min);
  return `${Math.max(1.5, ratio * 100)}%`;
}

function onSliderPointerDown(def: SliderDef, event: PointerEvent) {
  const track = event.currentTarget as HTMLElement;
  track.setPointerCapture(event.pointerId);
  const apply = (clientX: number) => {
    const rect = track.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const value = Math.round(def.min + ratio * (def.max - def.min));
    if (editSettings.value[def.key] === value) return;
    editSettings.value = { ...editSettings.value, [def.key]: value };
    applySettings();
  };
  apply(event.clientX);
  const move = (moveEvent: PointerEvent) => apply(moveEvent.clientX);
  const finish = () => {
    track.removeEventListener('pointermove', move);
    track.removeEventListener('pointerup', finish);
    track.removeEventListener('pointercancel', finish);
  };
  track.addEventListener('pointermove', move);
  track.addEventListener('pointerup', finish);
  track.addEventListener('pointercancel', finish);
  event.preventDefault();
}

// Theme-aware colors
/**
 * ADAPTED: the previews are canvas fills, so they cannot inherit a CSS token —
 * the original hard-coded neutral greys, which read as dead grey wells against
 * Atelier's blued surfaces. These read the app's own tokens instead, falling
 * back to the original values when the tokens are absent (standalone use).
 */
function token(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value ? `rgb(${value})` : fallback;
}

const previewColors = computed(() => {
  if (isDarkTheme.value) {
    return {
      brush: { r: 255, g: 255, b: 255 },
      presetBg: token('--color-matte-rgb', '#1e1e1e'),
    };
  } else {
    return {
      brush: { r: 40, g: 40, b: 40 },
      presetBg: token('--color-matte-rgb', '#e0e0e0'),
    };
  }
});

/**
 * The ribbon: one stroke drawn across the full width with the CURRENT
 * settings, sine pressure. It is the preview and the header in one — it
 * answers "what will this brush do" while sliders are dragged.
 */
function drawRibbon() {
  const canvas = ribbonCanvasRef.value;
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || 312;
  const height = canvas.clientHeight || 46;
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const colors = previewColors.value;
  ctx.fillStyle = colors.presetBg;
  ctx.fillRect(0, 0, width, height);

  const settings = editSettings.value;
  const definition = settings.presetId
    ? presetDefinitionById.get(settings.presetId)
    : undefined;
  const random = seededRandom(definition?.previewSeed ?? 2166136261);
  const steps = 40;
  for (let index = 0; index <= steps; index += 1) {
    const progress = index / steps;
    const input: BrushInputSample = {
      x: progress * width, y: height / 2, time: index * 8,
      pressure: 0.14 + Math.sin(progress * Math.PI) * 0.86,
      tiltX: 20, tiltY: 8, rotation: 0, tangentialPressure: 0,
      pointer: 'pen', eraser: false, velocity: 220,
      direction: 0, distance: progress * 160,
    };
    const x = 8 + progress * (width - 16);
    // The bottom ~14px belong to the label strip; the stroke rides above it.
    const strokeY = (height - 12) / 2;
    if (definition) {
      const dab = resolveBrushDab(input, settings, definition, random());
      const displaySize = Math.max(1.5, Math.min(height - 16, dab.size));
      drawMaskStamp(
        ctx, x, strokeY, displaySize, dab.hardness,
        dab.opacity, dab.flow, colors.brush, dab.aspect, dab.rotation, dab.tipAssetId,
      );
    } else {
      // Legacy settings with no preset: a plain round stroke, tapered by hand.
      const taper = 0.15 + Math.sin(progress * Math.PI) * 0.85;
      const displaySize = Math.max(1.5, Math.min(height - 16, settings.size * taper));
      drawMaskStamp(
        ctx, x, strokeY, displaySize,
        settings.hardness, settings.opacity, settings.flow, colors.brush,
      );
    }
  }

  // A big soft brush still bleeds into the strip; fade it back to the matte
  // so the label reads over any stroke.
  const matte = colors.presetBg.startsWith('rgb(') ? colors.presetBg : 'rgb(8 9 12)';
  const scrim = ctx.createLinearGradient(0, height - 20, 0, height);
  scrim.addColorStop(0, matte.replace(')', ' / 0)'));
  scrim.addColorStop(0.55, matte.replace(')', ' / 0.8)'));
  scrim.addColorStop(1, matte.replace(')', ' / 0.96)'));
  ctx.fillStyle = scrim;
  ctx.fillRect(0, height - 20, width, 20);
}

function drawMaskStamp(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  size: number,
  hardness: number,
  opacity: number,
  flow: number,
  color: { r: number; g: number; b: number },
  aspect = 1,
  rotation = 0,
  tipAssetId?: string,
) {
  const mask = createBrushMask(Math.max(1, Math.ceil(size)), hardness, aspect, rotation, tipAssetId);
  const stamp = document.createElement('canvas');
  stamp.width = mask.width;
  stamp.height = mask.height;
  const stampCtx = stamp.getContext('2d')!;
  stampCtx.putImageData(mask, 0, 0);
  stampCtx.globalCompositeOperation = 'source-in';
  stampCtx.fillStyle = `rgb(${color.r} ${color.g} ${color.b})`;
  stampCtx.fillRect(0, 0, stamp.width, stamp.height);
  ctx.globalAlpha = (opacity / 100) * (flow / 100);
  ctx.drawImage(stamp, x - stamp.width / 2, y - stamp.height / 2);
  ctx.globalAlpha = 1;
}

// Draw preset previews
function drawPresetPreviews() {
  const colors = previewColors.value;

  for (const preset of presets) {
    const canvas = presetCanvasRefs.value.get(preset.id);
    if (!canvas) continue;

    const ctx = canvas.getContext('2d');
    if (!ctx) continue;

    const definition = presetDefinitionById.get(preset.id);
    const width = canvas.width;
    const height = canvas.height;

    // Theme-aware background
    ctx.fillStyle = colors.presetBg;
    ctx.fillRect(0, 0, width, height);

    if (!definition) continue;
    const random = seededRandom(definition.previewSeed);
    for (let index = 0; index < 9; index += 1) {
      const progress = index / 8;
      const input: BrushInputSample = {
        x: progress * width, y: height / 2, time: index * 8,
        pressure: 0.14 + Math.sin(progress * Math.PI) * 0.86,
        tiltX: 20, tiltY: 8, rotation: 0, tangentialPressure: 0,
        pointer: 'pen', eraser: false, velocity: 220,
        direction: 0, distance: progress * 100,
      };
      const dab = resolveBrushDab(input, preset.settings, definition, random());
      const displaySize = Math.max(3, Math.min(16, 11 * dab.size / definition.base.size));
      drawMaskStamp(
        ctx, 4 + progress * (width - 8), height / 2, displaySize,
        dab.hardness, dab.opacity, dab.flow, colors.brush,
        dab.aspect, dab.rotation, dab.tipAssetId,
      );
    }
  }
}

// The ribbon tracks every settings change, external or local
watch(editSettings, () => {
  drawRibbon();
}, { deep: true });

// Redraw when theme changes
watch(isDarkTheme, () => {
  drawRibbon();
  drawPresetPreviews();
});

onMounted(() => {
  nextTick(() => {
    drawRibbon();
    drawPresetPreviews();
  });
});

// Expose isEraser for parent component
defineExpose({ isEraser });
</script>

<template>
  <div class="flex flex-col gap-2 select-none">
    <!-- Live stroke ribbon: preview + header in one -->
    <div class="relative h-[46px] rounded-media overflow-hidden bg-matte">
      <canvas ref="ribbonCanvasRef" class="absolute inset-0 w-full h-full" />
      <span class="absolute left-2 bottom-1.5 text-[11px] leading-none text-content-secondary">
        {{ ribbonLabel }}
      </span>
      <span class="absolute right-2 bottom-1.5 text-[11px] leading-none text-content-tertiary tabular-nums">
        {{ editSettings.size }}px
      </span>
    </div>

    <!-- Preset grid -->
    <div class="grid grid-cols-3 gap-1">
      <button
        v-for="preset in visiblePresets"
        :key="preset.id"
        type="button"
        class="min-w-0 rounded-md p-1 text-left"
        :class="isPresetActive(preset)
          ? 'bg-selection/15 ring-1 ring-inset ring-selection'
          : 'hover:bg-overlay-hover'"
        :title="preset.name"
        @click="selectPreset(preset)"
      >
        <canvas
          :ref="(el) => setPresetCanvasRef(el as HTMLCanvasElement, preset.id)"
          class="block w-full h-[26px] rounded-media bg-matte"
          width="100"
          height="26"
        />
        <span
          class="block mt-0.5 text-[10.5px] leading-[13px] truncate"
          :class="isPresetActive(preset) ? 'text-content' : 'text-content-tertiary'"
        >{{ preset.name }}</span>
      </button>
    </div>

    <!-- Bar sliders. Stylus dynamics sit ON the sliders they drive: the pen
         glyph at the end of Size and Flow toggles pressure for that property.
         Inert with a mouse, so they are safe to show unconditionally. -->
    <div class="flex flex-col gap-1">
      <div v-for="def in SLIDERS" :key="def.key" class="flex items-center gap-1.5">
        <div
          class="relative flex-1 h-[26px] compact:h-11 rounded-md bg-overlay-hover overflow-hidden cursor-ew-resize touch-none"
          @pointerdown="onSliderPointerDown(def, $event)"
        >
          <div
            class="absolute inset-y-0 left-0 bg-accent/15 border-r-2 border-accent/85"
            :style="{ width: sliderFillWidth(def) }"
          />
          <span class="absolute left-2 top-1/2 -translate-y-1/2 text-[11.5px] text-content-secondary pointer-events-none">
            {{ def.label }}
          </span>
          <span class="absolute right-2 top-1/2 -translate-y-1/2 text-[11.5px] text-content/85 tabular-nums pointer-events-none">
            {{ editSettings[def.key] }}{{ def.unit }}
          </span>
        </div>
        <button
          v-if="def.pressureKey"
          type="button"
          class="w-[22px] h-[26px] flex items-center justify-center rounded-md"
          :class="editSettings[def.pressureKey]
            ? 'bg-accent/15 text-accent-hi'
            : 'text-content-muted hover:bg-overlay-hover hover:text-content-secondary'"
          :title="def.pressureTitle"
          @click="togglePressure(def.pressureKey)"
        >
          <ToolIcon name="pencil" :size="12" />
        </button>
        <div v-else class="w-[22px]" />
      </div>
    </div>
  </div>
</template>
