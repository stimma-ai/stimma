/**
 * Basic geometry types used throughout the editor
 */

export interface Point {
  x: number;
  y: number;
}

export interface Size {
  width: number;
  height: number;
}

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * Color can be specified in multiple formats
 */
export type Color =
  | string // CSS color: '#ff0000', 'rgb(255,0,0)', 'red'
  | { r: number; g: number; b: number; a?: number }; // RGBA object (0-255)

/**
 * Convert color to CSS string
 */
export function colorToCss(color: Color): string {
  if (typeof color === 'string') return color;
  const { r, g, b, a = 1 } = color;
  return a === 1 ? `rgb(${r},${g},${b})` : `rgba(${r},${g},${b},${a})`;
}

/**
 * Image source types accepted by the editor
 */
export type ImageSource =
  | string // URL or data URL
  | File // File from input or drag-drop
  | Blob // Binary blob
  | HTMLImageElement // Existing image element
  | HTMLCanvasElement // Existing canvas
  | ImageBitmap; // ImageBitmap for performance
