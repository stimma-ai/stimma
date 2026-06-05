import type { Point, Size, ViewTransform } from '@/types';

/**
 * Create a canvas with the specified size
 */
export function createCanvas(width: number, height: number): HTMLCanvasElement {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  return canvas;
}

/**
 * Get 2D rendering context from canvas
 */
export function getContext(
  canvas: HTMLCanvasElement,
  alpha: boolean = true
): CanvasRenderingContext2D {
  const ctx = canvas.getContext('2d', { alpha });
  if (!ctx) {
    throw new Error('Failed to get 2D rendering context');
  }
  return ctx;
}

/**
 * Clear a canvas
 */
export function clearCanvas(ctx: CanvasRenderingContext2D): void {
  ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
}

/**
 * Apply view transform to context
 */
export function applyViewTransform(
  ctx: CanvasRenderingContext2D,
  transform: ViewTransform,
  imageSize: Size,
  canvasSize: Size
): void {
  const { zoom, panX, panY, rotation } = transform;

  // Calculate image center in canvas
  const centerX = canvasSize.width / 2 + panX;
  const centerY = canvasSize.height / 2 + panY;

  ctx.translate(centerX, centerY);
  ctx.rotate(rotation);
  ctx.scale(zoom, zoom);
  ctx.translate(-imageSize.width / 2, -imageSize.height / 2);
}

/**
 * Screen space → Canvas space
 */
export function screenToCanvas(
  point: Point,
  canvasRect: DOMRect
): Point {
  return {
    x: point.x - canvasRect.left,
    y: point.y - canvasRect.top,
  };
}

/**
 * Canvas space → Image space (0-1 normalized)
 */
export function canvasToImage(
  point: Point,
  transform: ViewTransform,
  imageSize: Size,
  canvasSize: Size
): Point {
  const { zoom, panX, panY, rotation } = transform;

  // Invert the view transform
  const centerX = canvasSize.width / 2 + panX;
  const centerY = canvasSize.height / 2 + panY;

  // Translate to center
  let x = point.x - centerX;
  let y = point.y - centerY;

  // Invert rotation
  if (rotation !== 0) {
    const cos = Math.cos(-rotation);
    const sin = Math.sin(-rotation);
    const rx = x * cos - y * sin;
    const ry = x * sin + y * cos;
    x = rx;
    y = ry;
  }

  // Invert scale
  x /= zoom;
  y /= zoom;

  // Translate back to image origin
  x += imageSize.width / 2;
  y += imageSize.height / 2;

  // Normalize to 0-1
  return {
    x: x / imageSize.width,
    y: y / imageSize.height,
  };
}

/**
 * Image space (0-1 normalized) → Canvas space
 */
export function imageToCanvas(
  point: Point,
  transform: ViewTransform,
  imageSize: Size,
  canvasSize: Size
): Point {
  const { zoom, panX, panY, rotation } = transform;

  // Denormalize from 0-1 to image pixels
  let x = point.x * imageSize.width;
  let y = point.y * imageSize.height;

  // Translate to center
  x -= imageSize.width / 2;
  y -= imageSize.height / 2;

  // Apply scale
  x *= zoom;
  y *= zoom;

  // Apply rotation
  if (rotation !== 0) {
    const cos = Math.cos(rotation);
    const sin = Math.sin(rotation);
    const rx = x * cos - y * sin;
    const ry = x * sin + y * cos;
    x = rx;
    y = ry;
  }

  // Translate to canvas center
  const centerX = canvasSize.width / 2 + panX;
  const centerY = canvasSize.height / 2 + panY;
  x += centerX;
  y += centerY;

  return { x, y };
}

/**
 * Screen space → Image space (convenience)
 */
export function screenToImage(
  point: Point,
  canvasRect: DOMRect,
  transform: ViewTransform,
  imageSize: Size,
  canvasSize: Size
): Point {
  const canvasPoint = screenToCanvas(point, canvasRect);
  return canvasToImage(canvasPoint, transform, imageSize, canvasSize);
}

/**
 * Image space → Screen space (convenience)
 */
export function imageToScreen(
  point: Point,
  canvasRect: DOMRect,
  transform: ViewTransform,
  imageSize: Size,
  canvasSize: Size
): Point {
  const canvasPoint = imageToCanvas(point, transform, imageSize, canvasSize);
  return {
    x: canvasPoint.x + canvasRect.left,
    y: canvasPoint.y + canvasRect.top,
  };
}

/**
 * Calculate zoom to fit image in canvas with padding
 */
export function calculateFitZoom(
  imageSize: Size,
  canvasSize: Size,
  padding: number = 40
): number {
  const availableWidth = canvasSize.width - padding * 2;
  const availableHeight = canvasSize.height - padding * 2;

  const scaleX = availableWidth / imageSize.width;
  const scaleY = availableHeight / imageSize.height;

  return Math.min(scaleX, scaleY, 1); // Don't zoom in past 100%
}

/**
 * Calculate view transform to fit a crop region in canvas
 * Returns zoom and pan values that will center and fit the crop region
 */
export function calculateCropViewTransform(
  crop: { x: number; y: number; width: number; height: number },
  imageSize: Size,
  canvasSize: Size,
  padding: number = 40
): { zoom: number; panX: number; panY: number } {
  // Crop dimensions in pixels
  const cropWidthPx = crop.width * imageSize.width;
  const cropHeightPx = crop.height * imageSize.height;

  // Calculate zoom to fit crop region
  const availableWidth = canvasSize.width - padding * 2;
  const availableHeight = canvasSize.height - padding * 2;

  const scaleX = availableWidth / cropWidthPx;
  const scaleY = availableHeight / cropHeightPx;
  const zoom = Math.min(scaleX, scaleY);

  // Calculate pan to center the crop region
  // Crop center in image pixels (relative to image center)
  const cropCenterX = (crop.x - 0.5) * imageSize.width;
  const cropCenterY = (crop.y - 0.5) * imageSize.height;

  // Pan needed to center the crop (scaled by zoom)
  const panX = -cropCenterX * zoom;
  const panY = -cropCenterY * zoom;

  return { zoom, panX, panY };
}

/**
 * Draw an image to canvas with proper sizing
 */
export function drawImage(
  ctx: CanvasRenderingContext2D,
  image: HTMLImageElement | HTMLCanvasElement | ImageBitmap,
  x: number = 0,
  y: number = 0,
  width?: number,
  height?: number
): void {
  if (width !== undefined && height !== undefined) {
    ctx.drawImage(image, x, y, width, height);
  } else {
    ctx.drawImage(image, x, y);
  }
}
