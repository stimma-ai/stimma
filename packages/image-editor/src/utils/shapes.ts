/**
 * Shape rendering utilities
 */
import type { Shape, PathShape, LineShape, CurvedArrowShape, RectangleShape, EllipseShape, TextShape, RedactShape, TriangleShape, StarShape, PolygonShape, ResizeHandle } from '@/types/shapes';
import { TEXT_BASE_FONT_SIZE } from '@/types/shapes';
import type { Size, Point } from '@/types/geometry';
import { colorToCss } from '@/types/geometry';
import { applyNeonEffect, createGradient, getEffectiveStyle, getGradientColorAt } from '@/utils/effects/shapeEffects';

/**
 * State for text editing on canvas
 */
export interface TextEditState {
  shapeId: string;
  cursorIndex: number;
  selectionAnchor: number | null; // null = no selection, otherwise start of selection
  cursorVisible: boolean;
}

// ============================================
// Path Smoothing Algorithms for Curved Arrows
// ============================================

/**
 * Douglas-Peucker path simplification algorithm
 * Reduces the number of points while preserving the overall shape
 */
export function simplifyPath(points: Point[], epsilon: number): Point[] {
  if (points.length <= 2) return points;

  // Find the point with the maximum distance from the line between first and last
  let maxDistance = 0;
  let maxIndex = 0;

  const first = points[0];
  const last = points[points.length - 1];

  for (let i = 1; i < points.length - 1; i++) {
    const distance = perpendicularDistance(points[i], first, last);
    if (distance > maxDistance) {
      maxDistance = distance;
      maxIndex = i;
    }
  }

  // If max distance is greater than epsilon, recursively simplify
  if (maxDistance > epsilon) {
    const left = simplifyPath(points.slice(0, maxIndex + 1), epsilon);
    const right = simplifyPath(points.slice(maxIndex), epsilon);
    return [...left.slice(0, -1), ...right];
  }

  // Return just the endpoints
  return [first, last];
}

/**
 * Calculate perpendicular distance from point to line
 */
function perpendicularDistance(point: Point, lineStart: Point, lineEnd: Point): number {
  const dx = lineEnd.x - lineStart.x;
  const dy = lineEnd.y - lineStart.y;
  const lengthSquared = dx * dx + dy * dy;

  if (lengthSquared === 0) {
    return Math.sqrt((point.x - lineStart.x) ** 2 + (point.y - lineStart.y) ** 2);
  }

  const t = Math.max(0, Math.min(1, ((point.x - lineStart.x) * dx + (point.y - lineStart.y) * dy) / lengthSquared));
  const projX = lineStart.x + t * dx;
  const projY = lineStart.y + t * dy;

  return Math.sqrt((point.x - projX) ** 2 + (point.y - projY) ** 2);
}

/**
 * Convert a series of points to Catmull-Rom spline control points,
 * then convert to cubic Bezier control points for Canvas rendering
 * Returns array of points: [p0, cp1, cp2, p1, cp1, cp2, p2, ...]
 */
export function catmullRomToBezier(points: Point[], tension: number = 0.2): Point[] {
  if (points.length < 2) return points;
  if (points.length === 2) {
    // Just return the two points with interpolated control points for a slight curve
    const p0 = points[0];
    const p1 = points[1];
    const dx = p1.x - p0.x;
    const dy = p1.y - p0.y;
    return [
      p0,
      { x: p0.x + dx * 0.33, y: p0.y + dy * 0.33 },
      { x: p0.x + dx * 0.67, y: p0.y + dy * 0.67 },
      p1
    ];
  }

  const result: Point[] = [];
  // Lower tension = smoother, more rounded curves
  const alpha = 1 - tension;

  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i === 0 ? 0 : i - 1];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2 >= points.length ? points.length - 1 : i + 2];

    // Calculate control points using Catmull-Rom to Bezier conversion
    // Using divisor of 3 instead of 6 for smoother curves with longer control handles
    const cp1: Point = {
      x: p1.x + (p2.x - p0.x) * alpha / 3,
      y: p1.y + (p2.y - p0.y) * alpha / 3
    };

    const cp2: Point = {
      x: p2.x - (p3.x - p1.x) * alpha / 3,
      y: p2.y - (p3.y - p1.y) * alpha / 3
    };

    if (i === 0) {
      result.push(p1); // Start point
    }
    result.push(cp1, cp2, p2);
  }

  return result;
}

/**
 * Chaikin's corner cutting algorithm for smoothing
 * Each iteration cuts corners to create smoother curves
 */
function chaikinSmooth(points: Point[], iterations: number = 2): Point[] {
  if (points.length < 3) return points;

  let result = points;
  for (let iter = 0; iter < iterations; iter++) {
    const smoothed: Point[] = [result[0]]; // Keep first point

    for (let i = 0; i < result.length - 1; i++) {
      const p0 = result[i];
      const p1 = result[i + 1];

      // Cut the corner at 25% and 75%
      smoothed.push({
        x: p0.x * 0.75 + p1.x * 0.25,
        y: p0.y * 0.75 + p1.y * 0.25
      });
      smoothed.push({
        x: p0.x * 0.25 + p1.x * 0.75,
        y: p0.y * 0.25 + p1.y * 0.75
      });
    }

    smoothed.push(result[result.length - 1]); // Keep last point
    result = smoothed;
  }

  return result;
}

/**
 * Main smoothing pipeline: simplify, smooth corners, then convert to bezier
 */
export function computeSmoothedPath(rawPoints: Point[], epsilon: number = 0.012): Point[] {
  if (rawPoints.length < 2) return rawPoints;

  // Step 1: Aggressively simplify to get key direction changes
  const simplified = simplifyPath(rawPoints, epsilon);

  // Step 2: Apply Chaikin smoothing to round corners (more passes = smoother)
  const chaikinPasses = simplified.length < 5 ? 4 : 3;
  const cornerSmoothed = chaikinSmooth(simplified, chaikinPasses);

  // Step 3: Convert to bezier for final smooth rendering
  const smoothed = catmullRomToBezier(cornerSmoothed, 0.05);

  return smoothed;
}

/**
 * Convert normalized (0-1) coordinates to pixel coordinates
 */
export function toPixels(value: number, dimension: number): number {
  return value * dimension;
}

/**
 * Draw an arrow head at the end of a line
 */
function drawArrowHead(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  angle: number,
  size: number,
  filled: boolean
) {
  const headLength = size * 3;
  const headAngle = Math.PI / 6;

  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(angle);

  ctx.beginPath();
  if (filled) {
    // Center the triangle on the anchor point so the front half covers
    // any round lineCap and the back half covers the stroke body
    const halfDepth = headLength * Math.cos(headAngle) / 2;
    ctx.moveTo(halfDepth, 0);
    ctx.lineTo(-halfDepth, -headLength * Math.sin(headAngle));
    ctx.lineTo(-halfDepth, headLength * Math.sin(headAngle));
    ctx.closePath();
    ctx.fill();
  } else {
    // For outline arrowheads, draw two separate lines
    ctx.moveTo(0, 0);
    ctx.lineTo(-headLength * Math.cos(headAngle), -headLength * Math.sin(headAngle));
    ctx.moveTo(0, 0);
    ctx.lineTo(-headLength * Math.cos(headAngle), headLength * Math.sin(headAngle));
    ctx.stroke();
  }
  ctx.restore();
}

/**
 * Render a line shape
 */
export function renderLine(
  ctx: CanvasRenderingContext2D,
  shape: LineShape,
  imageSize: Size
) {
  const x1 = toPixels(shape.x1, imageSize.width);
  const y1 = toPixels(shape.y1, imageSize.height);
  const x2 = toPixels(shape.x2, imageSize.width);
  const y2 = toPixels(shape.y2, imageSize.height);

  // Calculate center for rotation
  const centerX = (x1 + x2) / 2;
  const centerY = (y1 + y2) / 2;

  ctx.save();
  ctx.globalAlpha = shape.opacity;

  // Apply rotation around center
  ctx.translate(centerX, centerY);
  ctx.rotate(shape.rotation);
  ctx.translate(-centerX, -centerY);

  // Get effective style
  const effectiveStyle = getEffectiveStyle(shape.style);

  // Calculate bounds for gradient
  const bounds = {
    x: Math.min(x1, x2),
    y: Math.min(y1, y2),
    width: Math.abs(x2 - x1) || shape.strokeWidth,
    height: Math.abs(y2 - y1) || shape.strokeWidth,
  };

  // Set stroke style based on effect
  if (effectiveStyle.effect === 'gradient' && effectiveStyle.gradientColors.length >= 2) {
    ctx.strokeStyle = createGradient(ctx, bounds, effectiveStyle.gradientColors, effectiveStyle.gradientDirection);
  } else {
    ctx.strokeStyle = colorToCss(shape.strokeColor);
  }

  ctx.lineWidth = shape.strokeWidth;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  // Define render function for reuse with neon effect
  const renderStroke = () => {
    const angle = Math.atan2(y2 - y1, x2 - x1);
    const hasEnd = shape.lineEnd === 'arrow' || shape.lineEnd === 'arrow-solid';
    const hasStart = shape.lineStart === 'arrow' || shape.lineStart === 'arrow-solid';
    const isSolidEnd = shape.lineEnd === 'arrow-solid';
    const isSolidStart = shape.lineStart === 'arrow-solid';

    // Only shorten for outline arrows; solid arrows use centered triangle instead
    const headLen = shape.strokeWidth * 3;
    const hAngle = Math.PI / 6;
    const endShorten = (hasEnd && !isSolidEnd) ? headLen * Math.cos(hAngle) : 0;
    const startShorten = (hasStart && !isSolidStart) ? headLen * Math.cos(hAngle) : 0;

    ctx.beginPath();
    ctx.moveTo(
      x1 + Math.cos(angle) * startShorten,
      y1 + Math.sin(angle) * startShorten
    );
    ctx.lineTo(
      x2 - Math.cos(angle) * endShorten,
      y2 - Math.sin(angle) * endShorten
    );
    ctx.stroke();

    // Draw line ends
    if (hasEnd) {
      if (effectiveStyle.effect === 'gradient' && effectiveStyle.gradientColors.length >= 2) {
        const endColor = getGradientColorAt({ x: x2, y: y2 }, bounds, effectiveStyle.gradientColors, effectiveStyle.gradientDirection);
        const endColorCss = colorToCss(endColor);
        ctx.fillStyle = endColorCss;
        ctx.strokeStyle = endColorCss;
      } else {
        ctx.fillStyle = colorToCss(shape.strokeColor);
      }
      drawArrowHead(ctx, x2, y2, angle, shape.strokeWidth, isSolidEnd);
    }

    if (hasStart) {
      if (effectiveStyle.effect === 'gradient' && effectiveStyle.gradientColors.length >= 2) {
        const startColor = getGradientColorAt({ x: x1, y: y1 }, bounds, effectiveStyle.gradientColors, effectiveStyle.gradientDirection);
        const startColorCss = colorToCss(startColor);
        ctx.fillStyle = startColorCss;
        ctx.strokeStyle = startColorCss;
      } else {
        ctx.fillStyle = colorToCss(shape.strokeColor);
      }
      drawArrowHead(ctx, x1, y1, angle + Math.PI, shape.strokeWidth, isSolidStart);
    }
  };

  // Apply neon effect if enabled (using pencil-style rendering)
  if (effectiveStyle.effect === 'neon') {
    const glowColor = effectiveStyle.glowColor ?? shape.strokeColor;
    const color = typeof glowColor === 'string'
      ? { r: 255, g: 255, b: 255 }
      : glowColor;
    const glowIntensity = effectiveStyle.glowIntensity / 100;
    const baseWidth = shape.strokeWidth;

    const headLength = baseWidth * 3;
    const hA = Math.PI / 6;
    const lineAngle = Math.atan2(y2 - y1, x2 - x1);

    const hasEndArrow = shape.lineEnd === 'arrow' || shape.lineEnd === 'arrow-solid';
    const hasStartArrow = shape.lineStart === 'arrow' || shape.lineStart === 'arrow-solid';

    // Build a single combined path: line + arrowhead V lines
    // This avoids overlapping glow at the intersection
    const buildFullPath = () => {
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      // Add arrowhead V lines as part of the same path
      if (hasEndArrow) {
        ctx.lineTo(
          x2 - headLength * Math.cos(lineAngle + hA),
          y2 - headLength * Math.sin(lineAngle + hA)
        );
        ctx.moveTo(x2, y2);
        ctx.lineTo(
          x2 - headLength * Math.cos(lineAngle - hA),
          y2 - headLength * Math.sin(lineAngle - hA)
        );
      }
      if (hasStartArrow) {
        const startAngle = lineAngle + Math.PI;
        ctx.moveTo(x1, y1);
        ctx.lineTo(
          x1 - headLength * Math.cos(startAngle + hA),
          y1 - headLength * Math.sin(startAngle + hA)
        );
        ctx.moveTo(x1, y1);
        ctx.lineTo(
          x1 - headLength * Math.cos(startAngle - hA),
          y1 - headLength * Math.sin(startAngle - hA)
        );
      }
    };

    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    // Layer 0: Extra wide atmospheric halo
    buildFullPath();
    ctx.strokeStyle = `rgba(${color.r}, ${color.g}, ${color.b}, 0.15)`;
    ctx.lineWidth = baseWidth;
    ctx.shadowColor = `rgba(${color.r}, ${color.g}, ${color.b}, 1)`;
    ctx.shadowBlur = 120 * glowIntensity;
    ctx.stroke();
    ctx.stroke();

    // Layer 1: Wide diffuse outer glow
    buildFullPath();
    ctx.strokeStyle = `rgba(${color.r}, ${color.g}, ${color.b}, 0.25)`;
    ctx.lineWidth = baseWidth;
    ctx.shadowBlur = 70 * glowIntensity;
    ctx.stroke();
    ctx.stroke();

    // Layer 2: Medium glow
    buildFullPath();
    ctx.strokeStyle = `rgba(${color.r}, ${color.g}, ${color.b}, 0.5)`;
    ctx.lineWidth = baseWidth;
    ctx.shadowBlur = 35 * glowIntensity;
    ctx.stroke();

    // Layer 3: Tight inner glow
    buildFullPath();
    ctx.strokeStyle = `rgba(${color.r}, ${color.g}, ${color.b}, 0.8)`;
    ctx.lineWidth = baseWidth;
    ctx.shadowBlur = 15 * glowIntensity;
    ctx.stroke();

    // Layer 4: Solid core with small glow
    buildFullPath();
    ctx.strokeStyle = `rgb(${color.r}, ${color.g}, ${color.b})`;
    ctx.lineWidth = baseWidth;
    ctx.shadowBlur = 8 * glowIntensity;
    ctx.stroke();

    // Layer 5: Bright white/light center highlight
    const coreR = Math.min(255, color.r + 200);
    const coreG = Math.min(255, color.g + 200);
    const coreB = Math.min(255, color.b + 200);
    buildFullPath();
    ctx.strokeStyle = `rgba(${coreR}, ${coreG}, ${coreB}, ${0.7 * glowIntensity})`;
    ctx.lineWidth = Math.max(1, baseWidth * 0.5);
    ctx.shadowColor = `rgba(${coreR}, ${coreG}, ${coreB}, 1)`;
    ctx.shadowBlur = 6 * glowIntensity;
    ctx.stroke();
  } else {
    renderStroke();
  }

  ctx.restore();
}

/**
 * Render a curved arrow shape using bezier curves
 */
export function renderCurvedArrow(
  ctx: CanvasRenderingContext2D,
  shape: CurvedArrowShape,
  imageSize: Size
) {
  if (shape.smoothedPath.length < 4) return;

  // Calculate bounding box center for rotation
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const p of shape.rawPoints) {
    minX = Math.min(minX, p.x);
    minY = Math.min(minY, p.y);
    maxX = Math.max(maxX, p.x);
    maxY = Math.max(maxY, p.y);
  }
  const centerX = toPixels((minX + maxX) / 2, imageSize.width);
  const centerY = toPixels((minY + maxY) / 2, imageSize.height);

  ctx.save();
  ctx.globalAlpha = shape.opacity;

  // Apply rotation around center
  ctx.translate(centerX, centerY);
  ctx.rotate(shape.rotation);
  ctx.translate(-centerX, -centerY);

  // Get effective style
  const effectiveStyle = getEffectiveStyle(shape.style);

  // Calculate bounds for gradient
  const bounds = {
    x: toPixels(minX, imageSize.width),
    y: toPixels(minY, imageSize.height),
    width: toPixels(maxX - minX, imageSize.width) || shape.strokeWidth,
    height: toPixels(maxY - minY, imageSize.height) || shape.strokeWidth,
  };

  // Set stroke style based on effect
  if (effectiveStyle.effect === 'gradient' && effectiveStyle.gradientColors.length >= 2) {
    ctx.strokeStyle = createGradient(ctx, bounds, effectiveStyle.gradientColors, effectiveStyle.gradientDirection);
  } else {
    ctx.strokeStyle = colorToCss(shape.strokeColor);
  }

  ctx.lineWidth = shape.strokeWidth;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  const path = shape.smoothedPath;

  // Calculate arrowhead geometry for shortening the line
  const hasArrowEnd = shape.lineEnd === 'arrow' || shape.lineEnd === 'arrow-solid';
  const isSolidEnd = shape.lineEnd === 'arrow-solid';
  let arrowEndAngle = 0;
  let arrowShortenAmount = 0;
  if (hasArrowEnd) {
    const pathLen = path.length;
    const lastControlPoint = path[pathLen - 2];
    const endPoint = path[pathLen - 1];
    const endX = toPixels(endPoint.x, imageSize.width);
    const endY = toPixels(endPoint.y, imageSize.height);
    const cp2X = toPixels(lastControlPoint.x, imageSize.width);
    const cp2Y = toPixels(lastControlPoint.y, imageSize.height);
    arrowEndAngle = Math.atan2(endY - cp2Y, endX - cp2X);
    // For filled arrows, shorten to the base of the triangle
    // For outline arrows, shorten to the base of the V
    const headLength = shape.strokeWidth * 3;
    const headAngle = Math.PI / 6;
    arrowShortenAmount = headLength * Math.cos(headAngle);
  }

  // Define render function for reuse with neon effect
  const renderStroke = () => {
    // Draw the bezier path
    ctx.beginPath();
    const startX = toPixels(path[0].x, imageSize.width);
    const startY = toPixels(path[0].y, imageSize.height);
    ctx.moveTo(startX, startY);

    for (let i = 1; i < path.length; i += 3) {
      if (i + 2 >= path.length) break;

      const cp1x = toPixels(path[i].x, imageSize.width);
      const cp1y = toPixels(path[i].y, imageSize.height);
      const cp2x = toPixels(path[i + 1].x, imageSize.width);
      const cp2y = toPixels(path[i + 1].y, imageSize.height);
      let endX = toPixels(path[i + 2].x, imageSize.width);
      let endY = toPixels(path[i + 2].y, imageSize.height);

      // For outline arrows, shorten the last segment so line stops at the V base
      if (hasArrowEnd && !isSolidEnd && i + 3 >= path.length) {
        endX -= Math.cos(arrowEndAngle) * arrowShortenAmount;
        endY -= Math.sin(arrowEndAngle) * arrowShortenAmount;
      }

      ctx.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, endX, endY);
    }

    ctx.stroke();

    // Draw arrowhead at the end
    if (hasArrowEnd) {
      const endPoint = path[path.length - 1];
      const endX = toPixels(endPoint.x, imageSize.width);
      const endY = toPixels(endPoint.y, imageSize.height);

      if (effectiveStyle.effect === 'gradient' && effectiveStyle.gradientColors.length >= 2) {
        const arrowColor = getGradientColorAt(
          { x: endX, y: endY },
          bounds,
          effectiveStyle.gradientColors,
          effectiveStyle.gradientDirection
        );
        const arrowColorCss = colorToCss(arrowColor);
        ctx.fillStyle = arrowColorCss;
        ctx.strokeStyle = arrowColorCss;
      } else {
        ctx.fillStyle = colorToCss(shape.strokeColor);
      }
      drawArrowHead(ctx, endX, endY, arrowEndAngle, shape.strokeWidth, isSolidEnd);
    }
  };

  // Apply neon effect if enabled (using pencil-style rendering)
  if (effectiveStyle.effect === 'neon') {
    const glowColor = effectiveStyle.glowColor ?? shape.strokeColor;
    const color = typeof glowColor === 'string'
      ? { r: 255, g: 255, b: 255 }
      : glowColor;
    const glowIntensity = effectiveStyle.glowIntensity / 100;
    const baseWidth = shape.strokeWidth;

    const hasArrow = shape.lineEnd === 'arrow' || shape.lineEnd === 'arrow-solid';

    // Calculate arrow position/angle for arrowhead V lines
    let arrowEndX = 0, arrowEndY = 0, arrowAngle = 0;
    const headLength = baseWidth * 3;
    const hA = Math.PI / 6;
    if (hasArrow) {
      const pathLen = path.length;
      const lastControlPoint = path[pathLen - 2];
      const endPoint = path[pathLen - 1];
      arrowEndX = toPixels(endPoint.x, imageSize.width);
      arrowEndY = toPixels(endPoint.y, imageSize.height);
      const cp2X = toPixels(lastControlPoint.x, imageSize.width);
      const cp2Y = toPixels(lastControlPoint.y, imageSize.height);
      arrowAngle = Math.atan2(arrowEndY - cp2Y, arrowEndX - cp2X);
    }

    // Build a single combined path: bezier curve + arrowhead V lines
    // This avoids overlapping glow at the intersection
    const buildFullPath = () => {
      ctx.beginPath();
      const startX = toPixels(path[0].x, imageSize.width);
      const startY = toPixels(path[0].y, imageSize.height);
      ctx.moveTo(startX, startY);

      for (let i = 1; i < path.length; i += 3) {
        if (i + 2 >= path.length) break;
        const cp1x = toPixels(path[i].x, imageSize.width);
        const cp1y = toPixels(path[i].y, imageSize.height);
        const cp2x = toPixels(path[i + 1].x, imageSize.width);
        const cp2y = toPixels(path[i + 1].y, imageSize.height);
        const endX = toPixels(path[i + 2].x, imageSize.width);
        const endY = toPixels(path[i + 2].y, imageSize.height);
        ctx.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, endX, endY);
      }

      // Add arrowhead V lines as part of the same path
      if (hasArrow) {
        ctx.lineTo(
          arrowEndX - headLength * Math.cos(arrowAngle + hA),
          arrowEndY - headLength * Math.sin(arrowAngle + hA)
        );
        ctx.moveTo(arrowEndX, arrowEndY);
        ctx.lineTo(
          arrowEndX - headLength * Math.cos(arrowAngle - hA),
          arrowEndY - headLength * Math.sin(arrowAngle - hA)
        );
      }
    };

    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    // Layer 0: Extra wide atmospheric halo
    buildFullPath();
    ctx.strokeStyle = `rgba(${color.r}, ${color.g}, ${color.b}, 0.15)`;
    ctx.lineWidth = baseWidth;
    ctx.shadowColor = `rgba(${color.r}, ${color.g}, ${color.b}, 1)`;
    ctx.shadowBlur = 120 * glowIntensity;
    ctx.stroke();
    ctx.stroke();

    // Layer 1: Wide diffuse outer glow
    buildFullPath();
    ctx.strokeStyle = `rgba(${color.r}, ${color.g}, ${color.b}, 0.25)`;
    ctx.lineWidth = baseWidth;
    ctx.shadowBlur = 70 * glowIntensity;
    ctx.stroke();
    ctx.stroke();

    // Layer 2: Medium glow
    buildFullPath();
    ctx.strokeStyle = `rgba(${color.r}, ${color.g}, ${color.b}, 0.5)`;
    ctx.lineWidth = baseWidth;
    ctx.shadowBlur = 35 * glowIntensity;
    ctx.stroke();

    // Layer 3: Tight inner glow
    buildFullPath();
    ctx.strokeStyle = `rgba(${color.r}, ${color.g}, ${color.b}, 0.8)`;
    ctx.lineWidth = baseWidth;
    ctx.shadowBlur = 15 * glowIntensity;
    ctx.stroke();

    // Layer 4: Solid core with small glow
    buildFullPath();
    ctx.strokeStyle = `rgb(${color.r}, ${color.g}, ${color.b})`;
    ctx.lineWidth = baseWidth;
    ctx.shadowBlur = 8 * glowIntensity;
    ctx.stroke();

    // Layer 5: Bright white/light center highlight
    const coreR = Math.min(255, color.r + 200);
    const coreG = Math.min(255, color.g + 200);
    const coreB = Math.min(255, color.b + 200);
    buildFullPath();
    ctx.strokeStyle = `rgba(${coreR}, ${coreG}, ${coreB}, ${0.7 * glowIntensity})`;
    ctx.lineWidth = Math.max(1, baseWidth * 0.5);
    ctx.shadowColor = `rgba(${coreR}, ${coreG}, ${coreB}, 1)`;
    ctx.shadowBlur = 6 * glowIntensity;
    ctx.stroke();
  } else {
    renderStroke();
  }

  ctx.restore();
}

/**
 * Render a rectangle shape
 */
export function renderRectangle(
  ctx: CanvasRenderingContext2D,
  shape: RectangleShape,
  imageSize: Size
) {
  const x = toPixels(shape.x, imageSize.width);
  const y = toPixels(shape.y, imageSize.height);
  const width = toPixels(shape.width, imageSize.width);
  const height = toPixels(shape.height, imageSize.height);
  const radius = shape.cornerRadius ?? 0;

  ctx.save();
  ctx.globalAlpha = shape.opacity;
  ctx.translate(x + width / 2, y + height / 2);
  ctx.rotate(shape.rotation);
  ctx.translate(-width / 2, -height / 2);

  // Get effective style
  const effectiveStyle = getEffectiveStyle(shape.style);

  // Bounds in local coordinate space (after transform)
  const bounds = { x: 0, y: 0, width, height };

  // Build path function for reuse
  const buildPath = () => {
    ctx.beginPath();
    if (radius > 0) {
      ctx.roundRect(0, 0, width, height, radius);
    } else {
      ctx.rect(0, 0, width, height);
    }
  };

  // Define render function for potential neon effect
  const renderShape = () => {
    buildPath();

    if (shape.backgroundColor) {
      if (effectiveStyle.effect === 'gradient' && effectiveStyle.gradientColors.length >= 2) {
        ctx.fillStyle = createGradient(ctx, bounds, effectiveStyle.gradientColors, effectiveStyle.gradientDirection);
      } else {
        ctx.fillStyle = colorToCss(shape.backgroundColor);
      }
      ctx.fill();
    }

    if (shape.strokeColor && shape.strokeWidth) {
      if (effectiveStyle.effect === 'gradient' && effectiveStyle.gradientColors.length >= 2 && !shape.backgroundColor) {
        // Apply gradient to stroke if no fill
        ctx.strokeStyle = createGradient(ctx, bounds, effectiveStyle.gradientColors, effectiveStyle.gradientDirection);
      } else {
        ctx.strokeStyle = colorToCss(shape.strokeColor);
      }
      ctx.lineWidth = shape.strokeWidth;
      ctx.stroke();
    }
  };

  // Apply neon effect if enabled
  if (effectiveStyle.effect === 'neon') {
    const glowColor = effectiveStyle.glowColor ?? shape.strokeColor ?? shape.backgroundColor;
    if (glowColor) {
      applyNeonEffect(ctx, renderShape, glowColor, effectiveStyle.glowIntensity, buildPath, shape.strokeWidth);
    } else {
      renderShape();
    }
  } else {
    renderShape();
  }

  ctx.restore();
}

/**
 * Render an ellipse shape
 */
export function renderEllipse(
  ctx: CanvasRenderingContext2D,
  shape: EllipseShape,
  imageSize: Size
) {
  const x = toPixels(shape.x, imageSize.width);
  const y = toPixels(shape.y, imageSize.height);
  const rx = toPixels(shape.rx, imageSize.width);
  const ry = toPixels(shape.ry, imageSize.height);

  ctx.save();
  ctx.globalAlpha = shape.opacity;
  ctx.translate(x, y);
  ctx.rotate(shape.rotation);

  // Get effective style
  const effectiveStyle = getEffectiveStyle(shape.style);

  // Bounds in local coordinate space (centered at origin)
  const bounds = { x: -rx, y: -ry, width: rx * 2, height: ry * 2 };

  // Build path function for reuse
  const buildPath = () => {
    ctx.beginPath();
    ctx.ellipse(0, 0, rx, ry, 0, 0, Math.PI * 2);
  };

  // Define render function for potential neon effect
  const renderShape = () => {
    buildPath();

    if (shape.backgroundColor) {
      if (effectiveStyle.effect === 'gradient' && effectiveStyle.gradientColors.length >= 2) {
        ctx.fillStyle = createGradient(ctx, bounds, effectiveStyle.gradientColors, effectiveStyle.gradientDirection);
      } else {
        ctx.fillStyle = colorToCss(shape.backgroundColor);
      }
      ctx.fill();
    }

    if (shape.strokeColor && shape.strokeWidth) {
      if (effectiveStyle.effect === 'gradient' && effectiveStyle.gradientColors.length >= 2 && !shape.backgroundColor) {
        ctx.strokeStyle = createGradient(ctx, bounds, effectiveStyle.gradientColors, effectiveStyle.gradientDirection);
      } else {
        ctx.strokeStyle = colorToCss(shape.strokeColor);
      }
      ctx.lineWidth = shape.strokeWidth;
      ctx.stroke();
    }
  };

  // Apply neon effect if enabled
  if (effectiveStyle.effect === 'neon') {
    const glowColor = effectiveStyle.glowColor ?? shape.strokeColor ?? shape.backgroundColor;
    if (glowColor) {
      applyNeonEffect(ctx, renderShape, glowColor, effectiveStyle.glowIntensity, buildPath, shape.strokeWidth);
    } else {
      renderShape();
    }
  } else {
    renderShape();
  }

  ctx.restore();
}

/**
 * Render a triangle shape
 */
export function renderTriangle(
  ctx: CanvasRenderingContext2D,
  shape: TriangleShape,
  imageSize: Size
) {
  const x = toPixels(shape.x, imageSize.width);
  const y = toPixels(shape.y, imageSize.height);
  const width = toPixels(shape.width, imageSize.width);
  const height = toPixels(shape.height, imageSize.height);

  ctx.save();
  ctx.globalAlpha = shape.opacity;
  ctx.translate(x + width / 2, y + height / 2);
  ctx.rotate(shape.rotation);
  ctx.translate(-width / 2, -height / 2);

  // Get effective style
  const effectiveStyle = getEffectiveStyle(shape.style);

  // Bounds in local coordinate space
  const bounds = { x: 0, y: 0, width, height };

  // Build path function for reuse
  const buildPath = () => {
    ctx.beginPath();
    // Draw triangle: top center, bottom left, bottom right
    ctx.moveTo(width / 2, 0);
    ctx.lineTo(0, height);
    ctx.lineTo(width, height);
    ctx.closePath();
  };

  // Define render function for potential neon effect
  const renderShape = () => {
    buildPath();

    if (shape.backgroundColor) {
      if (effectiveStyle.effect === 'gradient' && effectiveStyle.gradientColors.length >= 2) {
        ctx.fillStyle = createGradient(ctx, bounds, effectiveStyle.gradientColors, effectiveStyle.gradientDirection);
      } else {
        ctx.fillStyle = colorToCss(shape.backgroundColor);
      }
      ctx.fill();
    }

    if (shape.strokeColor && shape.strokeWidth) {
      if (effectiveStyle.effect === 'gradient' && effectiveStyle.gradientColors.length >= 2 && !shape.backgroundColor) {
        ctx.strokeStyle = createGradient(ctx, bounds, effectiveStyle.gradientColors, effectiveStyle.gradientDirection);
      } else {
        ctx.strokeStyle = colorToCss(shape.strokeColor);
      }
      ctx.lineWidth = shape.strokeWidth;
      ctx.lineJoin = 'round';
      ctx.stroke();
    }
  };

  // Apply neon effect if enabled
  if (effectiveStyle.effect === 'neon') {
    const glowColor = effectiveStyle.glowColor ?? shape.strokeColor ?? shape.backgroundColor;
    if (glowColor) {
      applyNeonEffect(ctx, renderShape, glowColor, effectiveStyle.glowIntensity, buildPath, shape.strokeWidth);
    } else {
      renderShape();
    }
  } else {
    renderShape();
  }

  ctx.restore();
}

/**
 * Render a star shape
 */
export function renderStar(
  ctx: CanvasRenderingContext2D,
  shape: StarShape,
  imageSize: Size
) {
  const cx = toPixels(shape.x, imageSize.width);
  const cy = toPixels(shape.y, imageSize.height);
  // Use avgImageDim for uniform scaling (regular shapes)
  const avgImageDim = (imageSize.width + imageSize.height) / 2;
  const outerRadius = toPixels(shape.outerRadius, avgImageDim);
  const innerRadius = toPixels(shape.innerRadius, avgImageDim);
  const points = shape.points;
  const aspectRatio = shape.aspectRatio ?? 1.0;

  ctx.save();
  ctx.globalAlpha = shape.opacity;
  ctx.translate(cx, cy);
  ctx.rotate(shape.rotation);

  // Get effective style
  const effectiveStyle = getEffectiveStyle(shape.style);

  // Bounds in local coordinate space (centered at origin)
  const bounds = { x: -outerRadius * aspectRatio, y: -outerRadius, width: outerRadius * 2 * aspectRatio, height: outerRadius * 2 };

  // Build path function for reuse
  const buildPath = () => {
    ctx.beginPath();
    // Draw star points
    for (let i = 0; i < points * 2; i++) {
      const isOuter = i % 2 === 0;
      const r = isOuter ? outerRadius : innerRadius;
      // Start from top (-PI/2) and go clockwise
      const angle = (i * Math.PI) / points - Math.PI / 2;
      // Apply aspectRatio to x coordinate for non-uniform scaling
      const px = Math.cos(angle) * r * aspectRatio;
      const py = Math.sin(angle) * r;
      if (i === 0) {
        ctx.moveTo(px, py);
      } else {
        ctx.lineTo(px, py);
      }
    }
    ctx.closePath();
  };

  // Define render function for potential neon effect
  const renderShape = () => {
    buildPath();

    if (shape.backgroundColor) {
      if (effectiveStyle.effect === 'gradient' && effectiveStyle.gradientColors.length >= 2) {
        ctx.fillStyle = createGradient(ctx, bounds, effectiveStyle.gradientColors, effectiveStyle.gradientDirection);
      } else {
        ctx.fillStyle = colorToCss(shape.backgroundColor);
      }
      ctx.fill();
    }

    if (shape.strokeColor && shape.strokeWidth) {
      if (effectiveStyle.effect === 'gradient' && effectiveStyle.gradientColors.length >= 2 && !shape.backgroundColor) {
        ctx.strokeStyle = createGradient(ctx, bounds, effectiveStyle.gradientColors, effectiveStyle.gradientDirection);
      } else {
        ctx.strokeStyle = colorToCss(shape.strokeColor);
      }
      ctx.lineWidth = shape.strokeWidth;
      ctx.lineJoin = 'round';
      ctx.stroke();
    }
  };

  // Apply neon effect if enabled
  if (effectiveStyle.effect === 'neon') {
    const glowColor = effectiveStyle.glowColor ?? shape.strokeColor ?? shape.backgroundColor;
    if (glowColor) {
      applyNeonEffect(ctx, renderShape, glowColor, effectiveStyle.glowIntensity, buildPath, shape.strokeWidth);
    } else {
      renderShape();
    }
  } else {
    renderShape();
  }

  ctx.restore();
}

/**
 * Render a polygon shape
 */
export function renderPolygon(
  ctx: CanvasRenderingContext2D,
  shape: PolygonShape,
  imageSize: Size
) {
  const cx = toPixels(shape.x, imageSize.width);
  const cy = toPixels(shape.y, imageSize.height);
  // Use avgImageDim for uniform scaling (regular shapes)
  const avgImageDim = (imageSize.width + imageSize.height) / 2;
  const radius = toPixels(shape.radius, avgImageDim);
  const sides = shape.sides;
  const aspectRatio = shape.aspectRatio ?? 1.0;

  ctx.save();
  ctx.globalAlpha = shape.opacity;
  ctx.translate(cx, cy);
  ctx.rotate(shape.rotation);

  // Get effective style
  const effectiveStyle = getEffectiveStyle(shape.style);

  // Bounds in local coordinate space (centered at origin)
  const bounds = { x: -radius * aspectRatio, y: -radius, width: radius * 2 * aspectRatio, height: radius * 2 };

  // Build path function for reuse
  const buildPath = () => {
    ctx.beginPath();
    // Draw polygon vertices
    for (let i = 0; i < sides; i++) {
      // Start from top (-PI/2) and go clockwise
      const angle = (i * 2 * Math.PI) / sides - Math.PI / 2;
      // Apply aspectRatio to x coordinate for non-uniform scaling
      const px = Math.cos(angle) * radius * aspectRatio;
      const py = Math.sin(angle) * radius;
      if (i === 0) {
        ctx.moveTo(px, py);
      } else {
        ctx.lineTo(px, py);
      }
    }
    ctx.closePath();
  };

  // Define render function for potential neon effect
  const renderShape = () => {
    buildPath();

    if (shape.backgroundColor) {
      if (effectiveStyle.effect === 'gradient' && effectiveStyle.gradientColors.length >= 2) {
        ctx.fillStyle = createGradient(ctx, bounds, effectiveStyle.gradientColors, effectiveStyle.gradientDirection);
      } else {
        ctx.fillStyle = colorToCss(shape.backgroundColor);
      }
      ctx.fill();
    }

    if (shape.strokeColor && shape.strokeWidth) {
      if (effectiveStyle.effect === 'gradient' && effectiveStyle.gradientColors.length >= 2 && !shape.backgroundColor) {
        ctx.strokeStyle = createGradient(ctx, bounds, effectiveStyle.gradientColors, effectiveStyle.gradientDirection);
      } else {
        ctx.strokeStyle = colorToCss(shape.strokeColor);
      }
      ctx.lineWidth = shape.strokeWidth;
      ctx.lineJoin = 'round';
      ctx.stroke();
    }
  };

  // Apply neon effect if enabled
  if (effectiveStyle.effect === 'neon') {
    const glowColor = effectiveStyle.glowColor ?? shape.strokeColor ?? shape.backgroundColor;
    if (glowColor) {
      applyNeonEffect(ctx, renderShape, glowColor, effectiveStyle.glowIntensity, buildPath, shape.strokeWidth);
    } else {
      renderShape();
    }
  } else {
    renderShape();
  }

  ctx.restore();
}

/**
 * Create a brush stamp canvas for soft brush rendering
 */
function createBrushStamp(
  size: number,
  hardness: number,
  color: { r: number; g: number; b: number; a?: number },
  flow: number,
  glow: number = 0
): HTMLCanvasElement {
  // For glow, we need extra space for the blur effect
  const padding = glow > 0 ? Math.ceil(size * (glow / 100) * 0.8) : 0;
  const canvasSize = Math.ceil(size) + padding * 2;

  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = canvasSize;
  const ctx = canvas.getContext('2d')!;

  const center = canvasSize / 2;
  const radius = size / 2;

  // Flow controls the opacity of each stamp
  const alpha = (flow / 100) * (color.a ?? 1);

  // Apply glow effect (neon)
  if (glow > 0) {
    const glowSize = (glow / 100) * size * 0.8;
    ctx.shadowColor = `rgba(${color.r}, ${color.g}, ${color.b}, ${Math.min(1, alpha * 0.8)})`;
    ctx.shadowBlur = glowSize;
  }

  // Create gradient for brush stamp
  const gradient = ctx.createRadialGradient(center, center, 0, center, center, radius);
  const hardnessPoint = Math.max(0.01, hardness / 100);

  // For neon (glow > 30), use brighter center for that glowing effect
  if (glow > 30) {
    const centerR = Math.min(255, color.r + 100);
    const centerG = Math.min(255, color.g + 100);
    const centerB = Math.min(255, color.b + 100);
    gradient.addColorStop(0, `rgba(${centerR}, ${centerG}, ${centerB}, ${alpha})`);
    gradient.addColorStop(hardnessPoint * 0.5, `rgba(${color.r}, ${color.g}, ${color.b}, ${alpha})`);
  } else {
    gradient.addColorStop(0, `rgba(${color.r}, ${color.g}, ${color.b}, ${alpha})`);
  }
  gradient.addColorStop(hardnessPoint, `rgba(${color.r}, ${color.g}, ${color.b}, ${alpha})`);
  gradient.addColorStop(1, `rgba(${color.r}, ${color.g}, ${color.b}, 0)`);

  ctx.fillStyle = gradient;
  ctx.beginPath();
  ctx.arc(center, center, radius, 0, Math.PI * 2);
  ctx.fill();

  return canvas;
}


/**
 * Render a path/freehand shape with brush settings
 */
export function renderPath(
  ctx: CanvasRenderingContext2D,
  shape: PathShape,
  imageSize: Size
) {
  if (shape.points.length < 2) return;

  // Get brush settings with defaults
  const hardness = shape.hardness ?? 100;
  const flow = shape.flow ?? 100;
  const spacing = shape.spacing ?? 25;

  // Get effective style (handles both new style system and legacy glow property)
  const effectiveStyle = getEffectiveStyle(shape.style, shape.glow);
  const glow = effectiveStyle.effect === 'neon' ? effectiveStyle.glowIntensity : (shape.glow ?? 0);

  // Calculate bounding box center for rotation
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const p of shape.points) {
    minX = Math.min(minX, p.x);
    minY = Math.min(minY, p.y);
    maxX = Math.max(maxX, p.x);
    maxY = Math.max(maxY, p.y);
  }
  const centerX = toPixels((minX + maxX) / 2, imageSize.width);
  const centerY = toPixels((minY + maxY) / 2, imageSize.height);

  ctx.save();
  ctx.globalAlpha = shape.opacity;

  // Apply rotation around center
  ctx.translate(centerX, centerY);
  ctx.rotate(shape.rotation);
  ctx.translate(-centerX, -centerY);

  // Handle eraser mode
  if (shape.isEraser) {
    ctx.globalCompositeOperation = 'destination-out';
  }

  // Helper to build the path
  const buildPath = () => {
    ctx.beginPath();
    const firstPoint = shape.points[0];
    ctx.moveTo(
      toPixels(firstPoint.x, imageSize.width),
      toPixels(firstPoint.y, imageSize.height)
    );

    // Use quadratic curves for smoother lines
    for (let i = 1; i < shape.points.length - 1; i++) {
      const p1 = shape.points[i];
      const p2 = shape.points[i + 1];
      const midX = (toPixels(p1.x, imageSize.width) + toPixels(p2.x, imageSize.width)) / 2;
      const midY = (toPixels(p1.y, imageSize.height) + toPixels(p2.y, imageSize.height)) / 2;
      ctx.quadraticCurveTo(
        toPixels(p1.x, imageSize.width),
        toPixels(p1.y, imageSize.height),
        midX,
        midY
      );
    }

    // Connect to last point
    const lastPoint = shape.points[shape.points.length - 1];
    ctx.lineTo(
      toPixels(lastPoint.x, imageSize.width),
      toPixels(lastPoint.y, imageSize.height)
    );
  };

  // NEON rendering - glowing effect using shadowBlur
  if (glow > 0) {
    const color = typeof shape.strokeColor === 'string'
      ? { r: 255, g: 255, b: 255 }
      : shape.strokeColor;

    const glowIntensity = glow / 100;
    const baseWidth = shape.strokeWidth;

    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    // Layer 0: Extra wide atmospheric halo
    buildPath();
    ctx.strokeStyle = `rgba(${color.r}, ${color.g}, ${color.b}, 0.15)`;
    ctx.lineWidth = baseWidth;
    ctx.shadowColor = `rgba(${color.r}, ${color.g}, ${color.b}, 1)`;
    ctx.shadowBlur = 120 * glowIntensity;
    ctx.stroke();
    ctx.stroke(); // Double stroke for more intensity

    // Layer 1: Wide diffuse outer glow
    buildPath();
    ctx.strokeStyle = `rgba(${color.r}, ${color.g}, ${color.b}, 0.25)`;
    ctx.lineWidth = baseWidth;
    ctx.shadowBlur = 70 * glowIntensity;
    ctx.stroke();
    ctx.stroke();

    // Layer 2: Medium glow
    buildPath();
    ctx.strokeStyle = `rgba(${color.r}, ${color.g}, ${color.b}, 0.5)`;
    ctx.lineWidth = baseWidth;
    ctx.shadowBlur = 35 * glowIntensity;
    ctx.stroke();

    // Layer 3: Tight inner glow
    buildPath();
    ctx.strokeStyle = `rgba(${color.r}, ${color.g}, ${color.b}, 0.8)`;
    ctx.lineWidth = baseWidth;
    ctx.shadowBlur = 15 * glowIntensity;
    ctx.stroke();

    // Layer 4: Solid core with small glow
    buildPath();
    ctx.strokeStyle = `rgb(${color.r}, ${color.g}, ${color.b})`;
    ctx.lineWidth = baseWidth;
    ctx.shadowBlur = 8 * glowIntensity;
    ctx.stroke();

    // Layer 5: Bright white/light center highlight with soft edges
    const coreR = Math.min(255, color.r + 200);
    const coreG = Math.min(255, color.g + 200);
    const coreB = Math.min(255, color.b + 200);
    buildPath();
    ctx.strokeStyle = `rgba(${coreR}, ${coreG}, ${coreB}, ${0.7 * glowIntensity})`;
    ctx.lineWidth = Math.max(1, baseWidth * 0.5);
    ctx.shadowColor = `rgba(${coreR}, ${coreG}, ${coreB}, 1)`;
    ctx.shadowBlur = 6 * glowIntensity;
    ctx.stroke();
  }
  // For hard brushes (hardness >= 95) without glow, use simple stroke rendering for performance
  else if (hardness >= 95 && flow >= 95) {
    // Calculate bounds for gradient
    const bounds = {
      x: toPixels(minX, imageSize.width),
      y: toPixels(minY, imageSize.height),
      width: toPixels(maxX - minX, imageSize.width) || shape.strokeWidth,
      height: toPixels(maxY - minY, imageSize.height) || shape.strokeWidth,
    };

    // Set stroke style based on effect
    if (effectiveStyle.effect === 'gradient' && effectiveStyle.gradientColors.length >= 2) {
      ctx.strokeStyle = createGradient(ctx, bounds, effectiveStyle.gradientColors, effectiveStyle.gradientDirection);
    } else {
      ctx.strokeStyle = colorToCss(shape.strokeColor);
    }
    ctx.lineWidth = shape.strokeWidth;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    buildPath();

    if (shape.closed && shape.backgroundColor) {
      ctx.closePath();
      ctx.fillStyle = colorToCss(shape.backgroundColor);
      ctx.fill();
    }

    ctx.stroke();
  } else {
    // Stamp-based rendering for soft brushes
    const color = typeof shape.strokeColor === 'string'
      ? { r: 0, g: 0, b: 0, a: 1 } // fallback
      : shape.strokeColor;

    const brushSize = shape.strokeWidth;
    const jitter = shape.jitter ?? 0;
    const scatter = shape.scatter ?? 0;
    const stamp = createBrushStamp(brushSize, hardness, color, flow, glow);

    // Calculate the stamp's actual size (includes glow padding)
    const glowPadding = glow > 0 ? Math.ceil(brushSize * (glow / 100) * 0.8) : 0;
    const stampCanvasSize = brushSize + glowPadding * 2;

    // Calculate spacing between stamps
    const stampGap = Math.max(1, brushSize * (spacing / 100));

    // Jitter amount in pixels (percentage of brush size)
    const jitterAmount = brushSize * (jitter / 100);

    // Create a seeded random for consistent rendering
    // Use shape id hash for seed so same shape renders consistently
    let seed = 0;
    for (let i = 0; i < shape.id.length; i++) {
      seed = ((seed << 5) - seed) + shape.id.charCodeAt(i);
      seed = seed & seed;
    }
    const seededRandom = () => {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff;
      return seed / 0x7fffffff;
    };

    // Get interpolated pixel points
    const pixelPoints: Point[] = [];
    for (const p of shape.points) {
      pixelPoints.push({
        x: toPixels(p.x, imageSize.width),
        y: toPixels(p.y, imageSize.height)
      });
    }

    // Helper to draw a stamp with optional jitter
    const drawStamp = (x: number, y: number, applyJitter: boolean = true) => {
      let stampX = x;
      let stampY = y;

      if (applyJitter && jitterAmount > 0) {
        stampX += (seededRandom() - 0.5) * 2 * jitterAmount;
        stampY += (seededRandom() - 0.5) * 2 * jitterAmount;
      }

      ctx.drawImage(stamp, stampX - stampCanvasSize / 2, stampY - stampCanvasSize / 2);

      // For scatter effect, add random extra stamps nearby
      if (scatter > 0) {
        const scatterCount = Math.floor(seededRandom() * (scatter / 20)); // 0-5 extra stamps at max scatter
        const scatterRadius = brushSize * (scatter / 50); // Scatter distance

        for (let s = 0; s < scatterCount; s++) {
          const angle = seededRandom() * Math.PI * 2;
          const dist = seededRandom() * scatterRadius;
          const scatterX = stampX + Math.cos(angle) * dist;
          const scatterY = stampY + Math.sin(angle) * dist;

          // Vary the size slightly for scatter stamps
          const sizeVar = 0.5 + seededRandom() * 0.5;
          const scatterStampSize = stampCanvasSize * sizeVar;

          // Draw a slightly smaller/varied stamp
          ctx.save();
          ctx.globalAlpha = ctx.globalAlpha * (0.5 + seededRandom() * 0.5);
          ctx.drawImage(
            stamp,
            scatterX - scatterStampSize / 2,
            scatterY - scatterStampSize / 2,
            scatterStampSize,
            scatterStampSize
          );
          ctx.restore();
        }
      }
    };

    // Render stamps along the path
    let accumulatedDistance = 0;

    for (let i = 1; i < pixelPoints.length; i++) {
      const p0 = pixelPoints[i - 1];
      const p1 = pixelPoints[i];

      const dx = p1.x - p0.x;
      const dy = p1.y - p0.y;
      const segmentLength = Math.sqrt(dx * dx + dy * dy);

      if (segmentLength === 0) continue;

      // Place stamps along this segment
      while (accumulatedDistance < segmentLength) {
        const t = accumulatedDistance / segmentLength;
        const x = p0.x + dx * t;
        const y = p0.y + dy * t;

        drawStamp(x, y);

        accumulatedDistance += stampGap;
      }

      accumulatedDistance -= segmentLength;
    }

    // Always draw at least one stamp at the start
    if (pixelPoints.length > 0) {
      const p = pixelPoints[0];
      drawStamp(p.x, p.y);
    }

    // Draw at the end point
    if (pixelPoints.length > 1) {
      const p = pixelPoints[pixelPoints.length - 1];
      drawStamp(p.x, p.y);
    }
  }

  ctx.restore();
}

/**
 * Render a text shape using vector-based scaling
 * Text is rendered at BASE_FONT_SIZE and scaled using canvas transforms
 */
export function renderText(
  ctx: CanvasRenderingContext2D,
  shape: TextShape,
  imageSize: Size,
  editState?: TextEditState
) {
  // Skip rendering if no text AND not editing (cursor needs to show even for empty text)
  if (!shape.text && (!editState || editState.shapeId !== shape.id)) return;

  const x = toPixels(shape.x, imageSize.width);
  const y = toPixels(shape.y, imageSize.height);
  const width = toPixels(shape.width, imageSize.width);
  const height = toPixels(shape.height, imageSize.height);

  // Calculate base dimensions in pixels
  const baseWidthPx = toPixels(shape.baseWidth, imageSize.width);
  const baseHeightPx = toPixels(shape.baseHeight, imageSize.height);

  // Calculate scale from base to display size
  const scale = baseHeightPx > 0 ? height / baseHeightPx : 1;

  ctx.save();
  ctx.globalAlpha = shape.opacity;

  // Transform: move to center, rotate, scale, offset to top-left
  const centerX = x + width / 2;
  const centerY = y + height / 2;
  ctx.translate(centerX, centerY);
  ctx.rotate(shape.rotation);
  ctx.scale(scale, scale);
  ctx.translate(-baseWidthPx / 2, -baseHeightPx / 2);

  // Draw background at base dimensions
  // baseHeightPx now contains actual glyph-based height from measureTextBase,
  // so the background will match the selection bounds exactly
  if (shape.backgroundColor) {
    ctx.fillStyle = colorToCss(shape.backgroundColor);

    // Use baseHeightPx for consistent sizing with selection bounds
    const padding = (shape.backgroundPadding ?? 0) * baseHeightPx;
    const cornerRadius = (shape.backgroundCornerRadius ?? 0) * baseHeightPx * 0.5;

    ctx.beginPath();
    ctx.roundRect(
      -padding,
      -padding,
      baseWidthPx + padding * 2,
      baseHeightPx + padding * 2,
      cornerRadius
    );
    ctx.fill();
  }

  // Set font at BASE size
  const fontStyle = shape.fontStyle === 'italic' ? 'italic ' : '';
  const fontWeight = shape.fontWeight === 'bold' ? 'bold ' : '';
  ctx.font = `${fontStyle}${fontWeight}${TEXT_BASE_FONT_SIZE}px ${shape.fontFamily}`;
  ctx.textAlign = shape.textAlign;

  // Split text into lines
  const lines = shape.text.split('\n');
  const lineHeight = TEXT_BASE_FONT_SIZE * 1.2;

  // Measure actual glyph ascent with alphabetic baseline (same as measureTextBase)
  // This tells us how far glyphs extend above the baseline
  let maxActualAscent = 0;
  for (const line of lines) {
    if (line) {
      const metrics = ctx.measureText(line);
      maxActualAscent = Math.max(maxActualAscent, metrics.actualBoundingBoxAscent || TEXT_BASE_FONT_SIZE * 0.8);
    }
  }
  if (maxActualAscent === 0) {
    maxActualAscent = ctx.measureText('M').actualBoundingBoxAscent || TEXT_BASE_FONT_SIZE * 0.8;
  }

  // Use alphabetic baseline and position it so glyph tops are at y=0
  // With textBaseline='alphabetic', drawing at y=Y puts the baseline at Y
  // Glyphs extend from Y-actualAscent to Y+actualDescent
  // To put glyph top at y=0, we need baseline at y=actualAscent
  ctx.textBaseline = 'alphabetic';
  let baselineY = maxActualAscent;

  // Get the text effect
  const textEffect = shape.textEffect ?? 'none';

  // Calculate shadow offset for positioning - the main text needs to be shifted
  // to leave room for the shadow within the bounds
  let shadowOffsetX = 0;
  let shadowOffsetY = 0;
  if (textEffect === 'shadow' && shape.shadowLength !== undefined) {
    const shadowAmount = TEXT_BASE_FONT_SIZE * 0.5 * (shape.shadowLength / 100);
    const direction = shape.shadowDirection ?? 'bottom-right';
    // Shadow extends in a direction, so main text needs opposite offset
    switch (direction) {
      case 'bottom-left':
        shadowOffsetX = shadowAmount; // text shifts right
        break;
      case 'top-right':
        shadowOffsetY = shadowAmount; // text shifts down
        break;
      case 'top-left':
        shadowOffsetX = shadowAmount; // text shifts right
        shadowOffsetY = shadowAmount; // text shifts down
        break;
      // bottom-right: no offset needed, shadow extends into extra space
    }
    baselineY += shadowOffsetY;
  }

  // Calculate shadow extra space (used to determine content area)
  const shadowAmount = textEffect === 'shadow' && shape.shadowLength !== undefined
    ? TEXT_BASE_FONT_SIZE * 0.5 * (shape.shadowLength / 100)
    : 0;
  // Content width is baseWidth minus shadow extension
  const contentWidth = baseWidthPx - shadowAmount;

  // Calculate text x position based on alignment (in content area, not full width)
  let textX: number;
  switch (shape.textAlign) {
    case 'center':
      textX = shadowOffsetX + contentWidth / 2;
      break;
    case 'right':
      textX = shadowOffsetX + contentWidth;
      break;
    default: // 'left'
      textX = shadowOffsetX;
  }

  // Draw each line with the appropriate effect
  lines.forEach((line, index) => {
    const textY = baselineY + index * lineHeight;

    // Apply text effect
    switch (textEffect) {
      case 'neon':
        renderNeonText(ctx, line, textX, textY, shape, baseWidthPx, lineHeight * lines.length);
        break;

      case 'outline':
        renderOutlineText(ctx, line, textX, textY, shape);
        break;

      case 'gradient':
        renderGradientText(ctx, line, textX, textY, shape, baseWidthPx, lineHeight * lines.length, index, lines.length);
        break;

      case 'shadow':
        renderShadowText(ctx, line, textX, textY, shape, baseWidthPx, lineHeight * lines.length);
        break;

      case 'glitch':
        renderGlitchText(ctx, line, textX, textY, shape, baseWidthPx, lineHeight * lines.length);
        break;

      case 'knockout':
        renderKnockoutText(ctx, line, textX, textY, shape, baseWidthPx, baseHeightPx, index, lines.length);
        break;

      default: // 'none' - standard rendering
        // Draw stroke/outline if present
        if (shape.strokeColor && shape.strokeWidth && shape.strokeWidth > 0) {
          ctx.strokeStyle = colorToCss(shape.strokeColor);
          ctx.lineWidth = shape.strokeWidth;
          ctx.lineJoin = 'round';
          ctx.miterLimit = 2;
          ctx.strokeText(line, textX, textY);
        }

        // Draw fill
        ctx.fillStyle = colorToCss(shape.textColor);
        ctx.fillText(line, textX, textY);
        break;
    }
  });

  // Draw cursor/selection if editing
  if (editState && editState.shapeId === shape.id) {
    renderTextCursor(ctx, shape, editState, baseWidthPx, lineHeight, baseHeightPx, 0);
  }

  ctx.restore();
}

/**
 * Render text with neon glow effect
 * Creates a bright, vibrant neon sign look using shadowBlur for soft glow
 * Uses same approach as pencil path neon for consistency
 */
function renderNeonText(
  ctx: CanvasRenderingContext2D,
  line: string,
  textX: number,
  textY: number,
  shape: TextShape,
  _baseWidthPx: number,
  _totalHeight: number
) {
  const glowIntensity = (shape.glowIntensity ?? 50) / 100;
  const color = shape.textColor;
  const r = typeof color === 'string' ? 255 : color.r;
  const g = typeof color === 'string' ? 255 : color.g;
  const b = typeof color === 'string' ? 255 : color.b;

  // Save state
  const originalShadowBlur = ctx.shadowBlur;
  const originalShadowColor = ctx.shadowColor;
  const originalLineWidth = ctx.lineWidth;
  const originalLineJoin = ctx.lineJoin;

  // Neon text strategy: stroke the outline with neon layers (gives the gradient edge)
  // then fill the interior so it's not hollow
  const strokeWidth = Math.max(4, shape.strokeWidth ?? 6);
  ctx.lineWidth = strokeWidth;
  ctx.lineJoin = 'round';

  // Outer glow layers using strokeText
  // Layer 0: Extra wide atmospheric halo
  ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, 0.15)`;
  ctx.shadowColor = `rgba(${r}, ${g}, ${b}, 1)`;
  ctx.shadowBlur = 120 * glowIntensity;
  ctx.strokeText(line, textX, textY);
  ctx.strokeText(line, textX, textY);

  // Layer 1: Wide diffuse outer glow
  ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, 0.25)`;
  ctx.shadowBlur = 70 * glowIntensity;
  ctx.strokeText(line, textX, textY);
  ctx.strokeText(line, textX, textY);

  // Layer 2: Medium glow
  ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, 0.5)`;
  ctx.shadowBlur = 35 * glowIntensity;
  ctx.strokeText(line, textX, textY);

  // Layer 3: Tight inner glow
  ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, 0.8)`;
  ctx.shadowBlur = 15 * glowIntensity;
  ctx.strokeText(line, textX, textY);

  // Layer 4: Solid stroke
  ctx.strokeStyle = `rgb(${r}, ${g}, ${b})`;
  ctx.shadowBlur = 8 * glowIntensity;
  ctx.strokeText(line, textX, textY);

  // Layer 5: Bright center highlight stroke (thinner)
  const coreR = Math.min(255, r + 200);
  const coreG = Math.min(255, g + 200);
  const coreB = Math.min(255, b + 200);
  ctx.strokeStyle = `rgba(${coreR}, ${coreG}, ${coreB}, ${0.7 * glowIntensity})`;
  ctx.lineWidth = Math.max(1, strokeWidth * 0.5);
  ctx.shadowColor = `rgba(${coreR}, ${coreG}, ${coreB}, 1)`;
  ctx.shadowBlur = 6 * glowIntensity;
  ctx.strokeText(line, textX, textY);

  // Fill the interior with the bright highlight color so letters aren't hollow
  ctx.shadowBlur = 0;
  ctx.fillStyle = `rgb(${coreR}, ${coreG}, ${coreB})`;
  ctx.fillText(line, textX, textY);

  // Restore state
  ctx.shadowBlur = originalShadowBlur;
  ctx.shadowColor = originalShadowColor;
  ctx.lineWidth = originalLineWidth;
  ctx.lineJoin = originalLineJoin;
}

/**
 * Render text with outline-only effect (hollow text)
 * Popular TikTok/Instagram style - stroke only, no fill
 */
function renderOutlineText(
  ctx: CanvasRenderingContext2D,
  line: string,
  textX: number,
  textY: number,
  shape: TextShape
) {
  // Use strokeColor if set, otherwise use textColor for the outline
  const strokeColor = shape.strokeColor ? colorToCss(shape.strokeColor) : colorToCss(shape.textColor);
  // Stroke width, default to a visible outline
  const strokeWidth = shape.strokeWidth ?? Math.max(4, TEXT_BASE_FONT_SIZE * 0.04);

  ctx.strokeStyle = strokeColor;
  ctx.lineWidth = strokeWidth;
  ctx.lineJoin = 'round';
  ctx.miterLimit = 2;
  ctx.strokeText(line, textX, textY);

  // No fill - that's the whole point of outline effect!
}

/**
 * Render text with gradient fill effect
 * Instagram Stories-style gradient text
 */
function renderGradientText(
  ctx: CanvasRenderingContext2D,
  line: string,
  textX: number,
  textY: number,
  shape: TextShape,
  baseWidthPx: number,
  totalHeight: number,
  _lineIndex: number,
  _totalLines: number
) {
  const colors = shape.gradientColors ?? ['#ff6b6b', '#feca57', '#ff9ff3'];
  const direction = shape.gradientDirection ?? 'horizontal';

  // Create gradient based on direction
  let gradient: CanvasGradient;

  switch (direction) {
    case 'vertical':
      // Gradient spans all lines
      gradient = ctx.createLinearGradient(0, 0, 0, totalHeight);
      break;
    case 'diagonal':
      gradient = ctx.createLinearGradient(0, 0, baseWidthPx, totalHeight);
      break;
    default: // 'horizontal'
      gradient = ctx.createLinearGradient(0, 0, baseWidthPx, 0);
      break;
  }

  // Add color stops evenly distributed
  colors.forEach((color, index) => {
    gradient.addColorStop(index / (colors.length - 1), color);
  });

  // Draw stroke/outline if present (underneath gradient)
  if (shape.strokeColor && shape.strokeWidth && shape.strokeWidth > 0) {
    ctx.strokeStyle = colorToCss(shape.strokeColor);
    ctx.lineWidth = shape.strokeWidth;
    ctx.lineJoin = 'round';
    ctx.miterLimit = 2;
    ctx.strokeText(line, textX, textY);
  }

  // Draw gradient fill
  ctx.fillStyle = gradient;
  ctx.fillText(line, textX, textY);
}

/**
 * Render text with long shadow / 3D effect
 * Creates a retro poster-style stacked shadow
 */
function renderShadowText(
  ctx: CanvasRenderingContext2D,
  line: string,
  textX: number,
  textY: number,
  shape: TextShape,
  _baseWidthPx: number,
  _totalHeight: number
) {
  const shadowLength = (shape.shadowLength ?? 50) / 100;
  const direction = shape.shadowDirection ?? 'bottom-right';
  const textColor = colorToCss(shape.textColor);

  // Calculate shadow direction offsets
  let dx = 1, dy = 1;
  switch (direction) {
    case 'bottom-left': dx = -1; dy = 1; break;
    case 'top-right': dx = 1; dy = -1; break;
    case 'top-left': dx = -1; dy = -1; break;
    default: dx = 1; dy = 1; // bottom-right
  }

  // Shadow color - use provided or darken text color
  let shadowColor: string;
  if (shape.shadowColor) {
    shadowColor = colorToCss(shape.shadowColor);
  } else {
    // Create a darker version of the text color
    const tc = shape.textColor;
    if (typeof tc === 'string') {
      // If it's a string color, just use a dark gray
      shadowColor = 'rgba(30, 30, 30, 1)';
    } else {
      shadowColor = `rgba(${Math.floor(tc.r * 0.3)}, ${Math.floor(tc.g * 0.3)}, ${Math.floor(tc.b * 0.3)}, ${tc.a ?? 1})`;
    }
  }

  // Number of shadow layers based on length (more layers = smoother shadow)
  const maxOffset = TEXT_BASE_FONT_SIZE * 0.5 * shadowLength;
  const layers = Math.max(10, Math.floor(maxOffset / 2));

  // Draw shadow layers from back to front
  ctx.fillStyle = shadowColor;
  for (let i = layers; i >= 1; i--) {
    const offset = (i / layers) * maxOffset;
    ctx.fillText(line, textX + offset * dx, textY + offset * dy);
  }

  // Draw stroke if present
  if (shape.strokeColor && shape.strokeWidth && shape.strokeWidth > 0) {
    ctx.strokeStyle = colorToCss(shape.strokeColor);
    ctx.lineWidth = shape.strokeWidth;
    ctx.lineJoin = 'round';
    ctx.miterLimit = 2;
    ctx.strokeText(line, textX, textY);
  }

  // Draw main text on top
  ctx.fillStyle = textColor;
  ctx.fillText(line, textX, textY);
}

/**
 * Render text with glitch / chromatic aberration effect
 * Creates that vaporwave RGB split look
 */
function renderGlitchText(
  ctx: CanvasRenderingContext2D,
  line: string,
  textX: number,
  textY: number,
  shape: TextShape,
  _baseWidthPx: number,
  _totalHeight: number
) {
  const intensity = (shape.glitchIntensity ?? 50) / 100;
  const textColor = shape.textColor;

  // Offset amount based on intensity
  const offset = TEXT_BASE_FONT_SIZE * 0.05 * intensity;

  // Save composite operation
  const originalComposite = ctx.globalCompositeOperation;

  // Draw cyan channel (shifted left)
  ctx.globalCompositeOperation = 'screen';
  ctx.fillStyle = `rgba(0, 255, 255, 0.8)`;
  ctx.fillText(line, textX - offset, textY);

  // Draw red channel (shifted right)
  ctx.fillStyle = `rgba(255, 0, 0, 0.8)`;
  ctx.fillText(line, textX + offset, textY);

  // Draw main text on top
  ctx.globalCompositeOperation = 'source-over';
  ctx.fillStyle = colorToCss(textColor);
  ctx.fillText(line, textX, textY);

  // Add optional scan lines for extra glitch feel at high intensity
  if (intensity > 0.7) {
    ctx.globalCompositeOperation = 'overlay';
    ctx.fillStyle = 'rgba(0, 0, 0, 0.1)';
    const lineHeight = TEXT_BASE_FONT_SIZE * 1.2;
    for (let y = textY; y < textY + lineHeight; y += 4) {
      ctx.fillRect(textX - offset * 2, y, TEXT_BASE_FONT_SIZE * 10, 1);
    }
  }

  // Restore composite operation
  ctx.globalCompositeOperation = originalComposite;
}

/**
 * Render text with knockout / punch-out effect
 * Text cuts through a colored box, revealing what's behind
 * Uses an offscreen canvas to properly composite the knockout
 */
function renderKnockoutText(
  ctx: CanvasRenderingContext2D,
  _line: string,
  _textX: number,
  _textY: number,
  shape: TextShape,
  baseWidthPx: number,
  baseHeightPx: number,
  lineIndex: number,
  _totalLines: number
) {
  const lineHeight = TEXT_BASE_FONT_SIZE * 1.2;

  // Only render on the first line - we'll draw all text at once
  if (lineIndex !== 0) return;

  // Use text color for the knockout box
  const boxColor = shape.textColor;
  const padding = (shape.backgroundPadding ?? 0.15) * baseHeightPx;
  const cornerRadius = (shape.backgroundCornerRadius ?? 0.1) * baseHeightPx * 0.5;

  // Calculate box position based on text alignment
  let boxX = -padding;
  if (shape.textAlign === 'center') {
    boxX = -baseWidthPx / 2 - padding;
  } else if (shape.textAlign === 'right') {
    boxX = -baseWidthPx - padding;
  }

  const boxWidth = baseWidthPx + padding * 2;
  const boxHeight = baseHeightPx + padding * 2;

  // Create offscreen canvas for the knockout effect
  const offscreen = document.createElement('canvas');
  offscreen.width = Math.ceil(boxWidth + 20);
  offscreen.height = Math.ceil(boxHeight + 20);
  const offCtx = offscreen.getContext('2d')!;

  // Offset to account for negative coordinates and padding
  const offsetX = -boxX + 10;
  // Text starts at y=0 within the content area (after padding)
  const offsetY = padding + 10;

  // Draw the background box on offscreen canvas
  offCtx.fillStyle = colorToCss(boxColor);
  offCtx.beginPath();
  offCtx.roundRect(10, 10, boxWidth, boxHeight, cornerRadius);
  offCtx.fill();

  // Set up font on offscreen canvas (same as main)
  const fontStyle = shape.fontStyle === 'italic' ? 'italic ' : '';
  const fontWeight = shape.fontWeight === 'bold' ? 'bold ' : '';
  offCtx.font = `${fontStyle}${fontWeight}${TEXT_BASE_FONT_SIZE}px ${shape.fontFamily}`;
  offCtx.textAlign = shape.textAlign;

  // Measure actual glyph ascent (same approach as main renderText)
  const lines = shape.text.split('\n');
  let maxActualAscent = 0;
  for (const line of lines) {
    if (line) {
      const metrics = offCtx.measureText(line);
      maxActualAscent = Math.max(maxActualAscent, metrics.actualBoundingBoxAscent || TEXT_BASE_FONT_SIZE * 0.8);
    }
  }
  if (maxActualAscent === 0) {
    maxActualAscent = offCtx.measureText('M').actualBoundingBoxAscent || TEXT_BASE_FONT_SIZE * 0.8;
  }

  // Use alphabetic baseline positioned so glyph tops are at content top
  offCtx.textBaseline = 'alphabetic';
  const baselineY = maxActualAscent;

  // Cut out the text using destination-out
  offCtx.globalCompositeOperation = 'destination-out';
  offCtx.fillStyle = 'white';

  // Draw all lines of text - match the positioning in main renderText
  lines.forEach((textLine, idx) => {
    // Text y position: baseline at baselineY for first line, plus lineHeight for subsequent
    const y = offsetY + baselineY + idx * lineHeight;
    let x = offsetX;
    if (shape.textAlign === 'center') {
      x = offsetX + baseWidthPx / 2;
    } else if (shape.textAlign === 'right') {
      x = offsetX + baseWidthPx;
    }
    offCtx.fillText(textLine, x, y);
  });

  // Draw the offscreen canvas onto the main canvas
  ctx.drawImage(offscreen, boxX - 10, -padding - 10);
}

/**
 * Render the text cursor and selection highlight during editing
 */
function renderTextCursor(
  ctx: CanvasRenderingContext2D,
  shape: TextShape,
  editState: TextEditState,
  baseWidthPx: number,
  lineHeight: number,
  baseHeightPx: number,
  textYOffset: number
) {
  const text = shape.text;
  const lines = text.split('\n');
  const numLines = lines.length;

  // Calculate the actual content height per line based on glyph metrics
  // For single line: full baseHeightPx
  // For multiple lines: baseHeightPx = singleLineHeight + (n-1) * lineHeight
  // So singleLineHeight = baseHeightPx - (n-1) * lineHeight
  const singleLineContentHeight = numLines === 1
    ? baseHeightPx
    : Math.max(baseHeightPx - (numLines - 1) * lineHeight, TEXT_BASE_FONT_SIZE);

  // Calculate cursor position
  let charCount = 0;
  let cursorLine = 0;
  let cursorCol = 0;

  for (let i = 0; i < lines.length; i++) {
    const lineLength = lines[i].length;
    if (charCount + lineLength >= editState.cursorIndex) {
      cursorLine = i;
      cursorCol = editState.cursorIndex - charCount;
      break;
    }
    charCount += lineLength + 1; // +1 for newline
    if (i === lines.length - 1) {
      cursorLine = i;
      cursorCol = lineLength;
    }
  }

  // Measure text up to cursor position
  const lineText = lines[cursorLine] || '';
  const textBeforeCursor = lineText.substring(0, cursorCol);

  // Set up font for measurement (same as rendering)
  const fontStyle = shape.fontStyle === 'italic' ? 'italic ' : '';
  const fontWeight = shape.fontWeight === 'bold' ? 'bold ' : '';
  ctx.font = `${fontStyle}${fontWeight}${TEXT_BASE_FONT_SIZE}px ${shape.fontFamily}`;

  const textMetrics = ctx.measureText(textBeforeCursor);
  const fullLineMetrics = ctx.measureText(lineText);

  // Calculate x position based on alignment
  let lineStartX: number;
  switch (shape.textAlign) {
    case 'center':
      lineStartX = (baseWidthPx - fullLineMetrics.width) / 2;
      break;
    case 'right':
      lineStartX = baseWidthPx - fullLineMetrics.width;
      break;
    default: // 'left'
      lineStartX = 0;
  }

  const cursorX = lineStartX + textMetrics.width;
  const cursorY = cursorLine * lineHeight + textYOffset;

  // Draw selection highlight if there's a selection
  if (editState.selectionAnchor !== null && editState.selectionAnchor !== editState.cursorIndex) {
    const selStart = Math.min(editState.selectionAnchor, editState.cursorIndex);
    const selEnd = Math.max(editState.selectionAnchor, editState.cursorIndex);

    ctx.fillStyle = 'rgba(59, 130, 246, 0.3)'; // Blue highlight

    // Draw selection across lines
    let pos = 0;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const lineStart = pos;
      const lineEnd = pos + line.length;

      if (lineEnd >= selStart && lineStart <= selEnd) {
        const highlightStart = Math.max(selStart - lineStart, 0);
        const highlightEnd = Math.min(selEnd - lineStart, line.length);

        const beforeHighlight = line.substring(0, highlightStart);
        const highlightText = line.substring(highlightStart, highlightEnd);

        const beforeWidth = ctx.measureText(beforeHighlight).width;
        const highlightWidth = ctx.measureText(highlightText).width;

        const fullLine = ctx.measureText(line);
        let hlLineStartX: number;
        switch (shape.textAlign) {
          case 'center':
            hlLineStartX = (baseWidthPx - fullLine.width) / 2;
            break;
          case 'right':
            hlLineStartX = baseWidthPx - fullLine.width;
            break;
          default:
            hlLineStartX = 0;
        }

        // Use singleLineContentHeight for selection highlight to match bounds
        ctx.fillRect(
          hlLineStartX + beforeWidth,
          i * lineHeight + textYOffset,
          highlightWidth,
          singleLineContentHeight
        );
      }

      pos = lineEnd + 1; // +1 for newline
    }
  }

  // Draw cursor if visible
  if (editState.cursorVisible) {
    const cursorWidth = 3;
    const cursorPadding = 2; // Padding from top/bottom edges
    ctx.fillStyle = '#3b82f6'; // Blue cursor
    // Use singleLineContentHeight for cursor to match bounds
    ctx.fillRect(
      cursorX - cursorWidth / 2, // Center the cursor on the position
      cursorY + cursorPadding,
      cursorWidth,
      singleLineContentHeight - cursorPadding * 2
    );
  }
}

/**
 * Measure text dimensions at BASE_FONT_SIZE using actual glyph metrics
 * Returns dimensions in pixels at the base font size based on what's actually rendered
 * Uses font's bounding box metrics for consistent baseline-relative positioning
 */
export function measureTextBase(
  text: string,
  fontFamily: string,
  fontWeight: 'normal' | 'bold',
  fontStyle: 'normal' | 'italic',
  textEffect?: string,
  shadowLength?: number,
  _shadowDirection?: string
): { width: number; height: number; ascentOffset: number; actualAscent: number; actualDescent: number } {
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d')!;

  const fontStyleStr = fontStyle === 'italic' ? 'italic ' : '';
  const fontWeightStr = fontWeight === 'bold' ? 'bold ' : '';
  ctx.font = `${fontStyleStr}${fontWeightStr}${TEXT_BASE_FONT_SIZE}px ${fontFamily}`;

  const lines = text.split('\n');
  const lineHeight = TEXT_BASE_FONT_SIZE * 1.2;

  let maxWidth = 0;
  let maxActualAscent = 0;
  let maxActualDescent = 0;

  for (const line of lines) {
    const metrics = ctx.measureText(line || 'M'); // Use 'M' for empty lines to get reasonable metrics
    maxWidth = Math.max(maxWidth, line ? metrics.width : 0);

    // Get actual glyph bounds - these tell us the true visual extent
    // actualBoundingBoxAscent: distance from baseline to top of actual glyphs
    // actualBoundingBoxDescent: distance from baseline to bottom of actual glyphs
    if (line) {
      maxActualAscent = Math.max(maxActualAscent, metrics.actualBoundingBoxAscent || TEXT_BASE_FONT_SIZE * 0.8);
      maxActualDescent = Math.max(maxActualDescent, metrics.actualBoundingBoxDescent || TEXT_BASE_FONT_SIZE * 0.2);
    }
  }

  // Fallback for empty text or missing metrics
  if (maxActualAscent === 0) {
    const mMetrics = ctx.measureText('M');
    maxActualAscent = mMetrics.actualBoundingBoxAscent || TEXT_BASE_FONT_SIZE * 0.8;
    maxActualDescent = mMetrics.actualBoundingBoxDescent || TEXT_BASE_FONT_SIZE * 0.2;
  }

  // Add padding to account for font rendering variations and character overhangs
  // This ensures text doesn't escape the selection bounds (especially italic text
  // or characters with negative left bearing)
  const widthPadding = TEXT_BASE_FONT_SIZE * 0.05;

  // Calculate actual content height based on real glyph metrics:
  // - First line contributes its actual ascent + descent
  // - Subsequent lines add lineHeight for spacing
  const singleLineHeight = maxActualAscent + maxActualDescent;
  const actualTextHeight = lines.length === 1
    ? singleLineHeight
    : singleLineHeight + (lines.length - 1) * lineHeight;

  // The ascentOffset is how much the actual content top differs from the standard position
  // This allows the background to be positioned tightly around actual glyphs
  const standardAscent = TEXT_BASE_FONT_SIZE * 0.8; // Approximate cap height
  const ascentOffset = standardAscent - maxActualAscent;

  // Account for shadow effect extending the bounds
  let shadowWidthExtra = 0;
  let shadowHeightExtra = 0;
  if (textEffect === 'shadow' && shadowLength !== undefined) {
    const shadowOffset = TEXT_BASE_FONT_SIZE * 0.5 * (shadowLength / 100);
    // Shadow extends in a direction, adding to both width and height
    shadowWidthExtra = shadowOffset;
    shadowHeightExtra = shadowOffset;
  }

  return {
    width: maxWidth + widthPadding + shadowWidthExtra,
    height: actualTextHeight + shadowHeightExtra,
    ascentOffset,
    actualAscent: maxActualAscent,
    actualDescent: maxActualDescent,
  };
}

/**
 * Measure text dimensions for bounding box calculation
 * @deprecated Use measureTextBase instead - fontSize is now derived from scale
 */
export function measureText(
  text: string,
  fontSize: number,
  fontFamily: string,
  fontWeight: 'normal' | 'bold',
  fontStyle: 'normal' | 'italic'
): { width: number; height: number } {
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d')!;

  const fontStyleStr = fontStyle === 'italic' ? 'italic ' : '';
  const fontWeightStr = fontWeight === 'bold' ? 'bold ' : '';
  ctx.font = `${fontStyleStr}${fontWeightStr}${fontSize}px ${fontFamily}`;

  const lines = text.split('\n');
  const lineHeight = fontSize * 1.2;

  let maxWidth = 0;
  for (const line of lines) {
    const metrics = ctx.measureText(line);
    maxWidth = Math.max(maxWidth, metrics.width);
  }

  return {
    width: maxWidth,
    height: lines.length * lineHeight,
  };
}

/**
 * Render a redact shape with pixelation effect
 * Samples from the source image and applies block averaging
 */
export function renderRedact(
  ctx: CanvasRenderingContext2D,
  shape: RedactShape,
  imageSize: Size,
  sourceImage?: HTMLImageElement | HTMLCanvasElement
) {
  if (!sourceImage) return;

  const x = toPixels(shape.x, imageSize.width);
  const y = toPixels(shape.y, imageSize.height);
  const width = toPixels(shape.width, imageSize.width);
  const height = toPixels(shape.height, imageSize.height);
  const blockSize = Math.max(2, Math.round(shape.blockSize));

  if (width <= 0 || height <= 0) return;

  ctx.save();
  ctx.globalAlpha = shape.opacity;

  // Calculate center for rotation
  const centerX = x + width / 2;
  const centerY = y + height / 2;

  // Apply rotation around center
  ctx.translate(centerX, centerY);
  ctx.rotate(shape.rotation);
  ctx.translate(-centerX, -centerY);

  // Create a temporary canvas to sample from the source
  const tempCanvas = document.createElement('canvas');
  tempCanvas.width = Math.ceil(width);
  tempCanvas.height = Math.ceil(height);
  const tempCtx = tempCanvas.getContext('2d')!;

  // Draw the source region to temp canvas
  // Note: We need to sample from source at the shape's position in image space
  const sourceX = toPixels(shape.x, imageSize.width);
  const sourceY = toPixels(shape.y, imageSize.height);

  tempCtx.drawImage(
    sourceImage,
    sourceX, sourceY, width, height,
    0, 0, width, height
  );

  // Get the image data and apply pixelation
  const imageData = tempCtx.getImageData(0, 0, Math.ceil(width), Math.ceil(height));
  const data = imageData.data;
  const imgWidth = imageData.width;
  const imgHeight = imageData.height;

  // Process each block
  for (let blockY = 0; blockY < imgHeight; blockY += blockSize) {
    for (let blockX = 0; blockX < imgWidth; blockX += blockSize) {
      // Calculate block bounds
      const blockEndX = Math.min(blockX + blockSize, imgWidth);
      const blockEndY = Math.min(blockY + blockSize, imgHeight);

      // Calculate average color for this block
      let totalR = 0, totalG = 0, totalB = 0, totalA = 0;
      let pixelCount = 0;

      for (let py = blockY; py < blockEndY; py++) {
        for (let px = blockX; px < blockEndX; px++) {
          const idx = (py * imgWidth + px) * 4;
          totalR += data[idx];
          totalG += data[idx + 1];
          totalB += data[idx + 2];
          totalA += data[idx + 3];
          pixelCount++;
        }
      }

      const avgR = Math.round(totalR / pixelCount);
      const avgG = Math.round(totalG / pixelCount);
      const avgB = Math.round(totalB / pixelCount);
      const avgA = Math.round(totalA / pixelCount);

      // Apply average color to all pixels in block
      for (let py = blockY; py < blockEndY; py++) {
        for (let px = blockX; px < blockEndX; px++) {
          const idx = (py * imgWidth + px) * 4;
          data[idx] = avgR;
          data[idx + 1] = avgG;
          data[idx + 2] = avgB;
          data[idx + 3] = avgA;
        }
      }
    }
  }

  // Put pixelated data back
  tempCtx.putImageData(imageData, 0, 0);

  // Draw the pixelated result to the main canvas
  ctx.drawImage(tempCanvas, x, y);

  ctx.restore();
}

/**
 * Render a shape based on its type
 */
export function renderShape(
  ctx: CanvasRenderingContext2D,
  shape: Shape,
  imageSize: Size,
  sourceImage?: HTMLImageElement | HTMLCanvasElement,
  textEditState?: TextEditState | null
) {
  switch (shape.type) {
    case 'line':
      renderLine(ctx, shape, imageSize);
      break;
    case 'curved-arrow':
      renderCurvedArrow(ctx, shape, imageSize);
      break;
    case 'rectangle':
      renderRectangle(ctx, shape, imageSize);
      break;
    case 'ellipse':
      renderEllipse(ctx, shape, imageSize);
      break;
    case 'path':
      renderPath(ctx, shape, imageSize);
      break;
    case 'text': {
      // Pass edit state only for the shape being edited
      const editState = textEditState?.shapeId === shape.id ? textEditState : undefined;
      renderText(ctx, shape, imageSize, editState);
      break;
    }
    case 'redact':
      renderRedact(ctx, shape, imageSize, sourceImage);
      break;
    case 'triangle':
      renderTriangle(ctx, shape, imageSize);
      break;
    case 'star':
      renderStar(ctx, shape, imageSize);
      break;
    case 'polygon':
      renderPolygon(ctx, shape, imageSize);
      break;
    // Sticker rendering would go here
  }
}

/**
 * Render all shapes
 */
export function renderShapes(
  ctx: CanvasRenderingContext2D,
  shapes: Shape[],
  imageSize: Size,
  sourceImage?: HTMLImageElement | HTMLCanvasElement,
  textEditState?: TextEditState | null
) {
  for (const shape of shapes) {
    renderShape(ctx, shape, imageSize, sourceImage, textEditState);
  }
}

/**
 * Draw selection handles around a shape
 * - Corner handles are large circles
 * - Rotation handle is a lollipop above the shape
 * - Handles rotate with the shape
 * - shapeCenter is the actual rotation pivot point (shape.x, shape.y in normalized coords)
 */
export function drawSelectionHandles(
  ctx: CanvasRenderingContext2D,
  bounds: { x: number; y: number; width: number; height: number },
  imageSize: Size,
  rotation: number = 0,
  shapeCenter?: { x: number; y: number },
  scale: number = 1
) {
  const x = toPixels(bounds.x, imageSize.width);
  const y = toPixels(bounds.y, imageSize.height);
  const width = toPixels(bounds.width, imageSize.width);
  const height = toPixels(bounds.height, imageSize.height);

  // Compensate for zoom so handles remain fixed visual size
  const cornerRadius = 7 / scale;
  const rotateHandleRadius = 7 / scale;
  const lineWidth = 2 / scale;
  const borderDash = [6 / scale, 4 / scale];
  const stemDash = [4 / scale, 3 / scale];

  // Use same normalized offset as getResizeHandlePositions (0.03)
  const rotateHandleOffset = 0.03;
  const rotateHandleDistance = toPixels(rotateHandleOffset, imageSize.height);

  // Use provided shape center for rotation, or fall back to bounds center
  const centerX = shapeCenter ? toPixels(shapeCenter.x, imageSize.width) : x + width / 2;
  const centerY = shapeCenter ? toPixels(shapeCenter.y, imageSize.height) : y + height / 2;

  ctx.save();

  // Apply rotation around the center of the shape
  ctx.translate(centerX, centerY);
  ctx.rotate(rotation);
  ctx.translate(-centerX, -centerY);

  // Draw selection border - thicker and more visible
  ctx.strokeStyle = '#3b82f6';
  ctx.lineWidth = lineWidth;
  ctx.setLineDash(borderDash);
  ctx.strokeRect(x, y, width, height);
  ctx.setLineDash([]);

  // Draw rotation handle stem (dashed line from bottom center)
  const bottomCenterX = x + width / 2;
  const bottomCenterY = y + height;
  const rotateHandleY = y + height + rotateHandleDistance;

  ctx.strokeStyle = '#3b82f6';
  ctx.lineWidth = lineWidth;
  ctx.setLineDash(stemDash);
  ctx.beginPath();
  ctx.moveTo(bottomCenterX, bottomCenterY);
  ctx.lineTo(bottomCenterX, rotateHandleY);
  ctx.stroke();
  ctx.setLineDash([]);

  // Draw rotation handle circle (lollipop)
  ctx.fillStyle = '#ffffff';
  ctx.strokeStyle = '#3b82f6';
  ctx.lineWidth = lineWidth;
  ctx.beginPath();
  ctx.arc(bottomCenterX, rotateHandleY, rotateHandleRadius, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();

  // Draw corner handles as circles
  ctx.fillStyle = '#ffffff';
  ctx.strokeStyle = '#3b82f6';
  ctx.lineWidth = lineWidth;

  const corners = [
    { x: x, y: y }, // NW
    { x: x + width, y: y }, // NE
    { x: x + width, y: y + height }, // SE
    { x: x, y: y + height }, // SW
  ];

  for (const corner of corners) {
    ctx.beginPath();
    ctx.arc(corner.x, corner.y, cornerRadius, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }

  ctx.restore();
}

/**
 * Get bounding box for a shape (at stroke midpoint, not including full stroke width)
 * For star/polygon, imageSize is needed for accurate bounds matching avgImageDim rendering
 */
export function getShapeBounds(shape: Shape, imageSize?: Size): { x: number; y: number; width: number; height: number } {
  switch (shape.type) {
    case 'rectangle':
      return {
        x: shape.x,
        y: shape.y,
        width: shape.width,
        height: shape.height
      };
    case 'ellipse':
      return {
        x: shape.x - shape.rx,
        y: shape.y - shape.ry,
        width: shape.rx * 2,
        height: shape.ry * 2
      };
    case 'line': {
      const minX = Math.min(shape.x1, shape.x2);
      const minY = Math.min(shape.y1, shape.y2);
      const maxX = Math.max(shape.x1, shape.x2);
      const maxY = Math.max(shape.y1, shape.y2);
      return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
    }
    case 'curved-arrow': {
      if (shape.rawPoints.length === 0) return { x: 0, y: 0, width: 0, height: 0 };
      let caMinX = Infinity, caMinY = Infinity, caMaxX = -Infinity, caMaxY = -Infinity;
      for (const p of shape.rawPoints) {
        caMinX = Math.min(caMinX, p.x);
        caMinY = Math.min(caMinY, p.y);
        caMaxX = Math.max(caMaxX, p.x);
        caMaxY = Math.max(caMaxY, p.y);
      }
      return {
        x: caMinX,
        y: caMinY,
        width: caMaxX - caMinX,
        height: caMaxY - caMinY
      };
    }
    case 'path':
      if (shape.points.length === 0) return { x: 0, y: 0, width: 0, height: 0 };
      let pathMinX = Infinity, pathMinY = Infinity, pathMaxX = -Infinity, pathMaxY = -Infinity;
      for (const p of shape.points) {
        pathMinX = Math.min(pathMinX, p.x);
        pathMinY = Math.min(pathMinY, p.y);
        pathMaxX = Math.max(pathMaxX, p.x);
        pathMaxY = Math.max(pathMaxY, p.y);
      }
      return {
        x: pathMinX,
        y: pathMinY,
        width: pathMaxX - pathMinX,
        height: pathMaxY - pathMinY
      };
    case 'text':
      return {
        x: shape.x,
        y: shape.y,
        width: shape.width,
        height: shape.height
      };
    case 'redact':
      return {
        x: shape.x,
        y: shape.y,
        width: shape.width,
        height: shape.height
      };
    case 'triangle':
      return {
        x: shape.x,
        y: shape.y,
        width: shape.width,
        height: shape.height
      };
    case 'star': {
      // Calculate actual bounds from star vertices, accounting for avgImageDim rendering
      const starPoints = shape.points;
      const aspectRatio = shape.aspectRatio ?? 1.0;

      // Calculate scale factors from avgImageDim to normalized coords
      // Rendering uses: avgImageDim = (width + height) / 2
      // scaleX converts from avgImageDim-relative to width-relative normalized coords
      // scaleY converts from avgImageDim-relative to height-relative normalized coords
      let scaleX = 1.0, scaleY = 1.0;
      if (imageSize) {
        const avgImageDim = (imageSize.width + imageSize.height) / 2;
        scaleX = avgImageDim / imageSize.width;
        scaleY = avgImageDim / imageSize.height;
      }

      let starMinX = Infinity, starMinY = Infinity, starMaxX = -Infinity, starMaxY = -Infinity;
      for (let i = 0; i < starPoints * 2; i++) {
        const isOuter = i % 2 === 0;
        const radius = isOuter ? shape.outerRadius : shape.innerRadius;
        const angle = (i * Math.PI) / starPoints - Math.PI / 2;
        // Apply aspectRatio to x (matching rendering) and scale factors
        const vx = Math.cos(angle) * radius * aspectRatio * scaleX;
        const vy = Math.sin(angle) * radius * scaleY;
        starMinX = Math.min(starMinX, vx);
        starMinY = Math.min(starMinY, vy);
        starMaxX = Math.max(starMaxX, vx);
        starMaxY = Math.max(starMaxY, vy);
      }
      return {
        x: shape.x + starMinX,
        y: shape.y + starMinY,
        width: starMaxX - starMinX,
        height: starMaxY - starMinY
      };
    }
    case 'polygon': {
      // Calculate actual bounds from polygon vertices, accounting for avgImageDim rendering
      const sides = shape.sides;
      const aspectRatio = shape.aspectRatio ?? 1.0;

      // Calculate scale factors from avgImageDim to normalized coords
      let scaleX = 1.0, scaleY = 1.0;
      if (imageSize) {
        const avgImageDim = (imageSize.width + imageSize.height) / 2;
        scaleX = avgImageDim / imageSize.width;
        scaleY = avgImageDim / imageSize.height;
      }

      let polyMinX = Infinity, polyMinY = Infinity, polyMaxX = -Infinity, polyMaxY = -Infinity;
      for (let i = 0; i < sides; i++) {
        const angle = (i * 2 * Math.PI) / sides - Math.PI / 2;
        // Apply aspectRatio to x (matching rendering) and scale factors
        const vx = Math.cos(angle) * shape.radius * aspectRatio * scaleX;
        const vy = Math.sin(angle) * shape.radius * scaleY;
        polyMinX = Math.min(polyMinX, vx);
        polyMinY = Math.min(polyMinY, vy);
        polyMaxX = Math.max(polyMaxX, vx);
        polyMaxY = Math.max(polyMaxY, vy);
      }
      return {
        x: shape.x + polyMinX,
        y: shape.y + polyMinY,
        width: polyMaxX - polyMinX,
        height: polyMaxY - polyMinY
      };
    }
    default:
      return { x: shape.x, y: shape.y, width: 0.1, height: 0.1 };
  }
}

/**
 * Generate a unique shape ID
 */
export function generateShapeId(): string {
  return `shape_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

/**
 * Distance from point to line segment
 */
function distanceToLineSegment(point: Point, p1: Point, p2: Point): number {
  const dx = p2.x - p1.x;
  const dy = p2.y - p1.y;
  const lengthSquared = dx * dx + dy * dy;

  if (lengthSquared === 0) {
    return Math.sqrt((point.x - p1.x) ** 2 + (point.y - p1.y) ** 2);
  }

  let t = ((point.x - p1.x) * dx + (point.y - p1.y) * dy) / lengthSquared;
  t = Math.max(0, Math.min(1, t));

  const projX = p1.x + t * dx;
  const projY = p1.y + t * dy;

  return Math.sqrt((point.x - projX) ** 2 + (point.y - projY) ** 2);
}

/**
 * Check if point is inside a rectangle
 */
function pointInRect(point: Point, x: number, y: number, width: number, height: number): boolean {
  return point.x >= x && point.x <= x + width && point.y >= y && point.y <= y + height;
}

/**
 * Check if point is inside an ellipse
 */
function pointInEllipse(point: Point, cx: number, cy: number, rx: number, ry: number): boolean {
  if (rx === 0 || ry === 0) return false;
  const dx = point.x - cx;
  const dy = point.y - cy;
  return (dx * dx) / (rx * rx) + (dy * dy) / (ry * ry) <= 1;
}

/**
 * Get the center point of a shape for rotation
 */
export function getShapeCenter(shape: Shape): Point {
  switch (shape.type) {
    case 'rectangle':
      return { x: shape.x + shape.width / 2, y: shape.y + shape.height / 2 };
    case 'ellipse':
      return { x: shape.x, y: shape.y };
    case 'line':
      return { x: (shape.x1 + shape.x2) / 2, y: (shape.y1 + shape.y2) / 2 };
    case 'path': {
      if (shape.points.length === 0) return { x: 0, y: 0 };
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const p of shape.points) {
        minX = Math.min(minX, p.x);
        minY = Math.min(minY, p.y);
        maxX = Math.max(maxX, p.x);
        maxY = Math.max(maxY, p.y);
      }
      return { x: (minX + maxX) / 2, y: (minY + maxY) / 2 };
    }
    case 'curved-arrow': {
      if (shape.rawPoints.length === 0) return { x: 0, y: 0 };
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const p of shape.rawPoints) {
        minX = Math.min(minX, p.x);
        minY = Math.min(minY, p.y);
        maxX = Math.max(maxX, p.x);
        maxY = Math.max(maxY, p.y);
      }
      return { x: (minX + maxX) / 2, y: (minY + maxY) / 2 };
    }
    case 'sticker':
      return { x: shape.x + shape.width / 2, y: shape.y + shape.height / 2 };
    case 'text':
      return { x: shape.x + shape.width / 2, y: shape.y + shape.height / 2 };
    case 'redact':
      return { x: shape.x + shape.width / 2, y: shape.y + shape.height / 2 };
    case 'triangle':
      return { x: shape.x + shape.width / 2, y: shape.y + shape.height / 2 };
    case 'star':
      return { x: shape.x, y: shape.y };
    case 'polygon':
      return { x: shape.x, y: shape.y };
  }
}

/**
 * Hit test a shape at a given point (in image coordinates 0-1)
 * Returns true if the point hits the shape
 * @param aspectRatio - image width/height for correct rotation in normalized coordinates
 */
export function hitTestShape(shape: Shape, point: Point, tolerance: number = 0.01, aspectRatio: number = 1): boolean {
  if (shape.disableSelect) return false;

  // Transform the click point to local (unrotated) coordinate system
  const center = getShapeCenter(shape);
  const localPoint = rotatePoint(point, center, -(shape.rotation || 0), aspectRatio);

  switch (shape.type) {
    case 'rectangle': {
      // Check stroke (border) and fill
      const hasStroke = shape.strokeColor && shape.strokeWidth;
      const hasFill = shape.backgroundColor;
      const strokeTolerance = hasStroke ? (shape.strokeWidth ?? 0) / 200 + tolerance : tolerance;

      if (hasFill) {
        if (pointInRect(localPoint, shape.x, shape.y, shape.width, shape.height)) return true;
      }
      if (hasStroke) {
        // Check each edge
        const x1 = shape.x, y1 = shape.y;
        const x2 = shape.x + shape.width, y2 = shape.y + shape.height;
        if (distanceToLineSegment(localPoint, { x: x1, y: y1 }, { x: x2, y: y1 }) < strokeTolerance) return true;
        if (distanceToLineSegment(localPoint, { x: x2, y: y1 }, { x: x2, y: y2 }) < strokeTolerance) return true;
        if (distanceToLineSegment(localPoint, { x: x2, y: y2 }, { x: x1, y: y2 }) < strokeTolerance) return true;
        if (distanceToLineSegment(localPoint, { x: x1, y: y2 }, { x: x1, y: y1 }) < strokeTolerance) return true;
      }
      // Fallback: check bounding box with tolerance
      return pointInRect(localPoint, shape.x - tolerance, shape.y - tolerance,
        shape.width + tolerance * 2, shape.height + tolerance * 2);
    }

    case 'ellipse': {
      const strokeTolerance = (shape.strokeWidth ?? 0) / 200 + tolerance;
      const outerRx = shape.rx + strokeTolerance;
      const outerRy = shape.ry + strokeTolerance;

      // For selection, clicking anywhere inside the ellipse outline should hit
      // This makes unfilled ellipses much easier to select
      return pointInEllipse(localPoint, shape.x, shape.y, outerRx, outerRy);
    }

    case 'line': {
      const strokeTolerance = shape.strokeWidth / 200 + tolerance;
      return distanceToLineSegment(localPoint,
        { x: shape.x1, y: shape.y1 },
        { x: shape.x2, y: shape.y2 }
      ) < strokeTolerance;
    }

    case 'path': {
      // For paths/scribbles, use tight hit testing - only hit the actual stroke
      // Use a small fixed tolerance (about 12px on a 1000px image)
      const strokeTolerance = 0.012;
      // Check each segment
      for (let i = 0; i < shape.points.length - 1; i++) {
        if (distanceToLineSegment(localPoint, shape.points[i], shape.points[i + 1]) < strokeTolerance) {
          return true;
        }
      }
      return false;
    }

    case 'curved-arrow': {
      const strokeTolerance = shape.strokeWidth / 200 + tolerance;
      // Check each segment of rawPoints
      for (let i = 0; i < shape.rawPoints.length - 1; i++) {
        if (distanceToLineSegment(localPoint, shape.rawPoints[i], shape.rawPoints[i + 1]) < strokeTolerance) {
          return true;
        }
      }
      return false;
    }

    case 'sticker': {
      return pointInRect(localPoint, shape.x, shape.y, shape.width, shape.height);
    }

    case 'text': {
      return pointInRect(localPoint, shape.x, shape.y, shape.width, shape.height);
    }

    case 'redact': {
      return pointInRect(localPoint, shape.x, shape.y, shape.width, shape.height);
    }

    case 'triangle': {
      // Use bounding box for triangle hit testing
      return pointInRect(localPoint, shape.x, shape.y, shape.width, shape.height);
    }

    case 'star': {
      // Use bounding circle for star hit testing
      const strokeTolerance = (shape.strokeWidth ?? 0) / 200 + tolerance;
      const radius = shape.outerRadius + strokeTolerance;
      return pointInEllipse(localPoint, shape.x, shape.y, radius, radius);
    }

    case 'polygon': {
      // Use bounding circle for polygon hit testing
      const strokeTolerance = (shape.strokeWidth ?? 0) / 200 + tolerance;
      const radius = shape.radius + strokeTolerance;
      return pointInEllipse(localPoint, shape.x, shape.y, radius, radius);
    }

    default:
      return false;
  }
}

/**
 * Find the topmost shape at a given point
 * Returns the shape or null if none found
 */
export function findShapeAtPoint(shapes: Shape[], point: Point, tolerance: number = 0.01, aspectRatio: number = 1): Shape | null {
  // Iterate in reverse (topmost shapes are last in array)
  for (let i = shapes.length - 1; i >= 0; i--) {
    if (hitTestShape(shapes[i], point, tolerance, aspectRatio)) {
      return shapes[i];
    }
  }
  return null;
}

/**
 * Get resize handle positions for a shape's bounds
 */
export function getResizeHandlePositions(
  bounds: { x: number; y: number; width: number; height: number }
): Record<ResizeHandle, Point> {
  const { x, y, width, height } = bounds;
  // Rotation handle distance in normalized coords (approximate)
  const rotateHandleOffset = 0.03;

  return {
    nw: { x, y },
    n: { x: x + width / 2, y },
    ne: { x: x + width, y },
    e: { x: x + width, y: y + height / 2 },
    se: { x: x + width, y: y + height },
    s: { x: x + width / 2, y: y + height },
    sw: { x, y: y + height },
    w: { x, y: y + height / 2 },
    rotate: { x: x + width / 2, y: y + height + rotateHandleOffset },
  };
}

/**
 * Rotate a point around a center by an angle
 * @param aspectRatio - width/height ratio of the image. When provided, corrects for non-square images
 *                      so that rotation in normalized coordinates matches visual rotation in pixel space.
 *
 * The math: To rotate in pixel space but work in normalized coords:
 * - px = dx * W, py = dy * H (convert to pixels)
 * - Rotate: rx = px*cos - py*sin, ry = px*sin + py*cos
 * - Convert back: x_out = rx/W, y_out = ry/H
 * This simplifies to the formulas below.
 */
function rotatePoint(point: Point, center: Point, angle: number, aspectRatio: number = 1): Point {
  if (!angle || Math.abs(angle) < 0.001) return point;

  const dx = point.x - center.x;
  const dy = point.y - center.y;

  const cos = Math.cos(angle);
  const sin = Math.sin(angle);

  // Rotate with aspect ratio correction to match pixel-space rotation
  return {
    x: center.x + dx * cos - dy * sin / aspectRatio,
    y: center.y + dx * aspectRatio * sin + dy * cos
  };
}

/**
 * Hit test resize handles
 * Returns the handle name or null
 * Only tests corners and rotate handle (not edge handles)
 * @param aspectRatio - image width/height for correct rotation in normalized coordinates
 */
export function hitTestResizeHandle(
  bounds: { x: number; y: number; width: number; height: number },
  point: Point,
  handleRadius: number = 0.025, // Larger hit area for easier grabbing
  rotation: number = 0,
  aspectRatio: number = 1,
  shapeCenter?: Point
): ResizeHandle | null {
  const handles = getResizeHandlePositions(bounds);
  // Use provided shape center for rotation, or fall back to bounds center
  const center = shapeCenter ?? { x: bounds.x + bounds.width / 2, y: bounds.y + bounds.height / 2 };

  // Transform the click point to local (unrotated) coordinate system
  // by rotating it by the negative angle around the shape center
  const localPoint = rotatePoint(point, center, -rotation, aspectRatio);

  // Test rotate handle first (highest priority)
  // Scale dy to x-equivalent units for proper circular hit testing
  const rotateDx = localPoint.x - handles.rotate.x;
  const rotateDy = (localPoint.y - handles.rotate.y) * aspectRatio;
  if (Math.sqrt(rotateDx * rotateDx + rotateDy * rotateDy) < handleRadius) {
    return 'rotate';
  }

  // Test corner handles only (no edge handles)
  const corners: ResizeHandle[] = ['nw', 'ne', 'se', 'sw'];
  for (const name of corners) {
    const dx = localPoint.x - handles[name].x;
    const dy = (localPoint.y - handles[name].y) * aspectRatio;
    if (Math.sqrt(dx * dx + dy * dy) < handleRadius) {
      return name;
    }
  }

  return null;
}

/**
 * Get cursor style for a resize handle
 */
export function getResizeHandleCursor(handle: ResizeHandle | null): string {
  if (!handle) return 'default';
  switch (handle) {
    case 'n': case 's': return 'ns-resize';
    case 'e': case 'w': return 'ew-resize';
    case 'ne': case 'sw': return 'nesw-resize';
    case 'nw': case 'se': return 'nwse-resize';
    case 'rotate': return 'grab';
    default: return 'default';
  }
}

/**
 * Apply a resize operation to shape bounds
 */
export function resizeShapeBounds(
  shape: Shape,
  handle: ResizeHandle,
  dx: number,
  dy: number,
  constrainAspect: boolean = false,
  imageSize?: Size
): Partial<Shape> {
  const bounds = getShapeBounds(shape, imageSize);
  let { x, y, width, height } = bounds;

  // Apply delta based on handle
  switch (handle) {
    case 'nw':
      x += dx; y += dy; width -= dx; height -= dy;
      break;
    case 'n':
      y += dy; height -= dy;
      break;
    case 'ne':
      y += dy; width += dx; height -= dy;
      break;
    case 'e':
      width += dx;
      break;
    case 'se':
      width += dx; height += dy;
      break;
    case 's':
      height += dy;
      break;
    case 'sw':
      x += dx; width -= dx; height += dy;
      break;
    case 'w':
      x += dx; width -= dx;
      break;
  }

  // Constrain to 1:1 aspect ratio if shift is held (only for corner handles)
  if (constrainAspect && (handle === 'nw' || handle === 'ne' || handle === 'sw' || handle === 'se')) {
    // For corner handles, use the larger dimension to make a square
    const size = Math.max(Math.abs(width), Math.abs(height));
    const signW = width >= 0 ? 1 : -1;
    const signH = height >= 0 ? 1 : -1;

    // Adjust position for handles that move the origin
    if (handle === 'nw') {
      x = bounds.x + bounds.width - size * signW;
      y = bounds.y + bounds.height - size * signH;
    } else if (handle === 'ne') {
      y = bounds.y + bounds.height - size * signH;
    } else if (handle === 'sw') {
      x = bounds.x + bounds.width - size * signW;
    }
    // 'se' doesn't need position adjustment

    width = size * signW;
    height = size * signH;
  }

  // Ensure minimum size
  if (width < 0.01) { width = 0.01; }
  if (height < 0.01) { height = 0.01; }

  // Update shape based on type
  switch (shape.type) {
    case 'rectangle':
      return { x, y, width, height };
    case 'ellipse':
      return { x: x + width / 2, y: y + height / 2, rx: width / 2, ry: height / 2 };
    case 'line': {
      // For lines, adjust endpoints based on handle
      const x1 = handle.includes('w') ? x : shape.x1;
      const y1 = handle.includes('n') ? y : shape.y1;
      const x2 = handle.includes('e') ? x + width : shape.x2;
      const y2 = handle.includes('s') ? y + height : shape.y2;
      return { x1, y1, x2, y2, x: (x1 + x2) / 2, y: (y1 + y2) / 2 };
    }
    case 'curved-arrow': {
      // Scale all points relative to the new bounds
      const oldBounds = getShapeBounds(shape, imageSize);
      const scaleX = oldBounds.width > 0.001 ? width / oldBounds.width : 1;
      const scaleY = oldBounds.height > 0.001 ? height / oldBounds.height : 1;

      const newRawPoints = shape.rawPoints.map(p => ({
        x: x + (p.x - oldBounds.x) * scaleX,
        y: y + (p.y - oldBounds.y) * scaleY,
      }));
      const newSmoothedPath = shape.smoothedPath.map(p => ({
        x: x + (p.x - oldBounds.x) * scaleX,
        y: y + (p.y - oldBounds.y) * scaleY,
      }));

      return {
        x: x + width / 2,
        y: y + height / 2,
        rawPoints: newRawPoints,
        smoothedPath: newSmoothedPath,
      };
    }
    case 'sticker':
      return { x, y, width, height };
    case 'text': {
      // Text shapes have aspect-locked resizing based on baseWidth/baseHeight
      const textShape = shape as TextShape;
      const aspectRatio = textShape.baseWidth / textShape.baseHeight;
      const oldBounds = getShapeBounds(shape, imageSize);

      // Calculate scale based on handle direction, maintaining aspect ratio
      let scale: number;
      if (handle === 'e' || handle === 'w') {
        // Horizontal drag - scale based on width change
        scale = width / oldBounds.width;
      } else if (handle === 'n' || handle === 's') {
        // Vertical drag - scale based on height change
        scale = height / oldBounds.height;
      } else {
        // Corner drag - use the larger scale to make resizing feel natural
        const scaleX = width / oldBounds.width;
        const scaleY = height / oldBounds.height;
        scale = Math.max(scaleX, scaleY);
      }

      // Ensure minimum scale
      scale = Math.max(scale, 0.1);

      const newWidth = oldBounds.width * scale;
      const newHeight = newWidth / aspectRatio;

      // Anchor position based on handle
      let newX = x, newY = y;
      if (handle.includes('e')) {
        newX = oldBounds.x;
      } else if (handle.includes('w')) {
        newX = oldBounds.x + oldBounds.width - newWidth;
      } else if (handle === 'n' || handle === 's') {
        // For pure vertical handles, center horizontally
        newX = oldBounds.x + (oldBounds.width - newWidth) / 2;
      }

      if (handle.includes('s')) {
        newY = oldBounds.y;
      } else if (handle.includes('n')) {
        newY = oldBounds.y + oldBounds.height - newHeight;
      } else if (handle === 'e' || handle === 'w') {
        // For pure horizontal handles, center vertically
        newY = oldBounds.y + (oldBounds.height - newHeight) / 2;
      }

      return { x: newX, y: newY, width: newWidth, height: newHeight };
    }
    case 'redact':
      return { x, y, width, height };
    case 'triangle':
      return { x, y, width, height };
    case 'star': {
      // Calculate scale from old bounds to new bounds
      const oldBounds = getShapeBounds(shape, imageSize);
      const scaleX = oldBounds.width > 0.001 ? width / oldBounds.width : 1;
      const scaleY = oldBounds.height > 0.001 ? height / oldBounds.height : 1;
      const oldAspectRatio = shape.aspectRatio ?? 1.0;

      let newOuterRadius: number;
      let newAspectRatio: number;

      if (constrainAspect) {
        // Shift held: maintain regular shape (aspectRatio = 1.0), scale uniformly
        const scale = Math.max(scaleX, scaleY);
        newOuterRadius = shape.outerRadius * scale;
        newAspectRatio = 1.0;
      } else {
        // Free resize: scale the radius based on Y, adjust aspectRatio for X
        newOuterRadius = shape.outerRadius * scaleY;
        newAspectRatio = oldAspectRatio * (scaleX / scaleY);
      }

      const innerRatio = shape.innerRadius / shape.outerRadius;

      // Recalculate center from new bounds - find where center should be based on vertex offsets
      const starPoints = shape.points;
      let starMinX = Infinity, starMinY = Infinity;
      for (let i = 0; i < starPoints * 2; i++) {
        const isOuter = i % 2 === 0;
        const radius = isOuter ? newOuterRadius : newOuterRadius * innerRatio;
        const angle = (i * Math.PI) / starPoints - Math.PI / 2;
        // Use newAspectRatio for calculating center position
        starMinX = Math.min(starMinX, Math.cos(angle) * radius * newAspectRatio);
        starMinY = Math.min(starMinY, Math.sin(angle) * radius);
      }

      return {
        x: x - starMinX,
        y: y - starMinY,
        outerRadius: newOuterRadius,
        innerRadius: newOuterRadius * innerRatio,
        aspectRatio: newAspectRatio,
      };
    }
    case 'polygon': {
      // Calculate scale from old bounds to new bounds
      const oldBounds = getShapeBounds(shape, imageSize);
      const scaleX = oldBounds.width > 0.001 ? width / oldBounds.width : 1;
      const scaleY = oldBounds.height > 0.001 ? height / oldBounds.height : 1;
      const oldAspectRatio = shape.aspectRatio ?? 1.0;

      let newRadius: number;
      let newAspectRatio: number;

      if (constrainAspect) {
        // Shift held: maintain regular shape (aspectRatio = 1.0), scale uniformly
        const scale = Math.max(scaleX, scaleY);
        newRadius = shape.radius * scale;
        newAspectRatio = 1.0;
      } else {
        // Free resize: scale the radius based on Y, adjust aspectRatio for X
        newRadius = shape.radius * scaleY;
        newAspectRatio = oldAspectRatio * (scaleX / scaleY);
      }

      // Recalculate center from new bounds
      const sides = shape.sides;
      let polyMinX = Infinity, polyMinY = Infinity;
      for (let i = 0; i < sides; i++) {
        const angle = (i * 2 * Math.PI) / sides - Math.PI / 2;
        // Use newAspectRatio for calculating center position
        polyMinX = Math.min(polyMinX, Math.cos(angle) * newRadius * newAspectRatio);
        polyMinY = Math.min(polyMinY, Math.sin(angle) * newRadius);
      }

      return {
        x: x - polyMinX,
        y: y - polyMinY,
        radius: newRadius,
        aspectRatio: newAspectRatio,
      };
    }
    default:
      return { x, y };
  }
}

/**
 * Move a shape by delta
 */
export function moveShape(shape: Shape, dx: number, dy: number): Partial<Shape> {
  switch (shape.type) {
    case 'line':
      return {
        x: shape.x + dx,
        y: shape.y + dy,
        x1: shape.x1 + dx,
        y1: shape.y1 + dy,
        x2: shape.x2 + dx,
        y2: shape.y2 + dy,
      };
    case 'path':
      return {
        x: shape.x + dx,
        y: shape.y + dy,
        points: shape.points.map(p => ({ x: p.x + dx, y: p.y + dy })),
      };
    case 'curved-arrow':
      return {
        x: shape.x + dx,
        y: shape.y + dy,
        rawPoints: shape.rawPoints.map(p => ({ x: p.x + dx, y: p.y + dy })),
        smoothedPath: shape.smoothedPath.map(p => ({ x: p.x + dx, y: p.y + dy })),
      };
    case 'text':
      return { x: shape.x + dx, y: shape.y + dy };
    case 'redact':
      return { x: shape.x + dx, y: shape.y + dy };
    default:
      return { x: shape.x + dx, y: shape.y + dy };
  }
}

