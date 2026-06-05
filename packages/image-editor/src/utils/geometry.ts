import type { Point, Rect } from '@/types';

/**
 * Calculate distance between two points
 */
export function distance(p1: Point, p2: Point): number {
  const dx = p2.x - p1.x;
  const dy = p2.y - p1.y;
  return Math.sqrt(dx * dx + dy * dy);
}

/**
 * Calculate angle between two points (in radians)
 */
export function angle(p1: Point, p2: Point): number {
  return Math.atan2(p2.y - p1.y, p2.x - p1.x);
}

/**
 * Rotate a point around an origin
 */
export function rotatePoint(
  point: Point,
  origin: Point,
  angle: number
): Point {
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  const dx = point.x - origin.x;
  const dy = point.y - origin.y;
  return {
    x: origin.x + dx * cos - dy * sin,
    y: origin.y + dx * sin + dy * cos,
  };
}

/**
 * Clamp a value between min and max
 */
export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

/**
 * Linear interpolation
 */
export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/**
 * Check if a point is inside a rectangle
 */
export function pointInRect(point: Point, rect: Rect): boolean {
  return (
    point.x >= rect.x &&
    point.x <= rect.x + rect.width &&
    point.y >= rect.y &&
    point.y <= rect.y + rect.height
  );
}

/**
 * Get the center of a rectangle
 */
export function rectCenter(rect: Rect): Point {
  return {
    x: rect.x + rect.width / 2,
    y: rect.y + rect.height / 2,
  };
}

/**
 * Normalize angle to 0-2π range
 */
export function normalizeAngle(angle: number): number {
  const twoPi = Math.PI * 2;
  return ((angle % twoPi) + twoPi) % twoPi;
}

/**
 * Convert degrees to radians
 */
export function degToRad(degrees: number): number {
  return (degrees * Math.PI) / 180;
}

/**
 * Convert radians to degrees
 */
export function radToDeg(radians: number): number {
  return (radians * 180) / Math.PI;
}

/**
 * Remap point for 90° clockwise rotation
 */
export function remapFor90CW(point: Point): Point {
  return { x: 1 - point.y, y: point.x };
}

/**
 * Remap point for 90° counter-clockwise rotation
 */
export function remapFor90CCW(point: Point): Point {
  return { x: point.y, y: 1 - point.x };
}

/**
 * Flip point horizontally (mirror around x=0.5)
 */
export function flipHorizontal(point: Point): Point {
  return { x: 1 - point.x, y: point.y };
}

/**
 * Flip point vertically (mirror around y=0.5)
 */
export function flipVertical(point: Point): Point {
  return { x: point.x, y: 1 - point.y };
}
