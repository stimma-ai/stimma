<script setup lang="ts">
import {
  ref,
  onMounted,
  onUnmounted,
  watch,
  computed,
  inject,
} from 'vue';
import type { EditorState, ViewTransform, Size } from '@/types';
import {
  getContext,
  applyViewTransform,
  drawImage,
  createCanvas,
  imageToCanvas,
} from '@/utils/canvas';
import { combineAdjustments, applyColorMatrix, multiplyColorMatrices, applySplitToning, applyGradientMap, applyColorIsolation } from '@/utils/colorMatrix';
import { renderShapes, drawSelectionHandles, getShapeBounds, getShapeCenter, type TextEditState } from '@/utils/shapes';
import { hasEffects, applyEffects } from '@/utils/effects';
import { UI_COLOR, FILTER_MATRICES } from '@/constants';
import { logEditorDebug, isEditorDebugEnabled } from '@/utils/editorDebug';
import Icon from './icons/Icon.vue';
import ViewportScrollbars from './ViewportScrollbars.vue';

const props = defineProps<{
  state: EditorState;
  viewTransform: ViewTransform;
  sourceImage: HTMLImageElement | null;
  cursorStyle?: string;
  viewMode?: 'full' | 'crop';
  isAnimating?: boolean;
  retouchCanvas?: HTMLCanvasElement | null;
  renderTrigger?: number; // Increment to force re-render (only on stroke end)
  retouchDrawTrigger?: number; // Lightweight trigger for live retouch overlay during stroke
  debugSessionId?: number | null;
  isRetouchDrawing?: boolean; // When true, skip full reprocessing and composite retouch as overlay
  editingTextShapeId?: string | null; // Hide this shape during inline text editing
  textEditState?: TextEditState | null; // State for canvas-based text editing (cursor/selection)
  hideAnnotations?: boolean; // Hide annotation layer (e.g., when working in retouch mode)
}>();

const debugEnabled = isEditorDebugEnabled();

function debugLog(event: string, details: Record<string, unknown> = {}) {
  if (!debugEnabled || !props.debugSessionId) return;
  logEditorDebug('EditorCanvas', event, {
    restoreSession: props.debugSessionId,
    ...details,
  });
}


const emit = defineEmits<{
  (e: 'resize', size: Size): void;
  (e: 'reset-rotation'): void;
  (e: 'duplicate'): void;
  (e: 'delete'): void;
  (e: 'edit-text'): void;
  (e: 'pan', x: number, y: number): void;
  (e: 'bring-to-front'): void;
  (e: 'send-to-back'): void;
}>();

const canvasRef = ref<HTMLCanvasElement | null>(null);
const containerRef = ref<HTMLDivElement | null>(null);
const canvasSize = ref<Size>({ width: 800, height: 600 });

// Inject theme from parent
const isDarkTheme = inject<{ value: boolean }>('stimmaThemeIsDark', { value: false });

// Canvas background color based on theme
const canvasBackgroundColor = computed(() => {
  return isDarkTheme.value ? 'rgb(18, 18, 18)' : 'rgb(220, 220, 220)';
});

// Crop mask color based on theme (darken for light theme, lighten for dark theme)
const cropMaskColor = computed(() => {
  return isDarkTheme.value ? 'rgba(0, 0, 0, 0.5)' : 'rgba(0, 0, 0, 0.3)';
});

// Cached full processed image (source + retouch + color/effects)
let processedCanvas: HTMLCanvasElement | null = null;
let lastColorState: string = '';

// Cached BASE processed image (source + color/effects, NO retouch)
// Only changes when color/effect settings change — NOT on retouch changes.
// Used for: (1) fast overlay path during drawing, (2) getProcessedImageCanvas for retouch tools
let baseProcessedCanvas: HTMLCanvasElement | null = null;
let lastBaseColorState: string = '';

let resizeObserver: ResizeObserver | null = null;
let animationFrameId: number | null = null;
let resizeTimeoutId: ReturnType<typeof setTimeout> | null = null;
let pendingCanvasSize: { width: number; height: number } | null = null;

/**
 * Build the color/effects-only cache key (excludes retouch version).
 */
function buildBaseColorKey(): string {
  const brightness = props.state.brightness ?? 0;
  const contrast = props.state.contrast ?? 0;
  const saturation = props.state.saturation ?? 0;
  const exposure = props.state.exposure ?? 0;
  const temperature = props.state.temperature ?? 0;
  const gamma = props.state.gamma ?? 1;
  const filter = props.state.filter ?? null;

  const effectsState = {
    blur: props.state.blur ?? 0,
    sharpen: props.state.sharpen ?? 0,
    noise: props.state.noise ?? 0,
    glow: props.state.glow ?? 0,
    pixelate: props.state.pixelate ?? 0,
    chromaticAberration: props.state.chromaticAberration ?? 0,
    motionBlur: props.state.motionBlur ?? 0,
    motionBlurAngle: props.state.motionBlurAngle ?? 0,
    vignette: props.state.vignette ?? 0,
    clarity: props.state.clarity ?? 0,
    halftone: props.state.halftone ?? 0,
    halftoneAngle: props.state.halftoneAngle ?? 0,
    vhs: props.state.vhs ?? 0,
    glitch: props.state.glitch ?? 0,
    glitchBlockSize: props.state.glitchBlockSize ?? 16,
    ditherEnabled: props.state.ditherEnabled ?? false,
    ditherPalette: (props.state.ditherPalette === 'none' ? '8bit' : props.state.ditherPalette) ?? '8bit',
  };

  const creativeState = {
    splitToningEnabled: props.state.splitToningEnabled ?? false,
    splitToningShadowHue: props.state.splitToningShadowHue ?? 30,
    splitToningShadowSat: props.state.splitToningShadowSat ?? 50,
    splitToningHighlightHue: props.state.splitToningHighlightHue ?? 200,
    splitToningHighlightSat: props.state.splitToningHighlightSat ?? 50,
    splitToningBalance: props.state.splitToningBalance ?? 0,
    gradientMapEnabled: props.state.gradientMapEnabled ?? false,
    gradientMapShadowColor: props.state.gradientMapShadowColor,
    gradientMapHighlightColor: props.state.gradientMapHighlightColor,
    gradientMapIntensity: props.state.gradientMapIntensity ?? 100,
    colorIsolationEnabled: props.state.colorIsolationEnabled ?? false,
    colorIsolationHue: props.state.colorIsolationHue ?? 0,
    colorIsolationRange: props.state.colorIsolationRange ?? 30,
    colorIsolationFeather: props.state.colorIsolationFeather ?? 20,
  };

  return `${brightness},${contrast},${saturation},${exposure},${temperature},${gamma},${filter},${JSON.stringify(effectsState)},${JSON.stringify(creativeState)}`;
}

/**
 * Get the base processed image (source + color/effects, NO retouch).
 * Cached by color/effect settings only. Used by retouch tools as their source canvas,
 * and as the background during active drawing (overlay retouch on top).
 */
function getBaseProcessedImage(): HTMLCanvasElement | HTMLImageElement {
  // During active retouch drawing, skip expensive key building — color settings
  // don't change mid-stroke, so the cache is guaranteed valid.
  if (props.isRetouchDrawing && lastBaseColorState !== '') {
    return baseProcessedCanvas ?? props.sourceImage!;
  }

  const baseKey = buildBaseColorKey();

  // Check cache (handles both processed canvas and "no processing needed" cases)
  if (lastBaseColorState === baseKey) {
    return baseProcessedCanvas ?? props.sourceImage!;
  }

  const brightness = props.state.brightness ?? 0;
  const contrast = props.state.contrast ?? 0;
  const saturation = props.state.saturation ?? 0;
  const exposure = props.state.exposure ?? 0;
  const temperature = props.state.temperature ?? 0;
  const gamma = props.state.gamma ?? 1;
  const filter = props.state.filter ?? null;

  const effectsState = {
    blur: props.state.blur ?? 0,
    sharpen: props.state.sharpen ?? 0,
    noise: props.state.noise ?? 0,
    glow: props.state.glow ?? 0,
    pixelate: props.state.pixelate ?? 0,
    chromaticAberration: props.state.chromaticAberration ?? 0,
    motionBlur: props.state.motionBlur ?? 0,
    motionBlurAngle: props.state.motionBlurAngle ?? 0,
    vignette: props.state.vignette ?? 0,
    clarity: props.state.clarity ?? 0,
    halftone: props.state.halftone ?? 0,
    halftoneAngle: props.state.halftoneAngle ?? 0,
    vhs: props.state.vhs ?? 0,
    glitch: props.state.glitch ?? 0,
    glitchBlockSize: props.state.glitchBlockSize ?? 16,
    ditherEnabled: props.state.ditherEnabled ?? false,
    ditherPalette: (props.state.ditherPalette === 'none' ? '8bit' : props.state.ditherPalette) ?? '8bit',
  };

  const creativeState = {
    splitToningEnabled: props.state.splitToningEnabled ?? false,
    splitToningShadowHue: props.state.splitToningShadowHue ?? 30,
    splitToningShadowSat: props.state.splitToningShadowSat ?? 50,
    splitToningHighlightHue: props.state.splitToningHighlightHue ?? 200,
    splitToningHighlightSat: props.state.splitToningHighlightSat ?? 50,
    splitToningBalance: props.state.splitToningBalance ?? 0,
    gradientMapEnabled: props.state.gradientMapEnabled ?? false,
    gradientMapShadowColor: props.state.gradientMapShadowColor,
    gradientMapHighlightColor: props.state.gradientMapHighlightColor,
    gradientMapIntensity: props.state.gradientMapIntensity ?? 100,
    colorIsolationEnabled: props.state.colorIsolationEnabled ?? false,
    colorIsolationHue: props.state.colorIsolationHue ?? 0,
    colorIsolationRange: props.state.colorIsolationRange ?? 30,
    colorIsolationFeather: props.state.colorIsolationFeather ?? 20,
  };

  const hasColorAdjustments = brightness !== 0 || contrast !== 0 || saturation !== 0 ||
    exposure !== 0 || temperature !== 0 || gamma !== 1 || filter !== null;
  const hasCreativeEffects = creativeState.splitToningEnabled ||
    creativeState.gradientMapEnabled ||
    creativeState.colorIsolationEnabled;

  if (!hasColorAdjustments && !hasEffects(effectsState) && !hasCreativeEffects) {
    lastBaseColorState = baseKey;
    baseProcessedCanvas = null;
    return props.sourceImage!;
  }

  const imageSize = props.state.imageSize!;
  baseProcessedCanvas = createCanvas(imageSize.width, imageSize.height);
  const pctx = getContext(baseProcessedCanvas);

  // Draw source (NO retouch)
  pctx.drawImage(props.sourceImage!, 0, 0);

  // Apply color adjustments
  if (hasColorAdjustments) {
    const imageData = pctx.getImageData(0, 0, imageSize.width, imageSize.height);
    let matrix = combineAdjustments({ brightness, contrast, saturation, exposure, temperature, gamma });
    if (filter && FILTER_MATRICES[filter]) {
      matrix = multiplyColorMatrices(FILTER_MATRICES[filter], matrix);
    }
    applyColorMatrix(imageData, matrix);
    pctx.putImageData(imageData, 0, 0);
  }

  // Apply creative color effects
  if (hasCreativeEffects) {
    const imageData = pctx.getImageData(0, 0, imageSize.width, imageSize.height);
    if (creativeState.splitToningEnabled) {
      applySplitToning(imageData, creativeState.splitToningShadowHue, creativeState.splitToningShadowSat,
        creativeState.splitToningHighlightHue, creativeState.splitToningHighlightSat, creativeState.splitToningBalance);
    }
    if (creativeState.gradientMapEnabled && creativeState.gradientMapShadowColor && creativeState.gradientMapHighlightColor) {
      applyGradientMap(imageData, creativeState.gradientMapShadowColor, creativeState.gradientMapHighlightColor, creativeState.gradientMapIntensity);
    }
    if (creativeState.colorIsolationEnabled) {
      applyColorIsolation(imageData, creativeState.colorIsolationHue, creativeState.colorIsolationRange, creativeState.colorIsolationFeather);
    }
    pctx.putImageData(imageData, 0, 0);
  }

  // Apply effects
  if (hasEffects(effectsState)) {
    baseProcessedCanvas = applyEffects(baseProcessedCanvas, effectsState);
  }

  lastBaseColorState = baseKey;
  return baseProcessedCanvas;
}

/**
 * Get the processed image canvas for retouch tools (base + retouch composited, at original size).
 * Retouch tools sample from this to read the "current" image including prior retouch edits.
 * Cached by color settings + retouch version.
 */
function getProcessedImageCanvas(): HTMLCanvasElement | null {
  if (!props.sourceImage || !props.state.imageSize) return null;

  const stateKey = `${buildBaseColorKey()},rv:${props.renderTrigger ?? 0}`;

  if (cachedProcessedImageCanvas && lastProcessedState === stateKey) {
    return cachedProcessedImageCanvas;
  }

  const base = getBaseProcessedImage();
  const { width, height } = props.state.imageSize;

  if (!cachedProcessedImageCanvas ||
      cachedProcessedImageCanvas.width !== width ||
      cachedProcessedImageCanvas.height !== height) {
    cachedProcessedImageCanvas = createCanvas(width, height);
  }

  const ctx = getContext(cachedProcessedImageCanvas);
  ctx.clearRect(0, 0, width, height);
  ctx.drawImage(base, 0, 0, width, height);

  // Composite retouch layer on top of the base
  if (props.retouchCanvas) {
    ctx.drawImage(props.retouchCanvas, 0, 0);
  }

  lastProcessedState = stateKey;
  return cachedProcessedImageCanvas;
}

// Separate cache for getProcessedImageCanvas
let cachedProcessedImageCanvas: HTMLCanvasElement | null = null;
let lastProcessedState: string = '';

/**
 * Render synchronously without RAF scheduling.
 * Used during active retouch drawing where the caller is already RAF-gated.
 */
function renderImmediate() {
  if (animationFrameId !== null) {
    cancelAnimationFrame(animationFrameId);
    animationFrameId = null;
  }
  render();
}

// Expose canvas ref, processed image, and immediate render for parent components
defineExpose({
  canvasRef,
  getProcessedImageCanvas,
  renderImmediate,
});

const canvasStyle = computed(() => ({
  cursor: props.cursorStyle || 'grab',
}));

// Get selected shape for floating toolbar
const selectedShape = computed(() => {
  if (!props.state.selectedShapeId || props.state.activePlugin !== 'annotate') return null;
  return props.state.annotations?.find(s => s.id === props.state.selectedShapeId) ?? null;
});

// Calculate floating toolbar position (above the selected shape's visual bounding box)
const toolbarPosition = computed(() => {
  const shape = selectedShape.value;
  if (!shape || !props.state.imageSize) return null;

  const imageSize = props.state.imageSize;
  const bounds = getShapeBounds(shape, imageSize);
  const rotation = shape.rotation || 0;

  // Get all 4 corners of the shape
  const corners = [
    { x: bounds.x, y: bounds.y }, // NW
    { x: bounds.x + bounds.width, y: bounds.y }, // NE
    { x: bounds.x + bounds.width, y: bounds.y + bounds.height }, // SE
    { x: bounds.x, y: bounds.y + bounds.height }, // SW
  ];

  // Rotate corners if shape is rotated
  const shapeCenterX = bounds.x + bounds.width / 2;
  const shapeCenterY = bounds.y + bounds.height / 2;

  const rotatedCorners = corners.map(corner => {
    if (rotation === 0) return corner;
    const dx = corner.x - shapeCenterX;
    const dy = corner.y - shapeCenterY;
    const cos = Math.cos(rotation);
    const sin = Math.sin(rotation);
    return {
      x: shapeCenterX + dx * cos - dy * sin,
      y: shapeCenterY + dx * sin + dy * cos,
    };
  });

  // Find axis-aligned bounding box of rotated shape
  const minX = Math.min(...rotatedCorners.map(c => c.x));
  const maxX = Math.max(...rotatedCorners.map(c => c.x));
  const minY = Math.min(...rotatedCorners.map(c => c.y));

  // Position toolbar at center-top of the axis-aligned bounding box
  const centerX = (minX + maxX) / 2;
  const topY = minY;

  // Convert to canvas space
  const canvasPoint = imageToCanvas(
    { x: centerX, y: topY },
    props.viewTransform,
    imageSize,
    canvasSize.value
  );

  // Offset above the shape
  const offsetY = 45;

  return {
    left: `${canvasPoint.x}px`,
    top: `${canvasPoint.y - offsetY}px`,
  };
});

/**
 * Get the full processed image (source + retouch + color/effects).
 * Used for display rendering (not during active drawing).
 *
 * Optimization: uses getBaseProcessedImage() (cached) and composites the
 * retouch layer on top. Retouch pixels don't go through color adjustments
 * a second time, but this is visually imperceptible because:
 * - Paint brush: uses chosen color directly
 * - Clone/heal: samples from the already-adjusted image
 * - Blur/sharpen: operates on already-adjusted pixels
 * This avoids reprocessing every pixel (getImageData + color matrix on 12M+ pixels)
 * on every cache miss, making undo/redo and tool changes near-instant.
 */
function getProcessedImage(): HTMLCanvasElement | HTMLImageElement {
  const hasRetouch = !!props.retouchCanvas;
  const fullKey = `${buildBaseColorKey()},rv:${props.renderTrigger ?? 0}`;

  if (!hasRetouch) {
    // No retouch — base processed image is the full processed image
    return getBaseProcessedImage();
  }

  // Check cache
  if (processedCanvas && lastColorState === fullKey) {
    return processedCanvas;
  }

  // Use the cached base image (source + color/effects, no retouch) and
  // composite the retouch layer on top. Two fast drawImage calls (~2ms)
  // instead of reprocessing every pixel through color matrix math (~200ms+).
  const base = getBaseProcessedImage();
  const imageSize = props.state.imageSize!;

  processedCanvas = createCanvas(imageSize.width, imageSize.height);
  const pctx = getContext(processedCanvas);
  pctx.drawImage(base, 0, 0, imageSize.width, imageSize.height);
  pctx.drawImage(props.retouchCanvas!, 0, 0);

  lastColorState = fullKey;
  return processedCanvas;
}

/**
 * Draw crop overlay
 */
function drawCropOverlay(ctx: CanvasRenderingContext2D, imageSize: Size) {
  const { crop } = props.state;
  const { zoom, panX, panY } = props.viewTransform;
  const cropRotation = crop.rotation ?? 0;

  // Calculate crop rect center in canvas space
  const imgCenterX = canvasSize.value.width / 2 + panX;
  const imgCenterY = canvasSize.value.height / 2 + panY;

  const cropCenterX = imgCenterX + (crop.x - 0.5) * imageSize.width * zoom;
  const cropCenterY = imgCenterY + (crop.y - 0.5) * imageSize.height * zoom;
  const cropW = crop.width * imageSize.width * zoom;
  const cropH = crop.height * imageSize.height * zoom;

  // Helper to rotate a point around the crop center
  const rotatePoint = (px: number, py: number) => {
    const cos = Math.cos(cropRotation);
    const sin = Math.sin(cropRotation);
    const dx = px - cropCenterX;
    const dy = py - cropCenterY;
    return {
      x: cropCenterX + dx * cos - dy * sin,
      y: cropCenterY + dx * sin + dy * cos,
    };
  };

  // Get the 4 corners of the rotated crop rect
  const halfW = cropW / 2;
  const halfH = cropH / 2;
  const corners = [
    rotatePoint(cropCenterX - halfW, cropCenterY - halfH), // NW
    rotatePoint(cropCenterX + halfW, cropCenterY - halfH), // NE
    rotatePoint(cropCenterX + halfW, cropCenterY + halfH), // SE
    rotatePoint(cropCenterX - halfW, cropCenterY + halfH), // SW
  ];

  // Draw semi-transparent overlay outside crop area using path subtraction
  ctx.save();
  ctx.fillStyle = cropMaskColor.value;
  ctx.beginPath();
  // Outer rectangle (full canvas)
  ctx.rect(0, 0, canvasSize.value.width, canvasSize.value.height);
  // Inner crop rectangle (counter-clockwise to cut out)
  ctx.moveTo(corners[0].x, corners[0].y);
  ctx.lineTo(corners[3].x, corners[3].y);
  ctx.lineTo(corners[2].x, corners[2].y);
  ctx.lineTo(corners[1].x, corners[1].y);
  ctx.closePath();
  ctx.fill('evenodd');
  ctx.restore();

  // Draw crop border - use blue color like annotate selection
  ctx.strokeStyle = '#3b82f6';
  ctx.lineWidth = 2;
  ctx.setLineDash([6, 4]);
  ctx.beginPath();
  ctx.moveTo(corners[0].x, corners[0].y);
  ctx.lineTo(corners[1].x, corners[1].y);
  ctx.lineTo(corners[2].x, corners[2].y);
  ctx.lineTo(corners[3].x, corners[3].y);
  ctx.closePath();
  ctx.stroke();
  ctx.setLineDash([]);

  // Draw rule of thirds guides
  ctx.strokeStyle = UI_COLOR.guideLine;
  ctx.lineWidth = 1;

  // Helper to get point along edge
  const lerp = (p1: { x: number; y: number }, p2: { x: number; y: number }, t: number) => ({
    x: p1.x + (p2.x - p1.x) * t,
    y: p1.y + (p2.y - p1.y) * t,
  });

  ctx.beginPath();
  // Vertical lines (from top edge to bottom edge)
  for (const t of [1/3, 2/3]) {
    const top = lerp(corners[0], corners[1], t);
    const bottom = lerp(corners[3], corners[2], t);
    ctx.moveTo(top.x, top.y);
    ctx.lineTo(bottom.x, bottom.y);
  }
  // Horizontal lines (from left edge to right edge)
  for (const t of [1/3, 2/3]) {
    const left = lerp(corners[0], corners[3], t);
    const right = lerp(corners[1], corners[2], t);
    ctx.moveTo(left.x, left.y);
    ctx.lineTo(right.x, right.y);
  }
  ctx.stroke();

  // Draw center point indicator
  const centerSize = 8;
  const cos = Math.cos(cropRotation);
  const sin = Math.sin(cropRotation);

  ctx.beginPath();
  ctx.moveTo(cropCenterX - centerSize * cos, cropCenterY - centerSize * sin);
  ctx.lineTo(cropCenterX + centerSize * cos, cropCenterY + centerSize * sin);
  ctx.moveTo(cropCenterX + centerSize * sin, cropCenterY - centerSize * cos);
  ctx.lineTo(cropCenterX - centerSize * sin, cropCenterY + centerSize * cos);
  ctx.stroke();

  // Handle sizes (consistent with annotate)
  const handleRadius = 7;
  const rotateHandleRadius = 7;
  const rotateHandleDistance = 30;

  // Rotation handle is at bottom center, perpendicular to the bottom edge
  const bottomCenter = lerp(corners[3], corners[2], 0.5);

  // Calculate perpendicular direction to the bottom edge (pointing outward/down)
  // Bottom edge goes from SW (corners[3]) to SE (corners[2])
  const edgeX = corners[2].x - corners[3].x;
  const edgeY = corners[2].y - corners[3].y;
  const edgeLen = Math.sqrt(edgeX * edgeX + edgeY * edgeY);
  // Perpendicular pointing "down" from the crop is (-edgeY, edgeX) normalized
  // (rotate edge vector 90° clockwise)
  const perpX = -edgeY / edgeLen;
  const perpY = edgeX / edgeLen;

  const rotateHandleX = bottomCenter.x + perpX * rotateHandleDistance;
  const rotateHandleY = bottomCenter.y + perpY * rotateHandleDistance;

  // Draw rotation handle stem (dashed line from bottom center)
  ctx.strokeStyle = '#3b82f6';
  ctx.lineWidth = 2;
  ctx.setLineDash([4, 3]);
  ctx.beginPath();
  ctx.moveTo(bottomCenter.x, bottomCenter.y);
  ctx.lineTo(rotateHandleX, rotateHandleY);
  ctx.stroke();
  ctx.setLineDash([]);

  // Draw rotation handle circle (lollipop)
  ctx.fillStyle = '#ffffff';
  ctx.strokeStyle = '#3b82f6';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(rotateHandleX, rotateHandleY, rotateHandleRadius, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();

  // Draw corner handles as circles
  ctx.fillStyle = '#ffffff';
  ctx.strokeStyle = '#3b82f6';
  ctx.lineWidth = 2;

  for (const corner of corners) {
    ctx.beginPath();
    ctx.arc(corner.x, corner.y, handleRadius, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }
}

/**
 * Render the canvas
 */
function render() {
  const canvas = canvasRef.value;
  if (!canvas) return;

  const ctx = getContext(canvas, false); // Request opaque canvas (no alpha channel)

  // Reset transform and clear (handle DPR properly)
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  // Apply DPR scaling
  const dpr = window.devicePixelRatio || 1;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  // Ensure context is fully opaque
  ctx.globalAlpha = 1;
  ctx.globalCompositeOperation = 'source-over';

  // Draw background using theme-aware color
  const bgColor = canvasBackgroundColor.value;
  ctx.fillStyle = bgColor;
  ctx.fillRect(0, 0, canvasSize.value.width, canvasSize.value.height);

  // If no image, show nothing more
  if (!props.sourceImage || !props.state.imageSize) {
    return;
  }

  const imageSize = props.state.imageSize;
  const { rotation, rotation90, flipX, flipY, crop } = props.state;

  // Two-tier rendering: during active retouch drawing, skip the expensive
  // full pipeline and instead use the base processed image (source + colors/effects,
  // NO retouch) with the live retouch canvas composited on top as an overlay.
  // The base image is cached and only rebuilt when color/effect settings change.
  let imageToRender: HTMLCanvasElement | HTMLImageElement;
  if (props.isRetouchDrawing) {
    // Fast path: base image (no retouch) + overlay live retouch canvas
    imageToRender = getBaseProcessedImage();
  } else {
    // Full path: source + retouch + color adjustments + effects
    imageToRender = getProcessedImage();
  }

  ctx.save();

  // Get crop rotation for use in transforms
  const cropRotation = crop.rotation ?? 0;

  // If in crop view mode (not crop plugin), clip to crop region
  if (props.viewMode === 'crop') {
    // Calculate crop rect in canvas space
    const { zoom, panX, panY } = props.viewTransform;
    const imgCenterX = canvasSize.value.width / 2 + panX;
    const imgCenterY = canvasSize.value.height / 2 + panY;
    const cropCenterX = imgCenterX + (crop.x - 0.5) * imageSize.width * zoom;
    const cropCenterY = imgCenterY + (crop.y - 0.5) * imageSize.height * zoom;
    const cropW = crop.width * imageSize.width * zoom;
    const cropH = crop.height * imageSize.height * zoom;

    // For rotated crop, we clip to a horizontal rectangle but the image will be rotated
    // The clip rect is always axis-aligned (the crop dimensions)
    const cropX = cropCenterX - cropW / 2;
    const cropY = cropCenterY - cropH / 2;
    ctx.beginPath();
    ctx.rect(cropX, cropY, cropW, cropH);
    ctx.clip();
  }

  // Apply view transform (zoom/pan)
  applyViewTransform(ctx, props.viewTransform, imageSize, canvasSize.value);

  // Apply image transforms at the image center
  const centerX = imageSize.width / 2;
  const centerY = imageSize.height / 2;
  ctx.translate(centerX, centerY);

  // Apply crop rotation (rotate image so rotated crop region becomes horizontal)
  // This applies in crop view mode AND when not in crop plugin
  if (cropRotation !== 0 && props.viewMode === 'crop') {
    // Rotate around crop center, not image center
    const cropCenterXImg = crop.x * imageSize.width;
    const cropCenterYImg = crop.y * imageSize.height;
    // Translate to crop center, rotate, translate back
    ctx.translate(cropCenterXImg - centerX, cropCenterYImg - centerY);
    ctx.rotate(-cropRotation);
    ctx.translate(-(cropCenterXImg - centerX), -(cropCenterYImg - centerY));
  }

  // Apply fine rotation (image rotation from slider)
  if (rotation !== 0) {
    ctx.rotate(rotation);
  }

  // Apply 90° rotation increments
  if (rotation90 !== 0) {
    ctx.rotate((rotation90 * Math.PI) / 2);
  }

  // Apply flips
  ctx.scale(flipX ? -1 : 1, flipY ? -1 : 1);

  ctx.translate(-centerX, -centerY);

  // Draw the image (retouch layer is already composited into processed image
  // before color/filter/effects are applied -- except during active drawing)
  drawImage(ctx, imageToRender, 0, 0, imageSize.width, imageSize.height);

  // During active retouch drawing, composite the live retouch canvas on top
  // This gives real-time feedback without re-running the full processing pipeline
  if (props.isRetouchDrawing && props.retouchCanvas) {
    ctx.drawImage(props.retouchCanvas, 0, 0, imageSize.width, imageSize.height);
  }

  // Draw annotations (shapes), filtering out any shape being edited inline
  // Skip rendering if hideAnnotations is true (e.g., when working in retouch mode)
  if (!props.hideAnnotations && props.state.annotations && props.state.annotations.length > 0) {
    const shapesToRender = props.editingTextShapeId
      ? props.state.annotations.filter(s => s.id !== props.editingTextShapeId)
      : props.state.annotations;
    // imageToRender already includes retouch layer composited before color/effects
    renderShapes(ctx, shapesToRender, imageSize, imageToRender, props.textEditState);
  }

  ctx.restore();

  // Draw crop overlay if crop plugin is active
  if (props.state.activePlugin === 'crop') {
    drawCropOverlay(ctx, imageSize);
  }

  // Draw selection handles for selected shape (in screen space)
  if (props.state.activePlugin === 'annotate' && props.state.selectedShapeId) {
    const selectedShape = props.state.annotations?.find(
      (s) => s.id === props.state.selectedShapeId
    );
    if (selectedShape) {
      ctx.save();
      applyViewTransform(ctx, props.viewTransform, imageSize, canvasSize.value);
      const bounds = getShapeBounds(selectedShape, imageSize);
      const shapeCenter = getShapeCenter(selectedShape);
      drawSelectionHandles(ctx, bounds, imageSize, selectedShape.rotation, shapeCenter, props.viewTransform.zoom);
      ctx.restore();
    }
  }
}

/**
 * Request a render on next animation frame
 */
function requestRender() {
  if (animationFrameId !== null) {
    cancelAnimationFrame(animationFrameId);
  }
  animationFrameId = requestAnimationFrame(() => {
    render();
    animationFrameId = null;
  });
}

/**
 * Handle container resize with debounced canvas buffer resize
 * CSS size updates immediately, but canvas buffer resize is debounced to prevent flickering
 */
function handleResize(entries: ResizeObserverEntry[]) {
  const entry = entries[0];
  if (!entry) return;

  const { width, height } = entry.contentRect;

  if (canvasSize.value.width === width && canvasSize.value.height === height) {
    debugLog('resize:ignored', { width, height });
    return;
  }

  debugLog('resize:start', {
    width,
    height,
    prevWidth: canvasSize.value.width,
    prevHeight: canvasSize.value.height,
  });
  canvasSize.value = { width, height };

  const canvas = canvasRef.value;
  if (canvas) {
    // Update CSS size immediately for smooth visual resize
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;

    // Store pending size for debounced buffer resize
    pendingCanvasSize = { width, height };

    // Clear existing timeout
    if (resizeTimeoutId !== null) {
      clearTimeout(resizeTimeoutId);
    }

    // Debounce the actual canvas buffer resize to prevent flickering
    resizeTimeoutId = setTimeout(() => {
      if (pendingCanvasSize && canvas) {
        const dpr = window.devicePixelRatio || 1;
        canvas.width = pendingCanvasSize.width * dpr;
        canvas.height = pendingCanvasSize.height * dpr;
        pendingCanvasSize = null;
        resizeTimeoutId = null;
        requestRender();
      }
    }, 100);
  }

  debugLog('resize:emit', { width, height });
  emit('resize', canvasSize.value);
}

// Watch for changes that require re-render
// Note: We specifically exclude retouchLayerData and selectionMaskData from watching
// to avoid recursive updates. The renderTrigger prop handles retouch canvas refreshes.
watch(
  [
    // View transform (primitive values)
    () => props.viewTransform.zoom,
    () => props.viewTransform.panX,
    () => props.viewTransform.panY,
    () => props.viewTransform.rotation,
    // Source image
    () => props.sourceImage,
    // Render trigger for retouch layer changes (stroke end)
    () => props.renderTrigger,
    // Lightweight trigger for live retouch rendering during active strokes
    () => props.retouchDrawTrigger,
    // Text editing state (deep watch needed)
    () => props.textEditState,
    // Core state primitives
    () => props.state.imageSize?.width,
    () => props.state.imageSize?.height,
    () => props.state.crop?.x,
    () => props.state.crop?.y,
    () => props.state.crop?.width,
    () => props.state.crop?.height,
    () => props.state.crop?.rotation,
    () => props.state.rotation,
    () => props.state.rotation90,
    () => props.state.flipX,
    () => props.state.flipY,
    () => props.state.filter,
    () => props.state.brightness,
    () => props.state.contrast,
    () => props.state.saturation,
    () => props.state.exposure,
    () => props.state.temperature,
    () => props.state.gamma,
    () => props.state.blur,
    () => props.state.sharpen,
    () => props.state.noise,
    () => props.state.glow,
    () => props.state.pixelate,
    () => props.state.chromaticAberration,
    () => props.state.motionBlur,
    () => props.state.vignette,
    () => props.state.clarity,
    // Creative effects
    () => props.state.splitToningEnabled,
    () => props.state.gradientMapEnabled,
    () => props.state.colorIsolationEnabled,
    () => props.state.halftone,
    () => props.state.vhs,
    () => props.state.glitch,
    () => props.state.ditherEnabled,
    // UI state
    () => props.state.activePlugin,
    () => props.state.selectedShapeId,
    // Annotations need deep watch
    () => props.state.annotations,
  ],
  () => {
    debugLog('watch:render-deps', {
      activePlugin: props.state.activePlugin,
      selectedShapeId: props.state.selectedShapeId ?? null,
      renderTrigger: props.renderTrigger ?? 0,
    });
    requestRender();
  },
  // No { deep: true } — all sources are either primitives or replaced (not mutated) refs.
  // Annotations array is always replaced via spread/filter/map, never mutated in-place.
);

// Continuous render loop during animation
let animationLoopId: number | null = null;

function startAnimationLoop() {
  function loop() {
    render();
    if (props.isAnimating) {
      animationLoopId = requestAnimationFrame(loop);
    } else {
      animationLoopId = null;
    }
  }
  loop();
}

watch(
  () => props.isAnimating,
  (animating) => {
    debugLog('watch:is-animating', { animating });
    if (animating) {
      // Start continuous render loop
      if (animationLoopId !== null) {
        cancelAnimationFrame(animationLoopId);
      }
      startAnimationLoop();
    }
  }
);


onMounted(() => {
  // Setup resize observer
  if (containerRef.value) {
    resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(containerRef.value);

    // Trigger initial size calculation
    const rect = containerRef.value.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) {
      handleResize([{ contentRect: rect } as ResizeObserverEntry]);
    }
  }

  // Initial render
  requestRender();
});

onUnmounted(() => {
  if (resizeObserver) {
    resizeObserver.disconnect();
  }
  if (animationFrameId !== null) {
    cancelAnimationFrame(animationFrameId);
  }
  if (animationLoopId !== null) {
    cancelAnimationFrame(animationLoopId);
  }
  if (resizeTimeoutId !== null) {
    clearTimeout(resizeTimeoutId);
  }
});
</script>

<template>
  <div ref="containerRef" class="stimma-editor__canvas-container">
    <canvas
      ref="canvasRef"
      class="stimma-canvas"
      :style="canvasStyle"
      tabindex="0"
      role="img"
      aria-label="Image preview"
    />

    <!-- Viewport scrollbars -->
    <ViewportScrollbars
      :view-transform="viewTransform"
      :image-size="state.imageSize"
      :canvas-size="canvasSize"
      @pan="(x, y) => emit('pan', x, y)"
    />

    <!-- Floating contextual toolbar for selected shapes -->
    <div
      v-if="selectedShape && toolbarPosition"
      class="stimma-shape-toolbar"
      :style="toolbarPosition"
    >
      <button
        v-if="selectedShape.type === 'text'"
        class="stimma-shape-toolbar__btn"
        title="Edit text"
        @click.stop="emit('edit-text')"
      >
        <Icon name="pencil" :size="16" />
      </button>
      <button
        v-if="selectedShape.rotation"
        class="stimma-shape-toolbar__btn"
        title="Reset rotation"
        @click.stop="emit('reset-rotation')"
      >
        <Icon name="rotateCcw" :size="16" />
      </button>
      <button
        class="stimma-shape-toolbar__btn"
        title="Bring to front"
        @click.stop="emit('bring-to-front')"
      >
        <Icon name="arrowUp" :size="16" />
      </button>
      <button
        class="stimma-shape-toolbar__btn"
        title="Send to back"
        @click.stop="emit('send-to-back')"
      >
        <Icon name="arrowDown" :size="16" />
      </button>
      <button
        class="stimma-shape-toolbar__btn"
        title="Duplicate"
        @click.stop="emit('duplicate')"
      >
        <Icon name="copy" :size="16" />
      </button>
      <button
        class="stimma-shape-toolbar__btn"
        title="Delete"
        @click.stop="emit('delete')"
      >
        <Icon name="trash" :size="16" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.stimma-shape-toolbar {
  position: absolute;
  display: flex;
  gap: 2px;
  padding: 4px;
  background-color: rgba(30, 30, 30, 0.9);
  border-radius: var(--stimma-border-radius-lg);
  transform: translateX(-50%);
  pointer-events: auto;
  z-index: 100;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
}

.stimma-shape-toolbar__btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: var(--stimma-border-radius);
  background: transparent;
  color: #fff;
  cursor: pointer;
  transition: background-color 0.15s;
}

.stimma-shape-toolbar__btn:hover {
  background-color: rgba(255, 255, 255, 0.15);
}

.stimma-shape-toolbar__btn:active {
  background-color: rgba(255, 255, 255, 0.25);
}
</style>
