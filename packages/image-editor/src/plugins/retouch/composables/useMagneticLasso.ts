/**
 * Composable for magnetic lasso selection tool state management.
 * Coordinates gradient map computation, anchor placement, and path preview.
 */

import { ref, shallowRef } from 'vue';
import type { Point } from '@/types/geometry';
import { computeGradientMap, type GradientMap } from '../utils/edgeDetection';
import { findOptimalPath, simplifyPath, type LivewireConfig, DEFAULT_LIVEWIRE_CONFIG } from '../utils/livewire';

export interface MagneticLassoState {
  /** Whether the magnetic lasso is currently active (user is placing anchors) */
  isActive: boolean;
  /** Placed anchor points */
  anchors: Point[];
  /** Path segments between consecutive anchors */
  pathSegments: Point[][];
  /** Live preview path from last anchor to cursor */
  previewPath: Point[];
  /** Current cursor position */
  cursorPosition: Point | null;
  /** Whether cursor is near the first anchor (for closing) */
  isNearStart: boolean;
}

/** Close detection threshold in pixels */
const CLOSE_THRESHOLD = 10;

/** Minimum number of points needed to close a selection */
const MIN_ANCHORS_TO_CLOSE = 3;

export function useMagneticLasso() {
  // State
  const isActive = ref(false);
  const anchors = ref<Point[]>([]);
  const pathSegments = ref<Point[][]>([]);
  const previewPath = ref<Point[]>([]);
  const cursorPosition = ref<Point | null>(null);
  const isNearStart = ref(false);

  // Gradient map (cached for performance)
  const gradientMap = shallowRef<GradientMap | null>(null);

  // Configuration
  const config = ref<LivewireConfig>({ ...DEFAULT_LIVEWIRE_CONFIG });

  // Throttle for preview updates
  let lastPreviewTime = 0;
  const PREVIEW_THROTTLE_MS = 16; // ~60fps

  /**
   * Initialize the magnetic lasso with a source canvas.
   * Computes the gradient map for pathfinding.
   */
  function initialize(canvas: HTMLCanvasElement): void {
    if (!canvas) return;

    // Compute gradient map
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) return;

    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    gradientMap.value = computeGradientMap(imageData);

    // Reset state
    isActive.value = false;
    anchors.value = [];
    pathSegments.value = [];
    previewPath.value = [];
    cursorPosition.value = null;
    isNearStart.value = false;
  }

  /**
   * Update configuration (e.g., from UI controls)
   */
  function updateConfig(newConfig: Partial<LivewireConfig>): void {
    config.value = { ...config.value, ...newConfig };
  }

  /**
   * Place an anchor point at the given position.
   * If near the start and enough anchors exist, closes the selection instead.
   * Returns true if the selection was closed.
   */
  function placeAnchor(point: Point): boolean {
    if (!gradientMap.value) return false;

    // Check if we should close the selection
    if (isNearStart.value && anchors.value.length >= MIN_ANCHORS_TO_CLOSE) {
      // Close the selection by connecting back to start
      const lastAnchor = anchors.value[anchors.value.length - 1];
      const firstAnchor = anchors.value[0];

      if (lastAnchor) {
        const closePath = findOptimalPath(gradientMap.value, lastAnchor, firstAnchor, config.value);
        const simplified = simplifyPath(closePath, 1.5);
        pathSegments.value.push(simplified);
      }

      isActive.value = false;
      previewPath.value = [];
      cursorPosition.value = null;
      isNearStart.value = false;

      return true; // Selection closed
    }

    // Start or continue selection
    if (!isActive.value) {
      // First anchor - start new selection
      isActive.value = true;
      anchors.value = [{ ...point }];
      pathSegments.value = [];
      previewPath.value = [];
    } else {
      // Add new anchor and compute path from previous anchor
      const lastAnchor = anchors.value[anchors.value.length - 1];

      if (lastAnchor) {
        const path = findOptimalPath(gradientMap.value, lastAnchor, point, config.value);
        const simplified = simplifyPath(path, 1.5);
        pathSegments.value.push(simplified);
      }

      anchors.value.push({ ...point });
      previewPath.value = [];
    }

    return false; // Not closed yet
  }

  /**
   * Update the preview path to the current cursor position.
   * Called on mouse move when the magnetic lasso is active.
   */
  function updatePreview(point: Point): void {
    if (!isActive.value || !gradientMap.value || anchors.value.length === 0) return;

    // Throttle updates for performance
    const now = performance.now();
    if (now - lastPreviewTime < PREVIEW_THROTTLE_MS) return;
    lastPreviewTime = now;

    cursorPosition.value = { ...point };

    // Compute preview path from last anchor to cursor
    const lastAnchor = anchors.value[anchors.value.length - 1];
    if (lastAnchor) {
      const path = findOptimalPath(gradientMap.value, lastAnchor, point, config.value);
      previewPath.value = simplifyPath(path, 1.5);
    }

    // Check if cursor is near the start anchor (for closing)
    if (anchors.value.length >= MIN_ANCHORS_TO_CLOSE) {
      const firstAnchor = anchors.value[0];
      const dist = Math.sqrt(
        (point.x - firstAnchor.x) ** 2 + (point.y - firstAnchor.y) ** 2
      );
      isNearStart.value = dist <= CLOSE_THRESHOLD;
    } else {
      isNearStart.value = false;
    }
  }

  /**
   * Remove the last placed anchor and its path segment.
   * Returns true if there are still anchors remaining.
   */
  function removeLastAnchor(): boolean {
    if (!isActive.value || anchors.value.length === 0) return false;

    if (anchors.value.length === 1) {
      // Remove the only anchor - cancel selection
      cancel();
      return false;
    }

    // Remove last anchor and its path segment
    anchors.value.pop();
    if (pathSegments.value.length > 0) {
      pathSegments.value.pop();
    }

    // Recompute preview if cursor position is known
    if (cursorPosition.value && gradientMap.value) {
      const lastAnchor = anchors.value[anchors.value.length - 1];
      if (lastAnchor) {
        const path = findOptimalPath(gradientMap.value, lastAnchor, cursorPosition.value, config.value);
        previewPath.value = simplifyPath(path, 1.5);
      }
    }

    return true;
  }

  /**
   * Close the selection by connecting the last anchor to the first.
   * Returns all path points as a single array for creating the selection.
   */
  function closeSelection(): Point[] {
    if (!isActive.value || anchors.value.length < MIN_ANCHORS_TO_CLOSE || !gradientMap.value) {
      return [];
    }

    // Connect last anchor to first
    const lastAnchor = anchors.value[anchors.value.length - 1];
    const firstAnchor = anchors.value[0];

    if (lastAnchor && firstAnchor) {
      const closePath = findOptimalPath(gradientMap.value, lastAnchor, firstAnchor, config.value);
      const simplified = simplifyPath(closePath, 1.5);
      pathSegments.value.push(simplified);
    }

    // Collect all points from all segments
    const allPoints = collectAllPoints();

    // Clean up
    isActive.value = false;
    previewPath.value = [];
    cursorPosition.value = null;
    isNearStart.value = false;

    return allPoints;
  }

  /**
   * Collect all points from path segments into a single array.
   * Removes duplicate points at segment boundaries.
   */
  function collectAllPoints(): Point[] {
    const points: Point[] = [];

    for (const segment of pathSegments.value) {
      for (let i = 0; i < segment.length; i++) {
        const p = segment[i];

        // Skip duplicate points at segment boundaries
        if (points.length > 0) {
          const last = points[points.length - 1];
          if (Math.abs(p.x - last.x) < 0.5 && Math.abs(p.y - last.y) < 0.5) {
            continue;
          }
        }

        points.push({ ...p });
      }
    }

    return points;
  }

  /**
   * Get all path points (for creating selection without closing)
   */
  function getAllPoints(): Point[] {
    return collectAllPoints();
  }

  /**
   * Cancel the current magnetic lasso selection.
   */
  function cancel(): void {
    isActive.value = false;
    anchors.value = [];
    pathSegments.value = [];
    previewPath.value = [];
    cursorPosition.value = null;
    isNearStart.value = false;
  }

  /**
   * Check if the gradient map is ready
   */
  function isReady(): boolean {
    return gradientMap.value !== null;
  }

  /**
   * Invalidate the gradient map (call when source image changes)
   */
  function invalidate(): void {
    gradientMap.value = null;
    cancel();
  }

  return {
    // State
    isActive,
    anchors,
    pathSegments,
    previewPath,
    cursorPosition,
    isNearStart,
    config,

    // Methods
    initialize,
    updateConfig,
    placeAnchor,
    updatePreview,
    removeLastAnchor,
    closeSelection,
    getAllPoints,
    cancel,
    isReady,
    invalidate,
  };
}

export type MagneticLassoComposable = ReturnType<typeof useMagneticLasso>;
