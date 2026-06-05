import type { Point, Size } from '@/types/geometry';
import { colorDistance } from './pixelOps';

/**
 * Create an empty selection mask canvas
 */
export function createSelectionMask(size: Size): HTMLCanvasElement {
  const canvas = document.createElement('canvas');
  canvas.width = size.width;
  canvas.height = size.height;
  return canvas;
}

/**
 * Fill a rectangular region in the selection mask
 */
export function fillRectSelection(
  maskCtx: CanvasRenderingContext2D,
  x: number, y: number,
  width: number, height: number,
  mode: 'new' | 'add' | 'subtract' | 'intersect'
): void {
  const { width: w, height: h } = maskCtx.canvas;

  if (mode === 'new') {
    maskCtx.clearRect(0, 0, w, h);
  }

  if (mode === 'subtract') {
    maskCtx.globalCompositeOperation = 'destination-out';
  } else if (mode === 'intersect') {
    // For intersect, we need to create a temp canvas with the new selection
    // then use destination-in
    const tempCanvas = document.createElement('canvas');
    tempCanvas.width = w;
    tempCanvas.height = h;
    const tempCtx = tempCanvas.getContext('2d', { willReadFrequently: true })!;
    tempCtx.fillStyle = 'white';
    tempCtx.fillRect(x, y, width, height);

    maskCtx.globalCompositeOperation = 'destination-in';
    maskCtx.drawImage(tempCanvas, 0, 0);
    maskCtx.globalCompositeOperation = 'source-over';
    return;
  } else {
    maskCtx.globalCompositeOperation = 'source-over';
  }

  maskCtx.fillStyle = 'white';
  maskCtx.fillRect(x, y, width, height);
  maskCtx.globalCompositeOperation = 'source-over';
}

/**
 * Fill an elliptical region in the selection mask
 */
export function fillEllipseSelection(
  maskCtx: CanvasRenderingContext2D,
  centerX: number, centerY: number,
  radiusX: number, radiusY: number,
  mode: 'new' | 'add' | 'subtract' | 'intersect'
): void {
  const { width: w, height: h } = maskCtx.canvas;

  if (mode === 'new') {
    maskCtx.clearRect(0, 0, w, h);
  }

  if (mode === 'subtract') {
    maskCtx.globalCompositeOperation = 'destination-out';
  } else if (mode === 'intersect') {
    const tempCanvas = document.createElement('canvas');
    tempCanvas.width = w;
    tempCanvas.height = h;
    const tempCtx = tempCanvas.getContext('2d', { willReadFrequently: true })!;
    tempCtx.fillStyle = 'white';
    tempCtx.beginPath();
    tempCtx.ellipse(centerX, centerY, radiusX, radiusY, 0, 0, Math.PI * 2);
    tempCtx.fill();

    maskCtx.globalCompositeOperation = 'destination-in';
    maskCtx.drawImage(tempCanvas, 0, 0);
    maskCtx.globalCompositeOperation = 'source-over';
    return;
  } else {
    maskCtx.globalCompositeOperation = 'source-over';
  }

  maskCtx.fillStyle = 'white';
  maskCtx.beginPath();
  maskCtx.ellipse(centerX, centerY, radiusX, radiusY, 0, 0, Math.PI * 2);
  maskCtx.fill();
  maskCtx.globalCompositeOperation = 'source-over';
}

/**
 * Fill a polygon (lasso) region in the selection mask
 */
export function fillLassoSelection(
  maskCtx: CanvasRenderingContext2D,
  points: Point[],
  mode: 'new' | 'add' | 'subtract' | 'intersect'
): void {
  if (points.length < 3) return;

  const { width: w, height: h } = maskCtx.canvas;

  if (mode === 'new') {
    maskCtx.clearRect(0, 0, w, h);
  }

  if (mode === 'subtract') {
    maskCtx.globalCompositeOperation = 'destination-out';
  } else if (mode === 'intersect') {
    const tempCanvas = document.createElement('canvas');
    tempCanvas.width = w;
    tempCanvas.height = h;
    const tempCtx = tempCanvas.getContext('2d', { willReadFrequently: true })!;
    tempCtx.fillStyle = 'white';
    tempCtx.beginPath();
    tempCtx.moveTo(points[0].x, points[0].y);
    for (let i = 1; i < points.length; i++) {
      tempCtx.lineTo(points[i].x, points[i].y);
    }
    tempCtx.closePath();
    tempCtx.fill();

    maskCtx.globalCompositeOperation = 'destination-in';
    maskCtx.drawImage(tempCanvas, 0, 0);
    maskCtx.globalCompositeOperation = 'source-over';
    return;
  } else {
    maskCtx.globalCompositeOperation = 'source-over';
  }

  maskCtx.fillStyle = 'white';
  maskCtx.beginPath();
  maskCtx.moveTo(points[0].x, points[0].y);
  for (let i = 1; i < points.length; i++) {
    maskCtx.lineTo(points[i].x, points[i].y);
  }
  maskCtx.closePath();
  maskCtx.fill();
  maskCtx.globalCompositeOperation = 'source-over';
}

/**
 * Magic wand flood fill selection
 */
export function floodFillSelection(
  maskCtx: CanvasRenderingContext2D,
  sourceCtx: CanvasRenderingContext2D,
  startX: number, startY: number,
  tolerance: number,
  mode: 'new' | 'add' | 'subtract' | 'intersect'
): void {
  const { width, height } = maskCtx.canvas;

  // Get source image data
  const sourceData = sourceCtx.getImageData(0, 0, width, height);
  const srcPixels = sourceData.data;

  // Get the target color at start position
  const startIdx = (Math.floor(startY) * width + Math.floor(startX)) * 4;
  const targetR = srcPixels[startIdx];
  const targetG = srcPixels[startIdx + 1];
  const targetB = srcPixels[startIdx + 2];

  // Create result mask
  const resultCanvas = document.createElement('canvas');
  resultCanvas.width = width;
  resultCanvas.height = height;
  const resultCtx = resultCanvas.getContext('2d', { willReadFrequently: true })!;
  const resultData = resultCtx.getImageData(0, 0, width, height);
  const resultPixels = resultData.data;

  // Flood fill using scanline algorithm
  const visited = new Uint8Array(width * height);
  const stack: Array<[number, number]> = [[Math.floor(startX), Math.floor(startY)]];

  while (stack.length > 0) {
    const [x, y] = stack.pop()!;
    if (x < 0 || x >= width || y < 0 || y >= height) continue;

    const idx = y * width + x;
    if (visited[idx]) continue;
    visited[idx] = 1;

    const pixelIdx = idx * 4;
    const r = srcPixels[pixelIdx];
    const g = srcPixels[pixelIdx + 1];
    const b = srcPixels[pixelIdx + 2];

    const dist = colorDistance(r, g, b, targetR, targetG, targetB);
    if (dist <= tolerance) {
      // Mark as selected (white in mask)
      resultPixels[pixelIdx] = 255;
      resultPixels[pixelIdx + 1] = 255;
      resultPixels[pixelIdx + 2] = 255;
      resultPixels[pixelIdx + 3] = 255;

      // Add neighbors
      stack.push([x + 1, y]);
      stack.push([x - 1, y]);
      stack.push([x, y + 1]);
      stack.push([x, y - 1]);
    }
  }

  resultCtx.putImageData(resultData, 0, 0);

  // Apply to mask based on mode
  if (mode === 'new') {
    maskCtx.clearRect(0, 0, width, height);
    maskCtx.drawImage(resultCanvas, 0, 0);
  } else if (mode === 'add') {
    maskCtx.globalCompositeOperation = 'source-over';
    maskCtx.drawImage(resultCanvas, 0, 0);
    maskCtx.globalCompositeOperation = 'source-over';
  } else if (mode === 'subtract') {
    maskCtx.globalCompositeOperation = 'destination-out';
    maskCtx.drawImage(resultCanvas, 0, 0);
    maskCtx.globalCompositeOperation = 'source-over';
  } else if (mode === 'intersect') {
    maskCtx.globalCompositeOperation = 'destination-in';
    maskCtx.drawImage(resultCanvas, 0, 0);
    maskCtx.globalCompositeOperation = 'source-over';
  }
}

/**
 * Apply feather (blur) to selection mask
 */
export function featherSelection(
  maskCtx: CanvasRenderingContext2D,
  radius: number
): void {
  if (radius <= 0) return;

  const { width, height } = maskCtx.canvas;

  // Use CSS filter for fast blur
  const tempCanvas = document.createElement('canvas');
  tempCanvas.width = width;
  tempCanvas.height = height;
  const tempCtx = tempCanvas.getContext('2d', { willReadFrequently: true })!;

  tempCtx.filter = `blur(${radius}px)`;
  tempCtx.drawImage(maskCtx.canvas, 0, 0);

  maskCtx.clearRect(0, 0, width, height);
  maskCtx.drawImage(tempCanvas, 0, 0);
}

/**
 * Invert the selection mask
 *
 * The selection mask uses the alpha channel to determine selected areas:
 * - alpha=255 means fully selected
 * - alpha=0 means not selected
 * - intermediate values represent partial selection (feathered edges)
 *
 * Inversion flips the alpha channel so selected becomes unselected and vice versa.
 * This correctly handles:
 * - Simple selections (rect, ellipse, lasso)
 * - Selections with holes (e.g., subtract mode)
 * - Feathered selections (preserves the gradient, just inverted)
 * - Empty canvas (becomes full selection)
 */
export function invertSelection(maskCtx: CanvasRenderingContext2D): void {
  const { width, height } = maskCtx.canvas;
  const imageData = maskCtx.getImageData(0, 0, width, height);
  const data = imageData.data;

  for (let i = 0; i < data.length; i += 4) {
    // Invert the alpha channel - this is what actually controls selection
    // RGB is set to white (255) for visual consistency when debugging
    data[i] = 255;     // R
    data[i + 1] = 255; // G
    data[i + 2] = 255; // B
    data[i + 3] = 255 - data[i + 3]; // Invert alpha
  }

  maskCtx.putImageData(imageData, 0, 0);
}

/**
 * Clear (deselect) the entire selection
 */
export function clearSelection(maskCtx: CanvasRenderingContext2D): void {
  const { width, height } = maskCtx.canvas;
  maskCtx.clearRect(0, 0, width, height);
}

/**
 * Check if any selection exists
 */
export function hasSelection(maskCtx: CanvasRenderingContext2D): boolean {
  const { width, height } = maskCtx.canvas;
  const imageData = maskCtx.getImageData(0, 0, width, height);
  const data = imageData.data;

  for (let i = 3; i < data.length; i += 4) {
    if (data[i] > 0) return true;
  }
  return false;
}

/**
 * Get selection bounds (bounding box of selected region)
 */
export function getSelectionBounds(
  maskCtx: CanvasRenderingContext2D
): { x: number; y: number; width: number; height: number } | null {
  const { width, height } = maskCtx.canvas;
  const imageData = maskCtx.getImageData(0, 0, width, height);
  const data = imageData.data;

  let minX = width, minY = height, maxX = 0, maxY = 0;
  let hasPixels = false;

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const idx = (y * width + x) * 4 + 3;
      if (data[idx] > 0) {
        hasPixels = true;
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
      }
    }
  }

  if (!hasPixels) return null;

  return {
    x: minX,
    y: minY,
    width: maxX - minX + 1,
    height: maxY - minY + 1,
  };
}

/**
 * Get marching ants path from selection mask using marching squares algorithm
 * Returns an array of contour points for the marching ants animation
 *
 * This uses a proper marching squares algorithm that traces the boundary between
 * selected and unselected areas, producing clean connected contours.
 */
export function getMarchingAntsPath(
  maskCtx: CanvasRenderingContext2D
): Point[][] {
  const { width, height } = maskCtx.canvas;
  const imageData = maskCtx.getImageData(0, 0, width, height);
  const data = imageData.data;

  // Threshold for "selected" - pixel alpha > 128
  const isSelected = (x: number, y: number): boolean => {
    if (x < 0 || x >= width || y < 0 || y >= height) return false;
    return data[(y * width + x) * 4 + 3] > 128;
  };

  const paths: Point[][] = [];

  // Track visited edges: key is "x,y,edge" where edge is 'h' (horizontal) or 'v' (vertical)
  // Horizontal edges are between (x,y) and (x+1,y), vertical are between (x,y) and (x,y+1)
  const visitedEdges = new Set<string>();

  // Check if there's a boundary edge between two adjacent pixels
  // Returns the edge points if there's a boundary, null otherwise
  const getHorizontalEdge = (x: number, y: number): [Point, Point] | null => {
    // Horizontal edge is between row y-1 and row y
    const above = isSelected(x, y - 1);
    const below = isSelected(x, y);
    if (above !== below) {
      return [{ x, y }, { x: x + 1, y }];
    }
    return null;
  };

  const getVerticalEdge = (x: number, y: number): [Point, Point] | null => {
    // Vertical edge is between column x-1 and column x
    const left = isSelected(x - 1, y);
    const right = isSelected(x, y);
    if (left !== right) {
      return [{ x, y }, { x, y: y + 1 }];
    }
    return null;
  };

  // Get all edges connected to a point, returning the edge key and the OTHER endpoint
  const getConnectedEdges = (p: Point): Array<{ type: 'h' | 'v'; x: number; y: number; other: Point }> => {
    const edges: Array<{ type: 'h' | 'v'; x: number; y: number; other: Point }> = [];

    // Horizontal edge to the left: from (p.x-1, p.y) to (p.x, p.y) - other end is (p.x-1, p.y)
    if (getHorizontalEdge(p.x - 1, p.y)) {
      edges.push({ type: 'h', x: p.x - 1, y: p.y, other: { x: p.x - 1, y: p.y } });
    }
    // Horizontal edge to the right: from (p.x, p.y) to (p.x+1, p.y) - other end is (p.x+1, p.y)
    if (getHorizontalEdge(p.x, p.y)) {
      edges.push({ type: 'h', x: p.x, y: p.y, other: { x: p.x + 1, y: p.y } });
    }
    // Vertical edge above: from (p.x, p.y-1) to (p.x, p.y) - other end is (p.x, p.y-1)
    if (getVerticalEdge(p.x, p.y - 1)) {
      edges.push({ type: 'v', x: p.x, y: p.y - 1, other: { x: p.x, y: p.y - 1 } });
    }
    // Vertical edge below: from (p.x, p.y) to (p.x, p.y+1) - other end is (p.x, p.y+1)
    if (getVerticalEdge(p.x, p.y)) {
      edges.push({ type: 'v', x: p.x, y: p.y, other: { x: p.x, y: p.y + 1 } });
    }

    return edges;
  };

  // Trace a contour starting from a given edge
  const traceContour = (startX: number, startY: number, startType: 'h' | 'v'): Point[] | null => {
    const startKey = `${startX},${startY},${startType}`;
    if (visitedEdges.has(startKey)) return null;

    const contour: Point[] = [];

    // Get the start edge endpoints
    let currentPoint: Point;
    if (startType === 'h') {
      currentPoint = { x: startX, y: startY };
      contour.push({ ...currentPoint });
      currentPoint = { x: startX + 1, y: startY };
    } else {
      currentPoint = { x: startX, y: startY };
      contour.push({ ...currentPoint });
      currentPoint = { x: startX, y: startY + 1 };
    }
    contour.push({ ...currentPoint });
    visitedEdges.add(startKey);

    const maxIterations = (width + height) * 4;
    let iterations = 0;

    while (iterations++ < maxIterations) {
      // Find connected edges from current point
      const connected = getConnectedEdges(currentPoint);

      // Find an unvisited edge
      let nextEdge: { type: 'h' | 'v'; x: number; y: number; other: Point } | null = null;
      for (const edge of connected) {
        const edgeKey = `${edge.x},${edge.y},${edge.type}`;
        if (!visitedEdges.has(edgeKey)) {
          nextEdge = edge;
          break;
        }
      }

      if (!nextEdge) {
        // No unvisited edges - we're done
        break;
      }

      const edgeKey = `${nextEdge.x},${nextEdge.y},${nextEdge.type}`;
      visitedEdges.add(edgeKey);

      // Move to the other end of this edge
      currentPoint = nextEdge.other;
      contour.push({ ...currentPoint });

      // Check if we've returned to start
      if (currentPoint.x === contour[0].x && currentPoint.y === contour[0].y) {
        break;
      }
    }

    return contour.length >= 3 ? contour : null;
  };

  // Scan for all boundary edges and trace contours
  // Check horizontal edges (between rows)
  for (let y = 0; y <= height; y++) {
    for (let x = 0; x < width; x++) {
      if (getHorizontalEdge(x, y)) {
        const edgeKey = `${x},${y},h`;
        if (!visitedEdges.has(edgeKey)) {
          const contour = traceContour(x, y, 'h');
          if (contour) {
            paths.push(contour);
          }
        }
      }
    }
  }

  // Check vertical edges (between columns)
  for (let y = 0; y < height; y++) {
    for (let x = 0; x <= width; x++) {
      if (getVerticalEdge(x, y)) {
        const edgeKey = `${x},${y},v`;
        if (!visitedEdges.has(edgeKey)) {
          const contour = traceContour(x, y, 'v');
          if (contour) {
            paths.push(contour);
          }
        }
      }
    }
  }

  return paths;
}

/**
 * Simplify a path by reducing the number of points using Douglas-Peucker algorithm
 */
export function simplifyPath(points: Point[], tolerance: number = 1): Point[] {
  if (points.length < 3) return points;

  // Helper: perpendicular distance from point to line segment
  const perpendicularDistance = (p: Point, start: Point, end: Point): number => {
    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const lineLengthSq = dx * dx + dy * dy;

    if (lineLengthSq === 0) {
      // Start and end are the same point
      return Math.sqrt((p.x - start.x) ** 2 + (p.y - start.y) ** 2);
    }

    // Project point onto line
    const t = Math.max(0, Math.min(1, ((p.x - start.x) * dx + (p.y - start.y) * dy) / lineLengthSq));
    const projX = start.x + t * dx;
    const projY = start.y + t * dy;

    return Math.sqrt((p.x - projX) ** 2 + (p.y - projY) ** 2);
  };

  // Douglas-Peucker recursive simplification
  const douglasPeucker = (pts: Point[], startIdx: number, endIdx: number, result: Point[]): void => {
    if (endIdx <= startIdx + 1) return;

    let maxDist = 0;
    let maxIdx = startIdx;

    for (let i = startIdx + 1; i < endIdx; i++) {
      const dist = perpendicularDistance(pts[i], pts[startIdx], pts[endIdx]);
      if (dist > maxDist) {
        maxDist = dist;
        maxIdx = i;
      }
    }

    if (maxDist > tolerance) {
      // Recursively simplify both sides
      douglasPeucker(pts, startIdx, maxIdx, result);
      result.push(pts[maxIdx]);
      douglasPeucker(pts, maxIdx, endIdx, result);
    }
  };

  const result: Point[] = [points[0]];
  douglasPeucker(points, 0, points.length - 1, result);
  result.push(points[points.length - 1]);

  return result;
}
