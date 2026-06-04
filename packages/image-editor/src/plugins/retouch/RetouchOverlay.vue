<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, computed } from 'vue';
import type { EditorContext } from '@/types/plugins';
import type { Point, Size } from '@/types/geometry';
import type { ViewTransform, RetouchTool } from '@/types/editor';
import { logEditorDebug, isEditorDebugEnabled } from '@/utils/editorDebug';
import Icon from '@/components/icons/Icon.vue';

const props = defineProps<{
  editor: EditorContext;
  viewTransform: ViewTransform;
  canvasSize: Size;
  marchingAntsPaths: Point[][];
  cloneSource: Point | null;
  currentBrushSize: number;
  isDrawingSelection: boolean;
  selectionPreview: {
    type: 'rect' | 'ellipse' | 'lasso';
    startPoint: Point;
    currentPoint: Point;
    points?: Point[];
  } | null;
  // Patch tool state
  isPatchDragging?: boolean;
  isPatchDrawing?: boolean;
  patchDragOffset?: Point | null;
  patchDrawingPoints?: Point[];
  // Magnetic lasso state
  isMagneticLassoActive?: boolean;
  magneticLassoAnchors?: Point[];
  magneticLassoPathSegments?: Point[][];
  magneticLassoPreviewPath?: Point[];
  isMagneticLassoNearStart?: boolean;
  debugSessionId?: number | null;
}>();

const debugEnabled = isEditorDebugEnabled();

function debugLog(event: string, details: Record<string, unknown> = {}) {
  if (!debugEnabled || !props.debugSessionId) return;
  logEditorDebug('RetouchOverlay', event, {
    restoreSession: props.debugSessionId,
    ...details,
  });
}

// Canvas ref for overlay
const overlayRef = ref<HTMLCanvasElement | null>(null);

// Animation state
const antsOffset = ref(0);
let animationId: number | null = null;

// Mouse position tracking for brush cursor
const mousePos = ref<Point | null>(null);
const isMouseInCanvas = ref(false);

// Tools that should show a brush cursor
const brushTools = new Set<RetouchTool>([
  'clone', 'paint', 'spot-heal', 'dodge', 'burn', 'sponge', 'blur-brush', 'sharpen-brush'
]);

// Check if current tool should show brush cursor
const showBrushCursor = computed(() => {
  const tool = props.editor.state.retouchTool;
  return tool && brushTools.has(tool);
});

// Check if there's an active selection (from marching ants paths)
// Show toolbar even during drawing (for combine modes)
const hasSelection = computed(() => props.marchingAntsPaths.length > 0);

// Show floating toolbar when there's a selection (regardless of active tool)
const showSelectionToolbar = computed(() => hasSelection.value);

// Convert image space point to canvas space
function imageToCanvas(point: Point): Point {
  if (!props.editor.state.imageSize) return { x: 0, y: 0 };

  const imageSize = props.editor.state.imageSize;
  const { zoom, panX, panY } = props.viewTransform;
  const { width, height } = props.canvasSize;

  const imgCenterX = width / 2 + panX;
  const imgCenterY = height / 2 + panY;

  return {
    x: imgCenterX + (point.x - imageSize.width / 2) * zoom,
    y: imgCenterY + (point.y - imageSize.height / 2) * zoom,
  };
}

// Calculate floating toolbar position above the selection
const toolbarPosition = computed(() => {
  if (!showSelectionToolbar.value || props.marchingAntsPaths.length === 0) return null;

  // Find bounding box of all marching ants paths
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

  for (const path of props.marchingAntsPaths) {
    for (const point of path) {
      const canvasPoint = imageToCanvas(point);
      minX = Math.min(minX, canvasPoint.x);
      minY = Math.min(minY, canvasPoint.y);
      maxX = Math.max(maxX, canvasPoint.x);
      maxY = Math.max(maxY, canvasPoint.y);
    }
  }

  if (minX === Infinity) return null;

  // Position at center-top of selection
  const centerX = (minX + maxX) / 2;
  const offsetY = 45; // Offset above the selection

  return {
    left: `${centerX}px`,
    top: `${Math.max(10, minY - offsetY)}px`,
  };
});

// Selection operations
function invertSelection() {
  props.editor.retouch?.invertSelection();
}

function deselectSelection() {
  props.editor.retouch?.clearSelection();
}

// Draw the overlay
function draw() {
  const canvas = overlayRef.value;
  if (!canvas) return;

  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  // Clear
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  // Always draw existing marching ants if present
  if (props.marchingAntsPaths.length > 0) {
    drawMarchingAnts(ctx);
  }

  // Draw selection preview on top when drawing
  if (props.isDrawingSelection && props.selectionPreview) {
    drawSelectionPreview(ctx);
  }

  // Draw clone source indicator
  if (props.cloneSource && props.editor.state.retouchTool === 'clone') {
    drawCloneSourceIndicator(ctx);
  }

  // Draw patch tool lasso preview while drawing
  if (props.isPatchDrawing && props.patchDrawingPoints && props.patchDrawingPoints.length > 0) {
    drawPatchLassoPreview(ctx);
  }

  // Draw patch tool drag preview (ghost outline at source position)
  if (props.isPatchDragging && props.patchDragOffset && props.marchingAntsPaths.length > 0) {
    drawPatchDragPreview(ctx);
  }

  // Draw magnetic lasso preview
  if (props.isMagneticLassoActive) {
    drawMagneticLassoPreview(ctx);
  }

  // Draw brush cursor
  if (showBrushCursor.value && mousePos.value && isMouseInCanvas.value) {
    drawBrushCursor(ctx);
  }
}

// Draw marching ants animation
function drawMarchingAnts(ctx: CanvasRenderingContext2D) {
  ctx.save();

  for (const path of props.marchingAntsPaths) {
    if (path.length < 2) continue;

    // Draw dashed line with animation
    ctx.beginPath();

    const firstPoint = imageToCanvas(path[0]);
    ctx.moveTo(firstPoint.x, firstPoint.y);

    for (let i = 1; i < path.length; i++) {
      const point = imageToCanvas(path[i]);
      ctx.lineTo(point.x, point.y);
    }

    // Only close the path if the last point is close to the first
    // This prevents diagonal lines when contour tracing doesn't complete a loop
    const lastPoint = imageToCanvas(path[path.length - 1]);
    const closeThreshold = 5;
    const dx = lastPoint.x - firstPoint.x;
    const dy = lastPoint.y - firstPoint.y;
    if (dx * dx + dy * dy < closeThreshold * closeThreshold) {
      ctx.closePath();
    }

    // Draw white background line
    ctx.strokeStyle = 'white';
    ctx.lineWidth = 1;
    ctx.setLineDash([]);
    ctx.stroke();

    // Draw black dashed line with animation offset
    ctx.strokeStyle = 'black';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.lineDashOffset = -antsOffset.value;
    ctx.stroke();
  }

  ctx.restore();
}

// Draw selection preview while dragging
function drawSelectionPreview(ctx: CanvasRenderingContext2D) {
  if (!props.selectionPreview) return;

  const { type, startPoint, currentPoint, points } = props.selectionPreview;

  ctx.save();
  ctx.strokeStyle = 'rgba(100, 150, 255, 0.8)';
  ctx.fillStyle = 'rgba(100, 150, 255, 0.1)';
  ctx.lineWidth = 1;
  ctx.setLineDash([5, 5]);

  const start = imageToCanvas(startPoint);
  const current = imageToCanvas(currentPoint);

  if (type === 'rect') {
    const x = Math.min(start.x, current.x);
    const y = Math.min(start.y, current.y);
    const width = Math.abs(current.x - start.x);
    const height = Math.abs(current.y - start.y);

    ctx.fillRect(x, y, width, height);
    ctx.strokeRect(x, y, width, height);
  } else if (type === 'ellipse') {
    const centerX = (start.x + current.x) / 2;
    const centerY = (start.y + current.y) / 2;
    const radiusX = Math.abs(current.x - start.x) / 2;
    const radiusY = Math.abs(current.y - start.y) / 2;

    ctx.beginPath();
    ctx.ellipse(centerX, centerY, radiusX, radiusY, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  } else if (type === 'lasso' && points && points.length > 0) {
    ctx.beginPath();
    const firstLassoPoint = imageToCanvas(points[0]);
    ctx.moveTo(firstLassoPoint.x, firstLassoPoint.y);

    for (let i = 1; i < points.length; i++) {
      const p = imageToCanvas(points[i]);
      ctx.lineTo(p.x, p.y);
    }

    ctx.fill();
    ctx.stroke();
  }

  ctx.restore();
}

// Draw patch tool lasso preview while drawing selection
function drawPatchLassoPreview(ctx: CanvasRenderingContext2D) {
  const points = props.patchDrawingPoints;
  if (!points || points.length === 0) return;

  ctx.save();
  ctx.strokeStyle = 'rgba(100, 150, 255, 0.8)';
  ctx.fillStyle = 'rgba(100, 150, 255, 0.1)';
  ctx.lineWidth = 1;
  ctx.setLineDash([5, 5]);

  ctx.beginPath();
  const first = imageToCanvas(points[0]);
  ctx.moveTo(first.x, first.y);

  for (let i = 1; i < points.length; i++) {
    const p = imageToCanvas(points[i]);
    ctx.lineTo(p.x, p.y);
  }

  // Close path back to start
  ctx.closePath();
  ctx.fill();
  ctx.stroke();

  ctx.restore();
}

// Draw patch tool drag preview (ghost outline showing source region)
function drawPatchDragPreview(ctx: CanvasRenderingContext2D) {
  if (!props.patchDragOffset) return;

  ctx.save();
  ctx.strokeStyle = 'rgba(255, 150, 50, 0.8)';
  ctx.fillStyle = 'rgba(255, 150, 50, 0.1)';
  ctx.lineWidth = 2;
  ctx.setLineDash([6, 4]);

  // Draw the marching ants paths offset by the drag amount (showing source region)
  for (const path of props.marchingAntsPaths) {
    if (path.length < 2) continue;

    ctx.beginPath();

    // First point offset by drag
    const firstPoint = imageToCanvas({
      x: path[0].x + props.patchDragOffset.x,
      y: path[0].y + props.patchDragOffset.y,
    });
    ctx.moveTo(firstPoint.x, firstPoint.y);

    // Remaining points
    for (let i = 1; i < path.length; i++) {
      const point = imageToCanvas({
        x: path[i].x + props.patchDragOffset.x,
        y: path[i].y + props.patchDragOffset.y,
      });
      ctx.lineTo(point.x, point.y);
    }

    ctx.closePath();
    ctx.fill();
    ctx.stroke();
  }

  ctx.restore();
}

// Draw magnetic lasso preview (anchors, path segments, and preview path)
function drawMagneticLassoPreview(ctx: CanvasRenderingContext2D) {
  const anchors = props.magneticLassoAnchors || [];
  const pathSegments = props.magneticLassoPathSegments || [];
  const previewPath = props.magneticLassoPreviewPath || [];
  const isNearStart = props.isMagneticLassoNearStart || false;

  if (anchors.length === 0) return;

  ctx.save();

  // Draw confirmed path segments (solid blue line)
  ctx.strokeStyle = 'rgba(100, 150, 255, 0.9)';
  ctx.lineWidth = 2;
  ctx.setLineDash([]);

  for (const segment of pathSegments) {
    if (segment.length < 2) continue;

    ctx.beginPath();
    const firstPoint = imageToCanvas(segment[0]);
    ctx.moveTo(firstPoint.x, firstPoint.y);

    for (let i = 1; i < segment.length; i++) {
      const point = imageToCanvas(segment[i]);
      ctx.lineTo(point.x, point.y);
    }

    ctx.stroke();
  }

  // Draw preview path from last anchor to cursor (dashed line)
  if (previewPath.length >= 2) {
    ctx.strokeStyle = 'rgba(100, 150, 255, 0.6)';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([5, 5]);

    ctx.beginPath();
    const firstPreviewPoint = imageToCanvas(previewPath[0]);
    ctx.moveTo(firstPreviewPoint.x, firstPreviewPoint.y);

    for (let i = 1; i < previewPath.length; i++) {
      const point = imageToCanvas(previewPath[i]);
      ctx.lineTo(point.x, point.y);
    }

    ctx.stroke();
  }

  // Draw anchor points
  ctx.setLineDash([]);
  for (let i = 0; i < anchors.length; i++) {
    const anchor = anchors[i];
    const point = imageToCanvas(anchor);

    // Larger circle for first anchor (close target)
    const isFirstAnchor = i === 0;
    const radius = isFirstAnchor ? 6 : 4;

    // Highlight first anchor if cursor is near (close indicator)
    if (isFirstAnchor && isNearStart && anchors.length >= 3) {
      // Draw close indicator ring
      ctx.strokeStyle = 'rgba(50, 255, 50, 0.9)';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(point.x, point.y, radius + 4, 0, Math.PI * 2);
      ctx.stroke();
    }

    // Outer ring
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.9)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
    ctx.stroke();

    // Inner fill
    ctx.fillStyle = isFirstAnchor
      ? (isNearStart && anchors.length >= 3 ? 'rgba(50, 255, 50, 0.8)' : 'rgba(100, 150, 255, 0.8)')
      : 'rgba(100, 150, 255, 0.8)';
    ctx.beginPath();
    ctx.arc(point.x, point.y, radius - 1, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.restore();
}

// Draw clone source crosshair indicator
function drawCloneSourceIndicator(ctx: CanvasRenderingContext2D) {
  if (!props.cloneSource) return;

  const point = imageToCanvas(props.cloneSource);
  const { zoom } = props.viewTransform;
  const size = (props.currentBrushSize * zoom) / 2;

  ctx.save();

  // Draw crosshair circle
  ctx.strokeStyle = 'rgba(255, 100, 100, 0.8)';
  ctx.lineWidth = 2;
  ctx.setLineDash([]);

  ctx.beginPath();
  ctx.arc(point.x, point.y, size, 0, Math.PI * 2);
  ctx.stroke();

  // Draw crosshair lines
  const crossSize = Math.max(10, size);
  ctx.beginPath();
  ctx.moveTo(point.x - crossSize, point.y);
  ctx.lineTo(point.x + crossSize, point.y);
  ctx.moveTo(point.x, point.y - crossSize);
  ctx.lineTo(point.x, point.y + crossSize);
  ctx.stroke();

  ctx.restore();
}

// Draw brush cursor at mouse position
function drawBrushCursor(ctx: CanvasRenderingContext2D) {
  if (!mousePos.value) return;

  const { zoom } = props.viewTransform;
  const radius = (props.currentBrushSize * zoom) / 2;

  ctx.save();
  ctx.setLineDash([]);

  // Draw outer white circle for visibility on dark backgrounds
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.8)';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.arc(mousePos.value.x, mousePos.value.y, radius, 0, Math.PI * 2);
  ctx.stroke();

  // Draw inner black circle for visibility on light backgrounds
  ctx.strokeStyle = 'rgba(0, 0, 0, 0.8)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(mousePos.value.x, mousePos.value.y, radius, 0, Math.PI * 2);
  ctx.stroke();

  // Draw small crosshair in center for precision
  const crossSize = Math.min(4, radius / 2);
  if (crossSize >= 2) {
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.9)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(mousePos.value.x - crossSize, mousePos.value.y);
    ctx.lineTo(mousePos.value.x + crossSize, mousePos.value.y);
    ctx.moveTo(mousePos.value.x, mousePos.value.y - crossSize);
    ctx.lineTo(mousePos.value.x, mousePos.value.y + crossSize);
    ctx.stroke();
  }

  ctx.restore();
}

// Animation loop for marching ants (slow march like Photoshop)
let lastAnimTime = 0;
const MARCH_INTERVAL = 80; // ms between updates (slower = more like Photoshop)

function animate(time: number = 0) {
  if (time - lastAnimTime >= MARCH_INTERVAL) {
    antsOffset.value = (antsOffset.value + 1) % 8;
    draw();
    lastAnimTime = time;
  }
  animationId = requestAnimationFrame(animate);
}

// Watch for changes that require redraw
watch(
  [
    () => props.marchingAntsPaths,
    () => props.cloneSource,
    () => props.viewTransform,
    () => props.isDrawingSelection,
    () => props.selectionPreview,
    () => props.isPatchDragging,
    () => props.isPatchDrawing,
    () => props.patchDragOffset,
    () => props.patchDrawingPoints,
    () => props.isMagneticLassoActive,
    () => props.magneticLassoAnchors,
    () => props.magneticLassoPathSegments,
    () => props.magneticLassoPreviewPath,
    () => props.isMagneticLassoNearStart,
  ],
  () => {
    debugLog('watch:redraw', {
      pathCount: props.marchingAntsPaths.length,
      isDrawingSelection: props.isDrawingSelection,
      isPatchDragging: !!props.isPatchDragging,
      isMagneticLassoActive: !!props.isMagneticLassoActive,
    });
    draw();
  },
  { deep: true }
);

// Handle canvas resize
function handleResize() {
  const canvas = overlayRef.value;
  if (!canvas) return;

  debugLog('resize', {
    width: props.canvasSize.width,
    height: props.canvasSize.height,
  });
  const dpr = window.devicePixelRatio || 1;
  canvas.width = props.canvasSize.width * dpr;
  canvas.height = props.canvasSize.height * dpr;
  canvas.style.width = `${props.canvasSize.width}px`;
  canvas.style.height = `${props.canvasSize.height}px`;

  const ctx = canvas.getContext('2d');
  if (ctx) {
    ctx.scale(dpr, dpr);
  }

  draw();
}

watch(() => props.canvasSize, handleResize, { deep: true });

// Mouse event handlers for brush cursor
function handleMouseMove(event: MouseEvent) {
  const canvas = overlayRef.value;
  if (!canvas) return;

  const rect = canvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;

  // Check if mouse is within canvas bounds
  if (x >= 0 && x <= rect.width && y >= 0 && y <= rect.height) {
    mousePos.value = { x, y };
    isMouseInCanvas.value = true;
    draw();
  } else if (isMouseInCanvas.value) {
    isMouseInCanvas.value = false;
    mousePos.value = null;
    draw();
  }
}

function handleMouseLeave() {
  isMouseInCanvas.value = false;
  mousePos.value = null;
  draw();
}

onMounted(() => {
  handleResize();

  // Start animation loop
  animationId = requestAnimationFrame(animate);

  // Listen for mouse events at window level (overlay has pointer-events: none)
  window.addEventListener('mousemove', handleMouseMove);
  window.addEventListener('mouseleave', handleMouseLeave);
});

onUnmounted(() => {
  if (animationId !== null) {
    cancelAnimationFrame(animationId);
  }
  window.removeEventListener('mousemove', handleMouseMove);
  window.removeEventListener('mouseleave', handleMouseLeave);
});
</script>

<template>
  <div class="stimma-retouch-overlay-container">
    <canvas
      ref="overlayRef"
      class="stimma-retouch-overlay"
      :style="{
        width: `${canvasSize.width}px`,
        height: `${canvasSize.height}px`,
      }"
    />

    <!-- Floating selection toolbar -->
    <div
      v-if="showSelectionToolbar && toolbarPosition"
      class="stimma-selection-toolbar"
      :style="toolbarPosition"
    >
      <button
        class="stimma-selection-toolbar__btn"
        title="Invert selection"
        @click.stop="invertSelection"
      >
        <Icon name="invertSelection" :size="16" />
      </button>
      <button
        class="stimma-selection-toolbar__btn"
        title="Deselect"
        @click.stop="deselectSelection"
      >
        <Icon name="close" :size="16" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.stimma-retouch-overlay-container {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 10;
}

.stimma-retouch-overlay {
  position: absolute;
  top: 0;
  left: 0;
  pointer-events: none;
}

.stimma-selection-toolbar {
  position: absolute;
  display: flex;
  gap: 2px;
  padding: 4px;
  background-color: rgba(30, 30, 30, 0.9);
  border-radius: 8px;
  transform: translateX(-50%);
  pointer-events: auto;
  z-index: 100;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
}

.stimma-selection-toolbar__btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #fff;
  cursor: pointer;
  transition: background-color 0.15s;
}

.stimma-selection-toolbar__btn:hover {
  background-color: rgba(255, 255, 255, 0.15);
}

.stimma-selection-toolbar__btn:active {
  background-color: rgba(255, 255, 255, 0.25);
}
</style>
