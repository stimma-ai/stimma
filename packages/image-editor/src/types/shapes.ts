import type { Color, Point } from './geometry';
import type { IconName } from '@/components/icons';

/**
 * Brush settings for path drawing
 */
export interface BrushSettings {
  size: number;       // 1-100 pixels
  hardness: number;   // 0-100 (0=soft/fuzzy, 100=hard edge)
  opacity: number;    // 0-100
  flow: number;       // 0-100 (paint amount per stamp - lower = more transparent buildup)
  spacing: number;    // 0-100 (% of brush size between stamps - affects texture)
  glow?: number;      // 0-100 (neon glow intensity - 0=none, 100=max glow)
  jitter?: number;    // 0-100 (position randomness for chalk/spatter effects)
  scatter?: number;   // 0-100 (additional random stamps for spatter effect)
}

/**
 * Brush preset definition
 */
export interface BrushPreset {
  id: string;
  name: string;
  icon: IconName;
  settings: BrushSettings;
  isEraser?: boolean;
}

/**
 * Line end styles for arrows
 */
export type LineEndStyle =
  | 'none'
  | 'arrow'
  | 'arrow-solid'
  | 'circle'
  | 'circle-solid'
  | 'square'
  | 'square-solid'
  | 'bar';

/**
 * Base shape properties shared by all shapes
 */
export interface BaseShape {
  id: string;
  x: number; // Position (0-1 relative in image space)
  y: number;
  rotation: number; // radians
  opacity: number; // 0-1

  // Universal style (neon, gradient effects)
  style?: ShapeStyle;

  // Interaction locks
  disableSelect?: boolean;
  disableMove?: boolean;
  disableResize?: boolean;
  disableRotate?: boolean;
  disableRemove?: boolean;
}

export interface RectangleShape extends BaseShape {
  type: 'rectangle';
  width: number;
  height: number;
  cornerRadius?: number;
  backgroundColor?: Color;
  strokeColor?: Color;
  strokeWidth?: number;
}

export interface EllipseShape extends BaseShape {
  type: 'ellipse';
  rx: number; // x radius
  ry: number; // y radius
  backgroundColor?: Color;
  strokeColor?: Color;
  strokeWidth?: number;
}

export interface LineShape extends BaseShape {
  type: 'line';
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  strokeColor: Color;
  strokeWidth: number;
  lineStart?: LineEndStyle;
  lineEnd?: LineEndStyle;
}

export interface CurvedArrowShape extends BaseShape {
  type: 'curved-arrow';
  rawPoints: Point[];      // Mouse path points (normalized 0-1)
  smoothedPath: Point[];   // Bezier control points for rendering
  strokeColor: Color;
  strokeWidth: number;
  lineEnd: LineEndStyle;
}

export interface PathShape extends BaseShape {
  type: 'path';
  points: Point[];
  strokeColor: Color;
  strokeWidth: number;
  closed?: boolean;
  backgroundColor?: Color; // Only if closed
  // Brush properties
  hardness?: number;   // 0-100 (default 100 = hard edge)
  flow?: number;       // 0-100 (default 100 = full paint)
  spacing?: number;    // 0-100 (default 25 = smooth stroke)
  glow?: number;       // 0-100 (neon glow intensity)
  jitter?: number;     // 0-100 (position randomness)
  scatter?: number;    // 0-100 (random extra stamps)
  isEraser?: boolean;  // If true, uses destination-out composite
  penId?: string;      // ID of the pen preset used to create this path
}

export interface StickerShape extends BaseShape {
  type: 'sticker';
  src: string; // URL or data URL of sticker image
  width: number; // Size in image space (0-1)
  height: number;
  flipX?: boolean;
  flipY?: boolean;
}

/**
 * Base font size for measuring text - text is always measured at this size
 * and then scaled using canvas transforms
 */
export const TEXT_BASE_FONT_SIZE = 100;

/**
 * Text effect types for social media-style text styling
 */
export type TextEffect = 'none' | 'outline' | 'neon' | 'gradient' | 'shadow' | 'glitch' | 'knockout';

/**
 * Gradient direction for text gradient effect
 */
export type GradientDirection = 'horizontal' | 'vertical' | 'diagonal';

/**
 * Universal shape effect types (apply to all annotation types)
 */
export type ShapeEffect = 'none' | 'neon' | 'gradient';

/**
 * Universal style settings for shapes, arrows, text, and pen strokes
 */
export interface ShapeStyle {
  effect?: ShapeEffect;

  // Neon settings
  glowIntensity?: number;  // 0-100
  glowColor?: Color;       // defaults to stroke/text color

  // Gradient settings
  gradientColors?: Color[];           // 2-3 colors
  gradientDirection?: GradientDirection;
}

/**
 * Shadow direction for long shadow effect
 */
export type ShadowDirection = 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left';

/**
 * Gradient preset for quick selection
 */
export interface GradientPreset {
  id: string;
  name: string;
  colors: string[]; // CSS color strings
}

/**
 * Built-in gradient presets
 */
export const GRADIENT_PRESETS: GradientPreset[] = [
  { id: 'sunset', name: 'Sunset', colors: ['#ff6b6b', '#feca57', '#ff9ff3'] },
  { id: 'ocean', name: 'Ocean', colors: ['#0abde3', '#10ac84', '#48dbfb'] },
  { id: 'purple', name: 'Purple', colors: ['#a55eea', '#5f27cd', '#341f97'] },
  { id: 'fire', name: 'Fire', colors: ['#f9ca24', '#f0932b', '#eb4d4b'] },
  { id: 'neon-pink', name: 'Neon Pink', colors: ['#fd79a8', '#e84393', '#6c5ce7'] },
  { id: 'mint', name: 'Mint', colors: ['#00b894', '#55efc4', '#81ecec'] },
  { id: 'gold', name: 'Gold', colors: ['#f1c40f', '#e67e22', '#d35400'] },
  { id: 'rainbow', name: 'Rainbow', colors: ['#e74c3c', '#f39c12', '#2ecc71', '#3498db', '#9b59b6'] },
  { id: 'cosmic', name: 'Cosmic', colors: ['#0f0c29', '#302b63', '#24243e'] },
  { id: 'peach', name: 'Peach', colors: ['#ffecd2', '#fcb69f', '#ff9a9e'] },
  { id: 'arctic', name: 'Arctic', colors: ['#e0eafc', '#cfdef3', '#a8c0ff'] },
  { id: 'lime', name: 'Lime', colors: ['#a8e063', '#56ab2f', '#1d976c'] },
];

export interface TextShape extends BaseShape {
  type: 'text';
  text: string;                    // Content (supports \n for line breaks)

  // Bounding box (normalized 0-1) - this is the DISPLAY size
  width: number;
  height: number;

  // Reference dimensions at BASE_FONT_SIZE (normalized 0-1)
  // These capture the "natural" size when text was created/edited
  baseWidth: number;
  baseHeight: number;

  // Typography (no fontSize - scale derived from width/height vs base)
  fontFamily: string;              // e.g., 'Arial'
  fontWeight: 'normal' | 'bold';
  fontStyle: 'normal' | 'italic';
  textAlign: 'left' | 'center' | 'right';

  // Colors
  textColor: Color;
  backgroundColor?: Color;         // Optional background box
  strokeColor?: Color;             // Optional text outline
  strokeWidth?: number;

  // Background styling (only applies when backgroundColor is set)
  backgroundPadding?: number;           // 0..1, scales with text height
  backgroundCornerRadius?: number;      // 0..1, 1 = fully rounded

  // Text effects (social media style)
  textEffect?: TextEffect;              // 'none' | 'outline' | 'neon' | 'gradient'

  // Neon effect settings
  glowIntensity?: number;               // 0-100, glow strength
  glowColor?: Color;                    // Glow color (defaults to textColor)

  // Gradient effect settings
  gradientColors?: string[];            // Array of CSS color strings
  gradientDirection?: GradientDirection; // 'horizontal' | 'vertical' | 'diagonal'

  // Long shadow effect settings
  shadowDirection?: ShadowDirection;    // Direction of the shadow
  shadowLength?: number;                // 0-100, how far the shadow extends
  shadowColor?: Color;                  // Shadow color (defaults to darker textColor)

  // Glitch effect settings
  glitchIntensity?: number;             // 0-100, offset amount

  // Knockout effect settings
  knockoutColor?: Color;                // Background box color for knockout
}

export interface RedactShape extends BaseShape {
  type: 'redact';
  width: number;                   // Bounding box (normalized 0-1)
  height: number;
  blockSize: number;               // Pixelation block size (4-48 pixels)
}

export interface TriangleShape extends BaseShape {
  type: 'triangle';
  width: number;
  height: number;
  backgroundColor?: Color;
  strokeColor?: Color;
  strokeWidth?: number;
}

export interface StarShape extends BaseShape {
  type: 'star';
  outerRadius: number;             // Outer radius (normalized 0-1)
  innerRadius: number;             // Inner radius (normalized 0-1)
  points: number;                  // Number of points (5 = classic 5-pointed star)
  aspectRatio?: number;            // Width/height aspect ratio (1.0 = regular, default)
  backgroundColor?: Color;
  strokeColor?: Color;
  strokeWidth?: number;
}

export interface PolygonShape extends BaseShape {
  type: 'polygon';
  radius: number;                  // Radius (normalized 0-1)
  sides: number;                   // Number of sides (3 = triangle, 6 = hexagon, etc.)
  aspectRatio?: number;            // Width/height aspect ratio (1.0 = regular, default)
  backgroundColor?: Color;
  strokeColor?: Color;
  strokeWidth?: number;
}

export type Shape =
  | RectangleShape
  | EllipseShape
  | LineShape
  | CurvedArrowShape
  | PathShape
  | StickerShape
  | TextShape
  | RedactShape
  | TriangleShape
  | StarShape
  | PolygonShape;

/**
 * Annotation tool types
 */
export type AnnotateTool =
  | 'select'
  | 'sharpie'
  | 'eraser'
  | 'path'
  | 'line'
  | 'arrow'
  | 'rectangle'
  | 'ellipse'
  | 'triangle'
  | 'star'
  | 'polygon'
  | 'text'
  | 'redact';

/**
 * Resize handle positions
 */
export type ResizeHandle = 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w' | 'rotate';
