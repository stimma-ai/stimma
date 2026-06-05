import type { Color, ImageSource, Point, Size } from './geometry';
import type { Shape, StickerShape, BrushSettings, ShapeEffect, GradientDirection } from './shapes';

/**
 * Retouch tool types
 */
export type RetouchTool =
  | 'clone'
  | 'spot-heal'
  | 'patch'
  | 'dodge'
  | 'burn'
  | 'sponge'
  | 'blur-brush'
  | 'sharpen-brush'
  | 'paint'
  | 'fill'
  | 'marquee-rect'
  | 'marquee-ellipse'
  | 'lasso'
  | 'magnetic-lasso'
  | 'wand';

/**
 * Sponge tool mode
 */
export type SpongeMode = 'saturate' | 'desaturate';

/**
 * Selection mode for combining selections
 */
export type SelectionMode = 'new' | 'add' | 'subtract' | 'intersect';

/**
 * Dodge/Burn tonal range
 */
export type DodgeBurnRange = 'shadows' | 'midtones' | 'highlights';

/**
 * Crop rectangle definition
 */
export interface CropRect {
  // Position of crop rect center in image space (0-1)
  x: number; // 0 = left edge, 1 = right edge
  y: number; // 0 = top edge, 1 = bottom edge

  // Size relative to image dimensions
  width: number; // 0-1+ (can exceed 1 if cropLimitToImage=false)
  height: number;

  // Aspect ratio lock (null = free crop)
  aspectRatio: number | null;

  // Rotation of the crop rect in radians (0 = no rotation)
  rotation?: number;
}

/**
 * Transform state for rotation and flip
 */
export interface TransformState {
  rotation: number; // Fine rotation in radians (-π/4 to π/4)
  rotation90: 0 | 1 | 2 | 3; // Number of 90° CW rotations
  flipX: boolean;
  flipY: boolean;
}

/**
 * View transform for zoom and pan
 */
export interface ViewTransform {
  zoom: number; // Scale factor (1 = fit to canvas)
  panX: number; // Horizontal offset in canvas pixels
  panY: number; // Vertical offset in canvas pixels
  rotation: number; // View rotation in radians (for preview only)
}

/**
 * Crop guide overlay type
 */
export type CropGuide =
  | 'none'
  | 'rule-of-thirds'
  | 'golden-ratio'
  | 'diagonal'
  | 'center';

/**
 * Frame style configuration
 */
export interface FrameStyle {
  type: 'none' | 'mat' | 'bevel' | 'line' | 'hook' | 'polaroid' | 'custom';

  // Common options
  color?: Color;
  size?: number;
  sizeUnit?: 'px' | '%';

  // Mat frame options
  matInnerColor?: Color;
  matInnerSize?: number;

  // Bevel frame options
  bevelHighlight?: Color;
  bevelShadow?: Color;

  // Line frame options
  lineWidth?: number;
  lineStyle?: 'solid' | 'dashed' | 'dotted';

  // Hook frame options
  hookLength?: number;
  hookWidth?: number;

  // Polaroid frame options
  polaroidBottom?: number;

  // Custom frame
  customRenderer?: (ctx: CanvasRenderingContext2D, bounds: { x: number; y: number; width: number; height: number }) => void;
}

/**
 * Aspect ratio option for crop
 */
export interface AspectRatioOption {
  label: string;
  value: number | null; // Ratio (width/height), null = free, -1 = original
}

/**
 * Filter option
 */
export interface FilterOption {
  id: string;
  label: string;
  matrix: number[]; // 5x4 color matrix
  thumbnail?: string;
}

/**
 * Sticker group for organization
 */
export interface StickerGroup {
  id: string;
  label: string;
  stickers: StickerPreset[];
}

export interface StickerPreset {
  src: string;
  label?: string;
  width?: number;
  height?: number;
}

/**
 * Fill option for background
 */
export interface FillOption {
  type: 'color' | 'transparent' | 'pattern';
  color?: Color;
  pattern?: string;
  label: string;
}

/**
 * Main editor state
 */
export interface EditorState {
  // Source image
  src: ImageSource | null;
  imageSize: Size | null;

  // Crop & Transform
  crop: CropRect;
  rotation: number; // radians (fine rotation)
  rotation90: 0 | 1 | 2 | 3;
  flipX: boolean;
  flipY: boolean;

  // Color adjustments
  colorMatrix: number[] | null;
  brightness: number;
  contrast: number;
  saturation: number;
  exposure: number;
  temperature: number;
  gamma: number;

  // Active filter
  filter: string | null;

  // Effects
  blur: number;
  sharpen: number;
  noise: number;
  glow: number;
  pixelate: number;
  chromaticAberration: number;
  motionBlur: number;
  motionBlurAngle: number;
  vignette: number;
  clarity: number;

  // Creative Effects

  // Split Toning: Add color tints to shadows and highlights
  splitToningEnabled: boolean;
  splitToningShadowHue: number;      // 0-360
  splitToningShadowSat: number;      // 0-100
  splitToningHighlightHue: number;   // 0-360
  splitToningHighlightSat: number;   // 0-100
  splitToningBalance: number;        // -100 to 100 (negative = more shadow, positive = more highlight)

  // Gradient Map / Duotone: Map luminance to a 2-color gradient
  gradientMapEnabled: boolean;
  gradientMapShadowColor: { r: number; g: number; b: number; a?: number };     // Shadow color
  gradientMapHighlightColor: { r: number; g: number; b: number; a?: number };  // Highlight color
  gradientMapIntensity: number;      // 0-100

  // Color Isolation: Keep selected hue, desaturate rest
  colorIsolationEnabled: boolean;
  colorIsolationHue: number;         // 0-360
  colorIsolationRange: number;       // 0-180 (degrees of hue range to keep)
  colorIsolationFeather: number;     // 0-100 (transition softness)

  // Halftone: CMYK-style dot pattern
  halftone: number;                  // 0-100 (0 = off, dot size increases)
  halftoneAngle: number;             // 0-90 degrees

  // VHS / Analog: Retro analog distortion
  vhs: number;                       // 0-100 intensity

  // Glitch: Random RGB channel displacement
  glitch: number;                    // 0-100 intensity
  glitchBlockSize: number;           // 8-64 block size in pixels

  // Dither: Retro dithering effect
  ditherEnabled: boolean;
  ditherPalette: 'none' | 'bw' | '4bit' | '8bit' | 'gameboy' | 'cga';  // Color palette ('none' = disabled)

  // Shapes
  annotations: Shape[];
  decorations: Shape[];
  redactions: Shape[];

  // Stickers
  stickers: StickerShape[];

  // Frame
  frame: FrameStyle | null;

  // Fill/Background
  backgroundColor: Color | null;
  backgroundImage: string | null;

  // Output
  targetSize: Size | null;

  // UI State
  activePlugin: string;
  activeTool: string | null;
  selectedShapeId: string | null;

  // Annotation tool settings
  annotateStrokeColor: Color;
  annotateFillColor: Color | null;
  annotateStrokeWidth: number;
  annotateBrushSettings: BrushSettings;
  annotateIsEraser: boolean;
  annotatePenId: string;

  // Universal shape style settings (neon, gradient for all shapes)
  annotateShapeEffect: ShapeEffect;
  annotateGlowIntensity: number;        // 0-100
  annotateGradientColors: Color[];      // 2-3 colors
  annotateGradientDirection: GradientDirection;

  // Text tool settings
  annotateTextFontFamily: string;
  annotateTextFontSize: number;
  annotateTextFontWeight: 'normal' | 'bold';
  annotateTextFontStyle: 'normal' | 'italic';
  annotateTextAlign: 'left' | 'center' | 'right';
  annotateTextBackgroundPadding: number;
  annotateTextBackgroundCornerRadius: number;
  annotateTextColor: Color;           // Text-specific color (separate from stroke)
  annotateTextBgColor: Color | null;  // Text-specific background (separate from fill)

  // Text effect settings
  annotateTextEffect: 'none' | 'outline' | 'neon' | 'gradient' | 'shadow' | 'glitch' | 'knockout';
  annotateTextGlowIntensity: number;  // 0-100
  annotateTextGlowColor: Color | null;
  annotateTextGradientColors: string[];
  annotateTextGradientDirection: 'horizontal' | 'vertical' | 'diagonal';
  annotateTextShadowDirection: 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left';
  annotateTextShadowLength: number;   // 0-100
  annotateTextShadowColor: Color | null;
  annotateTextGlitchIntensity: number; // 0-100
  annotateTextKnockoutColor: Color;

  // Redact tool settings
  annotateRedactBlockSize: number;

  // Polygon tool settings
  annotatePolygonSides: number;

  // Retouch layer (canvas snapshot for history, data URL string for serialization)
  retouchLayerData: HTMLCanvasElement | string | null;

  // Selection mask (canvas snapshot for history, data URL string for serialization)
  selectionMaskData: HTMLCanvasElement | string | null;

  // Current retouch tool
  retouchTool: RetouchTool | null;
  retouchBrushSettings: BrushSettings;
  retouchCloneSource: Point | null;     // For clone stamp (image-space coords)
  retouchCloneOffset: Point | null;     // Offset from cursor to source

  // Selection settings
  selectionFeather: number;             // Feather radius in pixels
  wandTolerance: number;                // Magic wand color tolerance (0-255)
  selectionMode: SelectionMode;         // Combine mode for selections (new, add, subtract, intersect)

  // Magnetic lasso settings
  magneticLassoWidth: number;           // Detection corridor width (1-40px, default: 10)
  magneticLassoContrast: number;        // Edge sensitivity 1-100 (default: 50)

  // Dodge/Burn settings
  dodgeBurnExposure: number;            // Strength of effect (0-100)
  dodgeBurnRange: DodgeBurnRange;

  // Sponge settings
  spongeFlow: number;                   // Strength of saturation change (0-100)
  spongeMode: SpongeMode;               // saturate or desaturate

  // Blur/Sharpen strength
  blurSharpenStrength: number;          // 0-100

  // Patch tool settings
  patchBlendWidth: number;              // Additional edge blend radius (0-50px)

  // Persistent FG/BG colors for retouch (Photoshop-style, persists across tools)
  retouchForegroundColor: { r: number; g: number; b: number; a: number };
  retouchBackgroundColor: { r: number; g: number; b: number; a: number };

  // View options
  hideAnnotationsInRetouch: boolean;  // Hide annotation layer when in retouch mode
}

/**
 * Interaction state machine types
 */
export type CropHandle =
  | 'n'
  | 's'
  | 'e'
  | 'w'
  | 'ne'
  | 'nw'
  | 'se'
  | 'sw'
  | 'center'
  | 'rotation';

import type { ResizeHandle } from './shapes';

export type InteractionState =
  | { type: 'idle' }
  | { type: 'panning'; startPan: Point; startMouse: Point; startCrop?: CropRect }
  | { type: 'zooming'; startZoom: number; startDistance: number }
  | {
      type: 'crop-dragging';
      handle: CropHandle;
      startRect: CropRect;
      startMouse: Point;
    }
  | { type: 'crop-rotating'; startAngle: number; startRotation: number }
  | { type: 'shape-selected'; shapeId: string }
  | {
      type: 'shape-moving';
      shapeId: string;
      startPos: Point;
      startMouse: Point;
    }
  | {
      type: 'shape-resizing';
      shapeId: string;
      handle: ResizeHandle;
      startBounds: { x: number; y: number; width: number; height: number };
      startMouse: Point;
    }
  | {
      type: 'shape-rotating';
      shapeId: string;
      startAngle: number;
      startRotation: number;
    }
  | { type: 'shape-drawing'; tool: string; points: Point[] };

/**
 * Hit test result
 */
export interface HitTestResult {
  type:
    | 'none'
    | 'crop-handle'
    | 'crop-area'
    | 'shape-handle'
    | 'shape-body'
    | 'canvas';
  handle?: CropHandle | ResizeHandle;
  shapeId?: string;
}

/**
 * History entry for undo/redo
 */
export interface HistoryEntry {
  state: EditorState;
  timestamp: number;
  action: string;
}

/**
 * Export options
 */
export interface ExportOptions {
  format: 'image/jpeg' | 'image/png' | 'image/webp';
  quality: number; // 0-1 for JPEG/WebP
  maxWidth?: number;
  maxHeight?: number;
  backgroundColor?: string; // For JPEG (no transparency)
}

/**
 * Load result
 */
export interface LoadResult {
  imageSize: Size;
  src: ImageSource;
}

/**
 * Load progress
 */
export interface LoadProgress {
  loaded: number;
  total: number;
}

/**
 * Process result
 */
export interface ProcessResult {
  dest: Blob;
  imageSize: Size;
}

/**
 * Process progress
 */
export interface ProcessProgress {
  stage: string;
  progress: number;
}

/**
 * User preferences - subset of EditorState for persistence across sessions.
 * These settings are tool preferences that users typically want remembered.
 */
export type EditorSettings = Pick<EditorState,
  // Annotation colors/stroke
  | 'annotateStrokeColor'
  | 'annotateFillColor'
  | 'annotateStrokeWidth'
  | 'annotateBrushSettings'
  | 'annotateIsEraser'
  | 'annotatePenId'
  // Universal shape style settings
  | 'annotateShapeEffect'
  | 'annotateGlowIntensity'
  | 'annotateGradientColors'
  | 'annotateGradientDirection'
  // Text settings
  | 'annotateTextFontFamily'
  | 'annotateTextFontSize'
  | 'annotateTextFontWeight'
  | 'annotateTextFontStyle'
  | 'annotateTextAlign'
  | 'annotateTextBackgroundPadding'
  | 'annotateTextBackgroundCornerRadius'
  | 'annotateTextColor'
  | 'annotateTextBgColor'
  // Text effect settings
  | 'annotateTextEffect'
  | 'annotateTextGlowIntensity'
  | 'annotateTextGlowColor'
  | 'annotateTextGradientColors'
  | 'annotateTextGradientDirection'
  | 'annotateTextShadowDirection'
  | 'annotateTextShadowLength'
  | 'annotateTextShadowColor'
  | 'annotateTextGlitchIntensity'
  | 'annotateTextKnockoutColor'
  // Redact settings
  | 'annotateRedactBlockSize'
  // Polygon settings
  | 'annotatePolygonSides'
  // Retouch settings
  | 'retouchBrushSettings'
  | 'selectionFeather'
  | 'wandTolerance'
  | 'dodgeBurnExposure'
  | 'dodgeBurnRange'
  | 'spongeFlow'
  | 'spongeMode'
  | 'blurSharpenStrength'
  | 'patchBlendWidth'
  | 'retouchForegroundColor'
  | 'retouchBackgroundColor'
  // Magnetic lasso settings
  | 'magneticLassoWidth'
  | 'magneticLassoContrast'
>;

/**
 * Extended settings type for localStorage persistence.
 * Includes EditorSettings plus last selected tools for each mode.
 */
export interface PersistedSettings extends EditorSettings {
  /** Last selected tool in annotate mode (restored when entering annotate) */
  lastAnnotateTool: string | null;
  /** Last selected tool in retouch mode (restored when entering retouch) */
  lastRetouchTool: RetouchTool | null;
  /** Last active plugin/tab (restored when opening a new editor) */
  lastActivePlugin: string | null;
}
