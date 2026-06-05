/**
 * Shared effect rendering utilities for neon and gradient effects
 * Used by all shape types (rectangles, ellipses, stars, polygons, lines, arrows, paths, text)
 */
import type { Color } from '@/types/geometry';
import type { GradientDirection, ShapeStyle } from '@/types/shapes';
import { colorToCss } from '@/types/geometry';

/**
 * Bounds rectangle for gradient positioning
 */
export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * Get RGB values from a Color object
 */
function colorToRgb(color: Color): { r: number; g: number; b: number } {
  if (typeof color === 'string') {
    return { r: 255, g: 255, b: 255 };
  }
  return { r: color.r, g: color.g, b: color.b };
}

/**
 * Apply neon glow effect to a stroke or fill
 * Uses multi-layer shadowBlur technique for realistic neon glow
 *
 * The key to matching the draw tool's neon look is:
 * 1. Multiple glow layers with the base color
 * 2. A bright white/light CENTER that makes it look like a glowing tube
 *
 * @param ctx - Canvas rendering context
 * @param renderContent - Function that renders the actual shape (stroke or fill)
 * @param color - The base color for the glow
 * @param glowIntensity - Intensity of the glow (0-100)
 * @param buildPath - Optional function that builds the path (for drawing bright highlight)
 * @param strokeWidth - Optional stroke width for highlight layer
 */
export function applyNeonEffect(
  ctx: CanvasRenderingContext2D,
  renderContent: () => void,
  color: Color,
  glowIntensity: number,
  buildPath?: () => void,
  strokeWidth?: number
): void {
  const { r, g, b } = colorToRgb(color);
  const intensity = glowIntensity / 100;

  // Save original state
  const originalShadowBlur = ctx.shadowBlur;
  const originalShadowColor = ctx.shadowColor;
  const originalGlobalAlpha = ctx.globalAlpha;
  const originalFillStyle = ctx.fillStyle;
  const originalStrokeStyle = ctx.strokeStyle;
  const originalLineWidth = ctx.lineWidth;

  // Layer 0: Extra wide atmospheric halo
  ctx.globalAlpha = originalGlobalAlpha * 0.15;
  ctx.shadowColor = `rgba(${r}, ${g}, ${b}, 1)`;
  ctx.shadowBlur = 120 * intensity;
  renderContent();
  renderContent(); // Double for more intensity

  // Layer 1: Wide diffuse outer glow
  ctx.globalAlpha = originalGlobalAlpha * 0.25;
  ctx.shadowBlur = 70 * intensity;
  renderContent();
  renderContent();

  // Layer 2: Medium glow
  ctx.globalAlpha = originalGlobalAlpha * 0.5;
  ctx.shadowBlur = 35 * intensity;
  renderContent();

  // Layer 3: Tight inner glow
  ctx.globalAlpha = originalGlobalAlpha * 0.8;
  ctx.shadowBlur = 15 * intensity;
  renderContent();

  // Layer 4: Solid core with small glow
  ctx.globalAlpha = originalGlobalAlpha;
  ctx.shadowBlur = 8 * intensity;
  renderContent();

  // Layer 5: Bright center highlight - THIS IS THE KEY
  // If we have a buildPath function, we can draw the highlight with explicit bright colors
  if (buildPath) {
    const coreR = Math.min(255, r + 200);
    const coreG = Math.min(255, g + 200);
    const coreB = Math.min(255, b + 200);

    ctx.globalAlpha = originalGlobalAlpha * 0.7 * intensity;
    ctx.strokeStyle = `rgb(${coreR}, ${coreG}, ${coreB})`;
    ctx.fillStyle = `rgb(${coreR}, ${coreG}, ${coreB})`;
    ctx.shadowColor = `rgba(${coreR}, ${coreG}, ${coreB}, 1)`;
    ctx.shadowBlur = 6 * intensity;
    ctx.lineWidth = Math.max(1, (strokeWidth ?? originalLineWidth ?? 4) * 0.5);

    buildPath();
    ctx.stroke();
  }

  // Restore original state
  ctx.shadowBlur = originalShadowBlur;
  ctx.shadowColor = originalShadowColor;
  ctx.globalAlpha = originalGlobalAlpha;
  ctx.fillStyle = originalFillStyle;
  ctx.strokeStyle = originalStrokeStyle;
  ctx.lineWidth = originalLineWidth;
}

/**
 * Create a gradient for fill or stroke
 *
 * @param ctx - Canvas rendering context
 * @param bounds - Bounding rectangle for gradient positioning
 * @param colors - Array of colors for the gradient (2-3 colors)
 * @param direction - Direction of the gradient
 * @returns CanvasGradient object
 */
export function createGradient(
  ctx: CanvasRenderingContext2D,
  bounds: Rect,
  colors: Color[],
  direction: GradientDirection
): CanvasGradient {
  let gradient: CanvasGradient;

  switch (direction) {
    case 'vertical':
      gradient = ctx.createLinearGradient(
        bounds.x,
        bounds.y,
        bounds.x,
        bounds.y + bounds.height
      );
      break;
    case 'diagonal':
      gradient = ctx.createLinearGradient(
        bounds.x,
        bounds.y,
        bounds.x + bounds.width,
        bounds.y + bounds.height
      );
      break;
    default: // 'horizontal'
      gradient = ctx.createLinearGradient(
        bounds.x,
        bounds.y,
        bounds.x + bounds.width,
        bounds.y
      );
      break;
  }

  // Add color stops evenly distributed
  colors.forEach((color, index) => {
    gradient.addColorStop(index / Math.max(1, colors.length - 1), colorToCss(color));
  });

  return gradient;
}

/**
 * Get the gradient color at a specific position within bounds
 * Used for elements like arrowheads that need a solid color from the gradient
 *
 * @param position - Point within the bounds
 * @param bounds - Bounding rectangle
 * @param colors - Array of gradient colors
 * @param direction - Gradient direction
 * @returns The interpolated color at that position
 */
export function getGradientColorAt(
  position: { x: number; y: number },
  bounds: Rect,
  colors: Color[],
  direction: GradientDirection
): Color {
  if (colors.length === 0) return { r: 255, g: 255, b: 255, a: 1 };
  if (colors.length === 1) return colors[0];

  // Calculate position along gradient (0-1)
  let t: number;
  switch (direction) {
    case 'vertical':
      t = bounds.height > 0 ? (position.y - bounds.y) / bounds.height : 0;
      break;
    case 'diagonal':
      // Diagonal: average of x and y progress
      const tx = bounds.width > 0 ? (position.x - bounds.x) / bounds.width : 0;
      const ty = bounds.height > 0 ? (position.y - bounds.y) / bounds.height : 0;
      t = (tx + ty) / 2;
      break;
    default: // 'horizontal'
      t = bounds.width > 0 ? (position.x - bounds.x) / bounds.width : 0;
      break;
  }

  // Clamp t to 0-1
  t = Math.max(0, Math.min(1, t));

  // Find which segment of the gradient we're in
  const segmentCount = colors.length - 1;
  const scaledT = t * segmentCount;
  const segmentIndex = Math.min(Math.floor(scaledT), segmentCount - 1);
  const segmentT = scaledT - segmentIndex;

  // Interpolate between the two colors
  const c1 = colors[segmentIndex];
  const c2 = colors[segmentIndex + 1];

  const r1 = typeof c1 === 'string' ? 255 : c1.r;
  const g1 = typeof c1 === 'string' ? 255 : c1.g;
  const b1 = typeof c1 === 'string' ? 255 : c1.b;
  const a1 = typeof c1 === 'string' ? 1 : (c1.a ?? 1);

  const r2 = typeof c2 === 'string' ? 255 : c2.r;
  const g2 = typeof c2 === 'string' ? 255 : c2.g;
  const b2 = typeof c2 === 'string' ? 255 : c2.b;
  const a2 = typeof c2 === 'string' ? 1 : (c2.a ?? 1);

  return {
    r: Math.round(r1 + (r2 - r1) * segmentT),
    g: Math.round(g1 + (g2 - g1) * segmentT),
    b: Math.round(b1 + (b2 - b1) * segmentT),
    a: a1 + (a2 - a1) * segmentT,
  };
}

/**
 * Get effective style settings with defaults
 * Handles both new style property and legacy properties for backward compatibility
 */
export function getEffectiveStyle(
  style?: ShapeStyle,
  legacyGlow?: number
): {
  effect: 'none' | 'neon' | 'gradient';
  glowIntensity: number;
  glowColor: Color | undefined;
  gradientColors: Color[];
  gradientDirection: GradientDirection;
} {
  // Check for legacy glow on PathShape
  if (legacyGlow !== undefined && legacyGlow > 0 && (!style || style.effect === undefined)) {
    return {
      effect: 'neon',
      glowIntensity: legacyGlow,
      glowColor: undefined,
      gradientColors: [],
      gradientDirection: 'horizontal',
    };
  }

  // Use new style system
  return {
    effect: style?.effect ?? 'none',
    glowIntensity: style?.glowIntensity ?? 50,
    glowColor: style?.glowColor,
    gradientColors: style?.gradientColors ?? [],
    gradientDirection: style?.gradientDirection ?? 'horizontal',
  };
}
