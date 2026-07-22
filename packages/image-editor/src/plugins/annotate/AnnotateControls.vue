<script setup lang="ts">
import { ref, watch, computed, onMounted } from 'vue';
import type { EditorContext } from '@/types/plugins';
import type { AnnotateTool, Shape, PathShape, TextShape, RedactShape, PolygonShape, BrushSettings, TextEffect, GradientDirection, ShadowDirection, ShapeEffect, ShapeStyle } from '@/types/shapes';
import { GRADIENT_PRESETS } from '@/types/shapes';
import type { Color as BaseColor } from '@/types/geometry';
import type { Color } from '@/types/geometry';
import type { IconName } from '@/components/icons';
import Icon from '@/components/icons/Icon.vue';
import { Slider, ColorPicker } from '@/components/common';
import { extractImagePalette } from '@/utils/image';

const props = defineProps<{
  editor: EditorContext;
}>();

// Color object type
interface RGBAColor {
  r: number;
  g: number;
  b: number;
  a?: number;
}

// Image palette colors (extracted from the current image)
const imagePalette = ref<RGBAColor[]>([]);

// Extract palette from image on mount and when image changes
function updateImagePalette() {
  const imageElement = props.editor.getImageElement?.();
  if (imageElement && imageElement.complete && imageElement.naturalWidth > 0) {
    imagePalette.value = extractImagePalette(imageElement, 6);
  }
}

onMounted(() => {
  updateImagePalette();
  loadPerToolSettings();
});

// Watch for image changes (when editor state changes src)
watch(() => props.editor.state.src, () => {
  // Small delay to ensure image is loaded
  setTimeout(updateImagePalette, 100);
}, { immediate: true });

// Pen presets
interface PenPreset {
  id: string;
  name: string;
  icon: IconName;
  settings: BrushSettings;
  defaultColor: RGBAColor;
  defaultSize: number;
}

const penPresets: PenPreset[] = [
  {
    id: 'pen',
    name: 'Pen',
    icon: 'pencil',
    settings: { size: 4, hardness: 100, opacity: 100, flow: 100, spacing: 15, glow: 0 },
    defaultColor: { r: 0, g: 0, b: 0, a: 1 }, // Black
    defaultSize: 4,
  },
  {
    id: 'marker',
    name: 'Marker',
    icon: 'hardRound',
    settings: { size: 12, hardness: 100, opacity: 100, flow: 100, spacing: 15, glow: 0 },
    defaultColor: { r: 255, g: 59, b: 48, a: 1 }, // Red
    defaultSize: 12,
  },
  {
    id: 'highlighter',
    name: 'Highlighter',
    icon: 'softRound',
    settings: { size: 40, hardness: 100, opacity: 50, flow: 100, spacing: 10, glow: 0 },
    defaultColor: { r: 255, g: 230, b: 0, a: 1 }, // Yellow
    defaultSize: 40,
  },
  {
    id: 'neon',
    name: 'Neon',
    icon: 'neon',
    settings: { size: 10, hardness: 100, opacity: 100, flow: 100, spacing: 15, glow: 80 },
    defaultColor: { r: 0, g: 255, b: 128, a: 1 }, // Bright green
    defaultSize: 10,
  },
];

// Per-pen saved settings (color, size, and glow)
interface PenSavedSettings {
  color: RGBAColor;
  size: number;
  glow: number;
}

// Reactive glow intensity for current brush
const brushGlowIntensity = ref(0);

const penSavedSettings = ref<Record<string, PenSavedSettings>>({
  pen: { color: { r: 0, g: 0, b: 0, a: 1 }, size: 4, glow: 0 },
  marker: { color: { r: 255, g: 59, b: 48, a: 1 }, size: 12, glow: 0 },
  highlighter: { color: { r: 255, g: 230, b: 0, a: 1 }, size: 40, glow: 0 },
  neon: { color: { r: 0, g: 255, b: 128, a: 1 }, size: 10, glow: 80 },
});

// ============================================
// PER-TOOL SETTINGS PERSISTENCE (localStorage)
// ============================================
const TOOL_SETTINGS_KEY_SUFFIX = 'stimma-tool-settings';
const TOOL_SETTINGS_SAVE_DEBOUNCE_MS = 500;
let toolSettingsSaveTimeout: ReturnType<typeof setTimeout> | null = null;

function getToolSettingsKey(): string {
  return `${props.editor.storagePrefix}${TOOL_SETTINGS_KEY_SUFFIX}`;
}

function savePerToolSettings() {
  if (toolSettingsSaveTimeout) {
    clearTimeout(toolSettingsSaveTimeout);
  }
  toolSettingsSaveTimeout = setTimeout(() => {
    toolSettingsSaveTimeout = null;
    try {
      const data = {
        shapes: { ...shapeSavedSettings.value },
        pens: { ...penSavedSettings.value },
      };
      localStorage.setItem(getToolSettingsKey(), JSON.stringify(data));
    } catch (err) {
      // localStorage might be disabled or quota exceeded
    }
  }, TOOL_SETTINGS_SAVE_DEBOUNCE_MS);
}

function loadPerToolSettings() {
  try {
    const stored = localStorage.getItem(getToolSettingsKey());
    if (!stored) return;

    const data = JSON.parse(stored);

    // Restore shape settings
    if (data.shapes) {
      for (const tool of SHAPE_TOOLS) {
        if (data.shapes[tool]) {
          shapeSavedSettings.value[tool] = {
            ...defaultShapeSettings,
            ...data.shapes[tool],
            strokeColor: { ...(data.shapes[tool].strokeColor ?? defaultShapeSettings.strokeColor) },
            gradientColors: (data.shapes[tool].gradientColors ?? defaultShapeSettings.gradientColors).map((c: RGBAColor) => ({ ...c })),
            fillColor: data.shapes[tool].fillColor ? { ...data.shapes[tool].fillColor } : null,
          };
        }
      }
    }

    // Restore pen settings
    if (data.pens) {
      for (const pen of penPresets) {
        if (data.pens[pen.id]) {
          penSavedSettings.value[pen.id] = {
            color: { ...(data.pens[pen.id].color ?? pen.defaultColor) },
            size: data.pens[pen.id].size ?? pen.defaultSize,
            glow: data.pens[pen.id].glow ?? pen.settings.glow ?? 0,
          };
        }
      }
    }

    // Restore the active tool's settings into the display/tool refs
    const currentTool = props.editor.state.activeTool;
    if (currentTool && isShapeTool(currentTool)) {
      restoreShapeSettings(currentTool);
    } else if (currentTool === 'sharpie') {
      const currentPenId = props.editor.state.annotatePenId ?? 'marker';
      const saved = penSavedSettings.value[currentPenId];
      if (saved) {
        toolStrokeColor.value = { ...saved.color };
        toolStrokeWidth.value = saved.size;
        displayStrokeColor.value = { ...saved.color };
        displayStrokeWidth.value = saved.size;
        brushGlowIntensity.value = saved.glow;

        const preset = penPresets.find(p => p.id === currentPenId);
        if (preset) {
          props.editor.updateState({
            annotateStrokeColor: saved.color,
            annotateStrokeWidth: saved.size,
            annotateBrushSettings: { ...preset.settings, size: saved.size, glow: saved.glow },
          });
        }
      }
    }
  } catch (err) {
    // localStorage might be disabled or corrupted
  }
}

// Shape type labels for display (reserved for future use)
const _shapeTypeLabels: Record<string, string> = {
  'path': 'Drawing',
  'line': 'Line',
  'curved-arrow': 'Arrow',
  'rectangle': 'Rectangle',
  'ellipse': 'Ellipse',
  'star': 'Star',
  'polygon': 'Polygon',
  'sticker': 'Sticker',
  'text': 'Text',
  'redact': 'Redact',
};
void _shapeTypeLabels;

// Font family options - includes system fonts and Google Fonts
interface FontOption {
  name: string;
  family: string;
  category: 'system' | 'sans-serif' | 'serif' | 'display' | 'handwriting' | 'monospace';
  googleFont?: boolean;
}

const fontOptions: FontOption[] = [
  // System fonts (always available)
  { name: 'Arial', family: 'Arial', category: 'system' },
  { name: 'Helvetica', family: 'Helvetica', category: 'system' },
  { name: 'Georgia', family: 'Georgia', category: 'system' },
  { name: 'Times New Roman', family: 'Times New Roman', category: 'system' },
  { name: 'Courier New', family: 'Courier New', category: 'system' },
  { name: 'Verdana', family: 'Verdana', category: 'system' },
  // Google Fonts - Sans Serif
  { name: 'Inter', family: 'Inter', category: 'sans-serif', googleFont: true },
  { name: 'Roboto', family: 'Roboto', category: 'sans-serif', googleFont: true },
  { name: 'Open Sans', family: 'Open Sans', category: 'sans-serif', googleFont: true },
  { name: 'Lato', family: 'Lato', category: 'sans-serif', googleFont: true },
  { name: 'Poppins', family: 'Poppins', category: 'sans-serif', googleFont: true },
  { name: 'Montserrat', family: 'Montserrat', category: 'sans-serif', googleFont: true },
  // Google Fonts - Serif
  { name: 'Playfair Display', family: 'Playfair Display', category: 'serif', googleFont: true },
  { name: 'Merriweather', family: 'Merriweather', category: 'serif', googleFont: true },
  { name: 'Lora', family: 'Lora', category: 'serif', googleFont: true },
  { name: 'PT Serif', family: 'PT Serif', category: 'serif', googleFont: true },
  // Google Fonts - Display
  { name: 'Bebas Neue', family: 'Bebas Neue', category: 'display', googleFont: true },
  { name: 'Oswald', family: 'Oswald', category: 'display', googleFont: true },
  { name: 'Alfa Slab One', family: 'Alfa Slab One', category: 'display', googleFont: true },
  { name: 'Righteous', family: 'Righteous', category: 'display', googleFont: true },
  // Google Fonts - Handwriting
  { name: 'Pacifico', family: 'Pacifico', category: 'handwriting', googleFont: true },
  { name: 'Dancing Script', family: 'Dancing Script', category: 'handwriting', googleFont: true },
  { name: 'Caveat', family: 'Caveat', category: 'handwriting', googleFont: true },
  { name: 'Permanent Marker', family: 'Permanent Marker', category: 'handwriting', googleFont: true },
  { name: 'Indie Flower', family: 'Indie Flower', category: 'handwriting', googleFont: true },
  // Google Fonts - Monospace
  { name: 'Fira Code', family: 'Fira Code', category: 'monospace', googleFont: true },
  { name: 'JetBrains Mono', family: 'JetBrains Mono', category: 'monospace', googleFont: true },
  { name: 'Source Code Pro', family: 'Source Code Pro', category: 'monospace', googleFont: true },
];

// Track loaded Google Fonts
const loadedFonts = new Set<string>();

// Load a Google Font dynamically
function loadGoogleFont(fontFamily: string) {
  if (loadedFonts.has(fontFamily)) return;
  loadedFonts.add(fontFamily);

  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = `https://fonts.googleapis.com/css2?family=${encodeURIComponent(fontFamily)}:wght@400;700&display=swap`;
  document.head.appendChild(link);
}

// Preload all Google Fonts so there's no delay when switching
function preloadAllGoogleFonts() {
  const googleFonts = fontOptions.filter(f => f.googleFont);

  // Batch load all Google Fonts in a single request for efficiency
  if (googleFonts.length > 0) {
    const families = googleFonts.map(f => `${encodeURIComponent(f.family)}:wght@400;700`).join('&family=');
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = `https://fonts.googleapis.com/css2?family=${families}&display=swap`;
    document.head.appendChild(link);

    // Mark all as loaded
    googleFonts.forEach(f => loadedFonts.add(f.family));
  }
}

// Preload all fonts on mount
preloadAllGoogleFonts();

// ============================================
// PER-TOOL SAVED SETTINGS
// ============================================
// Shape tools that persist their own settings independently
const SHAPE_TOOLS = ['line', 'arrow', 'rectangle', 'ellipse', 'star', 'polygon'] as const;

interface ShapeSavedSettings {
  strokeColor: RGBAColor;
  fillColor: RGBAColor | null;
  strokeWidth: number;
  shapeEffect: ShapeEffect;
  glowIntensity: number;
  gradientColors: RGBAColor[];
  gradientDirection: GradientDirection;
  polygonSides?: number;
}

const defaultShapeSettings: ShapeSavedSettings = {
  strokeColor: { r: 255, g: 255, b: 255, a: 1 },
  fillColor: null,
  strokeWidth: 12,
  shapeEffect: 'none',
  glowIntensity: 50,
  gradientColors: [
    { r: 255, g: 107, b: 107, a: 1 },
    { r: 254, g: 202, b: 87, a: 1 },
    { r: 255, g: 159, b: 243, a: 1 },
  ],
  gradientDirection: 'horizontal',
};

const shapeSavedSettings = ref<Record<string, ShapeSavedSettings>>(
  Object.fromEntries(SHAPE_TOOLS.map(tool => [tool, {
    ...defaultShapeSettings,
    strokeColor: { ...defaultShapeSettings.strokeColor },
    gradientColors: defaultShapeSettings.gradientColors.map(c => ({ ...c })),
    ...(tool === 'polygon' ? { polygonSides: 6 } : {}),
  }]))
);

function isShapeTool(tool: string): boolean {
  return (SHAPE_TOOLS as readonly string[]).includes(tool);
}

function saveCurrentShapeSettings(tool: string) {
  if (!isShapeTool(tool)) return;
  shapeSavedSettings.value[tool] = {
    strokeColor: { ...toolStrokeColor.value },
    fillColor: toolFillColor.value ? { ...toolFillColor.value } : null,
    strokeWidth: toolStrokeWidth.value,
    shapeEffect: toolShapeEffect.value,
    glowIntensity: toolGlowIntensity.value,
    gradientColors: toolGradientColors.value.map(c => ({ ...c })),
    gradientDirection: toolGradientDirection.value,
    ...(tool === 'polygon' ? { polygonSides: toolPolygonSides.value } : {}),
  };
  savePerToolSettings();
}

function restoreShapeSettings(tool: string) {
  if (!isShapeTool(tool)) return;
  const saved = shapeSavedSettings.value[tool];
  if (!saved) return;

  toolStrokeColor.value = { ...saved.strokeColor };
  toolFillColor.value = saved.fillColor ? { ...saved.fillColor } : null;
  toolStrokeWidth.value = saved.strokeWidth;
  toolShapeEffect.value = saved.shapeEffect;
  toolGlowIntensity.value = saved.glowIntensity;
  toolGradientColors.value = saved.gradientColors.map(c => ({ ...c }));
  toolGradientDirection.value = saved.gradientDirection;
  if (tool === 'polygon' && saved.polygonSides !== undefined) {
    toolPolygonSides.value = saved.polygonSides;
  }

  // Sync display state
  displayStrokeColor.value = { ...saved.strokeColor };
  displayFillColor.value = saved.fillColor ? { ...saved.fillColor } : null;
  displayStrokeWidth.value = saved.strokeWidth;
  displayShapeEffect.value = saved.shapeEffect;
  displayGlowIntensity.value = saved.glowIntensity;
  displayGradientColors.value = saved.gradientColors.map(c => ({ ...c }));
  displayGradientDirection.value = saved.gradientDirection;
  if (tool === 'polygon' && saved.polygonSides !== undefined) {
    displayPolygonSides.value = saved.polygonSides;
  }

  // Push to editor state so new shapes use these settings
  props.editor.updateState({
    annotateStrokeColor: saved.strokeColor,
    annotateFillColor: saved.fillColor,
    annotateStrokeWidth: saved.strokeWidth,
    annotateShapeEffect: saved.shapeEffect,
    annotateGlowIntensity: saved.glowIntensity,
    annotateGradientColors: saved.gradientColors as BaseColor[],
    annotateGradientDirection: saved.gradientDirection,
  });
}

// ============================================
// TOOL-LEVEL SETTINGS (persist across selections)
// ============================================
// Default to white stroke
const toolStrokeColor = ref<RGBAColor>({ r: 255, g: 255, b: 255, a: 1 });
const toolFillColor = ref<RGBAColor | null>(null);
const toolStrokeWidth = ref(12);
const toolPenId = ref('marker');

// Active tool
const activeTool = ref<AnnotateTool>('sharpie');

// ============================================
// DISPLAY STATE (changes with selection)
// ============================================
// Default to marker pen settings (red, 12px)
const displayStrokeColor = ref<RGBAColor | null>({ r: 255, g: 59, b: 48, a: 1 });
const displayFillColor = ref<RGBAColor | null>(null);
const displayStrokeWidth = ref(12);
const displayPenId = ref('marker');

// Redact block size
const toolRedactBlockSize = ref(16);
const displayRedactBlockSize = ref(16);

// Polygon sides
const toolPolygonSides = ref(6);
const displayPolygonSides = ref(6);

// Shape style (universal neon/gradient for all shapes)
const toolShapeEffect = ref<ShapeEffect>('none');
const displayShapeEffect = ref<ShapeEffect>('none');
const toolGlowIntensity = ref(50);
const displayGlowIntensity = ref(50);
const toolGradientColors = ref<RGBAColor[]>([
  { r: 255, g: 107, b: 107, a: 1 },
  { r: 254, g: 202, b: 87, a: 1 },
  { r: 255, g: 159, b: 243, a: 1 },
]);
const displayGradientColors = ref<RGBAColor[]>([
  { r: 255, g: 107, b: 107, a: 1 },
  { r: 254, g: 202, b: 87, a: 1 },
  { r: 255, g: 159, b: 243, a: 1 },
]);
const toolGradientDirection = ref<GradientDirection>('horizontal');
const displayGradientDirection = ref<GradientDirection>('horizontal');

// Tools
const tools: { id: AnnotateTool; icon: IconName; label: string }[] = [
  { id: 'sharpie', icon: 'pencil', label: 'Draw' },
  { id: 'line', icon: 'minus', label: 'Line' },
  { id: 'arrow', icon: 'arrowUpRight', label: 'Arrow' },
  { id: 'rectangle', icon: 'square', label: 'Rectangle' },
  { id: 'ellipse', icon: 'circle', label: 'Ellipse' },
  { id: 'text', icon: 'type', label: 'Text' },
  { id: 'redact', icon: 'redact', label: 'Redact' },
];


// Helper to convert Color to RGBAColor
function toRGBA(color: Color): RGBAColor {
  if (typeof color === 'string') {
    return { r: 255, g: 0, b: 0, a: 1 };
  }
  return color;
}

// ============================================
// SELECTED SHAPE
// ============================================
const selectedShape = computed(() => {
  const id = props.editor.state.selectedShapeId;
  if (!id) return null;
  return props.editor.state.annotations.find((s: Shape) => s.id === id) ?? null;
});

const isPathShape = computed(() => selectedShape.value?.type === 'path');
const isTextShape = computed(() => selectedShape.value?.type === 'text');
const isRedactShape = computed(() => selectedShape.value?.type === 'redact');
const isPolygonShape = computed(() => selectedShape.value?.type === 'polygon');
const hasStroke = computed(() => {
  const shape = selectedShape.value;
  return shape && (shape.type === 'line' || shape.type === 'path' ||
    shape.type === 'rectangle' || shape.type === 'ellipse' || shape.type === 'curved-arrow' ||
    shape.type === 'star' || shape.type === 'polygon');
});
const hasFill = computed(() => {
  const shape = selectedShape.value;
  return shape && (shape.type === 'rectangle' || shape.type === 'ellipse' || shape.type === 'star' || shape.type === 'polygon');
});

const strokeCanBeNull = computed(() => {
  const shape = selectedShape.value;
  if (shape) {
    return shape.type === 'rectangle' || shape.type === 'ellipse' || shape.type === 'star' || shape.type === 'polygon';
  }
  return activeTool.value === 'rectangle' || activeTool.value === 'ellipse' || activeTool.value === 'star' || activeTool.value === 'polygon';
});

// Check if current tool/shape supports style effects (neon/gradient)
// Excludes: text (has own effects), redact (no styling), path (draw tool has brush styles)
const supportsShapeStyle = computed(() => {
  const shape = selectedShape.value;
  if (shape) {
    return shape.type !== 'text' && shape.type !== 'redact' && shape.type !== 'path';
  }
  // When no shape selected, check tool
  return activeTool.value !== 'text' && activeTool.value !== 'redact' && activeTool.value !== 'sharpie';
});

// Get icon for selected shape type (reserved for future use)
function _getShapeIcon(shape: typeof selectedShape.value): IconName {
  if (!shape) return 'pencil';
  if (shape.type === 'curved-arrow') return 'arrowUpRight';
  if (shape.type === 'path') return 'pencil';
  if (shape.type === 'text') return 'type';
  const tool = tools.find(t => t.id === shape.type);
  return tool?.icon || 'pencil';
}
void _getShapeIcon;

// ============================================
// SYNC SELECTION -> DISPLAY
// ============================================
watch(selectedShape, (shape, oldShape) => {
  if (shape) {
    // Show selected shape's properties
    if (shape.type === 'text') {
      // Text shapes use textColor instead of strokeColor
      const textShape = shape as TextShape;
      displayStrokeColor.value = textShape.textColor ? toRGBA(textShape.textColor) : null;
      displayFillColor.value = textShape.backgroundColor ? toRGBA(textShape.backgroundColor) : null;
    } else {
      if ('strokeColor' in shape) {
        displayStrokeColor.value = shape.strokeColor ? toRGBA(shape.strokeColor) : null;
      }
      if ('backgroundColor' in shape) {
        displayFillColor.value = shape.backgroundColor ? toRGBA(shape.backgroundColor) : null;
      }
    }
    if ('strokeWidth' in shape && shape.strokeWidth) {
      displayStrokeWidth.value = shape.strokeWidth as number;
    }

    // Sync pen preset for paths
    if (shape.type === 'path') {
      const pathShape = shape as PathShape;
      // Use the stored pen ID if available
      if (pathShape.penId) {
        displayPenId.value = pathShape.penId;
      } else {
        // Fallback to matching by glow/opacity for old paths without penId
        const matchingPreset = penPresets.find(p => {
          return (p.settings.glow ?? 0) === (pathShape.glow ?? 0) &&
                 p.settings.opacity === Math.round((pathShape.opacity ?? 1) * 100);
        });
        if (matchingPreset) {
          displayPenId.value = matchingPreset.id;
        }
      }
      // Sync brush glow intensity from path
      brushGlowIntensity.value = pathShape.glow ?? 0;
    }

    // Sync redact block size
    if (shape.type === 'redact') {
      displayRedactBlockSize.value = (shape as RedactShape).blockSize;
    }

    // Sync polygon sides
    if (shape.type === 'polygon') {
      displayPolygonSides.value = (shape as PolygonShape).sides;
    }

    // Sync shape style (neon/gradient)
    if (shape.style) {
      displayShapeEffect.value = shape.style.effect ?? 'none';
      displayGlowIntensity.value = shape.style.glowIntensity ?? 50;
      if (shape.style.gradientColors && shape.style.gradientColors.length >= 2) {
        displayGradientColors.value = shape.style.gradientColors.map(c => toRGBA(c));
      }
      displayGradientDirection.value = shape.style.gradientDirection ?? 'horizontal';
    } else {
      // Check legacy glow on paths
      if (shape.type === 'path' && (shape as PathShape).glow && (shape as PathShape).glow! > 0) {
        displayShapeEffect.value = 'neon';
        displayGlowIntensity.value = (shape as PathShape).glow!;
      } else {
        displayShapeEffect.value = 'none';
      }
    }

  } else if (oldShape) {
    // Deselected - restore tool settings
    displayStrokeColor.value = toolStrokeColor.value;
    displayFillColor.value = toolFillColor.value;
    displayStrokeWidth.value = toolStrokeWidth.value;
    displayPenId.value = toolPenId.value;
    displayRedactBlockSize.value = toolRedactBlockSize.value;
    displayPolygonSides.value = toolPolygonSides.value;
    displayShapeEffect.value = toolShapeEffect.value;
    displayGlowIntensity.value = toolGlowIntensity.value;
    displayGradientColors.value = [...toolGradientColors.value];
    displayGradientDirection.value = toolGradientDirection.value;
  }
}, { immediate: true });

// ============================================
// TOOL SELECTION (synced from editor state)
// ============================================
// Sync from editor state
watch(() => props.editor.state.activeTool, (tool) => {
  if (tool && tool !== activeTool.value) {
    const oldTool = activeTool.value;

    // Save outgoing tool's settings
    if (!selectedShape.value) {
      saveCurrentShapeSettings(oldTool);
    }

    activeTool.value = tool as AnnotateTool;

    // Restore incoming tool's settings (only when nothing selected)
    if (!selectedShape.value) {
      if (isShapeTool(tool)) {
        restoreShapeSettings(tool);
      } else if (tool === 'text') {
        const state = props.editor.state;
        const textColor = state.annotateTextColor ?? { r: 255, g: 255, b: 255, a: 1 };
        const textBgColor = state.annotateTextBgColor;
        displayStrokeColor.value = toRGBA(textColor);
        displayFillColor.value = textBgColor ? toRGBA(textBgColor) : null;
      }
    }
  }
}, { immediate: true });

// ============================================
// PEN SELECTION
// ============================================
function selectPen(pen: PenPreset) {
  // Always update tool-level settings
  toolPenId.value = pen.id;
  displayPenId.value = pen.id;

  // Load this pen's saved color, size, and glow
  const saved = penSavedSettings.value[pen.id];
  const penColor = saved?.color ?? pen.defaultColor;
  const penSize = saved?.size ?? pen.defaultSize;
  const penGlow = saved?.glow ?? pen.settings.glow ?? 0;

  // Update tool-level settings with this pen's saved values
  toolStrokeColor.value = { ...penColor };
  toolStrokeWidth.value = penSize;
  displayStrokeColor.value = { ...penColor };
  displayStrokeWidth.value = penSize;
  brushGlowIntensity.value = penGlow;

  props.editor.updateState({
    annotateStrokeColor: penColor,
    annotateStrokeWidth: penSize,
    annotateBrushSettings: { ...pen.settings, size: penSize, glow: penGlow },
    annotateIsEraser: false,
    annotatePenId: pen.id,
  });

  // If a path is selected, update it (including penId so the watch doesn't reset displayPenId)
  if (selectedShape.value?.type === 'path') {
    updateSelectedShape({
      strokeColor: penColor,
      strokeWidth: penSize,
      hardness: pen.settings.hardness,
      opacity: pen.settings.opacity / 100,
      flow: pen.settings.flow,
      spacing: pen.settings.spacing,
      glow: penGlow,
      penId: pen.id,
    });
  }
}

function handleBrushGlowChange(glow: number) {
  // Update reactive ref
  brushGlowIntensity.value = glow;

  // Save to current brush's settings
  if (toolPenId.value) {
    penSavedSettings.value[toolPenId.value] = {
      ...penSavedSettings.value[toolPenId.value],
      glow,
    };
    savePerToolSettings();
  }

  // Update editor state
  const currentSettings = props.editor.state.annotateBrushSettings;
  if (currentSettings) {
    props.editor.updateState({
      annotateBrushSettings: { ...currentSettings, glow },
    });
  }

  // If a path is selected, update it
  if (selectedShape.value?.type === 'path') {
    updateSelectedShape({ glow });
  }
}

// ============================================
// COLOR/STYLE CHANGES
// ============================================
function handleStrokeColorChange(color: RGBAColor | null) {
  displayStrokeColor.value = color;

  // Always persist to tool defaults for next creation
  if (color) {
    toolStrokeColor.value = color;
    props.editor.updateState({ annotateStrokeColor: color });

    // Save to current pen if in draw mode
    if (activeTool.value === 'sharpie' && toolPenId.value) {
      penSavedSettings.value[toolPenId.value] = {
        ...penSavedSettings.value[toolPenId.value],
        color: { ...color },
      };
      savePerToolSettings();
    }

    // Save to per-tool settings
    if (isShapeTool(activeTool.value)) {
      shapeSavedSettings.value[activeTool.value].strokeColor = { ...color };
      savePerToolSettings();
    }
  }

  if (selectedShape.value) {
    updateSelectedShape({ strokeColor: color ?? undefined });
  }
}

function handleFillColorChange(color: RGBAColor | null) {
  displayFillColor.value = color;

  // Always persist to tool defaults for next creation
  toolFillColor.value = color;
  props.editor.updateState({ annotateFillColor: color });

  // Save to per-tool settings
  if (isShapeTool(activeTool.value)) {
    shapeSavedSettings.value[activeTool.value].fillColor = color ? { ...color } : null;
    savePerToolSettings();
  }

  if (selectedShape.value && hasFill.value) {
    updateSelectedShape({ backgroundColor: color ?? undefined });
  }
}

function handleStrokeWidthChange(width: number) {
  displayStrokeWidth.value = width;

  // Always persist to tool defaults for next creation
  toolStrokeWidth.value = width;
  props.editor.updateState({ annotateStrokeWidth: width });

  // Save to current pen if in draw mode
  if (activeTool.value === 'sharpie' && toolPenId.value) {
    penSavedSettings.value[toolPenId.value] = {
      ...penSavedSettings.value[toolPenId.value],
      size: width,
    };
    savePerToolSettings();
    // Also update brush settings size
    const currentPen = penPresets.find(p => p.id === toolPenId.value);
    if (currentPen) {
      props.editor.updateState({
        annotateBrushSettings: { ...currentPen.settings, size: width },
      });
    }
  }

  // Save to per-tool settings
  if (isShapeTool(activeTool.value)) {
    shapeSavedSettings.value[activeTool.value].strokeWidth = width;
    savePerToolSettings();
  }

  if (selectedShape.value && hasStroke.value) {
    updateSelectedShape({ strokeWidth: width });
  }
}

// ============================================
// SHAPE STYLE SETTINGS (Universal Neon/Gradient)
// ============================================
function handleShapeEffectChange(effect: ShapeEffect) {
  displayShapeEffect.value = effect;

  // Always persist to tool defaults for next creation
  toolShapeEffect.value = effect;
  props.editor.updateState({ annotateShapeEffect: effect });

  // Effects other than 'none' clear the fill/background
  if (effect !== 'none') {
    displayFillColor.value = null;
    toolFillColor.value = null;
    props.editor.updateState({ annotateFillColor: null });
  }

  // Save to per-tool settings
  if (isShapeTool(activeTool.value)) {
    shapeSavedSettings.value[activeTool.value].shapeEffect = effect;
    if (effect !== 'none') {
      shapeSavedSettings.value[activeTool.value].fillColor = null;
    }
    savePerToolSettings();
  }

  // Update selected shape if one exists
  if (selectedShape.value && supportsShapeStyle.value) {
    const currentStyle = selectedShape.value.style ?? {};
    const updates: Record<string, unknown> = {
      style: {
        ...currentStyle,
        effect,
        glowIntensity: displayGlowIntensity.value,
        gradientColors: displayGradientColors.value as BaseColor[],
        gradientDirection: displayGradientDirection.value,
      } as ShapeStyle,
    };
    // Clear backgroundColor for non-normal effects
    if (effect !== 'none' && hasFill.value) {
      updates.backgroundColor = undefined;
    }
    updateSelectedShape(updates);
  }
}

function handleShapeGlowIntensityChange(intensity: number) {
  displayGlowIntensity.value = intensity;

  // Always persist to tool defaults for next creation
  toolGlowIntensity.value = intensity;
  props.editor.updateState({ annotateGlowIntensity: intensity });

  // Save to per-tool settings
  if (isShapeTool(activeTool.value)) {
    shapeSavedSettings.value[activeTool.value].glowIntensity = intensity;
    savePerToolSettings();
  }

  // Update selected shape if one exists
  if (selectedShape.value && supportsShapeStyle.value && displayShapeEffect.value === 'neon') {
    const currentStyle = selectedShape.value.style ?? {};
    updateSelectedShape({
      style: {
        ...currentStyle,
        effect: 'neon',
        glowIntensity: intensity,
      } as ShapeStyle,
    });
  }
}

function handleShapeGradientPresetChange(presetId: string) {
  const preset = GRADIENT_PRESETS.find(p => p.id === presetId);
  if (!preset) return;

  // Convert CSS colors to RGBAColor
  const colors: RGBAColor[] = preset.colors.map(cssColor => {
    // Parse hex colors
    const hex = cssColor.replace('#', '');
    return {
      r: parseInt(hex.substring(0, 2), 16),
      g: parseInt(hex.substring(2, 4), 16),
      b: parseInt(hex.substring(4, 6), 16),
      a: 1,
    };
  });

  displayGradientColors.value = colors;

  // Always persist to tool defaults for next creation
  toolGradientColors.value = colors;
  props.editor.updateState({ annotateGradientColors: colors as BaseColor[] });

  // Save to per-tool settings
  if (isShapeTool(activeTool.value)) {
    shapeSavedSettings.value[activeTool.value].gradientColors = colors.map(c => ({ ...c }));
    savePerToolSettings();
  }

  // Update selected shape if one exists
  if (selectedShape.value && supportsShapeStyle.value && displayShapeEffect.value === 'gradient') {
    const currentStyle = selectedShape.value.style ?? {};
    updateSelectedShape({
      style: {
        ...currentStyle,
        effect: 'gradient',
        gradientColors: colors as BaseColor[],
        gradientDirection: displayGradientDirection.value,
      } as ShapeStyle,
    });
  }
}

function handleShapeGradientDirectionChange(direction: GradientDirection) {
  displayGradientDirection.value = direction;

  // Always persist to tool defaults for next creation
  toolGradientDirection.value = direction;
  props.editor.updateState({ annotateGradientDirection: direction });

  // Save to per-tool settings
  if (isShapeTool(activeTool.value)) {
    shapeSavedSettings.value[activeTool.value].gradientDirection = direction;
    savePerToolSettings();
  }

  // Update selected shape if one exists
  if (selectedShape.value && supportsShapeStyle.value && displayShapeEffect.value === 'gradient') {
    const currentStyle = selectedShape.value.style ?? {};
    updateSelectedShape({
      style: {
        ...currentStyle,
        effect: 'gradient',
        gradientColors: displayGradientColors.value as BaseColor[],
        gradientDirection: direction,
      } as ShapeStyle,
    });
  }
}

// Check if current gradient matches a preset
function isGradientPresetActive(presetId: string): boolean {
  const preset = GRADIENT_PRESETS.find(p => p.id === presetId);
  if (!preset || displayGradientColors.value.length !== preset.colors.length) return false;

  // Compare colors
  for (let i = 0; i < preset.colors.length; i++) {
    const hex = preset.colors[i].replace('#', '');
    const presetR = parseInt(hex.substring(0, 2), 16);
    const presetG = parseInt(hex.substring(2, 4), 16);
    const presetB = parseInt(hex.substring(4, 6), 16);
    const displayColor = displayGradientColors.value[i];

    if (displayColor.r !== presetR || displayColor.g !== presetG || displayColor.b !== presetB) {
      return false;
    }
  }
  return true;
}

// Gradient color stop editing
const editingGradientStop = ref<number | null>(null);

function handleGradientStopClick(index: number) {
  editingGradientStop.value = editingGradientStop.value === index ? null : index;
}

function handleGradientStopColorChange(index: number, color: RGBAColor | null) {
  if (!color) return;

  const newColors = [...displayGradientColors.value];
  newColors[index] = color;
  displayGradientColors.value = newColors;

  // Persist to tool defaults
  toolGradientColors.value = newColors;
  props.editor.updateState({ annotateGradientColors: newColors as BaseColor[] });

  // Save to per-tool settings
  if (isShapeTool(activeTool.value)) {
    shapeSavedSettings.value[activeTool.value].gradientColors = newColors.map(c => ({ ...c }));
  }

  // Update selected shape if one exists
  if (selectedShape.value && supportsShapeStyle.value && displayShapeEffect.value === 'gradient') {
    const currentStyle = selectedShape.value.style ?? {};
    updateSelectedShape({
      style: {
        ...currentStyle,
        effect: 'gradient',
        gradientColors: newColors as BaseColor[],
        gradientDirection: displayGradientDirection.value,
      } as ShapeStyle,
    });
  }
}

function addGradientStop() {
  if (displayGradientColors.value.length >= 3) return;

  // Add a color between the last two colors (or a default)
  const lastColor = displayGradientColors.value[displayGradientColors.value.length - 1];
  const newColor = { ...lastColor, r: Math.min(255, lastColor.r + 50) };
  const newColors = [...displayGradientColors.value, newColor];

  displayGradientColors.value = newColors;
  toolGradientColors.value = newColors;
  props.editor.updateState({ annotateGradientColors: newColors as BaseColor[] });
  if (isShapeTool(activeTool.value)) {
    shapeSavedSettings.value[activeTool.value].gradientColors = newColors.map(c => ({ ...c }));
  }

  // Update selected shape if applicable
  if (selectedShape.value && supportsShapeStyle.value && displayShapeEffect.value === 'gradient') {
    const currentStyle = selectedShape.value.style ?? {};
    updateSelectedShape({
      style: {
        ...currentStyle,
        effect: 'gradient',
        gradientColors: newColors as BaseColor[],
        gradientDirection: displayGradientDirection.value,
      } as ShapeStyle,
    });
  }
}

function removeGradientStop(index: number) {
  if (displayGradientColors.value.length <= 2) return;

  const newColors = displayGradientColors.value.filter((_, i) => i !== index);
  displayGradientColors.value = newColors;
  toolGradientColors.value = newColors;
  props.editor.updateState({ annotateGradientColors: newColors as BaseColor[] });
  if (isShapeTool(activeTool.value)) {
    shapeSavedSettings.value[activeTool.value].gradientColors = newColors.map(c => ({ ...c }));
  }

  // Close editor if we removed the one being edited
  if (editingGradientStop.value === index) {
    editingGradientStop.value = null;
  } else if (editingGradientStop.value !== null && editingGradientStop.value > index) {
    editingGradientStop.value--;
  }

  // Update selected shape if applicable
  if (selectedShape.value && supportsShapeStyle.value && displayShapeEffect.value === 'gradient') {
    const currentStyle = selectedShape.value.style ?? {};
    updateSelectedShape({
      style: {
        ...currentStyle,
        effect: 'gradient',
        gradientColors: newColors as BaseColor[],
        gradientDirection: displayGradientDirection.value,
      } as ShapeStyle,
    });
  }
}

// ============================================
// TEXT SETTINGS
// ============================================
function handleFontFamilyChange(fontFamily: string) {
  // Load Google Font if needed
  const fontOption = fontOptions.find(f => f.family === fontFamily);
  if (fontOption?.googleFont) {
    loadGoogleFont(fontFamily);
  }

  // Always persist to tool defaults for next creation
  props.editor.updateState({ annotateTextFontFamily: fontFamily });

  if (selectedShape.value?.type === 'text') {
    updateSelectedShape({ fontFamily } as Partial<TextShape>);
  }
}

// Note: Font size is now controlled by resizing the text shape (vector scaling)
// The fontSize property has been replaced with baseWidth/baseHeight for proper scaling

function handleFontWeightToggle() {
  const currentWeight = selectedShape.value?.type === 'text'
    ? (selectedShape.value as TextShape).fontWeight
    : props.editor.state.annotateTextFontWeight;
  const newWeight = currentWeight === 'bold' ? 'normal' : 'bold';

  // Always persist to tool defaults for next creation
  props.editor.updateState({ annotateTextFontWeight: newWeight });

  if (selectedShape.value?.type === 'text') {
    updateSelectedShape({ fontWeight: newWeight } as Partial<TextShape>);
  }
}

function handleFontStyleToggle() {
  const currentStyle = selectedShape.value?.type === 'text'
    ? (selectedShape.value as TextShape).fontStyle
    : props.editor.state.annotateTextFontStyle;
  const newStyle = currentStyle === 'italic' ? 'normal' : 'italic';

  // Always persist to tool defaults for next creation
  props.editor.updateState({ annotateTextFontStyle: newStyle });

  if (selectedShape.value?.type === 'text') {
    updateSelectedShape({ fontStyle: newStyle } as Partial<TextShape>);
  }
}

function handleTextAlignChange(align: 'left' | 'center' | 'right') {
  // Always persist to tool defaults for next creation
  props.editor.updateState({ annotateTextAlign: align });

  if (selectedShape.value?.type === 'text') {
    updateSelectedShape({ textAlign: align } as Partial<TextShape>);
  }
}

function handleBackgroundPaddingChange(padding: number) {
  // Always persist to tool defaults for next creation
  props.editor.updateState({ annotateTextBackgroundPadding: padding });

  if (selectedShape.value?.type === 'text') {
    updateSelectedShape({ backgroundPadding: padding } as Partial<TextShape>);
  }
}

function handleBackgroundCornerRadiusChange(radius: number) {
  // Always persist to tool defaults for next creation
  props.editor.updateState({ annotateTextBackgroundCornerRadius: radius });

  if (selectedShape.value?.type === 'text') {
    updateSelectedShape({ backgroundCornerRadius: radius } as Partial<TextShape>);
  }
}

function handleTextColorChange(color: RGBAColor | null) {
  displayStrokeColor.value = color;

  // Always persist to tool defaults for next creation
  if (color) {
    toolStrokeColor.value = color;
    props.editor.updateState({ annotateTextColor: color });
  }

  if (selectedShape.value?.type === 'text') {
    if (color) {
      updateSelectedShape({ textColor: color } as Partial<TextShape>);
    }
  }
}

function handleTextBackgroundColorChange(color: RGBAColor | null) {
  displayFillColor.value = color;

  // Always persist to tool defaults for next creation
  toolFillColor.value = color;
  props.editor.updateState({ annotateTextBgColor: color });

  if (selectedShape.value?.type === 'text') {
    updateSelectedShape({ backgroundColor: color ?? undefined } as Partial<TextShape>);
  }
}

// ============================================
// REDACT SETTINGS
// ============================================
function handleRedactBlockSizeChange(blockSize: number) {
  displayRedactBlockSize.value = blockSize;

  // Always persist to tool defaults for next creation
  toolRedactBlockSize.value = blockSize;
  props.editor.updateState({ annotateRedactBlockSize: blockSize });

  // Also update selected shape if one exists
  if (selectedShape.value?.type === 'redact') {
    updateSelectedShape({ blockSize } as Partial<RedactShape>);
  }
}

const currentRedactBlockSize = computed(() =>
  selectedShape.value?.type === 'redact'
    ? (selectedShape.value as RedactShape).blockSize
    : props.editor.state.annotateRedactBlockSize ?? 16
);

// ============================================
// POLYGON SETTINGS
// ============================================
function handlePolygonSidesChange(sides: number) {
  displayPolygonSides.value = sides;

  // Always persist to tool defaults for next creation
  toolPolygonSides.value = sides;
  props.editor.updateState({ annotatePolygonSides: sides });

  // Save to per-tool settings
  if (activeTool.value === 'polygon') {
    shapeSavedSettings.value['polygon'].polygonSides = sides;
  }

  // Also update selected shape if one exists
  if (selectedShape.value?.type === 'polygon') {
    updateSelectedShape({ sides } as Partial<PolygonShape>);
  }
}

const currentPolygonSides = computed(() =>
  selectedShape.value?.type === 'polygon'
    ? (selectedShape.value as PolygonShape).sides
    : props.editor.state.annotatePolygonSides ?? 6
);

// Get current text settings (from selection or tool defaults)
const currentFontFamily = computed(() =>
  selectedShape.value?.type === 'text'
    ? (selectedShape.value as TextShape).fontFamily
    : props.editor.state.annotateTextFontFamily
);

// Note: currentFontSize removed - text size is now controlled by shape resize

const currentFontWeight = computed(() =>
  selectedShape.value?.type === 'text'
    ? (selectedShape.value as TextShape).fontWeight
    : props.editor.state.annotateTextFontWeight
);

const currentFontStyle = computed(() =>
  selectedShape.value?.type === 'text'
    ? (selectedShape.value as TextShape).fontStyle
    : props.editor.state.annotateTextFontStyle
);

const currentTextAlign = computed(() =>
  selectedShape.value?.type === 'text'
    ? (selectedShape.value as TextShape).textAlign
    : props.editor.state.annotateTextAlign
);

// Text opacity
const currentTextOpacity = computed(() =>
  selectedShape.value?.type === 'text'
    ? (selectedShape.value as TextShape).opacity ?? 1
    : 1
);

function handleTextOpacityChange(opacity: number) {
  if (selectedShape.value?.type === 'text') {
    updateSelectedShape({ opacity } as Partial<TextShape>);
  }
}

// Text background settings
const currentBackgroundPadding = computed(() =>
  selectedShape.value?.type === 'text'
    ? (selectedShape.value as TextShape).backgroundPadding ?? 0.1
    : props.editor.state.annotateTextBackgroundPadding ?? 0.1
);

const currentBackgroundCornerRadius = computed(() =>
  selectedShape.value?.type === 'text'
    ? (selectedShape.value as TextShape).backgroundCornerRadius ?? 0.1
    : props.editor.state.annotateTextBackgroundCornerRadius ?? 0.1
);

// ============================================
// TEXT EFFECT SETTINGS
// ============================================
const textEffectOptions: { id: TextEffect; label: string; icon: string }[] = [
  { id: 'none', label: 'Normal', icon: 'A' },
  { id: 'outline', label: 'Outline', icon: 'O' },
  { id: 'neon', label: 'Neon', icon: '✨' },
  { id: 'gradient', label: 'Gradient', icon: '🌈' },
  { id: 'shadow', label: '3D', icon: '🔲' },
  { id: 'glitch', label: 'Glitch', icon: '📺' },
  { id: 'knockout', label: 'Knockout', icon: '🔳' },
];

const currentTextEffect = computed((): TextEffect =>
  selectedShape.value?.type === 'text'
    ? (selectedShape.value as TextShape).textEffect ?? 'none'
    : (props.editor.state.annotateTextEffect as TextEffect) ?? 'none'
);

const currentGlowIntensity = computed(() =>
  selectedShape.value?.type === 'text'
    ? (selectedShape.value as TextShape).glowIntensity ?? 50
    : props.editor.state.annotateTextGlowIntensity ?? 50
);

const currentGradientColors = computed(() =>
  selectedShape.value?.type === 'text'
    ? (selectedShape.value as TextShape).gradientColors ?? ['#ff6b6b', '#feca57', '#ff9ff3']
    : props.editor.state.annotateTextGradientColors ?? ['#ff6b6b', '#feca57', '#ff9ff3']
);

const currentGradientDirection = computed((): GradientDirection =>
  selectedShape.value?.type === 'text'
    ? (selectedShape.value as TextShape).gradientDirection ?? 'horizontal'
    : (props.editor.state.annotateTextGradientDirection as GradientDirection) ?? 'horizontal'
);

function handleTextEffectChange(effect: TextEffect) {
  // Always persist to tool defaults for next creation
  props.editor.updateState({ annotateTextEffect: effect });

  // Effects other than 'none' default to transparent background
  if (effect !== 'none') {
    displayFillColor.value = null;
    toolFillColor.value = null;
    props.editor.updateState({ annotateFillColor: null, annotateTextBgColor: null });

    if (selectedShape.value?.type === 'text') {
      updateSelectedShape({ textEffect: effect, backgroundColor: undefined } as Partial<TextShape>);
      return;
    }
  }

  if (selectedShape.value?.type === 'text') {
    updateSelectedShape({ textEffect: effect } as Partial<TextShape>);
  }
}

function handleGlowIntensityChange(intensity: number) {
  // Always persist to tool defaults for next creation
  props.editor.updateState({ annotateTextGlowIntensity: intensity });

  if (selectedShape.value?.type === 'text') {
    updateSelectedShape({ glowIntensity: intensity } as Partial<TextShape>);
  }
}

function handleGradientPresetChange(presetId: string) {
  const preset = GRADIENT_PRESETS.find(p => p.id === presetId);
  if (!preset) return;

  // Always persist to tool defaults for next creation
  props.editor.updateState({ annotateTextGradientColors: [...preset.colors] });

  if (selectedShape.value?.type === 'text') {
    updateSelectedShape({ gradientColors: [...preset.colors] } as Partial<TextShape>);
  }
}

function handleGradientDirectionChange(direction: GradientDirection) {
  // Always persist to tool defaults for next creation
  props.editor.updateState({ annotateTextGradientDirection: direction });

  if (selectedShape.value?.type === 'text') {
    updateSelectedShape({ gradientDirection: direction } as Partial<TextShape>);
  }
}

// Text gradient stop editing
const editingTextGradientStop = ref<number | null>(null);

function hexToRgba(hex: string): RGBAColor {
  const h = hex.replace('#', '');
  return {
    r: parseInt(h.substring(0, 2), 16) || 0,
    g: parseInt(h.substring(2, 4), 16) || 0,
    b: parseInt(h.substring(4, 6), 16) || 0,
    a: 1,
  };
}

function rgbaToHex(c: RGBAColor): string {
  return `#${c.r.toString(16).padStart(2, '0')}${c.g.toString(16).padStart(2, '0')}${c.b.toString(16).padStart(2, '0')}`;
}

function handleTextGradientStopClick(index: number) {
  editingTextGradientStop.value = editingTextGradientStop.value === index ? null : index;
}

function handleTextGradientStopColorChange(index: number, color: RGBAColor | null) {
  if (!color) return;
  const newColors = [...currentGradientColors.value];
  newColors[index] = rgbaToHex(color);

  props.editor.updateState({ annotateTextGradientColors: newColors });

  if (selectedShape.value?.type === 'text') {
    updateSelectedShape({ gradientColors: newColors } as Partial<TextShape>);
  }
}

function addTextGradientStop() {
  if (currentGradientColors.value.length >= 3) return;
  const last = currentGradientColors.value[currentGradientColors.value.length - 1];
  const lastRgba = hexToRgba(last);
  const newColor = rgbaToHex({ ...lastRgba, r: Math.min(255, lastRgba.r + 50) });
  const newColors = [...currentGradientColors.value, newColor];

  props.editor.updateState({ annotateTextGradientColors: newColors });

  if (selectedShape.value?.type === 'text') {
    updateSelectedShape({ gradientColors: newColors } as Partial<TextShape>);
  }
}

function removeTextGradientStop(index: number) {
  if (currentGradientColors.value.length <= 2) return;
  const newColors = currentGradientColors.value.filter((_, i) => i !== index);

  props.editor.updateState({ annotateTextGradientColors: newColors });

  if (selectedShape.value?.type === 'text') {
    updateSelectedShape({ gradientColors: newColors } as Partial<TextShape>);
  }

  if (editingTextGradientStop.value === index) {
    editingTextGradientStop.value = null;
  } else if (editingTextGradientStop.value !== null && editingTextGradientStop.value > index) {
    editingTextGradientStop.value--;
  }
}

// Shadow effect settings
const currentShadowDirection = computed((): ShadowDirection =>
  selectedShape.value?.type === 'text'
    ? (selectedShape.value as TextShape).shadowDirection ?? 'bottom-right'
    : (props.editor.state.annotateTextShadowDirection as ShadowDirection) ?? 'bottom-right'
);

const currentShadowLength = computed(() =>
  selectedShape.value?.type === 'text'
    ? (selectedShape.value as TextShape).shadowLength ?? 50
    : props.editor.state.annotateTextShadowLength ?? 50
);

function handleShadowDirectionChange(direction: ShadowDirection) {
  // Always persist to tool defaults for next creation
  props.editor.updateState({ annotateTextShadowDirection: direction });

  if (selectedShape.value?.type === 'text') {
    updateSelectedShape({ shadowDirection: direction } as Partial<TextShape>);
  }
}

function handleShadowLengthChange(length: number) {
  // Always persist to tool defaults for next creation
  props.editor.updateState({ annotateTextShadowLength: length });

  if (selectedShape.value?.type === 'text') {
    updateSelectedShape({ shadowLength: length } as Partial<TextShape>);
  }
}

// Glitch effect settings
const currentGlitchIntensity = computed(() =>
  selectedShape.value?.type === 'text'
    ? (selectedShape.value as TextShape).glitchIntensity ?? 50
    : props.editor.state.annotateTextGlitchIntensity ?? 50
);

function handleGlitchIntensityChange(intensity: number) {
  // Always persist to tool defaults for next creation
  props.editor.updateState({ annotateTextGlitchIntensity: intensity });

  if (selectedShape.value?.type === 'text') {
    updateSelectedShape({ glitchIntensity: intensity } as Partial<TextShape>);
  }
}

// Knockout effect settings

// ============================================
// SHAPE UPDATES
// ============================================
function updateSelectedShape(updates: Partial<Shape>) {
  const shape = selectedShape.value;
  if (!shape) return;

  const annotations = props.editor.state.annotations.map((s: Shape) =>
    s.id === shape.id ? ({ ...s, ...updates } as Shape) : s
  ) as Shape[];
  props.editor.updateState({ annotations });
  props.editor.pushHistory('Update shape');
}

function clearAll() {
  if (props.editor.state.annotations.length === 0) return;
  props.editor.updateState({
    annotations: [],
    selectedShapeId: null,
  });
  props.editor.pushHistory('Clear annotations');
}

// ============================================
// INITIALIZATION
// ============================================
function initialize() {
  // Load tool defaults from editor state
  const state = props.editor.state;

  if (state.annotateStrokeColor) {
    toolStrokeColor.value = toRGBA(state.annotateStrokeColor);
    displayStrokeColor.value = toRGBA(state.annotateStrokeColor);
  }

  if (state.annotateFillColor) {
    toolFillColor.value = toRGBA(state.annotateFillColor);
    displayFillColor.value = toRGBA(state.annotateFillColor);
  }

  if (state.annotateStrokeWidth) {
    toolStrokeWidth.value = state.annotateStrokeWidth;
    displayStrokeWidth.value = state.annotateStrokeWidth;
  }

  // Load redact block size from state
  if (state.annotateRedactBlockSize) {
    toolRedactBlockSize.value = state.annotateRedactBlockSize;
    displayRedactBlockSize.value = state.annotateRedactBlockSize;
  }

  // Load polygon sides from state
  if (state.annotatePolygonSides) {
    toolPolygonSides.value = state.annotatePolygonSides;
    displayPolygonSides.value = state.annotatePolygonSides;
  }

  // Load pen ID from state
  const penId = state.annotatePenId;
  if (penId) {
    const matchingPreset = penPresets.find(p => p.id === penId);
    if (matchingPreset) {
      toolPenId.value = matchingPreset.id;
      displayPenId.value = matchingPreset.id;
      return;
    }
  }

  // Default to marker if no existing settings
  selectPen(penPresets[1]);
}

initialize();
</script>

<template>
  <div class="stimma-annotate-controls">
    <!-- ============================================ -->
    <!-- TEXT TOOL CONTROLS -->
    <!-- ============================================ -->
    <template v-if="activeTool === 'text' || isTextShape">
      <!-- Font (shared - always at top) -->
      <div class="stimma-panel__section">
        <div class="stimma-panel__section-title">Font</div>
        <select
          class="stimma-annotate-controls__select stimma-annotate-controls__font-select"
          :value="currentFontFamily"
          @change="handleFontFamilyChange(($event.target as HTMLSelectElement).value)"
        >
          <optgroup label="System">
            <option v-for="font in fontOptions.filter(f => f.category === 'system')" :key="font.family" :value="font.family">{{ font.name }}</option>
          </optgroup>
          <optgroup label="Sans Serif">
            <option v-for="font in fontOptions.filter(f => f.category === 'sans-serif')" :key="font.family" :value="font.family">{{ font.name }}</option>
          </optgroup>
          <optgroup label="Serif">
            <option v-for="font in fontOptions.filter(f => f.category === 'serif')" :key="font.family" :value="font.family">{{ font.name }}</option>
          </optgroup>
          <optgroup label="Display">
            <option v-for="font in fontOptions.filter(f => f.category === 'display')" :key="font.family" :value="font.family">{{ font.name }}</option>
          </optgroup>
          <optgroup label="Handwriting">
            <option v-for="font in fontOptions.filter(f => f.category === 'handwriting')" :key="font.family" :value="font.family">{{ font.name }}</option>
          </optgroup>
          <optgroup label="Monospace">
            <option v-for="font in fontOptions.filter(f => f.category === 'monospace')" :key="font.family" :value="font.family">{{ font.name }}</option>
          </optgroup>
        </select>
      </div>

      <!-- Formatting: Bold/Italic + Alignment (shared) -->
      <div class="stimma-panel__section">
        <div class="stimma-panel__section-title">Format</div>
        <div class="stimma-annotate-controls__text-formatting">
          <button
            class="stimma-annotate-controls__style-btn"
            :class="{ 'stimma-annotate-controls__style-btn--active': currentFontWeight === 'bold' }"
            title="Bold"
            @click="handleFontWeightToggle"
          ><Icon name="bold" :size="16" /></button>
          <button
            class="stimma-annotate-controls__style-btn"
            :class="{ 'stimma-annotate-controls__style-btn--active': currentFontStyle === 'italic' }"
            title="Italic"
            @click="handleFontStyleToggle"
          ><Icon name="italic" :size="16" /></button>
          <span class="stimma-annotate-controls__divider" />
          <button
            class="stimma-annotate-controls__style-btn"
            :class="{ 'stimma-annotate-controls__style-btn--active': currentTextAlign === 'left' }"
            title="Align Left"
            @click="handleTextAlignChange('left')"
          ><Icon name="alignLeft" :size="16" /></button>
          <button
            class="stimma-annotate-controls__style-btn"
            :class="{ 'stimma-annotate-controls__style-btn--active': currentTextAlign === 'center' }"
            title="Align Center"
            @click="handleTextAlignChange('center')"
          ><Icon name="alignCenter" :size="16" /></button>
          <button
            class="stimma-annotate-controls__style-btn"
            :class="{ 'stimma-annotate-controls__style-btn--active': currentTextAlign === 'right' }"
            title="Align Right"
            @click="handleTextAlignChange('right')"
          ><Icon name="alignRight" :size="16" /></button>
        </div>
      </div>

      <!-- Style Selection -->
      <div class="stimma-panel__section">
        <div class="stimma-panel__section-title">Style</div>
        <div class="stimma-annotate-controls__text-effects">
          <button
            v-for="effect in textEffectOptions"
            :key="effect.id"
            class="stimma-annotate-controls__effect-btn"
            :class="{ 'stimma-annotate-controls__effect-btn--active': currentTextEffect === effect.id }"
            :title="effect.label"
            @click="handleTextEffectChange(effect.id)"
          >
            <span class="stimma-annotate-controls__effect-icon">{{ effect.icon }}</span>
            <span class="stimma-annotate-controls__effect-label">{{ effect.label }}</span>
          </button>
        </div>
      </div>

      <!-- Style-specific settings -->

      <!-- Normal: color + optional background -->
      <template v-if="currentTextEffect === 'none'">
        <div class="stimma-panel__section">
          <div class="stimma-panel__section-title">Color</div>
          <ColorPicker
            :model-value="displayStrokeColor"
            :allow-null="false"
            :image-palette="imagePalette"
            @update:model-value="handleTextColorChange"
          />
        </div>
        <div class="stimma-panel__section">
          <div class="stimma-panel__section-title">Background</div>
          <ColorPicker
            :model-value="displayFillColor"
            :allow-null="true"
            :image-palette="imagePalette"
            @update:model-value="handleTextBackgroundColorChange"
          />
        </div>
        <div v-if="displayFillColor" class="stimma-panel__section stimma-panel__section--compact">
          <div class="stimma-annotate-controls__bg-sliders">
            <div class="stimma-annotate-controls__bg-slider-row">
              <span class="stimma-annotate-controls__bg-label">Pad</span>
              <Slider
                :model-value="currentBackgroundPadding"
                :min="0"
                :max="0.5"
                :step="0.01"
                :format-value="(v: number) => `${Math.round(v * 100)}%`"
                @update:model-value="handleBackgroundPaddingChange"
              />
            </div>
            <div class="stimma-annotate-controls__bg-slider-row">
              <span class="stimma-annotate-controls__bg-label">Round</span>
              <Slider
                :model-value="currentBackgroundCornerRadius"
                :min="0"
                :max="1"
                :step="0.01"
                :format-value="(v: number) => `${Math.round(v * 100)}%`"
                @update:model-value="handleBackgroundCornerRadiusChange"
              />
            </div>
          </div>
        </div>
      </template>

      <!-- Outline: color + optional background -->
      <template v-if="currentTextEffect === 'outline'">
        <div class="stimma-panel__section">
          <div class="stimma-panel__section-title">Color</div>
          <ColorPicker
            :model-value="displayStrokeColor"
            :allow-null="false"
            :image-palette="imagePalette"
            @update:model-value="handleTextColorChange"
          />
        </div>
        <div class="stimma-panel__section">
          <div class="stimma-panel__section-title">Background</div>
          <ColorPicker
            :model-value="displayFillColor"
            :allow-null="true"
            :image-palette="imagePalette"
            @update:model-value="handleTextBackgroundColorChange"
          />
        </div>
      </template>

      <!-- Neon: color + glow intensity + optional background -->
      <template v-if="currentTextEffect === 'neon'">
        <div class="stimma-panel__section">
          <div class="stimma-panel__section-title">Color</div>
          <ColorPicker
            :model-value="displayStrokeColor"
            :allow-null="false"
            :image-palette="imagePalette"
            @update:model-value="handleTextColorChange"
          />
        </div>
        <div class="stimma-panel__section">
          <div class="stimma-panel__section-title">Background</div>
          <ColorPicker
            :model-value="displayFillColor"
            :allow-null="true"
            :image-palette="imagePalette"
            @update:model-value="handleTextBackgroundColorChange"
          />
        </div>
        <div class="stimma-panel__section stimma-panel__section--compact">
          <div class="stimma-panel__section-title">Glow: {{ currentGlowIntensity }}%</div>
          <Slider
            :model-value="currentGlowIntensity"
            :min="10"
            :max="100"
            :step="5"
            @update:model-value="handleGlowIntensityChange"
          />
        </div>
      </template>

      <!-- Gradient: gradient picker + background -->
      <template v-if="currentTextEffect === 'gradient'">
        <div class="stimma-panel__section">
          <div class="stimma-panel__section-title">Background</div>
          <ColorPicker
            :model-value="displayFillColor"
            :allow-null="true"
            :image-palette="imagePalette"
            @update:model-value="handleTextBackgroundColorChange"
          />
        </div>
        <div class="stimma-panel__section">
          <div class="stimma-panel__section-title">Gradient</div>
          <!-- Editable gradient color stops -->
          <div class="stimma-annotate-controls__gradient-stops">
            <div
              class="stimma-annotate-controls__gradient-preview"
              :style="{ background: `linear-gradient(90deg, ${currentGradientColors.join(', ')})` }"
            />
            <div class="stimma-annotate-controls__gradient-stop-row">
              <button
                v-for="(color, index) in currentGradientColors"
                :key="index"
                class="stimma-annotate-controls__gradient-stop"
                :class="{ 'stimma-annotate-controls__gradient-stop--active': editingTextGradientStop === index }"
                :style="{ backgroundColor: color }"
                :title="`Color ${index + 1} - Click to edit`"
                @click="handleTextGradientStopClick(index)"
              />
              <button
                v-if="currentGradientColors.length < 3"
                class="stimma-annotate-controls__gradient-stop stimma-annotate-controls__gradient-stop--add"
                title="Add color stop"
                @click="addTextGradientStop"
              >+</button>
            </div>
          </div>

          <!-- Color editor for selected stop -->
          <div v-if="editingTextGradientStop !== null" class="stimma-annotate-controls__gradient-stop-editor">
            <div class="stimma-annotate-controls__gradient-stop-header">
              <span>Color {{ editingTextGradientStop + 1 }}</span>
              <button
                v-if="currentGradientColors.length > 2"
                class="stimma-annotate-controls__gradient-stop-remove"
                title="Remove this color"
                @click="removeTextGradientStop(editingTextGradientStop)"
              >×</button>
            </div>
            <ColorPicker
              :model-value="hexToRgba(currentGradientColors[editingTextGradientStop])"
              :allow-null="false"
              :image-palette="imagePalette"
              @update:model-value="(c) => handleTextGradientStopColorChange(editingTextGradientStop!, c)"
            />
          </div>

          <!-- Preset gradients -->
          <div class="stimma-annotate-controls__gradient-presets">
            <button
              v-for="preset in GRADIENT_PRESETS"
              :key="preset.id"
              class="stimma-annotate-controls__gradient-btn"
              :class="{ 'stimma-annotate-controls__gradient-btn--active': JSON.stringify(currentGradientColors) === JSON.stringify(preset.colors) }"
              :title="preset.name"
              :style="{ background: `linear-gradient(90deg, ${preset.colors.join(', ')})` }"
              @click="handleGradientPresetChange(preset.id)"
            />
          </div>
          <div class="stimma-annotate-controls__gradient-directions" style="margin-top: 8px;">
            <button
              class="stimma-annotate-controls__direction-btn"
              :class="{ 'stimma-annotate-controls__direction-btn--active': currentGradientDirection === 'horizontal' }"
              title="Horizontal"
              @click="handleGradientDirectionChange('horizontal')"
            >→</button>
            <button
              class="stimma-annotate-controls__direction-btn"
              :class="{ 'stimma-annotate-controls__direction-btn--active': currentGradientDirection === 'vertical' }"
              title="Vertical"
              @click="handleGradientDirectionChange('vertical')"
            >↓</button>
            <button
              class="stimma-annotate-controls__direction-btn"
              :class="{ 'stimma-annotate-controls__direction-btn--active': currentGradientDirection === 'diagonal' }"
              title="Diagonal"
              @click="handleGradientDirectionChange('diagonal')"
            >↘</button>
          </div>
        </div>
      </template>

      <!-- 3D Shadow: color + background + shadow direction/length -->
      <template v-if="currentTextEffect === 'shadow'">
        <div class="stimma-panel__section">
          <div class="stimma-panel__section-title">Color</div>
          <ColorPicker
            :model-value="displayStrokeColor"
            :allow-null="false"
            :image-palette="imagePalette"
            @update:model-value="handleTextColorChange"
          />
        </div>
        <div class="stimma-panel__section">
          <div class="stimma-panel__section-title">Background</div>
          <ColorPicker
            :model-value="displayFillColor"
            :allow-null="true"
            :image-palette="imagePalette"
            @update:model-value="handleTextBackgroundColorChange"
          />
        </div>
        <div class="stimma-panel__section stimma-panel__section--compact">
          <div class="stimma-annotate-controls__effect-row">
            <div class="stimma-annotate-controls__shadow-directions">
              <button
                class="stimma-annotate-controls__direction-btn"
                :class="{ 'stimma-annotate-controls__direction-btn--active': currentShadowDirection === 'top-left' }"
                title="Top Left"
                @click="handleShadowDirectionChange('top-left')"
              >↖</button>
              <button
                class="stimma-annotate-controls__direction-btn"
                :class="{ 'stimma-annotate-controls__direction-btn--active': currentShadowDirection === 'top-right' }"
                title="Top Right"
                @click="handleShadowDirectionChange('top-right')"
              >↗</button>
              <button
                class="stimma-annotate-controls__direction-btn"
                :class="{ 'stimma-annotate-controls__direction-btn--active': currentShadowDirection === 'bottom-left' }"
                title="Bottom Left"
                @click="handleShadowDirectionChange('bottom-left')"
              >↙</button>
              <button
                class="stimma-annotate-controls__direction-btn"
                :class="{ 'stimma-annotate-controls__direction-btn--active': currentShadowDirection === 'bottom-right' }"
                title="Bottom Right"
                @click="handleShadowDirectionChange('bottom-right')"
              >↘</button>
            </div>
            <div class="stimma-annotate-controls__effect-slider">
              <Slider
                :model-value="currentShadowLength"
                :min="10"
                :max="100"
                :step="5"
                @update:model-value="handleShadowLengthChange"
              />
            </div>
          </div>
        </div>
      </template>

      <!-- Glitch: color + background + intensity -->
      <template v-if="currentTextEffect === 'glitch'">
        <div class="stimma-panel__section">
          <div class="stimma-panel__section-title">Color</div>
          <ColorPicker
            :model-value="displayStrokeColor"
            :allow-null="false"
            :image-palette="imagePalette"
            @update:model-value="handleTextColorChange"
          />
        </div>
        <div class="stimma-panel__section">
          <div class="stimma-panel__section-title">Background</div>
          <ColorPicker
            :model-value="displayFillColor"
            :allow-null="true"
            :image-palette="imagePalette"
            @update:model-value="handleTextBackgroundColorChange"
          />
        </div>
        <div class="stimma-panel__section stimma-panel__section--compact">
          <div class="stimma-panel__section-title">Intensity: {{ currentGlitchIntensity }}%</div>
          <Slider
            :model-value="currentGlitchIntensity"
            :min="10"
            :max="100"
            :step="5"
            @update:model-value="handleGlitchIntensityChange"
          />
        </div>
      </template>

      <!-- Knockout: color (for the outline/border around the knockout) -->
      <template v-if="currentTextEffect === 'knockout'">
        <div class="stimma-panel__section">
          <div class="stimma-panel__section-title">Color</div>
          <ColorPicker
            :model-value="displayStrokeColor"
            :allow-null="false"
            :image-palette="imagePalette"
            @update:model-value="handleTextColorChange"
          />
        </div>
      </template>

      <!-- Opacity (only show when a text shape is selected) -->
      <div v-if="isTextShape" class="stimma-panel__section">
        <div class="stimma-panel__section-title">Opacity: {{ Math.round(currentTextOpacity * 100) }}%</div>
        <Slider
          :model-value="currentTextOpacity"
          :min="0.1"
          :max="1"
          :step="0.05"
          @update:model-value="handleTextOpacityChange"
        />
      </div>
    </template>

    <!-- ============================================ -->
    <!-- REDACT TOOL CONTROLS -->
    <!-- ============================================ -->
    <template v-else-if="activeTool === 'redact' || isRedactShape">
      <div class="stimma-panel__section">
        <div class="stimma-panel__section-title">Block Size: {{ currentRedactBlockSize }}px</div>
        <Slider
          :model-value="currentRedactBlockSize"
          :min="4"
          :max="48"
          :step="2"
          @update:model-value="handleRedactBlockSizeChange"
        />
      </div>
    </template>

    <!-- ============================================ -->
    <!-- DRAW TOOL CONTROLS -->
    <!-- ============================================ -->
    <template v-else-if="activeTool === 'sharpie' || isPathShape">
      <!-- Brush Style -->
      <div class="stimma-panel__section">
        <div class="stimma-panel__section-title">Brush</div>
        <div class="stimma-annotate-controls__style-effects">
          <button
            v-for="pen in penPresets"
            :key="pen.id"
            class="stimma-annotate-controls__effect-btn"
            :class="{ 'stimma-annotate-controls__effect-btn--active': displayPenId === pen.id }"
            :title="pen.name"
            @click="selectPen(pen)"
          >
            <Icon :name="pen.icon" :size="16" />
            <span class="stimma-annotate-controls__effect-label">{{ pen.name }}</span>
          </button>
        </div>
      </div>

      <!-- Size -->
      <div class="stimma-panel__section">
        <div class="stimma-panel__section-title">Size: {{ displayStrokeWidth }}px</div>
        <Slider
          :model-value="displayStrokeWidth"
          :min="1"
          :max="50"
          :step="1"
          @update:model-value="handleStrokeWidthChange"
        />
      </div>

      <!-- Color -->
      <div class="stimma-panel__section">
        <div class="stimma-panel__section-title">Color</div>
        <ColorPicker
          :model-value="displayStrokeColor"
          :allow-null="false"
          :image-palette="imagePalette"
          @update:model-value="handleStrokeColorChange"
        />
      </div>

      <!-- Glow Intensity (available for all brushes) -->
      <div class="stimma-panel__section stimma-panel__section--compact">
        <div class="stimma-panel__section-title">Glow: {{ brushGlowIntensity }}%</div>
        <Slider
          :model-value="brushGlowIntensity"
          :min="0"
          :max="100"
          :step="5"
          @update:model-value="handleBrushGlowChange"
        />
      </div>
    </template>

    <!-- ============================================ -->
    <!-- SHAPE TOOLS (Rectangle, Ellipse, Line, Arrow, Polygon) -->
    <!-- ============================================ -->
    <template v-else>
      <!-- Polygon-specific: sides -->
      <div v-if="activeTool === 'polygon' || isPolygonShape" class="stimma-panel__section">
        <div class="stimma-panel__section-title">Sides: {{ currentPolygonSides }}</div>
        <Slider
          :model-value="currentPolygonSides"
          :min="3"
          :max="12"
          :step="1"
          @update:model-value="handlePolygonSidesChange"
        />
      </div>
      <!-- Stroke Width -->
      <div v-if="hasStroke || !selectedShape" class="stimma-panel__section">
        <div class="stimma-panel__section-title">Size: {{ displayStrokeWidth }}px</div>
        <Slider
          :model-value="displayStrokeWidth"
          :min="1"
          :max="20"
          :step="1"
          @update:model-value="handleStrokeWidthChange"
        />
      </div>

      <!-- Style Selection (for shapes that support it) -->
      <div v-if="supportsShapeStyle" class="stimma-panel__section">
        <div class="stimma-panel__section-title">Style</div>
        <div class="stimma-annotate-controls__style-effects">
          <button
            class="stimma-annotate-controls__effect-btn"
            :class="{ 'stimma-annotate-controls__effect-btn--active': displayShapeEffect === 'none' }"
            title="Normal"
            @click="handleShapeEffectChange('none')"
          >
            <span class="stimma-annotate-controls__effect-icon"><Icon name="arrowUpRight" :size="16" /></span>
            <span class="stimma-annotate-controls__effect-label">Normal</span>
          </button>
          <button
            class="stimma-annotate-controls__effect-btn"
            :class="{ 'stimma-annotate-controls__effect-btn--active': displayShapeEffect === 'neon' }"
            title="Neon Glow"
            @click="handleShapeEffectChange('neon')"
          >
            <span class="stimma-annotate-controls__effect-icon">✨</span>
            <span class="stimma-annotate-controls__effect-label">Neon</span>
          </button>
          <button
            class="stimma-annotate-controls__effect-btn"
            :class="{ 'stimma-annotate-controls__effect-btn--active': displayShapeEffect === 'gradient' }"
            title="Gradient"
            @click="handleShapeEffectChange('gradient')"
          >
            <span class="stimma-annotate-controls__effect-icon">🌈</span>
            <span class="stimma-annotate-controls__effect-label">Gradient</span>
          </button>
        </div>
      </div>

      <!-- Style-specific settings -->
      <!-- Normal: color + fill (for closed shapes) -->
      <template v-if="!supportsShapeStyle || displayShapeEffect === 'none'">
        <div v-if="!selectedShape || hasStroke" class="stimma-panel__section">
          <div class="stimma-panel__section-title">Color</div>
          <ColorPicker
            :model-value="displayStrokeColor"
            :allow-null="strokeCanBeNull"
            :image-palette="imagePalette"
            @update:model-value="handleStrokeColorChange"
          />
        </div>
        <div v-if="(!selectedShape && (activeTool === 'rectangle' || activeTool === 'ellipse' || activeTool === 'star')) || hasFill" class="stimma-panel__section">
          <div class="stimma-panel__section-title">Fill</div>
          <ColorPicker
            :model-value="displayFillColor"
            :allow-null="true"
            :image-palette="imagePalette"
            @update:model-value="handleFillColorChange"
          />
        </div>
      </template>

      <!-- Neon: color + intensity (no fill) -->
      <template v-if="supportsShapeStyle && displayShapeEffect === 'neon'">
        <div class="stimma-panel__section">
          <div class="stimma-panel__section-title">Color</div>
          <ColorPicker
            :model-value="displayStrokeColor"
            :allow-null="false"
            :image-palette="imagePalette"
            @update:model-value="handleStrokeColorChange"
          />
        </div>
        <div class="stimma-panel__section stimma-panel__section--compact">
          <div class="stimma-panel__section-title">Glow: {{ displayGlowIntensity }}%</div>
          <Slider
            :model-value="displayGlowIntensity"
            :min="10"
            :max="100"
            :step="5"
            @update:model-value="handleShapeGlowIntensityChange"
          />
        </div>
      </template>

      <!-- Gradient: gradient picker only (no color or fill) -->
      <template v-if="supportsShapeStyle && displayShapeEffect === 'gradient'">
        <div class="stimma-panel__section">
          <div class="stimma-panel__section-title">Gradient</div>
          <!-- Editable gradient color stops -->
          <div class="stimma-annotate-controls__gradient-stops">
            <div
              class="stimma-annotate-controls__gradient-preview"
              :style="{ background: `linear-gradient(90deg, ${displayGradientColors.map(c => `rgb(${c.r},${c.g},${c.b})`).join(', ')})` }"
            />
            <div class="stimma-annotate-controls__gradient-stop-row">
              <button
                v-for="(color, index) in displayGradientColors"
                :key="index"
                class="stimma-annotate-controls__gradient-stop"
                :class="{ 'stimma-annotate-controls__gradient-stop--active': editingGradientStop === index }"
                :style="{ backgroundColor: `rgb(${color.r},${color.g},${color.b})` }"
                :title="`Color ${index + 1} - Click to edit`"
                @click="handleGradientStopClick(index)"
              />
              <button
                v-if="displayGradientColors.length < 3"
                class="stimma-annotate-controls__gradient-stop stimma-annotate-controls__gradient-stop--add"
                title="Add color stop"
                @click="addGradientStop"
              >+</button>
            </div>
          </div>

          <!-- Color editor for selected stop -->
          <div v-if="editingGradientStop !== null" class="stimma-annotate-controls__gradient-stop-editor">
            <div class="stimma-annotate-controls__gradient-stop-header">
              <span>Color {{ editingGradientStop + 1 }}</span>
              <button
                v-if="displayGradientColors.length > 2"
                class="stimma-annotate-controls__gradient-stop-remove"
                title="Remove this color"
                @click="removeGradientStop(editingGradientStop)"
              >×</button>
            </div>
            <ColorPicker
              :model-value="displayGradientColors[editingGradientStop]"
              :allow-null="false"
              :image-palette="imagePalette"
              @update:model-value="(c) => handleGradientStopColorChange(editingGradientStop!, c)"
            />
          </div>

          <!-- Preset gradients -->
          <div class="stimma-annotate-controls__gradient-presets">
            <button
              v-for="preset in GRADIENT_PRESETS"
              :key="preset.id"
              class="stimma-annotate-controls__gradient-btn"
              :class="{ 'stimma-annotate-controls__gradient-btn--active': isGradientPresetActive(preset.id) }"
              :title="preset.name"
              :style="{ background: `linear-gradient(90deg, ${preset.colors.join(', ')})` }"
              @click="handleShapeGradientPresetChange(preset.id)"
            />
          </div>
          <div class="stimma-annotate-controls__gradient-directions" style="margin-top: 8px;">
            <button
              class="stimma-annotate-controls__direction-btn"
              :class="{ 'stimma-annotate-controls__direction-btn--active': displayGradientDirection === 'horizontal' }"
              title="Horizontal"
              @click="handleShapeGradientDirectionChange('horizontal')"
            >→</button>
            <button
              class="stimma-annotate-controls__direction-btn"
              :class="{ 'stimma-annotate-controls__direction-btn--active': displayGradientDirection === 'vertical' }"
              title="Vertical"
              @click="handleShapeGradientDirectionChange('vertical')"
            >↓</button>
            <button
              class="stimma-annotate-controls__direction-btn"
              :class="{ 'stimma-annotate-controls__direction-btn--active': displayGradientDirection === 'diagonal' }"
              title="Diagonal"
              @click="handleShapeGradientDirectionChange('diagonal')"
            >↘</button>
          </div>
        </div>
      </template>

    </template>

    <!-- Clear All -->
    <div v-if="props.editor.state.annotations.length > 0" class="stimma-panel__section">
      <button
        class="stimma-button stimma-button--default stimma-button--full stimma-annotate-controls__clear-btn"
        @click="clearAll"
      >
        <Icon name="trash" :size="14" />
        Clear All
      </button>
    </div>
  </div>
</template>

<style scoped>
.stimma-annotate-controls__tools {
  display: flex;
  flex-wrap: wrap;
  gap: var(--stimma-spacing-xs);
}

.stimma-annotate-controls__tool {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: var(--stimma-border-radius);
  background-color: rgb(var(--stimma-color-foreground) / 0.05);
  border: 2px solid transparent;
  cursor: pointer;
  transition: all var(--stimma-transition-duration);
}

.stimma-annotate-controls__tool:hover {
  background-color: rgb(var(--stimma-color-foreground) / 0.1);
}

.stimma-annotate-controls__tool--active {
  background-color: rgb(var(--stimma-color-primary) / 0.15);
  border-color: rgb(var(--stimma-color-primary));
  color: rgb(var(--stimma-color-primary));
}

/* Pen presets */
.stimma-annotate-controls__pens {
  display: flex;
  flex-wrap: wrap;
  gap: var(--stimma-spacing-xs);
}

.stimma-annotate-controls__pen {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 6px 8px;
  border-radius: var(--stimma-border-radius);
  background-color: rgb(var(--stimma-color-foreground) / 0.05);
  border: 2px solid transparent;
  cursor: pointer;
  transition: all var(--stimma-transition-duration);
  min-width: 48px;
}

.stimma-annotate-controls__pen:hover {
  background-color: rgb(var(--stimma-color-foreground) / 0.1);
}

.stimma-annotate-controls__pen--active {
  background-color: rgb(var(--stimma-color-primary) / 0.15);
  border-color: rgb(var(--stimma-color-primary));
  color: rgb(var(--stimma-color-primary));
}

.stimma-annotate-controls__pen-label {
  font-size: 10px;
  font-weight: 500;
}

/* Background style buttons */
.stimma-annotate-controls__bg-styles {
  display: flex;
  flex-wrap: wrap;
  gap: var(--stimma-spacing-xs);
}

.stimma-annotate-controls__bg-style {
  padding: 4px 10px;
  border-radius: var(--stimma-border-radius);
  background-color: rgb(var(--stimma-color-foreground) / 0.05);
  border: 2px solid transparent;
  cursor: pointer;
  transition: all var(--stimma-transition-duration);
  font-size: 11px;
  font-weight: 500;
}

.stimma-annotate-controls__bg-style:hover {
  background-color: rgb(var(--stimma-color-foreground) / 0.1);
}

.stimma-annotate-controls__bg-style--active {
  background-color: rgb(var(--stimma-color-primary) / 0.15);
  border-color: rgb(var(--stimma-color-primary));
  color: rgb(var(--stimma-color-primary));
}

.stimma-annotate-controls__select {
  width: 100%;
  padding: var(--stimma-spacing-xs) var(--stimma-spacing-sm);
  border-radius: var(--stimma-border-radius);
  border: 1px solid rgb(var(--stimma-color-foreground) / 0.2);
  background-color: rgb(var(--stimma-color-foreground) / 0.05);
  color: inherit;
  font-size: 13px;
  cursor: pointer;
}

.stimma-annotate-controls__select:focus {
  outline: none;
  border-color: rgb(var(--stimma-color-primary));
}

.stimma-annotate-controls__font-select {
  font-size: 14px;
}

.stimma-annotate-controls__font-select optgroup {
  font-size: 11px;
  font-weight: 600;
  font-style: normal;
  color: rgb(var(--stimma-color-foreground) / 0.5);
}

.stimma-annotate-controls__font-select option {
  font-size: 14px;
  font-weight: normal;
  padding: 4px 8px;
}

.stimma-button--full {
  width: 100%;
}

/* Text tool styles */
.stimma-annotate-controls__text-styles,
.stimma-annotate-controls__text-align {
  display: flex;
  gap: var(--stimma-spacing-xs);
}

.stimma-annotate-controls__style-btn,
.stimma-annotate-controls__align-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: var(--stimma-border-radius);
  background-color: rgb(var(--stimma-color-foreground) / 0.05);
  border: 2px solid transparent;
  cursor: pointer;
  transition: all var(--stimma-transition-duration);
}

.stimma-annotate-controls__style-btn:hover,
.stimma-annotate-controls__align-btn:hover {
  background-color: rgb(var(--stimma-color-foreground) / 0.1);
}

.stimma-annotate-controls__style-btn--active,
.stimma-annotate-controls__align-btn--active {
  background-color: rgb(var(--stimma-color-primary) / 0.15);
  border-color: rgb(var(--stimma-color-primary));
  color: rgb(var(--stimma-color-primary));
}

.stimma-annotate-controls__clear-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--stimma-spacing-xs);
}

/* Shape Style Effects (universal neon/gradient) */
.stimma-annotate-controls__style-effects {
  display: flex;
  gap: 4px;
}

.stimma-annotate-controls__style-effects .stimma-annotate-controls__effect-btn {
  flex: 1;
}

/* Text Effects */
.stimma-annotate-controls__text-effects {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 4px;
}

.stimma-annotate-controls__effect-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  padding: 4px 2px;
  border-radius: var(--stimma-border-radius);
  background-color: rgb(var(--stimma-color-foreground) / 0.05);
  border: 2px solid transparent;
  cursor: pointer;
  transition: all var(--stimma-transition-duration);
}

.stimma-annotate-controls__effect-btn:hover {
  background-color: rgb(var(--stimma-color-foreground) / 0.1);
}

.stimma-annotate-controls__effect-btn--active {
  background-color: rgb(var(--stimma-color-primary) / 0.15);
  border-color: rgb(var(--stimma-color-primary));
  color: rgb(var(--stimma-color-primary));
}

.stimma-annotate-controls__effect-icon {
  font-size: 16px;
  line-height: 1;
}

.stimma-annotate-controls__effect-label {
  font-size: 9px;
  font-weight: 500;
}

/* Gradient presets */
.stimma-annotate-controls__gradient-presets {
  display: flex;
  flex-wrap: wrap;
  gap: var(--stimma-spacing-xs);
}

.stimma-annotate-controls__gradient-btn {
  width: 36px;
  height: 24px;
  border-radius: var(--stimma-border-radius);
  border: 2px solid transparent;
  cursor: pointer;
  transition: all var(--stimma-transition-duration);
}

.stimma-annotate-controls__gradient-btn:hover {
  transform: scale(1.05);
}

.stimma-annotate-controls__gradient-btn--active {
  border-color: rgb(var(--stimma-color-primary));
  box-shadow: 0 0 0 2px rgb(var(--stimma-color-primary) / 0.3);
}

/* Gradient directions */
.stimma-annotate-controls__gradient-directions {
  display: flex;
  gap: var(--stimma-spacing-xs);
}

.stimma-annotate-controls__direction-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: var(--stimma-border-radius);
  background-color: rgb(var(--stimma-color-foreground) / 0.05);
  border: 2px solid transparent;
  cursor: pointer;
  transition: all var(--stimma-transition-duration);
  font-size: 16px;
}

.stimma-annotate-controls__direction-btn:hover {
  background-color: rgb(var(--stimma-color-foreground) / 0.1);
}

.stimma-annotate-controls__direction-btn--active {
  background-color: rgb(var(--stimma-color-primary) / 0.15);
  border-color: rgb(var(--stimma-color-primary));
  color: rgb(var(--stimma-color-primary));
}

/* Shadow directions (2x2 grid) */
.stimma-annotate-controls__shadow-directions {
  display: grid;
  grid-template-columns: repeat(2, 36px);
  gap: var(--stimma-spacing-xs);
}

/* Combined text formatting row (bold, italic, divider, align) */
.stimma-annotate-controls__text-formatting {
  display: flex;
  align-items: center;
  gap: var(--stimma-spacing-xs);
}

.stimma-annotate-controls__divider {
  width: 1px;
  height: 20px;
  background-color: rgb(var(--stimma-color-foreground) / 0.2);
  margin: 0 4px;
}

/* Effect row with direction buttons + slider mentiside by side */
.stimma-annotate-controls__effect-row {
  display: flex;
  align-items: center;
  gap: var(--stimma-spacing-sm);
}

.stimma-annotate-controls__effect-slider {
  flex: 1;
}

/* Compact section */
.stimma-panel__section--compact {
  padding-top: 0;
}

/* Background sliders */
.stimma-annotate-controls__bg-sliders {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.stimma-annotate-controls__bg-slider-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.stimma-annotate-controls__bg-label {
  font-size: 11px;
  color: rgb(var(--stimma-color-foreground) / 0.6);
  width: 40px;
  flex-shrink: 0;
}

.stimma-annotate-controls__bg-slider-row :deep(.stimma-slider) {
  flex: 1;
}

/* Gradient stop editing */
.stimma-annotate-controls__gradient-stops {
  margin-bottom: 12px;
}

.stimma-annotate-controls__gradient-preview {
  height: 24px;
  border-radius: var(--stimma-border-radius);
  margin-bottom: 8px;
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.15);
}

.stimma-annotate-controls__gradient-stop-row {
  display: flex;
  gap: 6px;
  justify-content: center;
}

.stimma-annotate-controls__gradient-stop {
  width: 32px;
  height: 32px;
  border-radius: var(--stimma-border-radius-lg);
  border: 2px solid transparent;
  cursor: pointer;
  transition: all var(--stimma-transition-duration);
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.15), 0 0 0 1px rgba(255, 255, 255, 0.1);
}

.stimma-annotate-controls__gradient-stop:hover {
  transform: scale(1.1);
}

.stimma-annotate-controls__gradient-stop--active {
  border-color: rgb(var(--stimma-color-primary));
  box-shadow: 0 0 0 2px rgb(var(--stimma-color-primary) / 0.3);
}

.stimma-annotate-controls__gradient-stop--add {
  background: rgb(var(--stimma-color-foreground) / 0.1);
  color: rgb(var(--stimma-color-foreground) / 0.6);
  font-size: 18px;
  font-weight: 300;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: none;
}

.stimma-annotate-controls__gradient-stop--add:hover {
  background: rgb(var(--stimma-color-foreground) / 0.15);
  color: rgb(var(--stimma-color-foreground));
}

.stimma-annotate-controls__gradient-stop-editor {
  margin-bottom: 12px;
  padding: 8px;
  background: rgb(var(--stimma-color-foreground) / 0.05);
  border-radius: var(--stimma-border-radius-lg);
}

.stimma-annotate-controls__gradient-stop-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-size: 12px;
  font-weight: 500;
  color: rgb(var(--stimma-color-foreground) / 0.7);
}

.stimma-annotate-controls__gradient-stop-remove {
  width: 20px;
  height: 20px;
  border-radius: var(--stimma-border-radius-sm);
  border: none;
  background: rgb(var(--stimma-color-foreground) / 0.1);
  color: rgb(var(--stimma-color-foreground) / 0.6);
  font-size: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.stimma-annotate-controls__gradient-stop-remove:hover {
  background: rgba(255, 59, 48, 0.2);
  color: rgb(255, 59, 48);
}
</style>
