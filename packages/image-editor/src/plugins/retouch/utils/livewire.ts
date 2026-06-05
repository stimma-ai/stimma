/**
 * Livewire (Intelligent Scissors) pathfinding for the magnetic lasso tool.
 * Uses Dijkstra's algorithm to find optimal paths along image edges.
 */

import type { Point } from '@/types/geometry';
import type { GradientMap } from './edgeDetection';
import { getGradientMagnitude, getGradientDirection } from './edgeDetection';

export interface LivewireConfig {
  /** Weight for gradient cost (strong edges = low cost). Default: 0.43 */
  gradientWeight: number;
  /** Weight for direction continuity cost (smooth paths = low cost). Default: 0.57 */
  directionWeight: number;
  /** Search corridor width in pixels. Only search within this distance of straight line. Default: 20 */
  searchRadius: number;
  /** Edge sensitivity (0-100). Higher values make the tool more sensitive to weak edges. Default: 50 */
  edgeSensitivity: number;
}

export const DEFAULT_LIVEWIRE_CONFIG: LivewireConfig = {
  gradientWeight: 0.95,
  directionWeight: 0.05,
  searchRadius: 50,
  edgeSensitivity: 50,
};

// 8-connected neighbors with their movement vectors
const NEIGHBORS: [number, number][] = [
  [-1, -1], [0, -1], [1, -1],
  [-1,  0],          [1,  0],
  [-1,  1], [0,  1], [1,  1],
];

// Diagonal distance factor (sqrt(2) for diagonals)
const NEIGHBOR_DISTANCES: number[] = [
  Math.SQRT2, 1, Math.SQRT2,
  1,             1,
  Math.SQRT2, 1, Math.SQRT2,
];

/**
 * Priority queue implementation using a binary heap for Dijkstra's algorithm
 */
class PriorityQueue {
  private heap: Array<{ key: number; cost: number }> = [];
  private positionMap = new Map<number, number>();

  get size(): number {
    return this.heap.length;
  }

  push(key: number, cost: number): void {
    const existingPos = this.positionMap.get(key);
    if (existingPos !== undefined) {
      // Update existing entry if new cost is lower
      if (cost < this.heap[existingPos].cost) {
        this.heap[existingPos].cost = cost;
        this.bubbleUp(existingPos);
      }
      return;
    }

    const pos = this.heap.length;
    this.heap.push({ key, cost });
    this.positionMap.set(key, pos);
    this.bubbleUp(pos);
  }

  pop(): { key: number; cost: number } | undefined {
    if (this.heap.length === 0) return undefined;

    const result = this.heap[0];
    this.positionMap.delete(result.key);

    if (this.heap.length > 1) {
      this.heap[0] = this.heap.pop()!;
      this.positionMap.set(this.heap[0].key, 0);
      this.bubbleDown(0);
    } else {
      this.heap.pop();
    }

    return result;
  }

  private bubbleUp(pos: number): void {
    while (pos > 0) {
      const parent = Math.floor((pos - 1) / 2);
      if (this.heap[pos].cost >= this.heap[parent].cost) break;

      // Swap
      const temp = this.heap[pos];
      this.heap[pos] = this.heap[parent];
      this.heap[parent] = temp;

      this.positionMap.set(this.heap[pos].key, pos);
      this.positionMap.set(this.heap[parent].key, parent);

      pos = parent;
    }
  }

  private bubbleDown(pos: number): void {
    const length = this.heap.length;
    while (true) {
      const left = 2 * pos + 1;
      const right = 2 * pos + 2;
      let smallest = pos;

      if (left < length && this.heap[left].cost < this.heap[smallest].cost) {
        smallest = left;
      }
      if (right < length && this.heap[right].cost < this.heap[smallest].cost) {
        smallest = right;
      }

      if (smallest === pos) break;

      // Swap
      const temp = this.heap[pos];
      this.heap[pos] = this.heap[smallest];
      this.heap[smallest] = temp;

      this.positionMap.set(this.heap[pos].key, pos);
      this.positionMap.set(this.heap[smallest].key, smallest);

      pos = smallest;
    }
  }
}

/**
 * Check if a point is within the search corridor between start and end
 */
function isInCorridor(
  x: number, y: number,
  startX: number, startY: number,
  endX: number, endY: number,
  radius: number
): boolean {
  // Vector from start to end
  const dx = endX - startX;
  const dy = endY - startY;
  const len = Math.sqrt(dx * dx + dy * dy);

  if (len < 0.001) {
    // Start and end are the same point
    const dist = Math.sqrt((x - startX) ** 2 + (y - startY) ** 2);
    return dist <= radius;
  }

  // Normalize direction
  const dirX = dx / len;
  const dirY = dy / len;

  // Vector from start to point
  const vx = x - startX;
  const vy = y - startY;

  // Project onto line
  const proj = vx * dirX + vy * dirY;

  // Allow points slightly before start and after end
  const margin = radius;
  if (proj < -margin || proj > len + margin) return false;

  // Perpendicular distance
  const perpDist = Math.abs(vx * dirY - vy * dirX);

  return perpDist <= radius;
}

/**
 * Compute the edge cost for moving from one pixel to another.
 * Lower cost = better path (stronger edge, smoother direction).
 *
 * Cost formula: l(p,q) = wG * fG(q) + wD * fD(p,q)
 * - fG(q) = 1 - gradient(q) (strong edges have low cost)
 * - fD(p,q) = direction continuity penalty (aligned with edge = low cost)
 */
function computeEdgeCost(
  gradientMap: GradientMap,
  fromX: number, fromY: number,
  toX: number, toY: number,
  distance: number,
  config: LivewireConfig,
  prevDirX: number,
  prevDirY: number
): number {
  // Gradient cost: heavily penalize non-edge areas
  // Apply sensitivity scaling (higher sensitivity = more responsive to weak edges)
  const sensitivity = config.edgeSensitivity / 50; // 0-2 range
  const gradMag = getGradientMagnitude(gradientMap, toX, toY);

  // Use steep exponential cost: makes edges DRAMATICALLY cheaper than non-edges
  // At mag=1 (strong edge): cost ≈ 0.0003
  // At mag=0.5: cost ≈ 0.018
  // At mag=0.2: cost ≈ 0.20
  // At mag=0: cost = 1.0
  const boostedMag = Math.pow(gradMag, 1 / Math.max(0.3, sensitivity));
  const gradientCost = Math.exp(-8 * boostedMag); // Very steep exponential falloff

  // Direction cost: penalize turns that don't follow the edge
  let directionCost = 0;
  if (prevDirX !== 0 || prevDirY !== 0) {
    // Movement direction (unit vector)
    const moveX = (toX - fromX) / distance;
    const moveY = (toY - fromY) / distance;

    // Get edge direction at destination
    const [edgeDirX, edgeDirY] = getGradientDirection(gradientMap, toX, toY);

    if (edgeDirX !== 0 || edgeDirY !== 0) {
      // Cost based on how aligned movement is with edge direction
      // Edge direction can point either way along the edge, so use abs(dot)
      const alignment = Math.abs(moveX * edgeDirX + moveY * edgeDirY);
      directionCost = 1 - alignment; // Aligned = 0, perpendicular = 1
    }

    // Also penalize sharp turns from previous direction
    const continuity = prevDirX * (toX - fromX) / distance + prevDirY * (toY - fromY) / distance;
    directionCost += 0.2 * (1 - Math.max(0, continuity)); // Small penalty for turning
  }

  // Combined cost, scaled by distance
  const cost = (config.gradientWeight * gradientCost + config.directionWeight * directionCost) * distance;

  return cost;
}

/**
 * Find the optimal path between two points using Dijkstra's algorithm.
 * The path follows image edges based on the gradient map.
 */
export function findOptimalPath(
  gradientMap: GradientMap,
  start: Point,
  end: Point,
  config: LivewireConfig = DEFAULT_LIVEWIRE_CONFIG
): Point[] {
  const { width, height } = gradientMap;

  // Round to nearest pixel
  const startX = Math.round(start.x);
  const startY = Math.round(start.y);
  const endX = Math.round(end.x);
  const endY = Math.round(end.y);

  // If start and end are the same, return just that point
  if (startX === endX && startY === endY) {
    return [{ x: startX, y: startY }];
  }

  // Key function: encode (x, y) as single number
  const toKey = (x: number, y: number): number => y * width + x;
  const fromKey = (key: number): [number, number] => [key % width, Math.floor(key / width)];

  // Dijkstra's algorithm
  const costs = new Map<number, number>();
  const parents = new Map<number, number>();
  const directions = new Map<number, [number, number]>(); // Previous movement direction
  const pq = new PriorityQueue();

  const startKey = toKey(startX, startY);
  const endKey = toKey(endX, endY);

  costs.set(startKey, 0);
  directions.set(startKey, [0, 0]);
  pq.push(startKey, 0);

  // Limit iterations to prevent infinite loops on large images
  const maxIterations = width * height;
  let iterations = 0;

  while (pq.size > 0 && iterations++ < maxIterations) {
    const current = pq.pop();
    if (!current) break;

    const [cx, cy] = fromKey(current.key);

    // Found the end
    if (current.key === endKey) break;

    // Skip if we've found a better path to this node
    const knownCost = costs.get(current.key);
    if (knownCost !== undefined && current.cost > knownCost) continue;

    const prevDir = directions.get(current.key) || [0, 0];

    // Explore neighbors
    for (let i = 0; i < NEIGHBORS.length; i++) {
      const [dx, dy] = NEIGHBORS[i];
      const nx = cx + dx;
      const ny = cy + dy;

      // Bounds check
      if (nx < 0 || nx >= width || ny < 0 || ny >= height) continue;

      // Corridor check (optimization: only search near the straight line)
      if (!isInCorridor(nx, ny, startX, startY, endX, endY, config.searchRadius)) continue;

      const neighborKey = toKey(nx, ny);
      const edgeCost = computeEdgeCost(
        gradientMap,
        cx, cy,
        nx, ny,
        NEIGHBOR_DISTANCES[i],
        config,
        prevDir[0],
        prevDir[1]
      );

      const newCost = current.cost + edgeCost;
      const existingCost = costs.get(neighborKey);

      if (existingCost === undefined || newCost < existingCost) {
        costs.set(neighborKey, newCost);
        parents.set(neighborKey, current.key);
        directions.set(neighborKey, [dx / NEIGHBOR_DISTANCES[i], dy / NEIGHBOR_DISTANCES[i]]);
        pq.push(neighborKey, newCost);
      }
    }
  }

  // Reconstruct path
  const path: Point[] = [];
  let currentKey: number | undefined = endKey;

  // Check if we found a path
  if (!parents.has(endKey) && endKey !== startKey) {
    // No path found - fall back to straight line
    return [
      { x: startX, y: startY },
      { x: endX, y: endY },
    ];
  }

  while (currentKey !== undefined) {
    const [x, y] = fromKey(currentKey);
    path.unshift({ x, y });

    if (currentKey === startKey) break;
    currentKey = parents.get(currentKey);
  }

  return path;
}

/**
 * Simplify a path by removing redundant points using Douglas-Peucker algorithm
 */
export function simplifyPath(points: Point[], tolerance: number = 1.0): Point[] {
  if (points.length < 3) return points;

  // Helper: perpendicular distance from point to line segment
  const perpendicularDistance = (p: Point, start: Point, end: Point): number => {
    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const lineLengthSq = dx * dx + dy * dy;

    if (lineLengthSq === 0) {
      return Math.sqrt((p.x - start.x) ** 2 + (p.y - start.y) ** 2);
    }

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
