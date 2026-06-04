import { ref, shallowRef, markRaw } from 'vue';
import type { Size, Point, Color } from '@/types/geometry';
import type { SelectionMode } from '@/types/editor';
import {
  createSelectionMask,
  fillRectSelection,
  fillEllipseSelection,
  fillLassoSelection,
  floodFillSelection,
  featherSelection,
  invertSelection as invertMask,
  clearSelection as clearMask,
  hasSelection as checkHasSelection,
  getSelectionBounds,
  getMarchingAntsPath,
  simplifyPath,
} from '../utils/selection';

// Selection shape types for smooth marching ants rendering
type SelectionShape =
  | { type: 'rect'; x: number; y: number; width: number; height: number }
  | { type: 'ellipse'; centerX: number; centerY: number; radiusX: number; radiusY: number }
  | { type: 'lasso'; points: Point[] }
  | { type: 'magnetic-lasso'; points: Point[] }
  | { type: 'pixels' }; // For magic wand and other pixel-based selections

// Base shapes before inversion (for smooth marching ants on inverted selections)
type BaseShape =
  | { type: 'rect'; x: number; y: number; width: number; height: number }
  | { type: 'ellipse'; centerX: number; centerY: number; radiusX: number; radiusY: number }
  | { type: 'lasso'; points: Point[] }
  | { type: 'magnetic-lasso'; points: Point[] };

/**
 * Composable for managing selection mask
 */
export function useSelection() {
  // Selection mask canvas
  const selectionCanvas = shallowRef<HTMLCanvasElement | null>(null);
  const selectionCtx = shallowRef<CanvasRenderingContext2D | null>(null);

  // Selection size
  const selectionSize = ref<Size | null>(null);

  // Active drawing state
  const isDrawing = ref(false);
  const drawingPoints = ref<Point[]>([]);
  const drawingStartPoint = ref<Point | null>(null);
  const drawingCurrentPoint = ref<Point | null>(null);

  // Marching ants paths (cached)
  const marchingAntsPaths = ref<Point[][]>([]);

  // Selection shapes for smooth marching ants rendering
  const selectionShapes = ref<SelectionShape[]>([]);

  // Track inverted state and original shapes for smooth marching ants
  const isInverted = ref(false);
  const baseShapesBeforeInvert = ref<BaseShape[]>([]);

  // Track feather radius for rendering rounded corners on marching ants
  const currentFeatherRadius = ref(0);

  // Animation offset for marching ants
  const antsOffset = ref(0);

  /**
   * Initialize or resize the selection mask
   */
  function initSelection(size: Size): void {
    if (
      selectionCanvas.value &&
      selectionSize.value?.width === size.width &&
      selectionSize.value?.height === size.height
    ) {
      return;
    }

    const canvas = createSelectionMask(size);
    const ctx = canvas.getContext('2d', { willReadFrequently: true });

    if (!ctx) {
      throw new Error('Failed to get selection canvas context');
    }

    // Copy existing selection if resizing
    if (selectionCanvas.value && selectionCtx.value) {
      ctx.drawImage(selectionCanvas.value, 0, 0);
    }

    selectionCanvas.value = canvas;
    selectionCtx.value = ctx;
    selectionSize.value = { ...size };

    // Reset inverted state and recalculate marching ants for new dimensions
    // The old shape coordinates may no longer be valid after resize
    isInverted.value = false;
    baseShapesBeforeInvert.value = [];
    selectionShapes.value = hasSelection() ? [{ type: 'pixels' }] : [];
    updateMarchingAnts();
  }

  /**
   * Clear the selection
   */
  function clearSelection(): void {
    if (!selectionCtx.value) return;
    clearMask(selectionCtx.value);
    marchingAntsPaths.value = [];
    selectionShapes.value = [];
    isInverted.value = false;
    baseShapesBeforeInvert.value = [];
    currentFeatherRadius.value = 0;
  }

  /**
   * Check if there's an active selection
   */
  function hasSelection(): boolean {
    if (!selectionCtx.value) return false;
    return checkHasSelection(selectionCtx.value);
  }

  /**
   * Get selection bounds
   */
  function getBounds() {
    if (!selectionCtx.value) return null;
    return getSelectionBounds(selectionCtx.value);
  }

  /**
   * Check if a point is inside the selection
   */
  function isPointInSelection(point: Point): boolean {
    if (!selectionCtx.value || !hasSelection()) return false;
    const x = Math.floor(point.x);
    const y = Math.floor(point.y);
    const { width, height } = selectionCtx.value.canvas;
    if (x < 0 || x >= width || y < 0 || y >= height) return false;
    const pixel = selectionCtx.value.getImageData(x, y, 1, 1).data;
    return pixel[3] > 0; // Check alpha channel
  }

  /**
   * Generate smooth path for ellipse shape (closed loop)
   */
  function generateEllipsePath(
    centerX: number,
    centerY: number,
    radiusX: number,
    radiusY: number,
    numPoints: number = 64
  ): Point[] {
    const points: Point[] = [];
    for (let i = 0; i < numPoints; i++) {
      const angle = (i / numPoints) * Math.PI * 2;
      points.push({
        x: centerX + Math.cos(angle) * radiusX,
        y: centerY + Math.sin(angle) * radiusY,
      });
    }
    // Close the loop by adding the first point at the end
    if (points.length > 0) {
      points.push({ ...points[0] });
    }
    return points;
  }

  /**
   * Generate path for rectangle shape (with optional rounded corners for feathering)
   * Returns a closed loop (last point equals first point)
   */
  function generateRectPath(x: number, y: number, width: number, height: number, cornerRadius: number = 0): Point[] {
    if (cornerRadius <= 0) {
      // Simple rectangle - 5 points forming a closed loop
      return [
        { x, y },
        { x: x + width, y },
        { x: x + width, y: y + height },
        { x, y: y + height },
        { x, y }, // Close the loop
      ];
    }

    // Clamp corner radius to half the smaller dimension
    const r = Math.min(cornerRadius, width / 2, height / 2);
    const points: Point[] = [];
    const segments = 8; // Points per corner arc

    // Top-left corner
    for (let i = 0; i <= segments; i++) {
      const angle = Math.PI + (Math.PI / 2) * (i / segments);
      points.push({
        x: x + r + Math.cos(angle) * r,
        y: y + r + Math.sin(angle) * r,
      });
    }

    // Top-right corner
    for (let i = 0; i <= segments; i++) {
      const angle = -Math.PI / 2 + (Math.PI / 2) * (i / segments);
      points.push({
        x: x + width - r + Math.cos(angle) * r,
        y: y + r + Math.sin(angle) * r,
      });
    }

    // Bottom-right corner
    for (let i = 0; i <= segments; i++) {
      const angle = 0 + (Math.PI / 2) * (i / segments);
      points.push({
        x: x + width - r + Math.cos(angle) * r,
        y: y + height - r + Math.sin(angle) * r,
      });
    }

    // Bottom-left corner
    for (let i = 0; i <= segments; i++) {
      const angle = Math.PI / 2 + (Math.PI / 2) * (i / segments);
      points.push({
        x: x + r + Math.cos(angle) * r,
        y: y + height - r + Math.sin(angle) * r,
      });
    }

    // Close the loop by adding the first point at the end
    if (points.length > 0) {
      points.push({ ...points[0] });
    }

    return points;
  }

  /**
   * Generate path for a base shape (used for inverted selections)
   * All paths are closed loops (last point equals first point)
   */
  function generateBaseShapePath(shape: BaseShape, featherRadius: number = 0): Point[] {
    if (shape.type === 'rect') {
      return generateRectPath(shape.x, shape.y, shape.width, shape.height, featherRadius);
    } else if (shape.type === 'ellipse') {
      return generateEllipsePath(shape.centerX, shape.centerY, shape.radiusX, shape.radiusY);
    } else if (shape.type === 'lasso' || shape.type === 'magnetic-lasso') {
      const simplified = simplifyPath(shape.points, 1.5);
      // Ensure the path closes
      if (simplified.length > 0) {
        simplified.push({ ...simplified[0] });
      }
      return simplified;
    }
    return [];
  }

  /**
   * Update marching ants paths from current selection
   */
  function updateMarchingAnts(): void {
    if (!selectionCtx.value || !hasSelection()) {
      marchingAntsPaths.value = [];
      return;
    }

    const paths: Point[][] = [];

    // Handle inverted selections with smooth paths
    const featherR = currentFeatherRadius.value;
    if (isInverted.value && baseShapesBeforeInvert.value.length > 0) {
      // Add outer boundary (image edge) - use selectionSize for correct dimensions after crop
      const width = selectionSize.value?.width ?? selectionCtx.value.canvas.width;
      const height = selectionSize.value?.height ?? selectionCtx.value.canvas.height;
      paths.push(generateRectPath(0, 0, width, height));

      // Add inner shapes (the "holes") using smooth geometric paths with feather radius
      for (const shape of baseShapesBeforeInvert.value) {
        paths.push(generateBaseShapePath(shape, featherR));
      }

      marchingAntsPaths.value = paths;
      return;
    }

    // If we have stored shapes, generate smooth paths from them
    if (selectionShapes.value.length > 0) {
      for (const shape of selectionShapes.value) {
        if (shape.type === 'rect') {
          // Use feather radius for rounded corners
          paths.push(generateRectPath(shape.x, shape.y, shape.width, shape.height, featherR));
        } else if (shape.type === 'ellipse') {
          // Ellipses are already smooth, feathering doesn't change the outline shape
          paths.push(generateEllipsePath(shape.centerX, shape.centerY, shape.radiusX, shape.radiusY));
        } else if (shape.type === 'lasso' || shape.type === 'magnetic-lasso') {
          // Simplify lasso points for smoother rendering (tolerance of 1.5 pixels)
          const simplified = simplifyPath(shape.points, 1.5);
          // Ensure the path closes by adding the first point at the end
          if (simplified.length > 0) {
            simplified.push({ ...simplified[0] });
          }
          paths.push(simplified);
        } else if (shape.type === 'pixels') {
          // Fall back to pixel tracing for pixel-based selections
          const pixelPaths = getMarchingAntsPath(selectionCtx.value!);
          paths.push(...pixelPaths.map((p) => simplifyPath(p, 2)));
        }
      }
      marchingAntsPaths.value = paths;
    } else {
      // Fallback to pixel tracing
      const pixelPaths = getMarchingAntsPath(selectionCtx.value);
      marchingAntsPaths.value = pixelPaths.map((p) => simplifyPath(p, 2));
    }
  }

  /**
   * Start rectangle selection
   * Note: Don't clear shapes here - preserve existing selection for combine modes
   * Shapes will be updated appropriately in finishRectSelection based on mode
   */
  function startRectSelection(point: Point): void {
    isDrawing.value = true;
    drawingStartPoint.value = { ...point };
    drawingCurrentPoint.value = { ...point };
  }

  /**
   * Constrain point to create square aspect ratio from start point
   */
  function constrainToSquare(start: Point, current: Point): Point {
    const dx = current.x - start.x;
    const dy = current.y - start.y;
    const size = Math.max(Math.abs(dx), Math.abs(dy));
    return {
      x: start.x + Math.sign(dx) * size,
      y: start.y + Math.sign(dy) * size,
    };
  }

  /**
   * Update rectangle selection while dragging
   * For combine modes (add/subtract/intersect), we only update the preview coordinates
   * The actual selection modification happens in finishRectSelection
   */
  function updateRectSelection(point: Point, mode: SelectionMode, constrain: boolean = false): void {
    if (!isDrawing.value || !drawingStartPoint.value || !selectionCtx.value) return;

    const start = drawingStartPoint.value;
    const effectivePoint = constrain ? constrainToSquare(start, point) : point;
    drawingCurrentPoint.value = { ...effectivePoint };

    // For 'new' mode only, update the canvas during drag for live preview
    // For combine modes, the blue overlay shows the preview and canvas is only modified on finish
    if (mode === 'new') {
      const x = Math.min(start.x, effectivePoint.x);
      const y = Math.min(start.y, effectivePoint.y);
      const width = Math.abs(effectivePoint.x - start.x);
      const height = Math.abs(effectivePoint.y - start.y);

      const { width: w, height: h } = selectionCtx.value.canvas;
      selectionCtx.value.clearRect(0, 0, w, h);
      fillRectSelection(selectionCtx.value, x, y, width, height, 'new');
    }
    // Don't update marching ants during drag - blue preview is shown instead
  }

  /**
   * Finish rectangle selection
   */
  function finishRectSelection(point: Point, mode: SelectionMode, constrain: boolean = false): void {
    if (!isDrawing.value || !drawingStartPoint.value || !selectionCtx.value) return;

    const start = drawingStartPoint.value;
    const effectivePoint = constrain ? constrainToSquare(start, point) : point;
    const x = Math.min(start.x, effectivePoint.x);
    const y = Math.min(start.y, effectivePoint.y);
    const width = Math.abs(effectivePoint.x - start.x);
    const height = Math.abs(effectivePoint.y - start.y);

    fillRectSelection(selectionCtx.value, x, y, width, height, mode);

    // Store shape for smooth marching ants
    if (mode === 'new') {
      selectionShapes.value = [{ type: 'rect', x, y, width, height }];
      isInverted.value = false;
      baseShapesBeforeInvert.value = [];
      currentFeatherRadius.value = 0;
    } else {
      // For add/subtract/intersect, use pixel tracing to get unified outline
      selectionShapes.value = [{ type: 'pixels' }];
      // Reset inverted state since we're modifying the selection
      isInverted.value = false;
      baseShapesBeforeInvert.value = [];
    }

    updateMarchingAnts();

    isDrawing.value = false;
    drawingStartPoint.value = null;
    drawingCurrentPoint.value = null;
  }

  /**
   * Start ellipse selection
   * Note: Don't clear shapes here - preserve existing selection for combine modes
   */
  function startEllipseSelection(point: Point): void {
    isDrawing.value = true;
    drawingStartPoint.value = { ...point };
    drawingCurrentPoint.value = { ...point };
  }

  /**
   * Update ellipse selection while dragging
   * For combine modes, we only update preview coordinates - canvas is modified on finish
   */
  function updateEllipseSelection(point: Point, mode: SelectionMode, constrain: boolean = false): void {
    if (!isDrawing.value || !drawingStartPoint.value || !selectionCtx.value) return;

    const start = drawingStartPoint.value;
    const effectivePoint = constrain ? constrainToSquare(start, point) : point;
    drawingCurrentPoint.value = { ...effectivePoint };

    // For 'new' mode only, update the canvas during drag for live preview
    if (mode === 'new') {
      const centerX = (start.x + effectivePoint.x) / 2;
      const centerY = (start.y + effectivePoint.y) / 2;
      const radiusX = Math.abs(effectivePoint.x - start.x) / 2;
      const radiusY = Math.abs(effectivePoint.y - start.y) / 2;

      const { width: w, height: h } = selectionCtx.value.canvas;
      selectionCtx.value.clearRect(0, 0, w, h);
      fillEllipseSelection(selectionCtx.value, centerX, centerY, radiusX, radiusY, 'new');
    }
    // Don't update marching ants during drag - blue preview is shown instead
  }

  /**
   * Finish ellipse selection
   */
  function finishEllipseSelection(point: Point, mode: SelectionMode, constrain: boolean = false): void {
    if (!isDrawing.value || !drawingStartPoint.value || !selectionCtx.value) return;

    const start = drawingStartPoint.value;
    const effectivePoint = constrain ? constrainToSquare(start, point) : point;
    const centerX = (start.x + effectivePoint.x) / 2;
    const centerY = (start.y + effectivePoint.y) / 2;
    const radiusX = Math.abs(effectivePoint.x - start.x) / 2;
    const radiusY = Math.abs(effectivePoint.y - start.y) / 2;

    fillEllipseSelection(selectionCtx.value, centerX, centerY, radiusX, radiusY, mode);

    // Store shape for smooth marching ants
    if (mode === 'new') {
      selectionShapes.value = [{ type: 'ellipse', centerX, centerY, radiusX, radiusY }];
      isInverted.value = false;
      baseShapesBeforeInvert.value = [];
      currentFeatherRadius.value = 0;
    } else {
      // For add/subtract/intersect, use pixel tracing to get unified outline
      selectionShapes.value = [{ type: 'pixels' }];
      isInverted.value = false;
      baseShapesBeforeInvert.value = [];
    }

    updateMarchingAnts();

    isDrawing.value = false;
    drawingStartPoint.value = null;
    drawingCurrentPoint.value = null;
  }

  /**
   * Start lasso selection
   * Note: Don't clear shapes here - preserve existing selection for combine modes
   */
  function startLassoSelection(point: Point): void {
    isDrawing.value = true;
    drawingPoints.value = [{ ...point }];
    drawingCurrentPoint.value = { ...point };
  }

  /**
   * Continue lasso selection
   */
  function continueLassoSelection(point: Point): void {
    if (!isDrawing.value) return;
    drawingPoints.value.push({ ...point });
    drawingCurrentPoint.value = { ...point };
  }

  /**
   * Finish lasso selection
   */
  function finishLassoSelection(mode: SelectionMode): void {
    if (!isDrawing.value || !selectionCtx.value) return;

    if (drawingPoints.value.length >= 3) {
      const points = [...drawingPoints.value];
      fillLassoSelection(selectionCtx.value, points, mode);

      // Store shape for smooth marching ants
      if (mode === 'new') {
        selectionShapes.value = [{ type: 'lasso', points }];
        isInverted.value = false;
        baseShapesBeforeInvert.value = [];
        currentFeatherRadius.value = 0;
      } else {
        // For add/subtract/intersect, use pixel tracing to get unified outline
        selectionShapes.value = [{ type: 'pixels' }];
        isInverted.value = false;
        baseShapesBeforeInvert.value = [];
      }

      updateMarchingAnts();
    }

    isDrawing.value = false;
    drawingPoints.value = [];
    drawingCurrentPoint.value = null;
  }

  /**
   * Create a magnetic lasso selection from pre-computed path points.
   * This is called by useMagneticLasso when the selection is finalized.
   */
  function createMagneticLassoSelection(points: Point[], mode: SelectionMode): void {
    if (!selectionCtx.value || points.length < 3) return;

    fillLassoSelection(selectionCtx.value, points, mode);

    // Store shape for smooth marching ants
    if (mode === 'new') {
      selectionShapes.value = [{ type: 'magnetic-lasso', points: [...points] }];
      isInverted.value = false;
      baseShapesBeforeInvert.value = [];
      currentFeatherRadius.value = 0;
    } else {
      // For add/subtract/intersect, use pixel tracing to get unified outline
      selectionShapes.value = [{ type: 'pixels' }];
      isInverted.value = false;
      baseShapesBeforeInvert.value = [];
    }

    updateMarchingAnts();
  }

  /**
   * Magic wand selection based on color similarity
   */
  function magicWandSelect(
    sourceCtx: CanvasRenderingContext2D,
    point: Point,
    tolerance: number,
    mode: SelectionMode
  ): void {
    if (!selectionCtx.value) return;

    // Reset inverted state and feather for new selections
    if (mode === 'new') {
      isInverted.value = false;
      baseShapesBeforeInvert.value = [];
      currentFeatherRadius.value = 0;
    }

    floodFillSelection(
      selectionCtx.value,
      sourceCtx,
      point.x,
      point.y,
      tolerance,
      mode
    );

    // Magic wand creates pixel-based selection
    selectionShapes.value = [{ type: 'pixels' }];
    updateMarchingAnts();
  }

  /**
   * Apply feather to current selection
   */
  function feather(radius: number): void {
    if (!selectionCtx.value || !hasSelection()) return;
    featherSelection(selectionCtx.value, radius);
    // Store feather radius for marching ants rendering (rounded corners)
    // Keep the original shapes - don't switch to 'pixels' which looks terrible
    currentFeatherRadius.value = radius;
    // Note: we don't reset isInverted - feathering an inverted selection should keep it inverted
    updateMarchingAnts();
  }

  /**
   * Invert the selection
   */
  function invert(): void {
    if (!selectionCtx.value) return;
    invertMask(selectionCtx.value);

    // Toggle inverted state
    isInverted.value = !isInverted.value;

    if (isInverted.value) {
      // Save current shapes as base shapes for smooth marching ants
      // Only save geometric shapes (rect, ellipse, lasso, magnetic-lasso), not pixel-based
      const geometricShapes: BaseShape[] = [];
      for (const shape of selectionShapes.value) {
        if (shape.type === 'rect' || shape.type === 'ellipse' || shape.type === 'lasso' || shape.type === 'magnetic-lasso') {
          geometricShapes.push(shape as BaseShape);
        }
      }
      baseShapesBeforeInvert.value = geometricShapes;

      // If we have geometric shapes, we'll use them for smooth rendering
      // Otherwise fall back to pixel tracing
      if (geometricShapes.length === 0) {
        selectionShapes.value = [{ type: 'pixels' }];
      }
    } else {
      // Inverting back - restore original shapes if we had them
      if (baseShapesBeforeInvert.value.length > 0) {
        selectionShapes.value = baseShapesBeforeInvert.value.map(s => ({ ...s })) as SelectionShape[];
      }
      baseShapesBeforeInvert.value = [];
    }

    updateMarchingAnts();
  }

  /**
   * Fill selection with color on a target canvas
   */
  function fillWithColor(
    targetCtx: CanvasRenderingContext2D,
    color: Color
  ): void {
    if (!selectionCtx.value || !hasSelection()) return;

    // Convert color to CSS string
    let colorStr: string;
    if (typeof color === 'string') {
      colorStr = color;
    } else {
      const { r, g, b, a = 1 } = color;
      colorStr = `rgba(${r}, ${g}, ${b}, ${a})`;
    }

    // Save context state
    targetCtx.save();

    // Create clipping path from selection mask
    targetCtx.globalCompositeOperation = 'source-over';

    // Draw the fill color using the selection as a mask
    const tempCanvas = document.createElement('canvas');
    tempCanvas.width = targetCtx.canvas.width;
    tempCanvas.height = targetCtx.canvas.height;
    const tempCtx = tempCanvas.getContext('2d', { willReadFrequently: true })!;

    // Fill with color
    tempCtx.fillStyle = colorStr;
    tempCtx.fillRect(0, 0, tempCanvas.width, tempCanvas.height);

    // Use selection as mask
    tempCtx.globalCompositeOperation = 'destination-in';
    tempCtx.drawImage(selectionCanvas.value!, 0, 0);

    // Draw to target
    targetCtx.drawImage(tempCanvas, 0, 0);

    targetCtx.restore();
  }

  /**
   * Clear (delete) pixels in selection on a target canvas
   * If bgColor is provided and not fully transparent, fills with that color
   * Otherwise makes pixels transparent
   */
  function clearPixels(
    targetCtx: CanvasRenderingContext2D,
    bgColor?: { r: number; g: number; b: number; a: number }
  ): void {
    if (!selectionCtx.value || !hasSelection()) return;

    // If background color is transparent or not provided, just erase to transparent
    if (!bgColor || bgColor.a === 0) {
      targetCtx.save();
      targetCtx.globalCompositeOperation = 'destination-out';
      targetCtx.drawImage(selectionCanvas.value!, 0, 0);
      targetCtx.restore();
      return;
    }

    // Fill selected area with background color
    const width = targetCtx.canvas.width;
    const height = targetCtx.canvas.height;

    // Create temp canvas for masked fill
    const tempCanvas = document.createElement('canvas');
    tempCanvas.width = width;
    tempCanvas.height = height;
    const tempCtx = tempCanvas.getContext('2d', { willReadFrequently: true })!;

    // First, erase the selected area (make transparent)
    targetCtx.save();
    targetCtx.globalCompositeOperation = 'destination-out';
    targetCtx.drawImage(selectionCanvas.value!, 0, 0);
    targetCtx.restore();

    // Then fill with background color using selection as mask
    const colorStr = `rgba(${bgColor.r}, ${bgColor.g}, ${bgColor.b}, ${bgColor.a})`;
    tempCtx.fillStyle = colorStr;
    tempCtx.fillRect(0, 0, width, height);

    // Use selection as mask
    tempCtx.globalCompositeOperation = 'destination-in';
    tempCtx.drawImage(selectionCanvas.value!, 0, 0);

    // Draw to target (behind existing content if any)
    targetCtx.save();
    targetCtx.globalCompositeOperation = 'destination-over';
    targetCtx.drawImage(tempCanvas, 0, 0);
    targetCtx.restore();
  }

  /**
   * Load selection from data URL
   */
  async function loadFromDataUrl(dataUrl: string): Promise<void> {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        if (selectionCtx.value) {
          selectionCtx.value.clearRect(0, 0, img.width, img.height);
          selectionCtx.value.drawImage(img, 0, 0);
          updateMarchingAnts();
        }
        resolve();
      };
      img.onerror = reject;
      img.src = dataUrl;
    });
  }

  /**
   * Export selection to data URL
   */
  function toDataUrl(): string | null {
    if (!selectionCanvas.value) return null;
    return selectionCanvas.value.toDataURL('image/png');
  }

  /**
   * Get selection mask for external use
   */
  function getSelectionMask(): HTMLCanvasElement | null {
    return selectionCanvas.value;
  }

  /**
   * Create a fast canvas snapshot for history (~1ms vs 100-300ms for PNG)
   */
  function toSnapshot(): HTMLCanvasElement | null {
    if (!selectionCanvas.value || !selectionSize.value) return null;
    const snap = document.createElement('canvas');
    snap.width = selectionSize.value.width;
    snap.height = selectionSize.value.height;
    const ctx = snap.getContext('2d');
    if (ctx) {
      ctx.drawImage(selectionCanvas.value, 0, 0);
    }
    return markRaw(snap);
  }

  /**
   * Restore from a canvas snapshot (~1ms)
   */
  function loadFromSnapshot(snapshot: HTMLCanvasElement): void {
    if (!selectionCtx.value || !selectionSize.value) return;
    selectionCtx.value.clearRect(0, 0, selectionSize.value.width, selectionSize.value.height);
    selectionCtx.value.drawImage(snapshot, 0, 0);
    updateMarchingAnts();
  }

  return {
    selectionCanvas,
    selectionCtx,
    selectionSize,
    isDrawing,
    drawingPoints,
    drawingStartPoint,
    drawingCurrentPoint,
    marchingAntsPaths,
    antsOffset,
    initSelection,
    clearSelection,
    hasSelection,
    getBounds,
    isPointInSelection,
    updateMarchingAnts,
    startRectSelection,
    updateRectSelection,
    finishRectSelection,
    startEllipseSelection,
    updateEllipseSelection,
    finishEllipseSelection,
    startLassoSelection,
    continueLassoSelection,
    finishLassoSelection,
    createMagneticLassoSelection,
    magicWandSelect,
    feather,
    invert,
    fillWithColor,
    clearPixels,
    loadFromDataUrl,
    toDataUrl,
    toSnapshot,
    loadFromSnapshot,
    getSelectionMask,
  };
}
