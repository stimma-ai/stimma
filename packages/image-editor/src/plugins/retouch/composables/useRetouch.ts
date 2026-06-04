import { ref, computed, type Ref, type ComputedRef } from 'vue';
import type { Point, Size, Color } from '@/types/geometry';
import type { ViewTransform, RetouchTool, SelectionMode, DodgeBurnRange, SpongeMode } from '@/types/editor';
import type { BrushSettings } from '@/types/shapes';
import { useRetouchLayer } from './useRetouchLayer';
import { useSelection } from './useSelection';
import { useMagneticLasso } from './useMagneticLasso';
import { isEditorDebugEnabled, logEditorDebug } from '@/utils/editorDebug';

interface RetouchState {
  retouchTool: RetouchTool | null;
  retouchBrushSettings: BrushSettings;
  retouchCloneSource: Point | null;
  retouchCloneOffset: Point | null;
  selectionFeather: number;
  wandTolerance: number;
  selectionMode: SelectionMode;
  dodgeBurnExposure: number;
  dodgeBurnRange: DodgeBurnRange;
  spongeFlow: number;
  spongeMode: SpongeMode;
  blurSharpenStrength: number;
  patchBlendWidth: number;
  retouchForegroundColor: { r: number; g: number; b: number; a: number };
  retouchBackgroundColor: { r: number; g: number; b: number; a: number };
  // Magnetic lasso settings
  magneticLassoWidth: number;
  magneticLassoContrast: number;
  // Image transforms needed for coordinate conversion
  rotation: number;
  rotation90: number;
  flipX: boolean;
  flipY: boolean;
}

/**
 * Composable for handling all retouch tool interactions
 */
export function useRetouch(
  canvasRef: Ref<HTMLCanvasElement | null>,
  viewTransform: Ref<ViewTransform>,
  imageSize: ComputedRef<Size | null>,
  canvasSize: Ref<Size>,
  getState: () => RetouchState,
  getSourceCanvas: () => HTMLCanvasElement | null,
  updateState: (partial: Partial<RetouchState>) => void,
  pushHistory: (action: string) => void,
  requestRender: () => void,
  requestFullRender: () => void
) {
  // Retouch layer for pixel edits
  const retouchLayer = useRetouchLayer();

  // Selection mask
  const selection = useSelection();

  // Magnetic lasso
  const magneticLasso = useMagneticLasso();
  const debugEnabled = isEditorDebugEnabled();

  function debugLog(event: string, details: Record<string, unknown> = {}) {
    if (!debugEnabled) return;
    logEditorDebug('Retouch', event, details);
  }

  // Interaction state
  const isDrawing = ref(false);
  const isAltPressed = ref(false);
  const isShiftPressed = ref(false);
  const lastPoint = ref<Point | null>(null);
  const lastSelectionPoint = ref<Point | null>(null); // Track mouse pos for selection constraint updates

  // RAF-coalesced mouse events: buffer latest event, process at most once per frame
  let pendingMouseMoveEvent: MouseEvent | null = null;
  let mouseMoveRafId: number | null = null;

  // Cached source canvas during active stroke (avoids re-fetching on every mouse move)
  let cachedStrokeSourceCanvas: HTMLCanvasElement | null = null;

  // Cached state during active stroke (avoids 20+ Vue reactive reads per mouse move)
  let cachedStrokeState: RetouchState | null = null;

  // Patch tool state
  const isPatchDragging = ref(false);
  const isPatchDrawing = ref(false);  // Drawing lasso selection for patch tool
  const patchDragStart = ref<Point | null>(null);
  const patchDragCurrent = ref<Point | null>(null);
  const patchDrawingPoints = ref<Point[]>([]);  // Lasso points when drawing selection

  // Tools that use the circular brush cursor overlay
  const brushCursorTools = new Set<RetouchTool>([
    'clone', 'paint', 'spot-heal', 'dodge', 'burn', 'sponge', 'blur-brush', 'sharpen-brush'
  ]);

  // Cursor style
  const cursorStyle = computed(() => {
    const state = getState();
    const tool = state.retouchTool;

    if (!tool) return 'default';

    // Selection tools
    if (tool === 'marquee-rect' || tool === 'marquee-ellipse') {
      return 'crosshair';
    }
    if (tool === 'lasso') {
      return 'crosshair';
    }
    if (tool === 'magnetic-lasso') {
      return 'crosshair';
    }

    // Patch tool: crosshair when drawing selection, move when selection exists
    if (tool === 'patch') {
      if (isPatchDrawing.value) {
        return 'crosshair';
      }
      if (selection.hasSelection()) {
        return isPatchDragging.value ? 'grabbing' : 'move';
      }
      return 'crosshair';  // Ready to draw selection
    }

    // Brush-based tools: hide native cursor, use overlay circle
    if (brushCursorTools.has(tool)) {
      // Special case: clone tool with Alt pressed shows crosshair for setting source
      if (tool === 'clone' && isAltPressed.value) {
        return 'crosshair';
      }
      // Clone tool without source shows not-allowed
      if (tool === 'clone' && !state.retouchCloneSource) {
        return 'not-allowed';
      }
      // Hide cursor - overlay will show brush circle
      return 'none';
    }

    return 'crosshair';
  });

  /**
   * Get selection mode from UI state and keyboard modifiers (Photoshop-style)
   * Keyboard modifiers override the UI selection mode:
   * - Shift: Add to selection
   * - Alt/Option: Subtract from selection
   * - Shift + Alt: Intersect with selection
   * If no modifier is pressed, use the UI-selected mode
   */
  function getSelectionModeFromEvent(event: MouseEvent): SelectionMode {
    // Keyboard modifiers override UI selection mode
    if (event.shiftKey && event.altKey) {
      return 'intersect';
    } else if (event.altKey) {
      return 'subtract';
    } else if (event.shiftKey) {
      return 'add';
    }
    // Use UI-selected mode when no modifiers
    return getState().selectionMode;
  }

  /**
   * Convert canvas coordinates to image coordinates
   * Accounts for view transform (zoom, pan) AND image transforms (rotation, flip)
   */
  function canvasToImage(canvasPoint: Point): Point {
    const size = imageSize.value;
    if (!size) return { x: 0, y: 0 };

    const state = getState();
    const { zoom, panX, panY, rotation: viewRotation } = viewTransform.value;
    const { rotation: imageRotation, rotation90, flipX, flipY } = state;

    // Step 1: Invert view transform
    // Subtract canvas center + pan
    const canvasCenterX = canvasSize.value.width / 2 + panX;
    const canvasCenterY = canvasSize.value.height / 2 + panY;

    let x = canvasPoint.x - canvasCenterX;
    let y = canvasPoint.y - canvasCenterY;

    // Invert view rotation
    if (viewRotation !== 0) {
      const cos = Math.cos(-viewRotation);
      const sin = Math.sin(-viewRotation);
      const rx = x * cos - y * sin;
      const ry = x * sin + y * cos;
      x = rx;
      y = ry;
    }

    // Invert scale (divide by zoom)
    x /= zoom;
    y /= zoom;

    // Now we're at display-space coords relative to image center
    // Step 2: Invert image transforms (applied in reverse order of render)

    // Invert flips (flip is its own inverse)
    if (flipX) x = -x;
    if (flipY) y = -y;

    // Invert rotations (rotation90 then imageRotation, combined)
    const totalRotation = imageRotation + rotation90 * Math.PI / 2;
    if (totalRotation !== 0) {
      const cos = Math.cos(-totalRotation);
      const sin = Math.sin(-totalRotation);
      const rx = x * cos - y * sin;
      const ry = x * sin + y * cos;
      x = rx;
      y = ry;
    }

    // Translate from center-relative to absolute image coords
    x += size.width / 2;
    y += size.height / 2;

    return { x, y };
  }

  /**
   * Get mouse position from event
   */
  function getMousePos(event: MouseEvent): Point {
    const canvas = canvasRef.value;
    if (!canvas) return { x: 0, y: 0 };

    const rect = canvas.getBoundingClientRect();
    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
  }

  /**
   * Initialize layers when image loads
   */
  function initLayers(size: Size): void {
    retouchLayer.initLayer(size);
    selection.initSelection(size);
    // Invalidate magnetic lasso gradient map - will be recomputed when tool is used
    magneticLasso.invalidate();
  }

  /**
   * Initialize magnetic lasso when needed
   */
  function initMagneticLasso(): void {
    const sourceCanvas = getSourceCanvas();
    if (sourceCanvas && !magneticLasso.isReady()) {
      magneticLasso.initialize(sourceCanvas);
      const state = getState();
      magneticLasso.updateConfig({
        searchRadius: state.magneticLassoWidth,
        edgeSensitivity: state.magneticLassoContrast,
      });
    }
  }

  /**
   * Handle mouse down
   */
  function handleMouseDown(event: MouseEvent): void {
    const state = getState();
    const tool = state.retouchTool;
    if (!tool) return;

    const canvasPoint = getMousePos(event);
    const imagePoint = canvasToImage(canvasPoint);
    const sourceCanvas = getSourceCanvas();

    // Cache source canvas and state at stroke start to avoid re-fetching on every mouse move
    cachedStrokeSourceCanvas = sourceCanvas;
    cachedStrokeState = state;

    // Pass selection mask to retouch layer only if there's an active selection
    // When no selection, entire image is paintable
    retouchLayer.setSelectionMask(selection.hasSelection() ? selection.selectionCtx.value : null);

    // Check for Alt key (for clone stamp source)
    isAltPressed.value = event.altKey;

    if (tool === 'clone') {
      if (event.altKey) {
        // Set clone source
        updateState({
          retouchCloneSource: { ...imagePoint },
          retouchCloneOffset: null,
        });
        return;
      }

      if (!state.retouchCloneSource) {
        return; // No source set
      }

      // Start cloning
      isDrawing.value = true;
      retouchLayer.startStroke();

      // Set offset if not already set
      if (!state.retouchCloneOffset) {
        updateState({
          retouchCloneOffset: {
            x: state.retouchCloneSource.x - imagePoint.x,
            y: state.retouchCloneSource.y - imagePoint.y,
          },
        });
        retouchLayer.setCloneSource(
          sourceCanvas!,
          state.retouchCloneSource,
          imagePoint
        );
      }

      if (sourceCanvas) {
        retouchLayer.applyCloneStamp(
          sourceCanvas,
          imagePoint,
          state.retouchBrushSettings
        );
        requestRender();
      }
      lastPoint.value = imagePoint;
    } else if (tool === 'paint') {
      isDrawing.value = true;
      retouchLayer.startStroke();
      retouchLayer.applyPaintBrush(
        imagePoint,
        state.retouchBrushSettings,
        state.retouchForegroundColor
      );
      requestRender();
      lastPoint.value = imagePoint;
    } else if (tool === 'fill') {
      // Fill the selection with foreground color (or entire canvas if no selection)
      const ctx = retouchLayer.retouchCtx.value;
      if (ctx) {
        if (selection.hasSelection()) {
          selection.fillWithColor(ctx, state.retouchForegroundColor);
        } else {
          // No selection - fill entire canvas
          ctx.save();
          ctx.fillStyle = `rgba(${state.retouchForegroundColor.r}, ${state.retouchForegroundColor.g}, ${state.retouchForegroundColor.b}, ${state.retouchForegroundColor.a})`;
          ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height);
          ctx.restore();
        }
        requestFullRender();
        pushHistoryWithSync('Fill');
      }
    } else if (tool === 'spot-heal') {
      if (sourceCanvas) {
        retouchLayer.applySpotHeal(
          sourceCanvas,
          imagePoint,
          state.retouchBrushSettings.size
        );
        requestFullRender();
        pushHistoryWithSync('Spot heal');
      }
    } else if (tool === 'dodge' || tool === 'burn') {
      isDrawing.value = true;
      retouchLayer.startStroke();
      if (sourceCanvas) {
        retouchLayer.applyDodgeBurn(
          sourceCanvas,
          imagePoint,
          state.retouchBrushSettings,
          state.dodgeBurnExposure,
          state.dodgeBurnRange,
          tool === 'dodge'
        );
        requestRender();
      }
      lastPoint.value = imagePoint;
    } else if (tool === 'sponge') {
      isDrawing.value = true;
      retouchLayer.startStroke();
      if (sourceCanvas) {
        retouchLayer.applySaturationBrush(
          sourceCanvas,
          imagePoint,
          state.retouchBrushSettings,
          state.spongeFlow,
          state.spongeMode === 'saturate'
        );
        requestRender();
      }
      lastPoint.value = imagePoint;
    } else if (tool === 'blur-brush' || tool === 'sharpen-brush') {
      isDrawing.value = true;
      retouchLayer.startStroke();
      if (sourceCanvas) {
        if (tool === 'blur-brush') {
          retouchLayer.applyBlurBrush(
            sourceCanvas,
            imagePoint,
            state.retouchBrushSettings,
            state.blurSharpenStrength
          );
        } else {
          retouchLayer.applySharpenBrush(
            sourceCanvas,
            imagePoint,
            state.retouchBrushSettings,
            state.blurSharpenStrength
          );
        }
        requestRender();
      }
      lastPoint.value = imagePoint;
    } else if (tool === 'marquee-rect') {
      // In 'new' mode clicking outside starts a new selection (clearing old one)
      // For add/subtract/intersect, we want to combine selections
      if (state.selectionMode === 'new' && selection.hasSelection() && !selection.isPointInSelection(imagePoint)) {
        selection.clearSelection();
        // Don't return - continue to start new selection immediately
      }
      selection.startRectSelection(imagePoint);
    } else if (tool === 'marquee-ellipse') {
      // In 'new' mode clicking outside starts a new selection (clearing old one)
      if (state.selectionMode === 'new' && selection.hasSelection() && !selection.isPointInSelection(imagePoint)) {
        selection.clearSelection();
        // Don't return - continue to start new selection immediately
      }
      selection.startEllipseSelection(imagePoint);
    } else if (tool === 'lasso') {
      // In 'new' mode clicking outside starts a new selection (clearing old one)
      if (state.selectionMode === 'new' && selection.hasSelection() && !selection.isPointInSelection(imagePoint)) {
        selection.clearSelection();
        // Don't return - continue to start new selection immediately
      }
      selection.startLassoSelection(imagePoint);
    } else if (tool === 'magnetic-lasso') {
      // Initialize magnetic lasso if not ready
      const sourceCanvas = getSourceCanvas();
      if (sourceCanvas && !magneticLasso.isReady()) {
        magneticLasso.initialize(sourceCanvas);
        // Update config from state
        const state = getState();
        magneticLasso.updateConfig({
          searchRadius: state.magneticLassoWidth,
          edgeSensitivity: state.magneticLassoContrast,
        });
      }

      // Place anchor - this starts the selection or adds a new anchor
      const closed = magneticLasso.placeAnchor(imagePoint);
      if (closed) {
        // Selection was closed - create the selection mask
        finishMagneticLassoSelection();
      }
      requestRender();
    } else if (tool === 'patch') {
      // Patch tool has its own lasso selection built-in (like Photoshop)
      if (selection.hasSelection()) {
        // If clicking inside selection, start drag
        if (selection.isPointInSelection(imagePoint)) {
          isPatchDragging.value = true;
          patchDragStart.value = { ...imagePoint };
          patchDragCurrent.value = { ...imagePoint };
          return;
        }
        // Clicking outside - clear and start new selection
        selection.clearSelection();
      }
      // Start drawing lasso selection
      isPatchDrawing.value = true;
      patchDrawingPoints.value = [{ ...imagePoint }];
    }
  }

  /**
   * Handle mouse move (RAF-coalesced: buffers latest event, processes at most once per frame)
   */
  function handleMouseMove(event: MouseEvent): void {
    // Buffer the latest event
    pendingMouseMoveEvent = event;

    // Schedule processing on next animation frame if not already scheduled
    if (mouseMoveRafId === null) {
      mouseMoveRafId = requestAnimationFrame(() => {
        mouseMoveRafId = null;
        const evt = pendingMouseMoveEvent;
        if (!evt) return;
        pendingMouseMoveEvent = null;
        processMouseMove(evt);
      });
    }
  }

  /**
   * Process a mouse move event (called at most once per animation frame)
   */
  function processMouseMove(event: MouseEvent): void {
    // Use cached state during active stroke to avoid 20+ Vue reactive property reads
    const state = (isDrawing.value && cachedStrokeState) ? cachedStrokeState : getState();
    const tool = state.retouchTool;
    if (!tool) return;

    const canvasPoint = getMousePos(event);
    const imagePoint = canvasToImage(canvasPoint);
    // Use cached source canvas during active stroke, fall back to fresh fetch
    const sourceCanvas = isDrawing.value ? cachedStrokeSourceCanvas : getSourceCanvas();

    if (tool === 'clone' && isDrawing.value && sourceCanvas) {
      retouchLayer.applyCloneStamp(
        sourceCanvas,
        imagePoint,
        state.retouchBrushSettings
      );
      requestRender();
      lastPoint.value = imagePoint;
    } else if (tool === 'paint' && isDrawing.value) {
      retouchLayer.applyPaintBrush(
        imagePoint,
        state.retouchBrushSettings,
        state.retouchForegroundColor
      );
      requestRender();
      lastPoint.value = imagePoint;
    } else if ((tool === 'dodge' || tool === 'burn') && isDrawing.value && sourceCanvas) {
      retouchLayer.applyDodgeBurn(
        sourceCanvas,
        imagePoint,
        state.retouchBrushSettings,
        state.dodgeBurnExposure,
        state.dodgeBurnRange,
        tool === 'dodge'
      );
      requestRender();
      lastPoint.value = imagePoint;
    } else if (tool === 'sponge' && isDrawing.value && sourceCanvas) {
      retouchLayer.applySaturationBrush(
        sourceCanvas,
        imagePoint,
        state.retouchBrushSettings,
        state.spongeFlow,
        state.spongeMode === 'saturate'
      );
      requestRender();
      lastPoint.value = imagePoint;
    } else if ((tool === 'blur-brush' || tool === 'sharpen-brush') && isDrawing.value && sourceCanvas) {
      if (tool === 'blur-brush') {
        retouchLayer.applyBlurBrush(
          sourceCanvas,
          imagePoint,
          state.retouchBrushSettings,
          state.blurSharpenStrength
        );
      } else {
        retouchLayer.applySharpenBrush(
          sourceCanvas,
          imagePoint,
          state.retouchBrushSettings,
          state.blurSharpenStrength
        );
      }
      requestRender();
      lastPoint.value = imagePoint;
    } else if (tool === 'marquee-rect' && selection.isDrawing.value) {
      isShiftPressed.value = event.shiftKey;
      lastSelectionPoint.value = imagePoint;
      const selectionMode = getSelectionModeFromEvent(event);
      selection.updateRectSelection(imagePoint, selectionMode, event.shiftKey);
    } else if (tool === 'marquee-ellipse' && selection.isDrawing.value) {
      isShiftPressed.value = event.shiftKey;
      lastSelectionPoint.value = imagePoint;
      const selectionMode = getSelectionModeFromEvent(event);
      selection.updateEllipseSelection(imagePoint, selectionMode, event.shiftKey);
    } else if (tool === 'lasso' && selection.isDrawing.value) {
      selection.continueLassoSelection(imagePoint);
    } else if (tool === 'magnetic-lasso' && magneticLasso.isActive.value) {
      // Update preview path to cursor position
      magneticLasso.updatePreview(imagePoint);
      requestRender();
    } else if (tool === 'patch') {
      if (isPatchDrawing.value) {
        // Continue drawing lasso selection for patch tool
        patchDrawingPoints.value.push({ ...imagePoint });
        requestRender(); // Trigger overlay redraw for preview
      } else if (isPatchDragging.value) {
        patchDragCurrent.value = { ...imagePoint };
        requestRender(); // Trigger overlay redraw
      }
    }
  }

  /**
   * Handle mouse up
   */
  function handleMouseUp(event: MouseEvent): void {
    const state = getState();
    const tool = state.retouchTool;

    const canvasPoint = getMousePos(event);
    const imagePoint = canvasToImage(canvasPoint);

    if (tool === 'clone' && isDrawing.value) {
      retouchLayer.endStroke();
      pushHistoryWithSync('Clone stamp');
    } else if (tool === 'paint' && isDrawing.value) {
      retouchLayer.endStroke();
      pushHistoryWithSync('Paint');
    } else if ((tool === 'dodge' || tool === 'burn') && isDrawing.value) {
      retouchLayer.endStroke();
      pushHistoryWithSync(tool === 'dodge' ? 'Dodge' : 'Burn');
    } else if (tool === 'sponge' && isDrawing.value) {
      retouchLayer.endStroke();
      pushHistoryWithSync('Sponge');
    } else if ((tool === 'blur-brush' || tool === 'sharpen-brush') && isDrawing.value) {
      retouchLayer.endStroke();
      pushHistoryWithSync(tool === 'blur-brush' ? 'Blur brush' : 'Sharpen brush');
    } else if (tool === 'marquee-rect' && selection.isDrawing.value) {
      const selectionMode = getSelectionModeFromEvent(event);
      selection.finishRectSelection(imagePoint, selectionMode, event.shiftKey);
      lastSelectionPoint.value = null;
      // Auto-apply feather if radius > 0 (Photoshop-style)
      const featherRadius = state.selectionFeather;
      if (featherRadius > 0 && selection.hasSelection()) {
        selection.feather(featherRadius);
      }
      pushHistoryWithSync('Rectangle selection');
    } else if (tool === 'marquee-ellipse' && selection.isDrawing.value) {
      const selectionMode = getSelectionModeFromEvent(event);
      selection.finishEllipseSelection(imagePoint, selectionMode, event.shiftKey);
      lastSelectionPoint.value = null;
      // Auto-apply feather if radius > 0 (Photoshop-style)
      const featherRadius = state.selectionFeather;
      if (featherRadius > 0 && selection.hasSelection()) {
        selection.feather(featherRadius);
      }
      pushHistoryWithSync('Ellipse selection');
    } else if (tool === 'lasso' && selection.isDrawing.value) {
      const selectionMode = getSelectionModeFromEvent(event);
      selection.finishLassoSelection(selectionMode);
      // Auto-apply feather if radius > 0 (Photoshop-style)
      const featherRadius = state.selectionFeather;
      if (featherRadius > 0 && selection.hasSelection()) {
        selection.feather(featherRadius);
      }
      pushHistoryWithSync('Lasso selection');
    } else if (tool === 'patch') {
      if (isPatchDrawing.value) {
        // Finish drawing lasso selection for patch tool
        const points = patchDrawingPoints.value;
        if (points.length >= 3) {
          // Create the lasso selection directly
          selection.startLassoSelection(points[0]);
          for (let i = 1; i < points.length; i++) {
            selection.continueLassoSelection(points[i]);
          }
          selection.finishLassoSelection('new');

          // Auto-apply feather if radius > 0
          const featherRadius = state.selectionFeather;
          if (featherRadius > 0 && selection.hasSelection()) {
            selection.feather(featherRadius);
          }
        }

        // Reset drawing state
        isPatchDrawing.value = false;
        patchDrawingPoints.value = [];
        requestRender();
      } else if (isPatchDragging.value) {
        // Apply patch if drag distance is significant
        const start = patchDragStart.value;
        const current = patchDragCurrent.value;
        const patchSourceCanvas = getSourceCanvas();
        if (start && current && patchSourceCanvas) {
          const dx = current.x - start.x;
          const dy = current.y - start.y;
          const dragDistance = Math.sqrt(dx * dx + dy * dy);

          // Only apply if dragged more than 2 pixels (threshold to avoid accidental clicks)
          if (dragDistance > 2) {
            const bounds = selection.getBounds();
            if (bounds) {
              // Offset is from destination to source (source = dest + offset)
              // User drags FROM destination TO source, so offset is (current - start)
              const offset = { x: dx, y: dy };

              // Pass the selection mask to retouch layer
              retouchLayer.setSelectionMask(selection.selectionCtx.value);

              // Apply the patch with blend width for softer edges
              retouchLayer.applyPatchTool(patchSourceCanvas, offset, bounds, state.patchBlendWidth);

              // Clear selection after applying patch (ready for new patch operation)
              selection.clearSelection();

              requestFullRender();
              pushHistoryWithSync('Patch');
            }
          }
        }

        // Reset drag state
        isPatchDragging.value = false;
        patchDragStart.value = null;
        patchDragCurrent.value = null;
      }
    }

    isDrawing.value = false;
    lastPoint.value = null;
    cachedStrokeSourceCanvas = null;
    cachedStrokeState = null;
  }

  /**
   * Finish magnetic lasso selection and create the selection mask
   */
  function finishMagneticLassoSelection(): void {
    const points = magneticLasso.getAllPoints();
    if (points.length >= 3) {
      const state = getState();
      const selectionMode = state.selectionMode;
      selection.createMagneticLassoSelection(points, selectionMode);

      // Auto-apply feather if radius > 0
      const featherRadius = state.selectionFeather;
      if (featherRadius > 0 && selection.hasSelection()) {
        selection.feather(featherRadius);
      }

      pushHistoryWithSync('Magnetic lasso selection');
    }

    // Reset magnetic lasso state (anchors and path segments cleared)
    magneticLasso.cancel();
    requestRender();
  }

  /**
   * Handle key down (for Alt/Shift key tracking)
   */
  function handleKeyDown(event: KeyboardEvent): void {
    const state = getState();
    const tool = state.retouchTool;

    if (event.key === 'Alt') {
      isAltPressed.value = true;
    }
    if (event.key === 'Shift') {
      isShiftPressed.value = true;
      // Update selection constraint immediately if drawing
      updateSelectionConstraint(true);
    }

    // Magnetic lasso keyboard shortcuts
    if (tool === 'magnetic-lasso' && magneticLasso.isActive.value) {
      if (event.key === 'Backspace' || event.key === 'Delete') {
        // Remove last anchor
        event.preventDefault();
        magneticLasso.removeLastAnchor();
        requestRender();
      } else if (event.key === 'Enter') {
        // Close selection
        event.preventDefault();
        const points = magneticLasso.closeSelection();
        if (points.length >= 3) {
          const selectionMode = state.selectionMode;
          selection.createMagneticLassoSelection(points, selectionMode);

          // Auto-apply feather if radius > 0
          const featherRadius = state.selectionFeather;
          if (featherRadius > 0 && selection.hasSelection()) {
            selection.feather(featherRadius);
          }

          pushHistoryWithSync('Magnetic lasso selection');
        }
        requestRender();
      } else if (event.key === 'Escape') {
        // Cancel selection
        event.preventDefault();
        magneticLasso.cancel();
        requestRender();
      }
    }
  }

  /**
   * Handle key up
   */
  function handleKeyUp(event: KeyboardEvent): void {
    if (event.key === 'Alt') {
      isAltPressed.value = false;
    }
    if (event.key === 'Shift') {
      isShiftPressed.value = false;
      // Update selection constraint immediately if drawing
      updateSelectionConstraint(false);
    }
  }

  /**
   * Update selection constraint when Shift key changes during drawing
   */
  function updateSelectionConstraint(constrain: boolean): void {
    const state = getState();
    const tool = state.retouchTool;
    const point = lastSelectionPoint.value;

    if (!point || !selection.isDrawing.value) return;

    // Determine selection mode based on current key state
    const selectionMode = isShiftPressed.value && isAltPressed.value
      ? 'intersect'
      : isAltPressed.value
        ? 'subtract'
        : isShiftPressed.value
          ? 'add'
          : 'new';

    if (tool === 'marquee-rect') {
      selection.updateRectSelection(point, selectionMode, constrain);
    } else if (tool === 'marquee-ellipse') {
      selection.updateEllipseSelection(point, selectionMode, constrain);
    }
  }

  /**
   * Sync retouch layer and selection mask to state before recording history.
   * Uses fast canvas snapshots (~1ms) instead of PNG encoding (~100-300ms).
   */
  function syncToState(): void {
    const retouchSnapshot = retouchLayer.toSnapshot();
    const selectionSnapshot = selection.toSnapshot();
    updateState({
      retouchLayerData: retouchSnapshot,
      selectionMaskData: selectionSnapshot,
    } as any);
  }

  function createStateSnapshot(): {
    retouchLayerData: HTMLCanvasElement | null;
    selectionMaskData: HTMLCanvasElement | null;
  } {
    return {
      retouchLayerData: retouchLayer.toSnapshot(),
      selectionMaskData: selection.toSnapshot(),
    };
  }

  /**
   * Restore retouch layer and selection mask from state.
   * Handles both fast canvas snapshots (from history) and data URL strings (from project load).
   */
  async function restoreFromState(
    retouchData: HTMLCanvasElement | string | null,
    selectionData: HTMLCanvasElement | string | null
  ): Promise<void> {
    debugLog('restore-from-state:start', {
      hasRetouchData: !!retouchData,
      retouchDataType: typeof retouchData,
      hasSelectionData: !!selectionData,
      selectionDataType: typeof selectionData,
      hasRetouchCanvas: !!retouchLayer.retouchCanvas.value,
      hasSelectionCanvas: !!selection.selectionCanvas.value,
    });

    // Restore retouch layer
    if (retouchData instanceof HTMLCanvasElement) {
      retouchLayer.loadFromSnapshot(retouchData);
    } else if (typeof retouchData === 'string') {
      await retouchLayer.loadFromDataUrl(retouchData);
    } else {
      retouchLayer.clearLayer();
    }

    // Restore selection mask
    if (selectionData instanceof HTMLCanvasElement) {
      selection.loadFromSnapshot(selectionData);
    } else if (typeof selectionData === 'string') {
      await selection.loadFromDataUrl(selectionData);
    } else {
      selection.clearSelection();
    }

    debugLog('restore-from-state:end', {
      hasRetouchCanvas: !!retouchLayer.retouchCanvas.value,
      hasSelectionCanvas: !!selection.selectionCanvas.value,
      hasSelection: selection.hasSelection(),
    });
  }

  /**
   * Push history with canvas sync
   */
  function pushHistoryWithSync(action: string): void {
    syncToState();
    pushHistory(action);
  }

  // Selection operations
  function clearSelectionOp(): void {
    if (selection.hasSelection()) {
      selection.clearSelection();
      pushHistoryWithSync('Deselect');
    }
  }

  function fillSelectionOp(color: Color): void {
    const ctx = retouchLayer.retouchCtx.value;
    if (ctx && selection.hasSelection()) {
      selection.fillWithColor(ctx, color);
      requestFullRender();
      pushHistoryWithSync('Fill selection');
    }
  }

  function clearPixelsOp(bgColor?: { r: number; g: number; b: number; a: number }): void {
    const ctx = retouchLayer.retouchCtx.value;
    if (ctx && selection.hasSelection()) {
      selection.clearPixels(ctx, bgColor);
      requestFullRender();
      pushHistoryWithSync('Clear selection');
    }
  }

  function featherSelectionOp(radius: number): void {
    // Manual feather operation for existing selections
    if (selection.hasSelection() && radius > 0) {
      selection.feather(radius);
      pushHistoryWithSync('Feather selection');
    }
  }

  function invertSelectionOp(): void {
    if (selection.hasSelection()) {
      selection.invert();
      pushHistoryWithSync('Invert selection');
    }
  }

  // Event listener management
  let setupCanvas: HTMLCanvasElement | null = null;

  function setupListeners(): void {
    const canvas = canvasRef.value;
    if (!canvas) return;

    // Already set up on this canvas
    if (setupCanvas === canvas) return;

    // Clean up old listeners if canvas changed
    if (setupCanvas) {
      cleanupListeners();
    }

    // mousedown on canvas to start interactions
    canvas.addEventListener('mousedown', handleMouseDown);
    // mousemove and mouseup on window so drags continue even if mouse leaves canvas
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);

    setupCanvas = canvas;
  }

  function cleanupListeners(): void {
    if (!setupCanvas) return;

    setupCanvas.removeEventListener('mousedown', handleMouseDown);
    window.removeEventListener('mousemove', handleMouseMove);
    window.removeEventListener('mouseup', handleMouseUp);
    window.removeEventListener('keydown', handleKeyDown);
    window.removeEventListener('keyup', handleKeyUp);

    // Cancel any pending RAF
    if (mouseMoveRafId !== null) {
      cancelAnimationFrame(mouseMoveRafId);
      mouseMoveRafId = null;
    }
    pendingMouseMoveEvent = null;
    cachedStrokeSourceCanvas = null;
    cachedStrokeState = null;

    setupCanvas = null;
  }

  return {
    // State
    retouchLayer,
    selection,
    isDrawing,
    isAltPressed,
    isShiftPressed,
    cursorStyle,

    // Patch tool state
    isPatchDragging,
    isPatchDrawing,
    patchDragStart,
    patchDragCurrent,
    patchDrawingPoints,

    // Magnetic lasso state (for overlay rendering)
    magneticLasso,
    isMagneticLassoActive: magneticLasso.isActive,
    magneticLassoAnchors: magneticLasso.anchors,
    magneticLassoPathSegments: magneticLasso.pathSegments,
    magneticLassoPreviewPath: magneticLasso.previewPath,
    magneticLassoCursorPosition: magneticLasso.cursorPosition,
    isMagneticLassoNearStart: magneticLasso.isNearStart,

    // Methods
    initLayers,
    initMagneticLasso,
    setupListeners,
    cleanupListeners,

    // Selection operations
    clearSelection: clearSelectionOp,
    fillSelection: fillSelectionOp,
    clearPixels: clearPixelsOp,
    featherSelection: featherSelectionOp,
    invertSelection: invertSelectionOp,

    // Data access
    getRetouchCanvas: () => retouchLayer.retouchCanvas.value,
    getSelectionCanvas: () => selection.selectionCanvas.value,
    getMarchingAntsPaths: () => selection.marchingAntsPaths.value,
    hasSelection: () => selection.hasSelection(),
    getSelectionBounds: () => selection.getBounds(),

    // Selection drawing state for overlay
    isDrawingSelection: selection.isDrawing,
    selectionDrawingStartPoint: selection.drawingStartPoint,
    selectionDrawingCurrentPoint: selection.drawingCurrentPoint,
    selectionDrawingPoints: selection.drawingPoints,

    // History support
    restoreFromState,
    syncToState,
    createStateSnapshot,
  };
}
