/**
 * Annotation interaction composable
 * Handles selecting, moving, resizing, and drawing shapes on the canvas
 */
import { ref, computed } from 'vue';
import type { Point, Size, ViewTransform, Color } from '@/types';
import type { Shape, PathShape, LineShape, CurvedArrowShape, RectangleShape, EllipseShape, TextShape, RedactShape, TriangleShape, StarShape, PolygonShape, AnnotateTool, ResizeHandle, BrushSettings, TextEffect, GradientDirection, ShadowDirection, ShapeEffect, ShapeStyle } from '@/types/shapes';
import { screenToCanvas, canvasToImage } from '@/utils/canvas';
import {
  generateShapeId,
  getShapeBounds,
  getShapeCenter,
  findShapeAtPoint,
  hitTestResizeHandle,
  getResizeHandleCursor,
  moveShape,
  resizeShapeBounds,
  computeSmoothedPath,
  measureTextBase,
} from '@/utils/shapes';
import type { TextEditState } from '@/utils/shapes';
import { useTextEditing } from './useTextEditing';

/**
 * Map a shape to the corresponding annotation tool
 */
function shapeToTool(shape: Shape): AnnotateTool | null {
  switch (shape.type) {
    case 'rectangle':
      return 'rectangle';
    case 'ellipse':
      return 'ellipse';
    case 'line': {
      // Check if it's an arrow (has line end style that's not 'none')
      const lineShape = shape as LineShape;
      return (lineShape.lineEnd && lineShape.lineEnd !== 'none')
        ? 'arrow'
        : 'line';
    }
    case 'curved-arrow':
      return 'arrow'; // curved-arrow shapes use the arrow tool
    case 'path':
      return 'sharpie'; // path shapes use the sharpie/draw tool
    case 'text':
      return 'text';
    case 'redact':
      return 'redact';
    case 'triangle':
      return 'triangle';
    case 'star':
      return 'star';
    case 'polygon':
      return 'polygon';
    case 'sticker':
      return null; // Stickers don't map to a specific tool
    default:
      return null;
  }
}

export interface AnnotationState {
  activeTool: AnnotateTool | null;
  annotations: Shape[];
  selectedShapeId: string | null;
  annotateStrokeColor: Color;
  annotateFillColor: Color | null;
  annotateStrokeWidth: number;
  annotateBrushSettings?: BrushSettings;
  annotateIsEraser?: boolean;
  annotatePenId?: string;
  // Text tool settings
  annotateTextFontFamily?: string;
  annotateTextFontSize?: number;
  annotateTextFontWeight?: 'normal' | 'bold';
  annotateTextFontStyle?: 'normal' | 'italic';
  annotateTextAlign?: 'left' | 'center' | 'right';
  // Text background styling
  annotateTextBackgroundPadding?: number;
  annotateTextBackgroundCornerRadius?: number;
  // Text-specific colors
  annotateTextColor?: Color;
  annotateTextBgColor?: Color | null;
  // Text effect settings
  annotateTextEffect?: TextEffect;
  annotateTextGlowIntensity?: number;
  annotateTextGradientColors?: string[];
  annotateTextGradientDirection?: GradientDirection;
  annotateTextShadowDirection?: ShadowDirection;
  annotateTextShadowLength?: number;
  annotateTextShadowColor?: Color | null;
  annotateTextGlitchIntensity?: number;
  annotateTextKnockoutColor?: Color;
  // Redact tool settings
  annotateRedactBlockSize?: number;
  // Polygon tool settings
  annotatePolygonSides?: number;
  // Universal shape style settings
  annotateShapeEffect?: ShapeEffect;
  annotateGlowIntensity?: number;
  annotateGradientColors?: Color[];
  annotateGradientDirection?: GradientDirection;
}

type InteractionMode =
  | { type: 'idle' }
  | { type: 'pending'; startPoint: Point; screenStart: Point; shapeUnderCursor: Shape | null }
  | { type: 'drawing-path'; shape: PathShape }
  | { type: 'drawing-line'; shape: LineShape; startPoint: Point }
  | { type: 'drawing-curved-arrow'; shape: CurvedArrowShape; lastSampledPoint: Point }
  | { type: 'drawing-rect'; shape: RectangleShape; startPoint: Point }
  | { type: 'drawing-ellipse'; shape: EllipseShape; startPoint: Point }
  | { type: 'drawing-redact'; shape: RedactShape; startPoint: Point }
  | { type: 'drawing-triangle'; shape: TriangleShape; startPoint: Point }
  | { type: 'drawing-star'; shape: StarShape; startPoint: Point }
  | { type: 'drawing-polygon'; shape: PolygonShape; startPoint: Point }
  | { type: 'moving-shape'; shapeId: string; startPoint: Point; originalShape: Shape }
  | { type: 'resizing-shape'; shapeId: string; handle: ResizeHandle; startPoint: Point; originalShape: Shape }
  | { type: 'rotating-shape'; shapeId: string; startAngle: number; originalRotation: number; centerPoint: Point }
  | { type: 'erasing' }
  | { type: 'editing-text-canvas'; shapeId: string }; // Canvas-based text editing

// Drag threshold in pixels - movement below this is considered a click
const DRAG_THRESHOLD = 5;

export function useAnnotation(
  canvasRef: { value: HTMLCanvasElement | null },
  viewTransform: { value: ViewTransform },
  imageSize: { value: Size | null },
  canvasSize: { value: Size },
  getState: () => AnnotationState,
  updateState: (partial: Partial<AnnotationState>) => void,
  pushHistory: (action: string) => void
) {
  const interactionMode = ref<InteractionMode>({ type: 'idle' });
  const cursorStyle = ref<string>('default');

  // Refs for text editing composable
  const canvasRefComputed = computed(() => canvasRef.value);
  const viewTransformComputed = computed(() => viewTransform.value);
  const imageSizeComputed = computed(() => imageSize.value);
  const canvasSizeComputed = computed(() => canvasSize.value);

  /**
   * Update a shape in the annotations array (defined early for text editing)
   */
  function updateShape(shapeId: string, updates: Partial<Shape>) {
    const state = getState();
    const annotations = state.annotations.map(s =>
      s.id === shapeId ? { ...s, ...updates } as Shape : s
    );
    updateState({ annotations });
  }

  // Canvas-based text editing composable
  const textEditing = useTextEditing({
    canvasRef: canvasRefComputed,
    viewTransform: viewTransformComputed,
    imageSize: imageSizeComputed,
    canvasSize: canvasSizeComputed,
    getAnnotations: () => getState().annotations,
    updateShape,
    onStopEditing: () => {
      // Check if the text shape being edited has only whitespace content
      // If so, delete it instead of keeping an empty text box
      const mode = interactionMode.value;
      if (mode.type === 'editing-text-canvas') {
        const state = getState();
        const textShape = state.annotations.find(s => s.id === mode.shapeId);
        if (textShape && textShape.type === 'text') {
          const text = (textShape as TextShape).text;
          if (!text || text.trim().length === 0) {
            // Delete the empty text shape
            updateState({
              annotations: state.annotations.filter(s => s.id !== mode.shapeId),
              selectedShapeId: null,
            });
          }
        }
      }
      interactionMode.value = { type: 'idle' };
    },
  });

  // Export text edit state for rendering
  const textEditState = computed<TextEditState | null>(() => textEditing.editState.value);

  /**
   * Convert screen point to image coordinates (0-1)
   */
  function toImagePoint(screenPoint: Point): Point | null {
    const rect = canvasRef.value?.getBoundingClientRect();
    if (!rect || !imageSize.value) return null;

    const canvasPoint = screenToCanvas(screenPoint, rect);
    return canvasToImage(canvasPoint, viewTransform.value, imageSize.value, canvasSize.value);
  }

  /**
   * Get selected shape
   */
  function getSelectedShape(): Shape | null {
    const state = getState();
    if (!state.selectedShapeId) return null;
    return state.annotations.find(s => s.id === state.selectedShapeId) ?? null;
  }

  /**
   * Get the current shape style from state (only if effect is not 'none')
   */
  function getCurrentShapeStyle(): ShapeStyle | undefined {
    const state = getState();
    const effect = state.annotateShapeEffect ?? 'none';
    if (effect === 'none') return undefined;

    return {
      effect,
      glowIntensity: state.annotateGlowIntensity ?? 50,
      gradientColors: state.annotateGradientColors,
      gradientDirection: state.annotateGradientDirection ?? 'horizontal',
    };
  }

  /**
   * Start drawing a new shape
   */
  function startDrawing(imagePoint: Point) {
    const state = getState();
    if (!state.activeTool) return;

    const { annotateStrokeColor, annotateFillColor, annotateStrokeWidth } = state;
    const shapeStyle = getCurrentShapeStyle();

    // Deselect any selected shape
    updateState({ selectedShapeId: null });

    switch (state.activeTool) {
      case 'sharpie': {
        const brushSettings = state.annotateBrushSettings;
        const isEraser = state.annotateIsEraser ?? false;
        const shape: PathShape = {
          id: generateShapeId(),
          type: 'path',
          x: imagePoint.x,
          y: imagePoint.y,
          rotation: 0,
          opacity: brushSettings ? brushSettings.opacity / 100 : 1,
          points: [imagePoint],
          strokeColor: isEraser ? { r: 0, g: 0, b: 0, a: 1 } : annotateStrokeColor,
          strokeWidth: brushSettings?.size ?? annotateStrokeWidth,
          hardness: brushSettings?.hardness ?? 100,
          flow: brushSettings?.flow ?? 100,
          spacing: brushSettings?.spacing ?? 25,
          glow: brushSettings?.glow ?? 0,
          jitter: brushSettings?.jitter ?? 0,
          scatter: brushSettings?.scatter ?? 0,
          isEraser,
          penId: state.annotatePenId,
        };
        const annotations = [...state.annotations, shape];
        updateState({ annotations });
        interactionMode.value = { type: 'drawing-path', shape };
        break;
      }

      case 'line': {
        const shape: LineShape = {
          id: generateShapeId(),
          type: 'line',
          x: imagePoint.x,
          y: imagePoint.y,
          rotation: 0,
          opacity: 1,
          x1: imagePoint.x,
          y1: imagePoint.y,
          x2: imagePoint.x,
          y2: imagePoint.y,
          strokeColor: annotateStrokeColor,
          strokeWidth: annotateStrokeWidth,
          lineEnd: 'none',
          style: shapeStyle,
        };
        const annotations = [...state.annotations, shape];
        updateState({ annotations });
        interactionMode.value = { type: 'drawing-line', shape, startPoint: imagePoint };
        break;
      }

      case 'arrow': {
        const shape: CurvedArrowShape = {
          id: generateShapeId(),
          type: 'curved-arrow',
          x: imagePoint.x,
          y: imagePoint.y,
          rotation: 0,
          opacity: 1,
          rawPoints: [imagePoint],
          smoothedPath: [imagePoint],
          strokeColor: annotateStrokeColor,
          strokeWidth: annotateStrokeWidth,
          lineEnd: 'arrow-solid',
          style: shapeStyle,
        };
        const annotations = [...state.annotations, shape];
        updateState({ annotations });
        interactionMode.value = { type: 'drawing-curved-arrow', shape, lastSampledPoint: imagePoint };
        break;
      }

      case 'rectangle': {
        const shape: RectangleShape = {
          id: generateShapeId(),
          type: 'rectangle',
          x: imagePoint.x,
          y: imagePoint.y,
          rotation: 0,
          opacity: 1,
          width: 0,
          height: 0,
          strokeColor: annotateStrokeColor,
          strokeWidth: annotateStrokeWidth,
          backgroundColor: annotateFillColor ?? undefined,
          style: shapeStyle,
        };
        const annotations = [...state.annotations, shape];
        updateState({ annotations });
        interactionMode.value = { type: 'drawing-rect', shape, startPoint: imagePoint };
        break;
      }

      case 'ellipse': {
        const shape: EllipseShape = {
          id: generateShapeId(),
          type: 'ellipse',
          x: imagePoint.x,
          y: imagePoint.y,
          rotation: 0,
          opacity: 1,
          rx: 0,
          ry: 0,
          strokeColor: annotateStrokeColor,
          strokeWidth: annotateStrokeWidth,
          backgroundColor: annotateFillColor ?? undefined,
          style: shapeStyle,
        };
        const annotations = [...state.annotations, shape];
        updateState({ annotations });
        interactionMode.value = { type: 'drawing-ellipse', shape, startPoint: imagePoint };
        break;
      }

      case 'eraser': {
        // Create eraser path that uses destination-out composite
        const brushSettings = state.annotateBrushSettings;
        const shape: PathShape = {
          id: generateShapeId(),
          type: 'path',
          x: imagePoint.x,
          y: imagePoint.y,
          rotation: 0,
          opacity: 1,
          points: [imagePoint],
          strokeColor: { r: 0, g: 0, b: 0, a: 1 }, // Color doesn't matter for eraser
          strokeWidth: brushSettings?.size ?? 16,
          hardness: brushSettings?.hardness ?? 100,
          flow: brushSettings?.flow ?? 100,
          spacing: brushSettings?.spacing ?? 25,
          isEraser: true,
        };
        const annotations = [...state.annotations, shape];
        updateState({ annotations });
        interactionMode.value = { type: 'drawing-path', shape };
        break;
      }

      case 'text': {
        // Create text shape immediately with placeholder and enter canvas editing
        const fontFamily = state.annotateTextFontFamily ?? 'Poppins';
        const fontWeight = state.annotateTextFontWeight ?? 'normal';
        const fontStyle = state.annotateTextFontStyle ?? 'normal';
        const textAlign = state.annotateTextAlign ?? 'left';
        const placeholderText = '';  // Start with empty text

        // Measure at base font size to get dimensions
        // Use a wider placeholder text to create a comfortable initial editing area
        const measured = measureTextBase('M', fontFamily, fontWeight, fontStyle);
        const imgSize = imageSize.value;
        // Use a minimum width equivalent to ~6 characters for comfortable editing
        // but cap at 20% of image width to avoid exceeding bounds
        const minEditingWidth = measured.width * 6;
        const maxInitialWidth = imgSize ? imgSize.width * 0.2 : minEditingWidth;
        const baseWidth = imgSize ? Math.min(minEditingWidth, maxInitialWidth) / imgSize.width : 0.08;
        const baseHeight = imgSize ? measured.height / imgSize.height : 0.03;

        const shape: TextShape = {
          id: generateShapeId(),
          type: 'text',
          x: imagePoint.x,
          y: imagePoint.y,
          rotation: 0,
          opacity: 1,
          text: placeholderText,
          width: baseWidth,
          height: baseHeight,
          baseWidth,
          baseHeight,
          fontFamily,
          fontWeight,
          fontStyle,
          textAlign,
          textColor: state.annotateTextColor ?? { r: 255, g: 255, b: 255, a: 1 },
          backgroundColor: state.annotateTextBgColor ?? undefined,
          // Background styling defaults
          backgroundPadding: state.annotateTextBackgroundPadding ?? 0.1,
          backgroundCornerRadius: state.annotateTextBackgroundCornerRadius ?? 0.3,
          // Text effect settings
          textEffect: state.annotateTextEffect ?? 'none',
          glowIntensity: state.annotateTextGlowIntensity ?? 50,
          gradientColors: state.annotateTextGradientColors ?? ['#ff6b6b', '#feca57', '#ff9ff3'],
          gradientDirection: state.annotateTextGradientDirection ?? 'horizontal',
          shadowDirection: state.annotateTextShadowDirection ?? 'bottom-right',
          shadowLength: state.annotateTextShadowLength ?? 25,
          shadowColor: state.annotateTextShadowColor ?? undefined,
          glitchIntensity: state.annotateTextGlitchIntensity ?? 50,
          knockoutColor: state.annotateTextKnockoutColor ?? { r: 0, g: 0, b: 0, a: 1 },
        };

        const annotations = [...state.annotations, shape];
        updateState({ annotations, selectedShapeId: shape.id });

        // Immediately enter canvas editing mode (no selectAll since text is empty)
        startTextEditing(shape.id, 0, false, true);
        break;
      }

      case 'redact': {
        const blockSize = state.annotateRedactBlockSize ?? 16;
        const shape: RedactShape = {
          id: generateShapeId(),
          type: 'redact',
          x: imagePoint.x,
          y: imagePoint.y,
          rotation: 0,
          opacity: 1,
          width: 0,
          height: 0,
          blockSize,
        };
        const annotations = [...state.annotations, shape];
        updateState({ annotations });
        interactionMode.value = { type: 'drawing-redact', shape, startPoint: imagePoint };
        break;
      }

      case 'triangle': {
        const shape: TriangleShape = {
          id: generateShapeId(),
          type: 'triangle',
          x: imagePoint.x,
          y: imagePoint.y,
          rotation: 0,
          opacity: 1,
          width: 0,
          height: 0,
          strokeColor: annotateStrokeColor,
          strokeWidth: annotateStrokeWidth,
          backgroundColor: annotateFillColor ?? undefined,
          style: shapeStyle,
        };
        const annotations = [...state.annotations, shape];
        updateState({ annotations });
        interactionMode.value = { type: 'drawing-triangle', shape, startPoint: imagePoint };
        break;
      }

      case 'star': {
        const shape: StarShape = {
          id: generateShapeId(),
          type: 'star',
          x: imagePoint.x,
          y: imagePoint.y,
          rotation: 0,
          opacity: 1,
          outerRadius: 0,
          innerRadius: 0,
          points: 5, // Classic 5-pointed star
          strokeColor: annotateStrokeColor,
          strokeWidth: annotateStrokeWidth,
          backgroundColor: annotateFillColor ?? undefined,
          style: shapeStyle,
        };
        const annotations = [...state.annotations, shape];
        updateState({ annotations });
        interactionMode.value = { type: 'drawing-star', shape, startPoint: imagePoint };
        break;
      }

      case 'polygon': {
        const sides = state.annotatePolygonSides ?? 6; // Default to hexagon
        const shape: PolygonShape = {
          id: generateShapeId(),
          type: 'polygon',
          x: imagePoint.x,
          y: imagePoint.y,
          rotation: 0,
          opacity: 1,
          radius: 0,
          sides,
          strokeColor: annotateStrokeColor,
          strokeWidth: annotateStrokeWidth,
          backgroundColor: annotateFillColor ?? undefined,
          style: shapeStyle,
        };
        const annotations = [...state.annotations, shape];
        updateState({ annotations });
        interactionMode.value = { type: 'drawing-polygon', shape, startPoint: imagePoint };
        break;
      }
    }
  }

  /**
   * Continue an interaction (drawing, moving, resizing)
   */
  function continueInteraction(imagePoint: Point, shiftKey: boolean = false) {
    const mode = interactionMode.value;
    if (mode.type === 'idle') return;

    switch (mode.type) {
      case 'drawing-path': {
        mode.shape.points.push(imagePoint);
        updateShape(mode.shape.id, { points: [...mode.shape.points] });
        break;
      }

      case 'drawing-line': {
        mode.shape.x2 = imagePoint.x;
        mode.shape.y2 = imagePoint.y;
        mode.shape.x = (mode.shape.x1 + mode.shape.x2) / 2;
        mode.shape.y = (mode.shape.y1 + mode.shape.y2) / 2;
        updateShape(mode.shape.id, {
          x: mode.shape.x,
          y: mode.shape.y,
          x2: mode.shape.x2,
          y2: mode.shape.y2,
        });
        break;
      }

      case 'drawing-curved-arrow': {
        // Distance-based sampling - collect points less frequently for smoother curves
        const dx = imagePoint.x - mode.lastSampledPoint.x;
        const dy = imagePoint.y - mode.lastSampledPoint.y;
        const distance = Math.sqrt(dx * dx + dy * dy);

        if (distance >= 0.012) {
          mode.shape.rawPoints.push(imagePoint);
          mode.lastSampledPoint = imagePoint;

          // Recompute smoothed path
          const smoothed = computeSmoothedPath(mode.shape.rawPoints);
          mode.shape.smoothedPath = smoothed;

          // Update center position
          let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
          for (const p of mode.shape.rawPoints) {
            minX = Math.min(minX, p.x);
            minY = Math.min(minY, p.y);
            maxX = Math.max(maxX, p.x);
            maxY = Math.max(maxY, p.y);
          }

          updateShape(mode.shape.id, {
            x: (minX + maxX) / 2,
            y: (minY + maxY) / 2,
            rawPoints: [...mode.shape.rawPoints],
            smoothedPath: [...mode.shape.smoothedPath],
          });
        }
        break;
      }

      case 'drawing-rect': {
        let width = imagePoint.x - mode.startPoint.x;
        let height = imagePoint.y - mode.startPoint.y;

        // Shift key constrains to square
        if (shiftKey) {
          const size = Math.max(Math.abs(width), Math.abs(height));
          width = Math.sign(width) * size || size;
          height = Math.sign(height) * size || size;
        }

        const minX = Math.min(mode.startPoint.x, mode.startPoint.x + width);
        const minY = Math.min(mode.startPoint.y, mode.startPoint.y + height);
        mode.shape.x = minX;
        mode.shape.y = minY;
        mode.shape.width = Math.abs(width);
        mode.shape.height = Math.abs(height);
        updateShape(mode.shape.id, {
          x: mode.shape.x,
          y: mode.shape.y,
          width: mode.shape.width,
          height: mode.shape.height,
        });
        break;
      }

      case 'drawing-ellipse': {
        let dx = imagePoint.x - mode.startPoint.x;
        let dy = imagePoint.y - mode.startPoint.y;

        // Shift key constrains to circle
        if (shiftKey) {
          const size = Math.max(Math.abs(dx), Math.abs(dy));
          dx = Math.sign(dx) * size || size;
          dy = Math.sign(dy) * size || size;
        }

        const cx = mode.startPoint.x + dx / 2;
        const cy = mode.startPoint.y + dy / 2;
        mode.shape.x = cx;
        mode.shape.y = cy;
        mode.shape.rx = Math.abs(dx) / 2;
        mode.shape.ry = Math.abs(dy) / 2;
        updateShape(mode.shape.id, {
          x: mode.shape.x,
          y: mode.shape.y,
          rx: mode.shape.rx,
          ry: mode.shape.ry,
        });
        break;
      }

      case 'moving-shape': {
        const dx = imagePoint.x - mode.startPoint.x;
        const dy = imagePoint.y - mode.startPoint.y;
        const updates = moveShape(mode.originalShape, dx, dy);
        updateShape(mode.shapeId, updates);
        break;
      }

      case 'resizing-shape': {
        const dxImage = imagePoint.x - mode.startPoint.x;
        const dyImage = imagePoint.y - mode.startPoint.y;

        // Transform delta from image space to shape's local coordinate system
        const rotation = mode.originalShape.rotation || 0;
        const aspectRatio = imageSize.value ? imageSize.value.width / imageSize.value.height : 1;

        // Rotate the delta vector by -rotation (inverse of shape rotation)
        // Using the same aspect-ratio-corrected rotation as rotatePoint
        const cos = Math.cos(-rotation);
        const sin = Math.sin(-rotation);
        const dx = dxImage * cos - dyImage * sin / aspectRatio;
        const dy = dxImage * aspectRatio * sin + dyImage * cos;

        const updates = resizeShapeBounds(mode.originalShape, mode.handle, dx, dy, shiftKey, imageSize.value ?? undefined);
        updateShape(mode.shapeId, updates);
        break;
      }

      case 'rotating-shape': {
        const currentAngle = Math.atan2(
          imagePoint.y - mode.centerPoint.y,
          imagePoint.x - mode.centerPoint.x
        );
        const angleDelta = currentAngle - mode.startAngle;
        const newRotation = mode.originalRotation + angleDelta;
        updateShape(mode.shapeId, { rotation: newRotation });
        break;
      }

      case 'erasing': {
        eraseAtPoint(imagePoint);
        break;
      }

      case 'drawing-redact': {
        let width = imagePoint.x - mode.startPoint.x;
        let height = imagePoint.y - mode.startPoint.y;

        // Shift key constrains to square
        if (shiftKey) {
          const size = Math.max(Math.abs(width), Math.abs(height));
          width = Math.sign(width) * size || size;
          height = Math.sign(height) * size || size;
        }

        const minX = Math.min(mode.startPoint.x, mode.startPoint.x + width);
        const minY = Math.min(mode.startPoint.y, mode.startPoint.y + height);
        mode.shape.x = minX;
        mode.shape.y = minY;
        mode.shape.width = Math.abs(width);
        mode.shape.height = Math.abs(height);
        updateShape(mode.shape.id, {
          x: mode.shape.x,
          y: mode.shape.y,
          width: mode.shape.width,
          height: mode.shape.height,
        });
        break;
      }

      case 'drawing-triangle': {
        let width = imagePoint.x - mode.startPoint.x;
        let height = imagePoint.y - mode.startPoint.y;

        // Shift key constrains to equilateral
        if (shiftKey) {
          const size = Math.max(Math.abs(width), Math.abs(height));
          width = Math.sign(width) * size || size;
          height = Math.sign(height) * size || size;
        }

        const minX = Math.min(mode.startPoint.x, mode.startPoint.x + width);
        const minY = Math.min(mode.startPoint.y, mode.startPoint.y + height);
        mode.shape.x = minX;
        mode.shape.y = minY;
        mode.shape.width = Math.abs(width);
        mode.shape.height = Math.abs(height);
        updateShape(mode.shape.id, {
          x: mode.shape.x,
          y: mode.shape.y,
          width: mode.shape.width,
          height: mode.shape.height,
        });
        break;
      }

      case 'drawing-star': {
        // Star is drawn from center outward - always creates a regular star
        const dx = imagePoint.x - mode.startPoint.x;
        const dy = imagePoint.y - mode.startPoint.y;
        const outerRadius = Math.sqrt(dx * dx + dy * dy);

        // Inner radius is typically 40% of outer radius for a classic 5-pointed star
        const innerRadius = outerRadius * 0.4;

        mode.shape.x = mode.startPoint.x;
        mode.shape.y = mode.startPoint.y;
        mode.shape.outerRadius = outerRadius;
        mode.shape.innerRadius = innerRadius;
        updateShape(mode.shape.id, {
          x: mode.shape.x,
          y: mode.shape.y,
          outerRadius: mode.shape.outerRadius,
          innerRadius: mode.shape.innerRadius,
        });
        break;
      }

      case 'drawing-polygon': {
        // Polygon is drawn from center outward - always creates a regular polygon
        const dx = imagePoint.x - mode.startPoint.x;
        const dy = imagePoint.y - mode.startPoint.y;
        const radius = Math.sqrt(dx * dx + dy * dy);

        mode.shape.x = mode.startPoint.x;
        mode.shape.y = mode.startPoint.y;
        mode.shape.radius = radius;
        updateShape(mode.shape.id, {
          x: mode.shape.x,
          y: mode.shape.y,
          radius: mode.shape.radius,
        });
        break;
      }
    }
  }

  /**
   * Finish an interaction
   */
  function finishInteraction() {
    const mode = interactionMode.value;
    if (mode.type === 'idle') return;

    // Don't finish if we're editing text - text editing manages its own lifecycle
    if (mode.type === 'editing-text-canvas') return;

    // Push history based on action
    switch (mode.type) {
      case 'drawing-path':
        if (mode.shape.points.length > 1) {
          updateState({ selectedShapeId: mode.shape.id });
          pushHistory('Draw path');
        } else {
          // Remove single-point paths
          const state = getState();
          updateState({
            annotations: state.annotations.filter(s => s.id !== mode.shape.id)
          });
        }
        break;
      case 'drawing-line':
        updateState({ selectedShapeId: mode.shape.id });
        pushHistory('Draw line');
        break;
      case 'drawing-curved-arrow':
        // Only keep arrows with enough points for a meaningful curve
        if (mode.shape.rawPoints.length >= 2) {
          // Final smoothing pass with default epsilon for smooth curves
          const finalSmoothed = computeSmoothedPath(mode.shape.rawPoints);
          updateShape(mode.shape.id, { smoothedPath: finalSmoothed });
          updateState({ selectedShapeId: mode.shape.id });
          pushHistory('Draw arrow');
        } else {
          // Remove single-point arrows
          const state = getState();
          updateState({
            annotations: state.annotations.filter(s => s.id !== mode.shape.id)
          });
        }
        break;
      case 'drawing-rect':
        if (mode.shape.width > 0.005 && mode.shape.height > 0.005) {
          updateState({ selectedShapeId: mode.shape.id });
          pushHistory('Draw rectangle');
        } else {
          const state = getState();
          updateState({
            annotations: state.annotations.filter(s => s.id !== mode.shape.id)
          });
        }
        break;
      case 'drawing-ellipse':
        if (mode.shape.rx > 0.005 && mode.shape.ry > 0.005) {
          updateState({ selectedShapeId: mode.shape.id });
          pushHistory('Draw ellipse');
        } else {
          const state = getState();
          updateState({
            annotations: state.annotations.filter(s => s.id !== mode.shape.id)
          });
        }
        break;
      case 'drawing-redact':
        if (mode.shape.width > 0.005 && mode.shape.height > 0.005) {
          updateState({ selectedShapeId: mode.shape.id });
          pushHistory('Draw redact');
        } else {
          const state = getState();
          updateState({
            annotations: state.annotations.filter(s => s.id !== mode.shape.id)
          });
        }
        break;
      case 'drawing-triangle':
        if (mode.shape.width > 0.005 && mode.shape.height > 0.005) {
          updateState({ selectedShapeId: mode.shape.id });
          pushHistory('Draw triangle');
        } else {
          const state = getState();
          updateState({
            annotations: state.annotations.filter(s => s.id !== mode.shape.id)
          });
        }
        break;
      case 'drawing-star':
        if (mode.shape.outerRadius > 0.005) {
          updateState({ selectedShapeId: mode.shape.id });
          pushHistory('Draw star');
        } else {
          const state = getState();
          updateState({
            annotations: state.annotations.filter(s => s.id !== mode.shape.id)
          });
        }
        break;
      case 'drawing-polygon':
        if (mode.shape.radius > 0.005) {
          updateState({ selectedShapeId: mode.shape.id });
          pushHistory('Draw polygon');
        } else {
          const state = getState();
          updateState({
            annotations: state.annotations.filter(s => s.id !== mode.shape.id)
          });
        }
        break;
      case 'moving-shape':
        pushHistory('Move shape');
        break;
      case 'resizing-shape':
        pushHistory('Resize shape');
        break;
      case 'rotating-shape':
        pushHistory('Rotate shape');
        break;
      case 'erasing':
        pushHistory('Erase');
        break;
    }

    interactionMode.value = { type: 'idle' };
  }

  /**
   * Erase shapes at a point
   */
  function eraseAtPoint(imagePoint: Point) {
    const state = getState();
    const eraserRadius = 0.02;

    const annotations = state.annotations.filter(shape => {
      const bounds = getShapeBounds(shape, imageSize.value ?? undefined);
      const padding = eraserRadius;
      return !(
        imagePoint.x >= bounds.x - padding &&
        imagePoint.x <= bounds.x + bounds.width + padding &&
        imagePoint.y >= bounds.y - padding &&
        imagePoint.y <= bounds.y + bounds.height + padding
      );
    });

    if (annotations.length !== state.annotations.length) {
      updateState({ annotations, selectedShapeId: null });
    }
  }

  /**
   * Handle mouse down on canvas
   */
  function handleMouseDown(event: MouseEvent) {
    if (event.button !== 0) return;

    const state = getState();
    const screenPoint = { x: event.clientX, y: event.clientY };
    const imagePoint = toImagePoint(screenPoint);
    if (!imagePoint) return;

    // If we're editing text on canvas, check if click is inside or outside the text shape
    const mode = interactionMode.value;
    if (mode.type === 'editing-text-canvas') {
      // Check if click is on the text shape being edited
      const editingShape = state.annotations.find(s => s.id === mode.shapeId);
      if (editingShape) {
        const aspectRatio = imageSize.value ? imageSize.value.width / imageSize.value.height : 1;
        const clickedShape = findShapeAtPoint(state.annotations, imagePoint, 0.01, aspectRatio);
        if (clickedShape?.id === mode.shapeId) {
          // Click inside the text - let text editing handle it for cursor positioning
          textEditing.handleClick(screenPoint);
          return;
        }
      }
      // Click outside the text shape - stop editing and continue with normal handling
      textEditing.stopEditing(true);
      interactionMode.value = { type: 'idle' };
      // Don't return - continue with normal click handling below
    }

    // Check if clicking on a resize/rotate handle of selected shape
    if (state.selectedShapeId) {
      const selectedShape = state.annotations.find(s => s.id === state.selectedShapeId);
      if (selectedShape) {
        const bounds = getShapeBounds(selectedShape, imageSize.value ?? undefined);
        const shapeCenter = getShapeCenter(selectedShape);
        const aspectRatio = imageSize.value ? imageSize.value.width / imageSize.value.height : 1;
        const handle = hitTestResizeHandle(bounds, imagePoint, 0.025, selectedShape.rotation || 0, aspectRatio, shapeCenter);
        if (handle === 'rotate' && !selectedShape.disableRotate) {
          // Start rotating - use the actual shape center for rotation
          const centerX = shapeCenter.x;
          const centerY = shapeCenter.y;
          const startAngle = Math.atan2(imagePoint.y - centerY, imagePoint.x - centerX);
          interactionMode.value = {
            type: 'rotating-shape',
            shapeId: selectedShape.id,
            startAngle,
            originalRotation: selectedShape.rotation,
            centerPoint: { x: centerX, y: centerY },
          };
          return;
        } else if (handle && !selectedShape.disableResize) {
          // Start resizing
          interactionMode.value = {
            type: 'resizing-shape',
            shapeId: selectedShape.id,
            handle,
            startPoint: imagePoint,
            originalShape: { ...selectedShape },
          };
          return;
        }
      }
    }

    // Check if clicking on a shape (for potential move)
    const shapeAspectRatio = imageSize.value ? imageSize.value.width / imageSize.value.height : 1;
    const shapeUnderCursor = findShapeAtPoint(state.annotations, imagePoint, 0.01, shapeAspectRatio);

    // Enter pending mode - we'll decide on mouseup/mousemove if it's a click or drag
    interactionMode.value = {
      type: 'pending',
      startPoint: imagePoint,
      screenStart: screenPoint,
      shapeUnderCursor,
    };
  }

  /**
   * Handle mouse move on canvas
   */
  function handleMouseMove(event: MouseEvent) {
    const mode = interactionMode.value;
    const screenPoint = { x: event.clientX, y: event.clientY };
    const imagePoint = toImagePoint(screenPoint);
    if (!imagePoint) return;

    // Update cursor based on hover state
    if (mode.type === 'idle') {
      const state = getState();

      const aspectRatio = imageSize.value ? imageSize.value.width / imageSize.value.height : 1;

      // Check resize handles if shape is selected
      if (state.selectedShapeId) {
        const selectedShape = state.annotations.find(s => s.id === state.selectedShapeId);
        if (selectedShape && !selectedShape.disableResize) {
          const bounds = getShapeBounds(selectedShape, imageSize.value ?? undefined);
          const shapeCenter = getShapeCenter(selectedShape);
          const handle = hitTestResizeHandle(bounds, imagePoint, 0.025, selectedShape.rotation || 0, aspectRatio, shapeCenter);
          if (handle) {
            cursorStyle.value = getResizeHandleCursor(handle);
            return;
          }
        }
      }

      // Check if hovering over a shape (for move cursor)
      const hitShape = findShapeAtPoint(state.annotations, imagePoint, 0.01, aspectRatio);
      if (hitShape) {
        cursorStyle.value = hitShape.disableMove ? 'default' : 'move';
        return;
      }

      cursorStyle.value = state.activeTool === 'eraser' ? 'cell' : 'crosshair';
      return;
    }

    // Pending mode: check if we've moved beyond the drag threshold
    if (mode.type === 'pending') {
      const dx = screenPoint.x - mode.screenStart.x;
      const dy = screenPoint.y - mode.screenStart.y;
      const distance = Math.sqrt(dx * dx + dy * dy);

      if (distance > DRAG_THRESHOLD) {
        // Exceeded threshold - start drawing or moving
        if (mode.shapeUnderCursor && !mode.shapeUnderCursor.disableMove) {
          let shapeToMove = mode.shapeUnderCursor;

          // Option-drag: duplicate the shape first, then move the duplicate
          if (event.altKey) {
            const newId = generateShapeId();
            const duplicatedShape = structuredClone(mode.shapeUnderCursor) as Shape;
            duplicatedShape.id = newId;

            // Add the duplicate to annotations
            const state = getState();
            const annotations = [...state.annotations, duplicatedShape];
            updateState({ annotations });

            shapeToMove = duplicatedShape;
          }

          // Start moving the shape (original or duplicate) and switch to its tool
          const tool = shapeToTool(shapeToMove);
          const updates: Partial<AnnotationState> = { selectedShapeId: shapeToMove.id };
          if (tool) {
            updates.activeTool = tool;
          }
          updateState(updates);
          interactionMode.value = {
            type: 'moving-shape',
            shapeId: shapeToMove.id,
            startPoint: mode.startPoint,
            originalShape: { ...shapeToMove },
          };
        } else {
          // Start drawing with current tool
          startDrawing(mode.startPoint);
        }
      }
      return;
    }

    // Continue current interaction
    continueInteraction(imagePoint, event.shiftKey);
  }

  /**
   * Handle mouse up on canvas
   */
  function handleMouseUp(_event: MouseEvent) {
    const mode = interactionMode.value;

    // If still in pending mode, it was a click (not a drag)
    if (mode.type === 'pending') {
      // Click on a shape: select it and switch to its tool
      if (mode.shapeUnderCursor) {
        const tool = shapeToTool(mode.shapeUnderCursor);
        const updates: Partial<AnnotationState> = { selectedShapeId: mode.shapeUnderCursor.id };
        if (tool) {
          updates.activeTool = tool;
        }
        updateState(updates);
        interactionMode.value = { type: 'idle' };
        return;
      }

      // Text tool: clicking on empty space should start placing text
      const state = getState();
      if (state.activeTool === 'text') {
        startDrawing(mode.startPoint);
        return;
      }

      // Click on empty space: deselect
      updateState({ selectedShapeId: null });
      interactionMode.value = { type: 'idle' };
      return;
    }

    finishInteraction();
  }

  /**
   * Wrapper for keyboard events that checks if we're editing text
   */
  function handleKeyDownWrapper(event: KeyboardEvent) {
    if (handleKeyDown(event)) {
      event.preventDefault();
    }
  }

  /**
   * Setup annotation event listeners
   */
  function setupListeners() {
    const canvas = canvasRef.value;
    if (!canvas) return;

    canvas.addEventListener('mousedown', handleMouseDown);
    canvas.addEventListener('dblclick', handleDoubleClick);
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    window.addEventListener('keydown', handleKeyDownWrapper);
  }

  /**
   * Cleanup annotation event listeners
   */
  function cleanupListeners() {
    // Stop any active text editing
    if (interactionMode.value.type === 'editing-text-canvas' || textEditing.editState.value) {
      textEditing.stopEditing(true);
      interactionMode.value = { type: 'idle' };
    }

    const canvas = canvasRef.value;
    if (canvas) {
      canvas.removeEventListener('mousedown', handleMouseDown);
      canvas.removeEventListener('dblclick', handleDoubleClick);
    }
    window.removeEventListener('mousemove', handleMouseMove);
    window.removeEventListener('mouseup', handleMouseUp);
    window.removeEventListener('keydown', handleKeyDownWrapper);
  }

  /**
   * Handle double click (for editing text)
   */
  function handleDoubleClick(event: MouseEvent) {
    const screenPoint = { x: event.clientX, y: event.clientY };
    const imagePoint = toImagePoint(screenPoint);
    if (!imagePoint) return;

    const state = getState();
    const aspectRatio = imageSize.value ? imageSize.value.width / imageSize.value.height : 1;
    const shape = findShapeAtPoint(state.annotations, imagePoint, 0.01, aspectRatio);

    if (shape && shape.type === 'text') {
      // Start canvas-based text editing
      interactionMode.value = {
        type: 'editing-text-canvas',
        shapeId: shape.id,
      };
      updateState({ selectedShapeId: shape.id });
      textEditing.startEditing(shape.id);

      // Also do word selection at click point
      textEditing.handleDoubleClick(screenPoint);
    }
  }

  /**
   * Complete text entry (legacy - kept for API compatibility)
   * Text creation and editing is now handled directly via canvas-based editing
   */
  function completeText(_text: string) {
    // Canvas-based text editing handles text updates directly via updateShape
    // This function is kept for backwards compatibility
    interactionMode.value = { type: 'idle' };
  }

  /**
   * Cancel text entry (reverts changes)
   */
  function cancelText() {
    const mode = interactionMode.value;

    if (mode.type === 'editing-text-canvas') {
      // Stop canvas editing without committing
      textEditing.stopEditing(false);
    }

    interactionMode.value = { type: 'idle' };
  }

  /**
   * Commit text entry (keeps changes)
   */
  function commitText() {
    const mode = interactionMode.value;

    if (mode.type === 'editing-text-canvas' || textEditing.editState.value) {
      // Stop canvas editing and commit changes
      textEditing.stopEditing(true);
    }

    interactionMode.value = { type: 'idle' };
  }

  /**
   * Handle keyboard events for text editing
   * Returns true if the event was handled
   */
  function handleKeyDown(event: KeyboardEvent): boolean {
    const mode = interactionMode.value;

    // Handle canvas-based text editing
    if (mode.type === 'editing-text-canvas') {
      return textEditing.handleKeyDown(event);
    }

    return false;
  }

  /**
   * Start editing a text shape (for external calls like context menu)
   * @param selectAll - whether to select all text when entering edit mode (default true)
   */
  function startTextEditing(
    shapeId: string,
    initialCursor?: number,
    selectAll: boolean = true,
    autoFitWhileEditing: boolean = true
  ) {
    const shape = getState().annotations.find(s => s.id === shapeId);
    if (!shape || shape.type !== 'text') return;

    interactionMode.value = {
      type: 'editing-text-canvas',
      shapeId,
    };
    updateState({ selectedShapeId: shapeId });
    textEditing.startEditing(shapeId, initialCursor, selectAll, autoFitWhileEditing);
  }

  /**
   * Check if currently editing text on canvas
   */
  function isEditingTextOnCanvas(): boolean {
    // Check both interaction mode AND text edit state to be safe
    const modeIsEditing = interactionMode.value.type === 'editing-text-canvas';
    const hasEditState = textEditing.editState.value !== null;
    return modeIsEditing || hasEditState;
  }

  return {
    interactionMode,
    cursorStyle,
    setupListeners,
    cleanupListeners,
    getSelectedShape,
    updateShape,
    handleDoubleClick,
    completeText,
    cancelText,
    commitText,
    // Canvas-based text editing
    textEditState,
    handleKeyDown,
    startTextEditing,
    isEditingTextOnCanvas,
  };
}
