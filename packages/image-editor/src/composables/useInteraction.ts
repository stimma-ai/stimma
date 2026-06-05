import { ref } from 'vue';
import type { Point, InteractionState, ViewTransform, Size, CropRect, CropHandle } from '@/types';
import { ZOOM_CONFIG, TOUCH_CONFIG, HIT_TEST } from '@/constants';
import { screenToCanvas, canvasToImage } from '@/utils/canvas';
import { distance } from '@/utils/geometry';

export interface InteractionCallbacks {
  onPanChange: (panX: number, panY: number) => void;
  onZoomChange: (zoom: number, center?: Point) => void;
  onCropChange?: (crop: CropRect) => void;
}

export interface InteractionState2 {
  activePlugin: string;
  crop: CropRect;
}

/**
 * Mouse/touch interaction composable
 */
export function useInteraction(
  canvasRef: { value: HTMLCanvasElement | null },
  viewTransform: { value: ViewTransform },
  imageSize: { value: Size | null },
  canvasSize: { value: Size },
  onPanChange: (panX: number, panY: number) => void,
  onZoomChange: (zoom: number, center?: Point) => void
) {
  const interactionState = ref<InteractionState>({ type: 'idle' });
  const cursorStyle = ref('default');
  const lastTap = ref<{ time: number; point: Point } | null>(null);

  // Crop interaction state
  let cropCallback: ((crop: CropRect) => void) | null = null;
  let editorStateGetter: (() => InteractionState2) | null = null;

  // Touch state
  const touches = ref<Touch[]>([]);
  const initialPinchDistance = ref(0);
  const initialPinchZoom = ref(1);

  /**
   * Set crop change callback
   */
  function setCropCallback(
    cb: (crop: CropRect) => void,
    stateGetter: () => InteractionState2
  ) {
    cropCallback = cb;
    editorStateGetter = stateGetter;
  }

  /**
   * Get canvas bounding rect
   */
  function getCanvasRect(): DOMRect | null {
    return canvasRef.value?.getBoundingClientRect() ?? null;
  }

  /**
   * Convert screen point to canvas point
   */
  function toCanvasPoint(screenPoint: Point): Point | null {
    const rect = getCanvasRect();
    if (!rect) return null;
    return screenToCanvas(screenPoint, rect);
  }

  /**
   * Convert screen point to image point (0-1)
   */
  function toImagePoint(screenPoint: Point): Point | null {
    const rect = getCanvasRect();
    if (!rect || !imageSize.value) return null;
    return canvasToImage(
      screenToCanvas(screenPoint, rect),
      viewTransform.value,
      imageSize.value,
      canvasSize.value
    );
  }

  /**
   * Get crop rect in canvas coordinates (center-based)
   */
  function getCropCanvasRect(): { x: number; y: number; w: number; h: number; cx: number; cy: number; rotation: number } | null {
    if (!imageSize.value || !editorStateGetter) return null;
    const { crop } = editorStateGetter();
    const { zoom, panX, panY } = viewTransform.value;
    const imgSize = imageSize.value;

    const imgCenterX = canvasSize.value.width / 2 + panX;
    const imgCenterY = canvasSize.value.height / 2 + panY;

    // Crop center in canvas space
    const cx = imgCenterX + (crop.x - 0.5) * imgSize.width * zoom;
    const cy = imgCenterY + (crop.y - 0.5) * imgSize.height * zoom;
    const w = crop.width * imgSize.width * zoom;
    const h = crop.height * imgSize.height * zoom;
    const rotation = crop.rotation ?? 0;

    // Top-left corner (for backwards compat)
    const x = cx - w / 2;
    const y = cy - h / 2;

    return { x, y, w, h, cx, cy, rotation };
  }

  /**
   * Rotate a point around a center
   */
  function rotatePoint(px: number, py: number, cx: number, cy: number, angle: number): Point {
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);
    const dx = px - cx;
    const dy = py - cy;
    return {
      x: cx + dx * cos - dy * sin,
      y: cy + dx * sin + dy * cos,
    };
  }

  /**
   * Hit test crop handles (handles rotation)
   */
  function hitTestCropHandle(canvasPoint: Point): CropHandle | null {
    const cropRect = getCropCanvasRect();
    if (!cropRect) return null;

    const { w, h, cx, cy, rotation } = cropRect;
    const radius = HIT_TEST.handleRadius;
    const rotationRadius = HIT_TEST.rotationRadius;
    const rotateHandleDistance = 30; // Same as in EditorCanvas

    const halfW = w / 2;
    const halfH = h / 2;

    // Get rotated corner positions
    const corners = {
      nw: rotatePoint(cx - halfW, cy - halfH, cx, cy, rotation),
      ne: rotatePoint(cx + halfW, cy - halfH, cx, cy, rotation),
      se: rotatePoint(cx + halfW, cy + halfH, cx, cy, rotation),
      sw: rotatePoint(cx - halfW, cy + halfH, cx, cy, rotation),
    };

    // Bottom center and rotation handle position (perpendicular to bottom edge)
    const bottomCenterX = (corners.sw.x + corners.se.x) / 2;
    const bottomCenterY = (corners.sw.y + corners.se.y) / 2;
    // Calculate perpendicular direction to the bottom edge (pointing outward/down)
    const edgeX = corners.se.x - corners.sw.x;
    const edgeY = corners.se.y - corners.sw.y;
    const edgeLen = Math.sqrt(edgeX * edgeX + edgeY * edgeY);
    // Perpendicular pointing "down" is (-edgeY, edgeX) normalized (90° clockwise from edge)
    const perpX = -edgeY / edgeLen;
    const perpY = edgeX / edgeLen;
    const rotateHandleX = bottomCenterX + perpX * rotateHandleDistance;
    const rotateHandleY = bottomCenterY + perpY * rotateHandleDistance;

    // Test rotation handle first (highest priority)
    if (distance(canvasPoint, { x: rotateHandleX, y: rotateHandleY }) < rotationRadius) {
      return 'rotation';
    }

    // Test corners
    if (distance(canvasPoint, corners.nw) < radius) return 'nw';
    if (distance(canvasPoint, corners.ne) < radius) return 'ne';
    if (distance(canvasPoint, corners.sw) < radius) return 'sw';
    if (distance(canvasPoint, corners.se) < radius) return 'se';

    // Test inside crop area (transform point to local space)
    const localPoint = rotatePoint(canvasPoint.x, canvasPoint.y, cx, cy, -rotation);
    if (localPoint.x >= cx - halfW && localPoint.x <= cx + halfW &&
        localPoint.y >= cy - halfH && localPoint.y <= cy + halfH) {
      return 'center';
    }

    return null;
  }

  /**
   * Get cursor for crop handle
   */
  function getCropCursor(handle: CropHandle | null): string {
    if (!handle) return 'grab';
    switch (handle) {
      case 'n': case 's': return 'ns-resize';
      case 'e': case 'w': return 'ew-resize';
      case 'ne': case 'sw': return 'nesw-resize';
      case 'nw': case 'se': return 'nwse-resize';
      case 'center': return 'move';
      case 'rotation': return 'grab';
      default: return 'grab';
    }
  }

  /**
   * Handle mouse down
   */
  function handleMouseDown(event: MouseEvent) {
    // Middle mouse button (button === 1) always starts panning regardless of plugin
    const isMiddleClick = event.button === 1;

    if (event.button !== 0 && !isMiddleClick) return;

    const point = { x: event.clientX, y: event.clientY };
    const canvasPoint = toCanvasPoint(point);
    if (!canvasPoint) return;

    // Middle click always pans, skip plugin checks
    if (isMiddleClick) {
      event.preventDefault();
      // In crop mode, also store starting crop to keep it visually stationary
      const startCrop = editorStateGetter && editorStateGetter().activePlugin === 'crop'
        ? { ...editorStateGetter().crop }
        : undefined;

      interactionState.value = {
        type: 'panning',
        startPan: { x: viewTransform.value.panX, y: viewTransform.value.panY },
        startMouse: canvasPoint,
        startCrop,
      };
      cursorStyle.value = 'grabbing';
      return;
    }

    // Check for crop interaction
    if (editorStateGetter && editorStateGetter().activePlugin === 'crop') {
      const handle = hitTestCropHandle(canvasPoint);
      if (handle) {
        if (handle === 'rotation') {
          // Start rotation interaction
          const state = editorStateGetter();
          const cropRect = getCropCanvasRect();
          if (cropRect) {
            // Use crop center
            const { cx, cy } = cropRect;
            // Calculate starting angle from center to mouse
            const startAngle = Math.atan2(canvasPoint.y - cy, canvasPoint.x - cx);
            interactionState.value = {
              type: 'crop-rotating',
              startAngle,
              startRotation: state.crop.rotation ?? 0,
            };
            cursorStyle.value = 'grabbing';
            return;
          }
        } else {
          const { crop } = editorStateGetter();
          interactionState.value = {
            type: 'crop-dragging',
            handle,
            startRect: { ...crop },
            startMouse: canvasPoint,
          };
          cursorStyle.value = getCropCursor(handle);
          return;
        }
      }
    }

    // Don't start panning when annotate or retouch plugin is active (let them handle it)
    if (editorStateGetter) {
      const activePlugin = editorStateGetter().activePlugin;
      if (activePlugin === 'annotate' || activePlugin === 'retouch') {
        return;
      }
    }

    // Start panning - in crop mode, also store starting crop to keep it visually stationary
    const startCrop = editorStateGetter && editorStateGetter().activePlugin === 'crop'
      ? { ...editorStateGetter().crop }
      : undefined;

    interactionState.value = {
      type: 'panning',
      startPan: { x: viewTransform.value.panX, y: viewTransform.value.panY },
      startMouse: canvasPoint,
      startCrop,
    };
    cursorStyle.value = 'grabbing';
  }

  /**
   * Handle mouse move
   */
  function handleMouseMove(event: MouseEvent) {
    const point = { x: event.clientX, y: event.clientY };
    const canvasPoint = toCanvasPoint(point);
    if (!canvasPoint) return;

    const state = interactionState.value;

    if (state.type === 'panning') {
      const dx = canvasPoint.x - state.startMouse.x;
      const dy = canvasPoint.y - state.startMouse.y;
      onPanChange(state.startPan.x + dx, state.startPan.y + dy);

      // In crop mode, adjust crop position to keep it visually stationary
      if (state.startCrop && cropCallback && imageSize.value) {
        const { zoom } = viewTransform.value;
        const imgSize = imageSize.value;
        // Convert canvas pan delta to image space and move crop in opposite direction
        const cropDx = -dx / (imgSize.width * zoom);
        const cropDy = -dy / (imgSize.height * zoom);
        cropCallback({
          ...state.startCrop,
          x: state.startCrop.x + cropDx,
          y: state.startCrop.y + cropDy,
        });
      }
    } else if (state.type === 'crop-dragging') {
      handleCropDrag(canvasPoint, state, event.shiftKey);
    } else if (state.type === 'crop-rotating') {
      handleCropRotate(canvasPoint, state);
    } else if (state.type === 'idle') {
      // Update cursor based on hover
      if (editorStateGetter && editorStateGetter().activePlugin === 'crop') {
        const handle = hitTestCropHandle(canvasPoint);
        cursorStyle.value = getCropCursor(handle);
      } else {
        cursorStyle.value = 'grab';
      }
    }
  }

  /**
   * Handle crop dragging
   */
  function handleCropDrag(
    canvasPoint: Point,
    state: { type: 'crop-dragging'; handle: CropHandle; startRect: CropRect; startMouse: Point },
    shiftKey: boolean = false
  ) {
    if (!cropCallback || !imageSize.value) return;

    const { zoom } = viewTransform.value;
    const imgSize = imageSize.value;

    // Convert delta from canvas to image space (0-1)
    const dx = (canvasPoint.x - state.startMouse.x) / (imgSize.width * zoom);
    const dy = (canvasPoint.y - state.startMouse.y) / (imgSize.height * zoom);

    const newCrop = { ...state.startRect };
    const { handle } = state;

    // Apply changes based on handle
    if (handle === 'center') {
      // Move entire crop
      newCrop.x = state.startRect.x + dx;
      newCrop.y = state.startRect.y + dy;
    } else {
      // Resize from handle - adjust size and position
      // Use locked aspect ratio, or if shift is held, use starting rect's aspect ratio
      // Note: aspectRatio is in pixel space (width/height), but we work in normalized coords
      // Convert: normalizedAR = pixelAR / imageAR
      const imgSize = imageSize.value;
      const imageAR = imgSize.width / imgSize.height;
      const pixelAR = newCrop.aspectRatio ?? (shiftKey ? (state.startRect.width * imgSize.width) / (state.startRect.height * imgSize.height) : null);
      const aspectRatio = pixelAR ? pixelAR / imageAR : null;

      const isCorner = handle.length === 2;
      const hasNorth = handle.includes('n');
      const hasSouth = handle.includes('s');
      const hasWest = handle.includes('w');
      const hasEast = handle.includes('e');

      // Calculate the fixed edge/corner positions (in image space 0-1)
      const startLeft = state.startRect.x - state.startRect.width / 2;
      const startRight = state.startRect.x + state.startRect.width / 2;
      const startTop = state.startRect.y - state.startRect.height / 2;
      const startBottom = state.startRect.y + state.startRect.height / 2;

      // Calculate where the dragged handle would be based on mouse movement
      const draggedX = hasWest ? startLeft + dx : hasEast ? startRight + dx : null;
      const draggedY = hasNorth ? startTop + dy : hasSouth ? startBottom + dy : null;

      let newLeft = startLeft;
      let newRight = startRight;
      let newTop = startTop;
      let newBottom = startBottom;

      if (aspectRatio && isCorner) {
        // For corners with aspect ratio: project mouse onto aspect diagonal from fixed corner
        // Fixed corner is opposite to dragged corner
        const fixedX = hasWest ? startRight : startLeft;
        const fixedY = hasNorth ? startBottom : startTop;

        // Mouse position relative to fixed corner
        const mouseX = draggedX!;
        const mouseY = draggedY!;
        const relX = mouseX - fixedX;
        const relY = mouseY - fixedY;

        // Direction signs for this corner (which way width/height grow)
        const signX = hasEast ? 1 : -1;
        const signY = hasSouth ? 1 : -1;

        // Project onto aspect ratio diagonal
        // The diagonal has slope: dy/dx = (1/aspectRatio) * (signY/signX)
        // Parameterized line from fixed corner: (fixedX + signX*ar*t, fixedY + signY*t)
        // where t is the height and ar*t is the width
        // We want t that minimizes distance to mouse
        // t = (signX * ar * relX + signY * relY) / (ar² + 1)
        const ar = aspectRatio;
        const t = (signX * ar * relX + signY * relY) / (ar * ar + 1);

        // Ensure positive dimensions
        const clampedT = Math.max(0.05, Math.abs(t)) * Math.sign(t || 1);
        const newWidth = Math.abs(ar * clampedT);
        const newHeight = Math.abs(clampedT);

        // Set edges based on fixed corner and new dimensions
        if (hasEast) {
          newLeft = fixedX;
          newRight = fixedX + newWidth;
        } else {
          newRight = fixedX;
          newLeft = fixedX - newWidth;
        }
        if (hasSouth) {
          newTop = fixedY;
          newBottom = fixedY + newHeight;
        } else {
          newBottom = fixedY;
          newTop = fixedY - newHeight;
        }
      } else if (aspectRatio && !isCorner) {
        // Edge drag with aspect ratio: the dragged edge moves, perpendicular expands symmetrically
        if (hasNorth) {
          newTop = startTop + dy;
          const newHeight = newBottom - newTop;
          const newWidth = newHeight * aspectRatio;
          const centerX = (newLeft + newRight) / 2;
          newLeft = centerX - newWidth / 2;
          newRight = centerX + newWidth / 2;
        } else if (hasSouth) {
          newBottom = startBottom + dy;
          const newHeight = newBottom - newTop;
          const newWidth = newHeight * aspectRatio;
          const centerX = (newLeft + newRight) / 2;
          newLeft = centerX - newWidth / 2;
          newRight = centerX + newWidth / 2;
        } else if (hasWest) {
          newLeft = startLeft + dx;
          const newWidth = newRight - newLeft;
          const newHeight = newWidth / aspectRatio;
          const centerY = (newTop + newBottom) / 2;
          newTop = centerY - newHeight / 2;
          newBottom = centerY + newHeight / 2;
        } else if (hasEast) {
          newRight = startRight + dx;
          const newWidth = newRight - newLeft;
          const newHeight = newWidth / aspectRatio;
          const centerY = (newTop + newBottom) / 2;
          newTop = centerY - newHeight / 2;
          newBottom = centerY + newHeight / 2;
        }
      } else {
        // Free resize (no aspect ratio)
        if (hasNorth) newTop = startTop + dy;
        if (hasSouth) newBottom = startBottom + dy;
        if (hasWest) newLeft = startLeft + dx;
        if (hasEast) newRight = startRight + dx;
      }

      // Calculate new dimensions and center
      const newWidth = newRight - newLeft;
      const newHeight = newBottom - newTop;

      // Apply minimum size constraint
      if (newWidth > 0.05 && newHeight > 0.05) {
        newCrop.width = newWidth;
        newCrop.height = newHeight;
        newCrop.x = (newLeft + newRight) / 2;
        newCrop.y = (newTop + newBottom) / 2;
      }
    }

    cropCallback(newCrop);
  }

  /**
   * Handle crop rotation
   */
  function handleCropRotate(
    canvasPoint: Point,
    state: { type: 'crop-rotating'; startAngle: number; startRotation: number }
  ) {
    if (!cropCallback || !editorStateGetter) return;

    const cropRect = getCropCanvasRect();
    if (!cropRect) return;

    // Use crop center
    const { cx, cy } = cropRect;

    // Calculate current angle from center to mouse
    const currentAngle = Math.atan2(canvasPoint.y - cy, canvasPoint.x - cx);

    // Calculate rotation delta
    const deltaAngle = currentAngle - state.startAngle;

    // Calculate new rotation (clamp to -45 to 45 degrees, which is -PI/4 to PI/4)
    let newRotation = state.startRotation + deltaAngle;
    const maxRotation = Math.PI / 4;
    newRotation = Math.max(-maxRotation, Math.min(maxRotation, newRotation));

    // Update crop with new rotation
    const { crop } = editorStateGetter();
    cropCallback({ ...crop, rotation: newRotation });
  }

  /**
   * Handle mouse up
   */
  function handleMouseUp(_event: MouseEvent) {
    if (interactionState.value.type === 'panning') {
      interactionState.value = { type: 'idle' };
      cursorStyle.value = 'grab';
    } else if (interactionState.value.type === 'crop-dragging') {
      interactionState.value = { type: 'idle' };
    } else if (interactionState.value.type === 'crop-rotating') {
      interactionState.value = { type: 'idle' };
      cursorStyle.value = 'default';
    }
  }

  /**
   * Handle mouse wheel (zoom/pan)
   * - Regular wheel → Zoom (centered on cursor)
   * - Shift + wheel → Horizontal pan
   * - Trackpad two-finger gesture → Pan in both X/Y
   * - Ctrl/Cmd + wheel (pinch gesture) → Zoom
   */
  function handleWheel(event: WheelEvent) {
    event.preventDefault();

    const point = { x: event.clientX, y: event.clientY };
    const canvasPoint = toCanvasPoint(point);
    if (!canvasPoint) return;

    // Detect trackpad pan gesture:
    // - Has horizontal delta (deltaX !== 0), OR
    // - Shift key is held for horizontal panning, OR
    // - No ctrlKey and small precise deltas (typical of trackpad pan vs mouse wheel)
    const hasHorizontalDelta = Math.abs(event.deltaX) > 0;
    const isShiftHorizontalPan = event.shiftKey && !event.ctrlKey;
    const isTrackpadPan = !event.ctrlKey && hasHorizontalDelta;

    if (isTrackpadPan || isShiftHorizontalPan) {
      // Pan mode: trackpad two-finger swipe or Shift+wheel
      let deltaX = event.deltaX;
      let deltaY = event.deltaY;

      // For Shift+wheel (mouse), use deltaY as horizontal pan
      if (isShiftHorizontalPan && !hasHorizontalDelta) {
        deltaX = event.deltaY;
        deltaY = 0;
      }

      const newPanX = viewTransform.value.panX - deltaX;
      const newPanY = viewTransform.value.panY - deltaY;
      onPanChange(newPanX, newPanY);

      // In crop mode, adjust crop position to keep it visually stationary
      if (editorStateGetter && editorStateGetter().activePlugin === 'crop' && cropCallback && imageSize.value) {
        const { zoom } = viewTransform.value;
        const { crop } = editorStateGetter();
        const imgSize = imageSize.value;
        // Pan delta is -deltaX/-deltaY, so crop needs to move by +delta in image space
        const cropDx = deltaX / (imgSize.width * zoom);
        const cropDy = deltaY / (imgSize.height * zoom);
        cropCallback({
          ...crop,
          x: crop.x + cropDx,
          y: crop.y + cropDy,
        });
      }
    } else {
      // Zoom mode: regular mouse wheel or pinch gesture
      const delta = -event.deltaY * ZOOM_CONFIG.wheelFactor;
      const newZoom = viewTransform.value.zoom * (1 + delta);
      const clampedZoom = Math.max(ZOOM_CONFIG.min, Math.min(ZOOM_CONFIG.max, newZoom));

      if (clampedZoom !== viewTransform.value.zoom) {
        const scale = clampedZoom / viewTransform.value.zoom;
        const centerX = canvasSize.value.width / 2;
        const centerY = canvasSize.value.height / 2;

        const dx = canvasPoint.x - centerX - viewTransform.value.panX;
        const dy = canvasPoint.y - centerY - viewTransform.value.panY;

        const newPanX = viewTransform.value.panX - dx * (scale - 1);
        const newPanY = viewTransform.value.panY - dy * (scale - 1);

        onPanChange(newPanX, newPanY);
        onZoomChange(clampedZoom, canvasPoint);
      }
    }
  }

  /**
   * Handle touch start
   */
  function handleTouchStart(event: TouchEvent) {
    event.preventDefault();
    touches.value = Array.from(event.touches);

    if (touches.value.length === 1) {
      const touch = touches.value[0];
      const point = { x: touch.clientX, y: touch.clientY };
      const canvasPoint = toCanvasPoint(point);
      if (!canvasPoint) return;

      // Check for double tap
      const now = Date.now();
      if (
        lastTap.value &&
        now - lastTap.value.time < TOUCH_CONFIG.doubleTapWindow &&
        distance(point, lastTap.value.point) < TOUCH_CONFIG.tapMaxDistance
      ) {
        if (imageSize.value) {
          const fitZoom =
            canvasSize.value.width / imageSize.value.width < 1
              ? canvasSize.value.width / imageSize.value.width
              : 1;
          onZoomChange(
            viewTransform.value.zoom === fitZoom ? ZOOM_CONFIG.doubleTapZoom : fitZoom
          );
          onPanChange(0, 0);
        }
        lastTap.value = null;
        return;
      }

      lastTap.value = { time: now, point };

      // Check for crop interaction
      if (editorStateGetter && editorStateGetter().activePlugin === 'crop') {
        const handle = hitTestCropHandle(canvasPoint);
        if (handle) {
          const { crop } = editorStateGetter();
          interactionState.value = {
            type: 'crop-dragging',
            handle,
            startRect: { ...crop },
            startMouse: canvasPoint,
          };
          return;
        }
      }

      // In crop mode, also store starting crop to keep it visually stationary
      const startCrop = editorStateGetter && editorStateGetter().activePlugin === 'crop'
        ? { ...editorStateGetter().crop }
        : undefined;

      interactionState.value = {
        type: 'panning',
        startPan: { x: viewTransform.value.panX, y: viewTransform.value.panY },
        startMouse: canvasPoint,
        startCrop,
      };
    } else if (touches.value.length === 2) {
      const t1 = touches.value[0];
      const t2 = touches.value[1];
      initialPinchDistance.value = distance(
        { x: t1.clientX, y: t1.clientY },
        { x: t2.clientX, y: t2.clientY }
      );
      initialPinchZoom.value = viewTransform.value.zoom;

      interactionState.value = {
        type: 'zooming',
        startZoom: viewTransform.value.zoom,
        startDistance: initialPinchDistance.value,
      };
    }
  }

  /**
   * Handle touch move
   */
  function handleTouchMove(event: TouchEvent) {
    event.preventDefault();
    const currentTouches = Array.from(event.touches);

    if (currentTouches.length === 1) {
      const touch = currentTouches[0];
      const canvasPoint = toCanvasPoint({ x: touch.clientX, y: touch.clientY });
      if (!canvasPoint) return;

      const state = interactionState.value;

      if (state.type === 'panning') {
        const dx = canvasPoint.x - state.startMouse.x;
        const dy = canvasPoint.y - state.startMouse.y;
        onPanChange(state.startPan.x + dx, state.startPan.y + dy);

        // In crop mode, adjust crop position to keep it visually stationary
        if (state.startCrop && cropCallback && imageSize.value) {
          const { zoom } = viewTransform.value;
          const imgSize = imageSize.value;
          const cropDx = -dx / (imgSize.width * zoom);
          const cropDy = -dy / (imgSize.height * zoom);
          cropCallback({
            ...state.startCrop,
            x: state.startCrop.x + cropDx,
            y: state.startCrop.y + cropDy,
          });
        }
      } else if (state.type === 'crop-dragging') {
        handleCropDrag(canvasPoint, state);
      }
    } else if (currentTouches.length === 2 && interactionState.value.type === 'zooming') {
      const t1 = currentTouches[0];
      const t2 = currentTouches[1];
      const currentDistance = distance(
        { x: t1.clientX, y: t1.clientY },
        { x: t2.clientX, y: t2.clientY }
      );

      const scale = currentDistance / initialPinchDistance.value;
      const newZoom = initialPinchZoom.value * scale;
      const clampedZoom = Math.max(ZOOM_CONFIG.min, Math.min(ZOOM_CONFIG.max, newZoom));
      onZoomChange(clampedZoom);
    }
  }

  /**
   * Handle touch end
   */
  function handleTouchEnd(event: TouchEvent) {
    const currentTouches = Array.from(event.touches);

    if (currentTouches.length === 0) {
      interactionState.value = { type: 'idle' };
    } else if (currentTouches.length === 1) {
      touches.value = currentTouches;
      const touch = currentTouches[0];
      const canvasPoint = toCanvasPoint({ x: touch.clientX, y: touch.clientY });
      if (canvasPoint) {
        // In crop mode, also store starting crop to keep it visually stationary
        const startCrop = editorStateGetter && editorStateGetter().activePlugin === 'crop'
          ? { ...editorStateGetter().crop }
          : undefined;

        interactionState.value = {
          type: 'panning',
          startPan: { x: viewTransform.value.panX, y: viewTransform.value.panY },
          startMouse: canvasPoint,
          startCrop,
        };
      }
    }
  }

  /**
   * Setup event listeners
   */
  function setupListeners() {
    const canvas = canvasRef.value;
    if (!canvas) return;

    canvas.addEventListener('mousedown', handleMouseDown);
    canvas.addEventListener('wheel', handleWheel, { passive: false });
    canvas.addEventListener('touchstart', handleTouchStart, { passive: false });
    canvas.addEventListener('touchmove', handleTouchMove, { passive: false });
    canvas.addEventListener('touchend', handleTouchEnd);
    canvas.addEventListener('touchcancel', handleTouchEnd);

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
  }

  /**
   * Cleanup event listeners
   */
  function cleanupListeners() {
    const canvas = canvasRef.value;
    if (canvas) {
      canvas.removeEventListener('mousedown', handleMouseDown);
      canvas.removeEventListener('wheel', handleWheel);
      canvas.removeEventListener('touchstart', handleTouchStart);
      canvas.removeEventListener('touchmove', handleTouchMove);
      canvas.removeEventListener('touchend', handleTouchEnd);
      canvas.removeEventListener('touchcancel', handleTouchEnd);
    }

    window.removeEventListener('mousemove', handleMouseMove);
    window.removeEventListener('mouseup', handleMouseUp);
  }

  return {
    interactionState,
    cursorStyle,
    toCanvasPoint,
    toImagePoint,
    setupListeners,
    cleanupListeners,
    setCropCallback,
  };
}

export type Interaction = ReturnType<typeof useInteraction>;
