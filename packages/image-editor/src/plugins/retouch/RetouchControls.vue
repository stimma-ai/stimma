<script setup lang="ts">
import { ref, watch, computed, reactive, onMounted } from 'vue';
import type { EditorContext } from '@/types/plugins';
import type { RetouchTool, DodgeBurnRange, SpongeMode, SelectionMode } from '@/types/editor';
import type { BrushSettings } from '@/types/shapes';
import { Slider, BrushPicker, ColorPicker } from '@/components/common';
import Icon from '@/components/icons/Icon.vue';
import { extractImagePalette } from '@/utils/image';

const props = defineProps<{
  editor: EditorContext;
}>();

function colorsEqual(
  a: { r: number; g: number; b: number; a: number } | null | undefined,
  b: { r: number; g: number; b: number; a: number } | null | undefined
): boolean {
  if (!a && !b) return true;
  if (!a || !b) return false;
  return a.r === b.r && a.g === b.g && a.b === b.b && a.a === b.a;
}

function brushSettingsEqual(a: BrushSettings, b: BrushSettings): boolean {
  return a.size === b.size &&
    a.hardness === b.hardness &&
    a.opacity === b.opacity &&
    a.flow === b.flow &&
    a.spacing === b.spacing &&
    a.glow === b.glow &&
    a.jitter === b.jitter &&
    a.scatter === b.scatter;
}

// Active tool
const activeTool = ref<RetouchTool | null>(null);

// Default brush settings per tool type
const defaultBrushSettings: Record<string, BrushSettings> = {
  paint: { size: 20, hardness: 80, opacity: 100, flow: 100, spacing: 25, glow: 0, jitter: 0, scatter: 0 },
  clone: { size: 30, hardness: 70, opacity: 100, flow: 100, spacing: 25, glow: 0, jitter: 0, scatter: 0 },
  'spot-heal': { size: 25, hardness: 50, opacity: 100, flow: 100, spacing: 25, glow: 0, jitter: 0, scatter: 0 },
  dodge: { size: 40, hardness: 30, opacity: 50, flow: 50, spacing: 25, glow: 0, jitter: 0, scatter: 0 },
  burn: { size: 40, hardness: 30, opacity: 50, flow: 50, spacing: 25, glow: 0, jitter: 0, scatter: 0 },
  sponge: { size: 40, hardness: 30, opacity: 50, flow: 50, spacing: 25, glow: 0, jitter: 0, scatter: 0 },
  'blur-brush': { size: 30, hardness: 50, opacity: 100, flow: 100, spacing: 15, glow: 0, jitter: 0, scatter: 0 },
  'sharpen-brush': { size: 30, hardness: 50, opacity: 100, flow: 100, spacing: 15, glow: 0, jitter: 0, scatter: 0 },
  redact: { size: 40, hardness: 100, opacity: 100, flow: 100, spacing: 15, glow: 0, jitter: 0, scatter: 0 },
};

// Per-tool brush settings storage
const toolBrushSettings = reactive<Record<string, BrushSettings>>({});

// Current brush settings (computed based on active tool)
// Note: Don't mutate inside getter - initialization happens in selectTool
const brushSettings = computed({
  get: () => {
    const tool = activeTool.value;
    if (!tool) return defaultBrushSettings.paint;
    // Return stored settings or defaults (selectTool handles initialization)
    return toolBrushSettings[tool] || defaultBrushSettings[tool] || defaultBrushSettings.paint;
  },
  set: (value: BrushSettings) => {
    const tool = activeTool.value;
    if (tool) {
      toolBrushSettings[tool] = { ...value };
      props.editor.updateState({ retouchBrushSettings: value });
    }
  }
});

// Clone source indicator
const hasCloneSource = computed(() => props.editor.state.retouchCloneSource !== null);

// Selection indicator (for patch tool)
const hasSelection = computed(() => props.editor.retouch?.hasSelection() ?? false);

// Dodge/Burn settings
const dodgeBurnExposure = ref(50);
const dodgeBurnRange = ref<DodgeBurnRange>('midtones');

// Sponge settings
const spongeFlow = ref(50);
const spongeMode = ref<SpongeMode>('desaturate');

// Blur/Sharpen strength
const blurSharpenStrength = ref(50);

// Patch tool settings
const patchBlendWidth = ref(15);

// Selection settings
const wandTolerance = ref(32);
const featherRadius = ref(5);
const selectionMode = ref<SelectionMode>('new');

// Magnetic lasso settings
const magneticLassoWidth = ref(40);
const magneticLassoContrast = ref(80);

// Combine mode options
const combineModes: Array<{ id: SelectionMode; label: string; icon: string; title: string }> = [
  { id: 'new', label: 'New', icon: 'selectionNew', title: 'New selection' },
  { id: 'add', label: 'Add', icon: 'selectionAdd', title: 'Add to selection (Shift)' },
  { id: 'subtract', label: 'Subtract', icon: 'selectionSubtract', title: 'Subtract from selection (Alt)' },
  { id: 'intersect', label: 'Intersect', icon: 'selectionIntersect', title: 'Intersect with selection (Shift+Alt)' },
];

// Color (persistent)
const retouchColor = ref<{ r: number; g: number; b: number; a: number }>({ r: 255, g: 255, b: 255, a: 1 });

// Image palette colors (extracted from the current image)
const imagePalette = ref<{ r: number; g: number; b: number; a: number }[]>([]);

// Extract palette from image on mount and when image changes
function updateImagePalette() {
  const imageElement = props.editor.getImageElement?.();
  if (imageElement && imageElement.complete && imageElement.naturalWidth > 0) {
    imagePalette.value = extractImagePalette(imageElement, 6);
  }
}

onMounted(() => {
  updateImagePalette();
});

// Watch for image changes
watch(() => props.editor.state.src, () => {
  setTimeout(updateImagePalette, 100);
}, { immediate: true });

const dodgeBurnRanges: Array<{ id: DodgeBurnRange; label: string }> = [
  { id: 'shadows', label: 'Shadows' },
  { id: 'midtones', label: 'Midtones' },
  { id: 'highlights', label: 'Highlights' },
];

// Computed for UI
const isDodgeBurnTool = computed(() => {
  return activeTool.value === 'dodge' || activeTool.value === 'burn';
});

const isSpongeTool = computed(() => {
  return activeTool.value === 'sponge';
});

const isBlurSharpenTool = computed(() => {
  return activeTool.value === 'blur-brush' || activeTool.value === 'sharpen-brush';
});

const isSelectionTool = computed(() => {
  const tool = activeTool.value;
  return tool === 'marquee-rect' || tool === 'marquee-ellipse' || tool === 'lasso' || tool === 'magnetic-lasso';
});

const isMagneticLassoTool = computed(() => {
  return activeTool.value === 'magnetic-lasso';
});

// Tools that have a brush
const hasBrush = computed(() => {
  const tool = activeTool.value;
  return tool === 'paint' || tool === 'clone' || tool === 'spot-heal' ||
         tool === 'dodge' || tool === 'burn' || tool === 'sponge' ||
         tool === 'blur-brush' || tool === 'sharpen-brush';
});

// Tools that depend on color (paint, fill)
const hasColor = computed(() => {
  const tool = activeTool.value;
  return tool === 'paint' || tool === 'fill';
});

// Black color for brush preview in retouch mode
// Using black on light gray background provides maximum contrast
const brushPreviewColor = { r: 0, g: 0, b: 0, a: 1 };

// Initialize from state and sync brush settings when tool changes
watch(
  () => props.editor.state.retouchTool,
  (tool) => {
    if (tool && tool !== activeTool.value) {
      activeTool.value = tool;

      // Initialize this tool's brush settings if not already set
      if (!toolBrushSettings[tool]) {
        toolBrushSettings[tool] = { ...(defaultBrushSettings[tool] || defaultBrushSettings.paint) };
      }

      // Sync this tool's settings to global state so the brush picker updates
      const nextSettings = { ...toolBrushSettings[tool] };
      if (!brushSettingsEqual(props.editor.state.retouchBrushSettings, nextSettings)) {
        props.editor.updateState({
          retouchBrushSettings: nextSettings,
        });
      }
    }
  },
  { immediate: true }
);

// Note: We don't sync FROM global state TO local per-tool settings.
// Each tool maintains its own settings in toolBrushSettings.
// The global retouchBrushSettings is only used for the current tool and is
// synced TO (not FROM) when the user changes settings or switches tools.

watch(
  () => props.editor.state.dodgeBurnExposure,
  (exposure) => {
    dodgeBurnExposure.value = exposure;
  },
  { immediate: true }
);

watch(
  () => props.editor.state.dodgeBurnRange,
  (range) => {
    dodgeBurnRange.value = range;
  },
  { immediate: true }
);

watch(
  () => props.editor.state.blurSharpenStrength,
  (strength) => {
    blurSharpenStrength.value = strength;
  },
  { immediate: true }
);

watch(
  () => props.editor.state.patchBlendWidth,
  (width) => {
    patchBlendWidth.value = width;
  },
  { immediate: true }
);

watch(
  () => props.editor.state.spongeFlow,
  (flow) => {
    spongeFlow.value = flow;
  },
  { immediate: true }
);

watch(
  () => props.editor.state.spongeMode,
  (mode) => {
    spongeMode.value = mode;
  },
  { immediate: true }
);

watch(
  () => props.editor.state.wandTolerance,
  (tolerance) => {
    wandTolerance.value = tolerance;
  },
  { immediate: true }
);

watch(
  () => props.editor.state.selectionFeather,
  (radius) => {
    featherRadius.value = radius;
  },
  { immediate: true }
);

watch(
  () => props.editor.state.selectionMode,
  (mode) => {
    selectionMode.value = mode;
  },
  { immediate: true }
);

watch(
  () => props.editor.state.magneticLassoWidth,
  (width) => {
    magneticLassoWidth.value = width;
  },
  { immediate: true }
);

watch(
  () => props.editor.state.magneticLassoContrast,
  (contrast) => {
    magneticLassoContrast.value = contrast;
  },
  { immediate: true }
);

watch(
  () => props.editor.state.retouchForegroundColor,
  (color) => {
    if (color && typeof color === 'object' && !colorsEqual(retouchColor.value, color)) {
      retouchColor.value = { ...color };
    }
  },
  { immediate: true }
);

// Sync color changes to state
watch(
  retouchColor,
  (color) => {
    if (!colorsEqual(props.editor.state.retouchForegroundColor, color)) {
      props.editor.updateState({ retouchForegroundColor: color });
    }
  },
  { deep: true }
);

// Brush settings update - sync per-tool settings changes to editor state
function updateBrushSettings(settings: BrushSettings) {
  const tool = activeTool.value;
  if (tool) {
    toolBrushSettings[tool] = { ...settings };
    if (!brushSettingsEqual(props.editor.state.retouchBrushSettings, settings)) {
      props.editor.updateState({ retouchBrushSettings: settings });
    }
  }
}

// Dodge/Burn settings update
function updateDodgeBurnExposure(value: number) {
  dodgeBurnExposure.value = value;
  props.editor.updateState({ dodgeBurnExposure: value });
}

function updateDodgeBurnRange(range: DodgeBurnRange) {
  dodgeBurnRange.value = range;
  props.editor.updateState({ dodgeBurnRange: range });
}

// Blur/Sharpen strength update
function updateBlurSharpenStrength(value: number) {
  blurSharpenStrength.value = value;
  props.editor.updateState({ blurSharpenStrength: value });
}

// Patch blend width update
function updatePatchBlendWidth(value: number) {
  patchBlendWidth.value = value;
  props.editor.updateState({ patchBlendWidth: value });
}

// Sponge settings update
function updateSpongeFlow(value: number) {
  spongeFlow.value = value;
  props.editor.updateState({ spongeFlow: value });
}

function updateSpongeMode(mode: SpongeMode) {
  spongeMode.value = mode;
  props.editor.updateState({ spongeMode: mode });
}

// Wand tolerance update (will be used when wand UI is added)
function _updateWandTolerance(value: number) {
  wandTolerance.value = value;
  props.editor.updateState({ wandTolerance: value });
}
void _updateWandTolerance; // Suppress unused warning

// Feather radius update
function updateFeatherRadius(value: number) {
  featherRadius.value = value;
  props.editor.updateState({ selectionFeather: value });
}

// Selection mode update
function updateSelectionMode(mode: SelectionMode) {
  selectionMode.value = mode;
  props.editor.updateState({ selectionMode: mode });
}

// Magnetic lasso settings update
function updateMagneticLassoWidth(value: number) {
  magneticLassoWidth.value = value;
  props.editor.updateState({ magneticLassoWidth: value });
}

function updateMagneticLassoContrast(value: number) {
  magneticLassoContrast.value = value;
  props.editor.updateState({ magneticLassoContrast: value });
}

// Color update handler
function handleColorChange(color: { r: number; g: number; b: number; a?: number } | null) {
  if (color) {
    retouchColor.value = { ...color, a: color.a ?? 1 };
  }
}
</script>

<template>
  <div class="stimma-retouch-controls">
    <!-- Selection Options (only show when selection tool is active) -->
    <div v-if="isSelectionTool" class="stimma-panel__section">
      <!-- Combine Mode -->
      <div class="stimma-panel__section-title">Combine Mode</div>
      <div class="stimma-retouch-controls__combine-modes">
        <button
          v-for="mode in combineModes"
          :key="mode.id"
          class="stimma-retouch-controls__combine-btn"
          :class="{ 'stimma-retouch-controls__combine-btn--active': selectionMode === mode.id }"
          :title="mode.title"
          @click="updateSelectionMode(mode.id)"
        >
          <Icon :name="mode.icon as any" :size="18" />
        </button>
      </div>

      <!-- Feather (only for selection tools) -->
      <div class="stimma-retouch-controls__feather">
        <div class="stimma-panel__section-title">Feather <span class="stimma-retouch-controls__feather-hint">{{ featherRadius }}px</span></div>
        <Slider
          v-model="featherRadius"
          :min="0"
          :max="50"
          :step="1"
          @update:model-value="updateFeatherRadius"
        />
      </div>
    </div>

    <!-- Magnetic Lasso Settings -->
    <div v-if="isMagneticLassoTool" class="stimma-panel__section">
      <div class="stimma-panel__section-title">Magnetic Lasso</div>
      <div class="stimma-retouch-controls__help">
        <p>Click to place anchor points. The path snaps to image edges automatically.</p>
        <p style="margin-top: 4px;"><strong>Enter</strong> to close selection, <strong>Backspace</strong> to undo last anchor, <strong>Escape</strong> to cancel.</p>
      </div>

      <div class="stimma-retouch-controls__setting" style="margin-top: 12px;">
        <div class="stimma-panel__section-title">Width <span class="stimma-retouch-controls__feather-hint">{{ magneticLassoWidth }}px</span></div>
        <Slider
          v-model="magneticLassoWidth"
          :min="1"
          :max="40"
          :step="1"
          @update:model-value="updateMagneticLassoWidth"
        />
      </div>

      <div class="stimma-retouch-controls__setting" style="margin-top: 12px;">
        <div class="stimma-panel__section-title">Edge Contrast <span class="stimma-retouch-controls__feather-hint">{{ magneticLassoContrast }}%</span></div>
        <Slider
          v-model="magneticLassoContrast"
          :min="1"
          :max="100"
          :step="1"
          @update:model-value="updateMagneticLassoContrast"
        />
      </div>
    </div>

    <!-- Clone Stamp Help -->
    <div v-if="activeTool === 'clone'" class="stimma-panel__section">
      <div class="stimma-panel__section-title">Clone Stamp</div>
      <div class="stimma-retouch-controls__help">
        <p v-if="!hasCloneSource">
          <strong>Alt+Click</strong> to set source point
        </p>
        <p v-else>
          Source set. Click and drag to clone.
        </p>
      </div>
    </div>

    <!-- Patch Tool Help -->
    <div v-if="activeTool === 'patch'" class="stimma-panel__section">
      <div class="stimma-panel__section-title">Patch Tool</div>
      <div class="stimma-retouch-controls__help">
        <p v-if="!hasSelection">
          Draw around the area to repair, then drag to a clean source area.
        </p>
        <p v-else>
          Drag the selection to sample from another area. The source content will fill the destination with seamless blending.
        </p>
      </div>

      <div class="stimma-retouch-controls__setting" style="margin-top: 12px;">
        <div class="stimma-panel__section-title">Edge Blend <span class="stimma-retouch-controls__feather-hint">{{ patchBlendWidth }}px</span></div>
        <Slider
          v-model="patchBlendWidth"
          :min="0"
          :max="50"
          :step="1"
          @update:model-value="updatePatchBlendWidth"
        />
      </div>
    </div>

    <!-- Color (only for tools that use color) -->
    <div v-if="hasColor" class="stimma-panel__section">
      <div class="stimma-panel__section-title">Color</div>
      <ColorPicker
        :model-value="retouchColor"
        :allow-null="false"
        :image-palette="imagePalette"
        @update:model-value="handleColorChange"
      />
    </div>

    <!-- Dodge/Burn Settings -->
    <div v-if="isDodgeBurnTool" class="stimma-panel__section">
      <div class="stimma-panel__section-title">Strength</div>
      <Slider
        v-model="dodgeBurnExposure"
        :min="0"
        :max="100"
        :step="1"
        @update:model-value="updateDodgeBurnExposure"
      />

      <div class="stimma-panel__section-title" style="margin-top: 12px;">Tonal Range</div>
      <div class="stimma-segmented">
        <button
          v-for="range in dodgeBurnRanges"
          :key="range.id"
          class="stimma-segmented__btn"
          :class="{ 'stimma-segmented__btn--active': dodgeBurnRange === range.id }"
          @click="updateDodgeBurnRange(range.id)"
        >
          {{ range.label }}
        </button>
      </div>
    </div>

    <!-- Sponge Settings -->
    <div v-if="isSpongeTool" class="stimma-panel__section">
      <div class="stimma-panel__section-title">Mode</div>
      <div class="stimma-segmented">
        <button
          class="stimma-segmented__btn"
          :class="{ 'stimma-segmented__btn--active': spongeMode === 'desaturate' }"
          @click="updateSpongeMode('desaturate')"
        >
          Desaturate
        </button>
        <button
          class="stimma-segmented__btn"
          :class="{ 'stimma-segmented__btn--active': spongeMode === 'saturate' }"
          @click="updateSpongeMode('saturate')"
        >
          Saturate
        </button>
      </div>

      <div class="stimma-panel__section-title" style="margin-top: 12px;">Flow</div>
      <Slider
        v-model="spongeFlow"
        :min="0"
        :max="100"
        :step="1"
        @update:model-value="updateSpongeFlow"
      />
    </div>

    <!-- Blur/Sharpen Settings -->
    <div v-if="isBlurSharpenTool" class="stimma-panel__section">
      <div class="stimma-panel__section-title">Strength</div>
      <Slider
        v-model="blurSharpenStrength"
        :min="0"
        :max="100"
        :step="1"
        @update:model-value="updateBlurSharpenStrength"
      />
    </div>

    <!-- Brush Settings (for tools with brush) - always last -->
    <div v-if="hasBrush" class="stimma-panel__section">
      <div class="stimma-panel__section-title">Brush</div>
      <BrushPicker
        :model-value="brushSettings"
        :stroke-color="brushPreviewColor"
        @update:model-value="updateBrushSettings"
      />
    </div>

  </div>
</template>

<style scoped>
/* Tool grid with labels */
.stimma-retouch-controls__tool-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
}

.stimma-retouch-controls__tool-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 8px 4px;
  border-radius: var(--stimma-border-radius);
  background-color: rgba(var(--stimma-color-foreground), 0.05);
  border: 2px solid transparent;
  cursor: pointer;
  transition: all var(--stimma-transition-duration);
}

.stimma-retouch-controls__tool-btn:hover {
  background-color: rgba(var(--stimma-color-foreground), 0.1);
}

.stimma-retouch-controls__tool-btn--active {
  background-color: rgba(var(--stimma-color-primary), 0.15);
  border-color: rgb(var(--stimma-color-primary));
  color: rgb(var(--stimma-color-primary));
}

.stimma-retouch-controls__tool-label {
  font-size: 10px;
  font-weight: 500;
  text-align: center;
  line-height: 1.1;
  opacity: 0.8;
}

.stimma-retouch-controls__tool-btn--active .stimma-retouch-controls__tool-label {
  opacity: 1;
}

/* Legacy tool styles (keeping for compatibility) */
.stimma-retouch-controls__tools {
  display: flex;
  flex-wrap: wrap;
  gap: var(--stimma-spacing-xs);
}

.stimma-retouch-controls__tool {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: var(--stimma-border-radius);
  background-color: rgba(var(--stimma-color-foreground), 0.05);
  border: 2px solid transparent;
  cursor: pointer;
  transition: all var(--stimma-transition-duration);
}

.stimma-retouch-controls__tool:hover {
  background-color: rgba(var(--stimma-color-foreground), 0.1);
}

.stimma-retouch-controls__tool--active {
  background-color: rgba(var(--stimma-color-primary), 0.15);
  border-color: rgb(var(--stimma-color-primary));
  color: rgb(var(--stimma-color-primary));
}

.stimma-retouch-controls__help {
  font-size: 12px;
  color: rgba(var(--stimma-color-foreground), 0.7);
  line-height: 1.4;
}

.stimma-retouch-controls__help p {
  margin: 0;
}

/* Segmented control */
.stimma-segmented {
  display: flex;
  background-color: rgba(var(--stimma-color-foreground), 0.08);
  border-radius: var(--stimma-border-radius);
  padding: 2px;
}

.stimma-segmented__btn {
  flex: 1;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 500;
  border: none;
  background: transparent;
  color: rgba(var(--stimma-color-foreground), 0.6);
  cursor: pointer;
  border-radius: calc(var(--stimma-border-radius) - 2px);
  transition: all var(--stimma-transition-duration);
}

.stimma-segmented__btn:hover {
  color: rgba(var(--stimma-color-foreground), 0.9);
}

.stimma-segmented__btn--active {
  background-color: rgba(var(--stimma-color-foreground), 0.12);
  color: rgb(var(--stimma-color-foreground));
}

.stimma-retouch-controls__feather {
  margin-top: 12px;
}

.stimma-retouch-controls__feather-hint {
  font-weight: 400;
  opacity: 0.6;
  font-size: 11px;
  margin-left: 4px;
}

/* Combine mode buttons (Photoshop-style) */
.stimma-retouch-controls__combine-modes {
  display: flex;
  gap: 2px;
  margin-bottom: 12px;
}

.stimma-retouch-controls__combine-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: var(--stimma-border-radius);
  background-color: rgba(var(--stimma-color-foreground), 0.08);
  border: 2px solid transparent;
  cursor: pointer;
  transition: all var(--stimma-transition-duration);
  color: rgba(var(--stimma-color-foreground), 0.7);
}

.stimma-retouch-controls__combine-btn:hover {
  background-color: rgba(var(--stimma-color-foreground), 0.15);
  color: rgba(var(--stimma-color-foreground), 0.9);
}

.stimma-retouch-controls__combine-btn--active {
  background-color: rgba(var(--stimma-color-primary), 0.15);
  border-color: rgb(var(--stimma-color-primary));
  color: rgb(var(--stimma-color-primary));
}
</style>
