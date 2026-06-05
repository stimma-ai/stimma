import type {
  AspectRatioOption,
  CropGuide,
  EditorState,
  ExportOptions,
  ViewTransform,
} from './types';

/**
 * Hit testing radii in screen pixels (not affected by zoom)
 */
export const HIT_TEST = {
  handleRadius: 12,
  rotationRadius: 24,
  strokeTolerance: 4,
  edgeTolerance: 8,
} as const;

/**
 * Visual dimensions in screen pixels
 */
export const UI_SIZE = {
  handleSquare: 10,
  handleBorder: 2,
  rotationDistance: 30,
  rotationCircle: 8,
  selectionStroke: 1,
  cropStroke: 2,
  guideStroke: 1,
  minCropDimension: 20,
  minShapeDimension: 10,
  toolbarHeight: 48,
  tabsHeight: 56,
  panelWidth: 280,
  panelWidthMobile: '100%',
} as const;

/**
 * UI colors (CSS values)
 */
export const UI_COLOR = {
  handle: '#ffffff',
  handleBorder: '#000000',
  handleHover: '#3b82f6',
  handleActive: '#2563eb',
  selection: '#3b82f6',
  selectionFill: 'rgba(59, 130, 246, 0.1)',
  cropMask: 'rgba(0, 0, 0, 0.5)',
  cropBorder: '#ffffff',
  cropBorderActive: '#3b82f6',
  guideLine: 'rgba(255, 255, 255, 0.5)',
  guideLineDark: 'rgba(0, 0, 0, 0.3)',
} as const;

/**
 * Animation timing (milliseconds)
 */
export const TIMING = {
  zoomTransition: 200,
  panTransition: 150,
  cropAdjust: 100,
  filterDebounce: 50,
  sliderDebounce: 16, // ~60fps
  historyDebounce: 300,
} as const;

/**
 * Zoom configuration
 */
export const ZOOM_CONFIG = {
  min: 0.1,
  max: 10,
  default: 1,
  buttonStep: 0.25,
  wheelFactor: 0.003,
  pinchFactor: 1,
  doubleTapZoom: 2,
} as const;

/**
 * Touch gesture thresholds
 */
export const TOUCH_CONFIG = {
  tapMaxDuration: 200,
  tapMaxDistance: 10,
  doubleTapWindow: 300,
  longPressDelay: 500,
  panThreshold: 5,
  pinchThreshold: 10,
} as const;

/**
 * Canvas rendering
 */
export const RENDER_CONFIG = {
  maxPreviewSize: 2048,
  exportQualityDefault: 0.92,
  antialiasThreshold: 1.5,
} as const;

/**
 * Default crop rectangle (full image)
 */
export const DEFAULT_CROP = {
  x: 0.5,
  y: 0.5,
  width: 1,
  height: 1,
  aspectRatio: null,
} as const;

/**
 * Default editor state
 */
export const DEFAULT_EDITOR_STATE: EditorState = {
  src: null,
  imageSize: null,

  crop: { ...DEFAULT_CROP },
  rotation: 0,
  rotation90: 0,
  flipX: false,
  flipY: false,

  colorMatrix: null,
  brightness: 0,
  contrast: 0,
  saturation: 0,
  exposure: 0,
  temperature: 0,
  gamma: 1,

  filter: null,

  // Effects
  blur: 0,
  sharpen: 0,
  noise: 0,
  glow: 0,
  pixelate: 0,
  chromaticAberration: 0,
  motionBlur: 0,
  motionBlurAngle: 0,
  vignette: 0,
  clarity: 0,

  // Creative Effects

  // Split Toning
  splitToningEnabled: false,
  splitToningShadowHue: 30,          // Warm sepia-ish default
  splitToningShadowSat: 50,          // Default saturation when enabled
  splitToningHighlightHue: 200,      // Cool blue default
  splitToningHighlightSat: 50,       // Default saturation when enabled
  splitToningBalance: 0,             // Balanced

  // Gradient Map / Duotone
  gradientMapEnabled: false,
  gradientMapShadowColor: { r: 0, g: 0, b: 64, a: 1 },       // Deep blue
  gradientMapHighlightColor: { r: 255, g: 200, b: 100, a: 1 }, // Warm orange
  gradientMapIntensity: 100,

  // Color Isolation
  colorIsolationEnabled: false,
  colorIsolationHue: 0,              // Red
  colorIsolationRange: 30,           // 30 degrees
  colorIsolationFeather: 20,         // Smooth transition

  // Halftone
  halftone: 0,
  halftoneAngle: 0,

  // VHS / Analog
  vhs: 0,

  // Glitch
  glitch: 0,
  glitchBlockSize: 16,

  // Dither
  ditherEnabled: false,
  ditherPalette: 'none' as const,

  annotations: [],
  decorations: [],
  redactions: [],
  stickers: [],

  frame: null,

  backgroundColor: null,
  backgroundImage: null,

  targetSize: null,

  activePlugin: 'crop',
  activeTool: null,
  selectedShapeId: null,

  // Annotation tool defaults
  annotateStrokeColor: { r: 255, g: 255, b: 255, a: 1 }, // White
  annotateFillColor: null,
  annotateStrokeWidth: 8,
  annotateBrushSettings: {
    size: 8,
    hardness: 100,
    opacity: 100,
    flow: 100,
    spacing: 25,
    glow: 0,
    jitter: 0,
    scatter: 0,
  },
  annotateIsEraser: false,
  annotatePenId: 'marker',

  // Universal shape style defaults (neon, gradient for all shapes)
  annotateShapeEffect: 'none' as const,
  annotateGlowIntensity: 50,
  annotateGradientColors: [
    { r: 255, g: 107, b: 107, a: 1 },  // #ff6b6b
    { r: 254, g: 202, b: 87, a: 1 },   // #feca57
    { r: 255, g: 159, b: 243, a: 1 },  // #ff9ff3
  ],
  annotateGradientDirection: 'horizontal' as const,

  // Text tool defaults
  annotateTextFontFamily: 'Poppins',
  annotateTextFontSize: 32,
  annotateTextFontWeight: 'normal',
  annotateTextFontStyle: 'normal',
  annotateTextAlign: 'left',
  annotateTextBackgroundPadding: 0.1,        // 10% padding default
  annotateTextBackgroundCornerRadius: 0.3,   // 30% corner radius default
  annotateTextColor: { r: 255, g: 255, b: 255, a: 1 },     // White text
  annotateTextBgColor: null,   // Transparent background by default

  // Text effect defaults
  annotateTextEffect: 'none' as const,
  annotateTextGlowIntensity: 50,
  annotateTextGlowColor: null,
  annotateTextGradientColors: ['#ff6b6b', '#feca57', '#ff9ff3'],  // Sunset default
  annotateTextGradientDirection: 'horizontal' as const,
  annotateTextShadowDirection: 'bottom-right' as const,
  annotateTextShadowLength: 25,
  annotateTextShadowColor: null,  // Will default to darker version of text color
  annotateTextGlitchIntensity: 50,
  annotateTextKnockoutColor: { r: 0, g: 0, b: 0, a: 1 },  // Black knockout box

  // Redact tool defaults
  annotateRedactBlockSize: 16,

  // Polygon tool defaults
  annotatePolygonSides: 6,

  // Retouch defaults
  retouchLayerData: null,
  selectionMaskData: null,
  retouchTool: null,
  retouchBrushSettings: {
    size: 20,
    hardness: 50,
    opacity: 100,
    flow: 100,
    spacing: 25,
    glow: 0,
    jitter: 0,
    scatter: 0,
  },
  retouchCloneSource: null,
  retouchCloneOffset: null,
  selectionFeather: 0,
  wandTolerance: 32,
  selectionMode: 'new' as const,
  magneticLassoWidth: 40,
  magneticLassoContrast: 80,
  dodgeBurnExposure: 50,
  dodgeBurnRange: 'midtones',
  spongeFlow: 50,
  spongeMode: 'desaturate',
  blurSharpenStrength: 50,
  patchBlendWidth: 15, // Additional edge blend radius for patch tool

  // Persistent FG/BG colors for retouch (Photoshop-style)
  retouchForegroundColor: { r: 0, g: 0, b: 0, a: 1 },       // Black
  retouchBackgroundColor: { r: 255, g: 255, b: 255, a: 1 }, // White

  // View options
  hideAnnotationsInRetouch: false, // Show annotations by default
};

/**
 * Default view transform
 */
export const DEFAULT_VIEW_TRANSFORM: ViewTransform = {
  zoom: 1,
  panX: 0,
  panY: 0,
  rotation: 0,
};

/**
 * Default crop guide
 */
export const DEFAULT_CROP_GUIDE: CropGuide = 'rule-of-thirds';

/**
 * Default aspect ratio options
 */
export const DEFAULT_ASPECT_RATIOS: AspectRatioOption[] = [
  { label: 'Free', value: null },
  { label: 'Original', value: -1 },
  { label: '16:9', value: 16 / 9 },
  { label: '3:2', value: 3 / 2 },
  { label: '4:3', value: 4 / 3 },
  { label: '1:1', value: 1 },
  { label: '3:4', value: 3 / 4 },
  { label: '2:3', value: 2 / 3 },
  { label: '9:16', value: 9 / 16 },
];

/**
 * Default export options
 */
export const DEFAULT_EXPORT_OPTIONS: ExportOptions = {
  format: 'image/jpeg',
  quality: 0.92,
  backgroundColor: '#ffffff',
};

/**
 * History configuration
 */
export const HISTORY_CONFIG = {
  maxEntries: 50,
} as const;

/**
 * Filter preset matrices (5x4 color matrices)
 */
export const FILTER_MATRICES: Record<string, number[]> = {
  none: [
    1, 0, 0, 0, 0,
    0, 1, 0, 0, 0,
    0, 0, 1, 0, 0,
    0, 0, 0, 1, 0,
  ],
  chrome: [
    1.2, 0.1, 0.1, 0, -20,
    0.1, 1.1, 0.1, 0, -10,
    0.1, 0.1, 1.3, 0, -20,
    0, 0, 0, 1, 0,
  ],
  fade: [
    1, 0, 0, 0, 30,
    0, 1, 0, 0, 30,
    0, 0, 1, 0, 30,
    0, 0, 0, 0.9, 0,
  ],
  cold: [
    0.9, 0, 0.1, 0, 0,
    0, 0.95, 0.1, 0, 0,
    0.1, 0.1, 1.2, 0, 10,
    0, 0, 0, 1, 0,
  ],
  warm: [
    1.2, 0.1, 0, 0, 10,
    0.1, 1.05, 0, 0, 5,
    0, 0, 0.9, 0, -10,
    0, 0, 0, 1, 0,
  ],
  pastel: [
    1.1, 0.1, 0.1, 0, 20,
    0.1, 1.1, 0.1, 0, 20,
    0.1, 0.1, 1.1, 0, 20,
    0, 0, 0, 1, 0,
  ],
  mono: [
    0.33, 0.33, 0.33, 0, 0,
    0.33, 0.33, 0.33, 0, 0,
    0.33, 0.33, 0.33, 0, 0,
    0, 0, 0, 1, 0,
  ],
  noir: [
    0.4, 0.4, 0.2, 0, -20,
    0.3, 0.4, 0.2, 0, -10,
    0.2, 0.3, 0.4, 0, 0,
    0, 0, 0, 1, 0,
  ],
  stark: [
    0.5, 0.5, 0.5, 0, -50,
    0.5, 0.5, 0.5, 0, -50,
    0.5, 0.5, 0.5, 0, -50,
    0, 0, 0, 1, 0,
  ],
  sepia: [
    0.393, 0.769, 0.189, 0, 0,
    0.349, 0.686, 0.168, 0, 0,
    0.272, 0.534, 0.131, 0, 0,
    0, 0, 0, 1, 0,
  ],
  vintage: [
    0.9, 0.2, 0.1, 0, 20,
    0.1, 0.8, 0.2, 0, 15,
    0.1, 0.1, 0.7, 0, 30,
    0, 0, 0, 1, 0,
  ],
  vivid: [
    1.3, -0.1, -0.1, 0, 0,
    -0.1, 1.3, -0.1, 0, 0,
    -0.1, -0.1, 1.3, 0, 0,
    0, 0, 0, 1, 0,
  ],
  dramatic: [
    1.3, -0.1, -0.1, 0, -20,
    -0.1, 1.3, -0.1, 0, -20,
    -0.1, -0.1, 1.3, 0, -20,
    0, 0, 0, 1, 0,
  ],

  // Film Emulation Filters

  // Portra 400: Warm, creamy skin tones, lifted shadows, muted greens
  'portra-400': [
    1.05, 0.08, 0.02, 0, 8,
    0.02, 1.0, 0.05, 0, 6,
    -0.02, 0.05, 0.92, 0, 15,
    0, 0, 0, 1, 0,
  ],

  // Velvia: High saturation, punchy blues/greens, deep shadows
  velvia: [
    1.2, -0.05, -0.05, 0, -15,
    -0.05, 1.15, -0.05, 0, -10,
    -0.05, 0.05, 1.3, 0, -20,
    0, 0, 0, 1, 0,
  ],

  // Kodachrome: Rich reds, unique cyan-blue shadows, golden tones
  kodachrome: [
    1.15, 0.1, -0.05, 0, 5,
    0.05, 1.05, 0.0, 0, 0,
    -0.05, 0.1, 1.1, 0, 10,
    0, 0, 0, 1, 0,
  ],

  // Cinestill 800T: Tungsten-balanced, teal highlights, warm shadows
  'cinestill-800t': [
    0.95, 0.05, 0.1, 0, 10,
    0.0, 1.0, 0.1, 0, 5,
    0.1, 0.1, 1.15, 0, 0,
    0, 0, 0, 1, 0,
  ],

  // Polaroid 600: Faded, lifted blacks, subtle yellow/teal split
  'polaroid-600': [
    1.0, 0.05, 0.0, 0, 25,
    0.02, 0.98, 0.05, 0, 20,
    0.0, 0.08, 0.9, 0, 30,
    0, 0, 0, 0.95, 0,
  ],

  // Tri-X 400: Classic B&W with rich midtones and distinctive grain curve
  'tri-x-400': [
    0.35, 0.45, 0.2, 0, 0,
    0.35, 0.45, 0.2, 0, 0,
    0.35, 0.45, 0.2, 0, 0,
    0, 0, 0, 1, 0,
  ],
};

/**
 * Default filter options for the filter plugin
 */
/**
 * Filter categories for organized display
 */
export const FILTER_CATEGORIES = [
  {
    id: 'none',
    label: '',
    filters: [
      { id: 'none', label: 'None' },
    ],
  },
  {
    id: 'color',
    label: 'Color',
    filters: [
      { id: 'chrome', label: 'Chrome' },
      { id: 'vivid', label: 'Vivid' },
      { id: 'dramatic', label: 'Dramatic' },
      { id: 'cold', label: 'Cold' },
      { id: 'warm', label: 'Warm' },
      { id: 'pastel', label: 'Pastel' },
      { id: 'fade', label: 'Fade' },
      { id: 'vintage', label: 'Vintage' },
    ],
  },
  {
    id: 'bw',
    label: 'Black & White',
    filters: [
      { id: 'mono', label: 'Mono' },
      { id: 'noir', label: 'Noir' },
      { id: 'stark', label: 'Stark' },
      { id: 'tri-x-400', label: 'Tri-X 400' },
      { id: 'sepia', label: 'Sepia' },
    ],
  },
  {
    id: 'film',
    label: 'Film',
    filters: [
      { id: 'portra-400', label: 'Portra 400' },
      { id: 'velvia', label: 'Velvia' },
      { id: 'kodachrome', label: 'Kodachrome' },
      { id: 'cinestill-800t', label: 'Cinestill' },
      { id: 'polaroid-600', label: 'Polaroid' },
    ],
  },
];

/**
 * Flat list of all filters (for backwards compatibility)
 */
export const DEFAULT_FILTERS = FILTER_CATEGORIES.flatMap(cat => cat.filters);
