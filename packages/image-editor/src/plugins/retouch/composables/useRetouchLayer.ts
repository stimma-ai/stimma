import { ref, shallowRef, markRaw } from 'vue';
import type { Size, Point } from '@/types/geometry';
import type { BrushSettings } from '@/types/shapes';
import {
  createBrushMask,
  getStrokePoints,
  adjustLuminosity,
  adjustSaturation,
  sampleRegion,
  sampleSurroundingPixels,
  interpolateFromSamples,
  applyPatch,
} from '../utils/pixelOps';
import { applyLocalBlur, applyLocalSharpen } from '../utils/imageFilters';

/**
 * Composable for managing the retouch bitmap layer
 */
export function useRetouchLayer() {
  // The retouch layer canvas (stores all pixel edits)
  const retouchCanvas = shallowRef<HTMLCanvasElement | null>(null);
  const retouchCtx = shallowRef<CanvasRenderingContext2D | null>(null);

  // Layer size (should match image size)
  const layerSize = ref<Size | null>(null);

  // Brush state
  const currentBrushMask = shallowRef<ImageData | null>(null);

  // Brush mask cache: keyed by "size,hardness"
  let cachedBrushMaskKey = '';
  let cachedBrushMaskData: ImageData | null = null;

  // Clone stamp state
  const cloneSourceCanvas = shallowRef<HTMLCanvasElement | null>(null);
  const cloneOffset = ref<Point | null>(null);

  // Selection mask reference (for constraining operations)
  let selectionMaskCtx: CanvasRenderingContext2D | null = null;

  // Reusable work canvas for blur/sharpen (avoids allocation per dab)
  let workCanvas: HTMLCanvasElement | null = null;
  let workCtx: CanvasRenderingContext2D | null = null;
  let workCanvasSize = 0;

  // Stroke tracking for spacing
  let lastStrokePoint: Point | null = null;

  /**
   * Set the selection mask canvas for constraining operations
   */
  function setSelectionMask(ctx: CanvasRenderingContext2D | null): void {
    selectionMaskCtx = ctx;
  }

  /**
   * Get selection alpha at a specific pixel (0 = not selected, 1 = fully selected)
   */
  function getSelectionAlpha(x: number, y: number): number {
    if (!selectionMaskCtx) return 1; // No selection = everything selected

    const width = selectionMaskCtx.canvas.width;
    const height = selectionMaskCtx.canvas.height;

    if (x < 0 || x >= width || y < 0 || y >= height) return 0;

    const pixel = selectionMaskCtx.getImageData(Math.floor(x), Math.floor(y), 1, 1);
    // Selection mask uses alpha channel (or could use any channel since it's grayscale)
    return pixel.data[3] / 255;
  }

  /**
   * Get selection mask data for a region
   */
  function getSelectionMaskRegion(x: number, y: number, w: number, h: number): Uint8Array | null {
    if (!selectionMaskCtx) return null; // No selection = no mask needed

    const maskData = selectionMaskCtx.getImageData(x, y, w, h);
    // Return just the alpha values
    const alphas = new Uint8Array(w * h);
    for (let i = 0; i < alphas.length; i++) {
      alphas[i] = maskData.data[i * 4 + 3];
    }
    return alphas;
  }

  /**
   * Initialize or resize the retouch layer
   */
  function initLayer(size: Size): void {
    if (
      retouchCanvas.value &&
      layerSize.value?.width === size.width &&
      layerSize.value?.height === size.height
    ) {
      return;
    }

    const canvas = document.createElement('canvas');
    canvas.width = size.width;
    canvas.height = size.height;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });

    if (!ctx) {
      throw new Error('Failed to get retouch canvas context');
    }

    // If we have existing content, copy it
    if (retouchCanvas.value && retouchCtx.value) {
      ctx.drawImage(retouchCanvas.value, 0, 0);
    }

    retouchCanvas.value = canvas;
    retouchCtx.value = ctx;
    layerSize.value = { ...size };
  }

  /**
   * Clear the retouch layer
   */
  function clearLayer(): void {
    if (!retouchCtx.value || !layerSize.value) return;
    retouchCtx.value.clearRect(0, 0, layerSize.value.width, layerSize.value.height);
  }

  /**
   * Load retouch layer from data URL (used for project deserialization)
   */
  async function loadFromDataUrl(dataUrl: string): Promise<void> {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        if (!retouchCtx.value || !retouchCanvas.value) {
          reject(new Error('Retouch canvas not initialized before restore'));
          return;
        }

        retouchCtx.value.clearRect(
          0,
          0,
          retouchCanvas.value.width,
          retouchCanvas.value.height
        );
        retouchCtx.value.drawImage(
          img,
          0,
          0,
          retouchCanvas.value.width,
          retouchCanvas.value.height
        );
        resolve();
      };
      img.onerror = reject;
      img.src = dataUrl;
    });
  }

  /**
   * Export retouch layer to data URL (used for project serialization)
   */
  function toDataUrl(): string | null {
    if (!retouchCanvas.value) return null;
    return retouchCanvas.value.toDataURL('image/png');
  }

  /**
   * Create a fast canvas snapshot for history (drawImage clone, ~1ms vs 100-300ms for PNG).
   * markRaw prevents Vue from deeply proxying the canvas DOM element.
   */
  function toSnapshot(): HTMLCanvasElement | null {
    if (!retouchCanvas.value || !layerSize.value) return null;
    const snap = document.createElement('canvas');
    snap.width = layerSize.value.width;
    snap.height = layerSize.value.height;
    const ctx = snap.getContext('2d');
    if (ctx) {
      ctx.drawImage(retouchCanvas.value, 0, 0);
    }
    return markRaw(snap);
  }

  /**
   * Restore from a canvas snapshot (fast, ~1ms)
   */
  function loadFromSnapshot(snapshot: HTMLCanvasElement): void {
    if (!retouchCtx.value || !layerSize.value) return;
    retouchCtx.value.clearRect(0, 0, layerSize.value.width, layerSize.value.height);
    retouchCtx.value.drawImage(snapshot, 0, 0);
  }

  /**
   * Get or create brush mask for current settings (cached by size+hardness)
   */
  function getBrushMask(size: number, hardness: number): ImageData {
    const ceilSize = Math.ceil(size);
    const key = `${ceilSize},${hardness}`;
    if (cachedBrushMaskKey === key && cachedBrushMaskData) {
      currentBrushMask.value = cachedBrushMaskData;
      return cachedBrushMaskData;
    }
    cachedBrushMaskData = createBrushMask(ceilSize, hardness);
    cachedBrushMaskKey = key;
    currentBrushMask.value = cachedBrushMaskData;
    return cachedBrushMaskData;
  }

  /**
   * Set clone source from the processed image
   */
  function setCloneSource(
    sourceCanvas: HTMLCanvasElement,
    sourcePoint: Point,
    destinationPoint: Point
  ): void {
    // Store the source canvas reference
    cloneSourceCanvas.value = sourceCanvas;

    // Calculate offset from destination to source
    cloneOffset.value = {
      x: sourcePoint.x - destinationPoint.x,
      y: sourcePoint.y - destinationPoint.y,
    };
  }

  /**
   * Apply clone stamp at position
   * Uses Photoshop-style blending: opacity caps the stroke, flow controls buildup
   */
  function applyCloneStamp(
    sourceCanvas: HTMLCanvasElement,
    destPoint: Point,
    brushSettings: BrushSettings
  ): void {
    if (!retouchCtx.value || !cloneOffset.value) return;

    const { size, hardness, opacity, flow, spacing } = brushSettings;
    const brushMask = getBrushMask(size, hardness);

    // Get points along stroke if we have a previous point
    const points: Point[] = lastStrokePoint
      ? getStrokePoints(
          lastStrokePoint.x,
          lastStrokePoint.y,
          destPoint.x,
          destPoint.y,
          size * (spacing / 100)
        )
      : [destPoint];

    if (points.length === 0) points.push(destPoint);

    // Get source canvas context
    const sourceCtx = sourceCanvas.getContext('2d');
    if (!sourceCtx) return;

    const halfSize = size / 2;
    const maxOpacity = opacity / 100;
    const flowRate = flow / 100;

    for (const point of points) {
      const srcX = point.x + cloneOffset.value.x;
      const srcY = point.y + cloneOffset.value.y;

      // Sample from source (the combined base + retouch image)
      const sourceData = sampleRegion(
        sourceCtx,
        srcX - halfSize,
        srcY - halfSize,
        size,
        size
      );

      // Apply to retouch layer with brush mask
      const destX = Math.floor(point.x - halfSize);
      const destY = Math.floor(point.y - halfSize);

      const destData = retouchCtx.value!.getImageData(destX, destY, size, size);
      const maskData = brushMask.data;
      const srcPixels = sourceData.data;
      const destPixels = destData.data;

      // Get selection mask for this region
      const selectionMask = getSelectionMaskRegion(destX, destY, size, size);

      for (let i = 0; i < maskData.length; i += 4) {
        const pixelIdx = i / 4;

        // Apply selection mask if present
        const selectionAlpha = selectionMask ? selectionMask[pixelIdx] / 255 : 1;
        if (selectionAlpha === 0) continue;

        // Brush mask determines the shape
        const brushAlpha = maskData[i + 3] / 255;
        if (brushAlpha === 0) continue;

        // Blend strength for this dab: brush shape * flow * opacity * selection
        const blendStrength = brushAlpha * flowRate * maxOpacity * selectionAlpha;
        if (blendStrength === 0) continue;

        // Standard alpha compositing: new over old
        const srcA = blendStrength;
        const dstA = destPixels[i + 3] / 255;
        const outA = srcA + dstA * (1 - srcA);

        if (outA > 0) {
          // Blend colors with proper alpha weighting
          destPixels[i] = (srcPixels[i] * srcA + destPixels[i] * dstA * (1 - srcA)) / outA;
          destPixels[i + 1] = (srcPixels[i + 1] * srcA + destPixels[i + 1] * dstA * (1 - srcA)) / outA;
          destPixels[i + 2] = (srcPixels[i + 2] * srcA + destPixels[i + 2] * dstA * (1 - srcA)) / outA;
          destPixels[i + 3] = outA * 255;
        }
      }

      retouchCtx.value!.putImageData(destData, destX, destY);
    }

    lastStrokePoint = { ...destPoint };
  }

  /**
   * Apply spot heal at position
   * Uses texture-preserving healing similar to Photoshop's spot healing brush
   */
  function applySpotHeal(
    sourceCanvas: HTMLCanvasElement,
    point: Point,
    brushSize: number
  ): void {
    if (!retouchCtx.value) return;

    const sourceCtx = sourceCanvas.getContext('2d');
    if (!sourceCtx) return;

    const radius = brushSize / 2;
    const halfSize = brushSize / 2;
    const destX = Math.floor(point.x - halfSize);
    const destY = Math.floor(point.y - halfSize);

    // Sample surrounding pixels from a wider area for better color matching
    const samples = sampleSurroundingPixels(
      sourceCtx,
      point.x,
      point.y,
      radius * 1.2,  // Start sampling just outside the brush
      radius * 3,    // Sample from a wider surrounding area
      24             // More samples for smoother results
    );

    // Get the original pixels to preserve texture/luminosity variation
    const originalData = sourceCtx.getImageData(destX, destY, brushSize, brushSize);
    const originalPixels = originalData.data;

    // Create the healed region
    const destData = retouchCtx.value.getImageData(destX, destY, brushSize, brushSize);
    const destPixels = destData.data;

    // Create very soft brush mask for healing (Photoshop uses very soft edges)
    const brushMask = getBrushMask(brushSize, 15);
    const maskData = brushMask.data;

    // Calculate average luminosity of samples for texture preservation
    let sampleLumSum = 0;
    for (const sample of samples) {
      sampleLumSum += (sample.r * 0.299 + sample.g * 0.587 + sample.b * 0.114);
    }
    const avgSampleLum = sampleLumSum / samples.length;

    for (let py = 0; py < brushSize; py++) {
      for (let px = 0; px < brushSize; px++) {
        const idx = (py * brushSize + px) * 4;
        const maskAlpha = maskData[idx + 3] / 255;
        if (maskAlpha === 0) continue;

        const targetX = destX + px;
        const targetY = destY + py;

        // Interpolate base color from surrounding samples
        const interpolated = interpolateFromSamples(targetX, targetY, samples);

        // Get original pixel luminosity for texture preservation
        const origLum = originalPixels[idx] * 0.299 + originalPixels[idx + 1] * 0.587 + originalPixels[idx + 2] * 0.114;

        // Preserve some of the original texture variation
        // This prevents the "flat blob" look by maintaining local luminosity differences
        const lumDiff = origLum - avgSampleLum;
        const texturePreserve = 0.3; // How much original texture to preserve (0-1)
        const lumAdjust = lumDiff * texturePreserve;

        // Apply luminosity adjustment to interpolated color
        let finalR = Math.max(0, Math.min(255, interpolated.r + lumAdjust));
        let finalG = Math.max(0, Math.min(255, interpolated.g + lumAdjust));
        let finalB = Math.max(0, Math.min(255, interpolated.b + lumAdjust));

        // Blend with existing using the soft mask
        const srcA = maskAlpha;
        const dstA = destPixels[idx + 3] / 255;
        const outA = srcA + dstA * (1 - srcA);

        if (outA > 0) {
          destPixels[idx] = (finalR * srcA + destPixels[idx] * dstA * (1 - srcA)) / outA;
          destPixels[idx + 1] = (finalG * srcA + destPixels[idx + 1] * dstA * (1 - srcA)) / outA;
          destPixels[idx + 2] = (finalB * srcA + destPixels[idx + 2] * dstA * (1 - srcA)) / outA;
          destPixels[idx + 3] = outA * 255;
        }
      }
    }

    retouchCtx.value.putImageData(destData, destX, destY);
  }

  /**
   * Apply dodge or burn at position
   */
  function applyDodgeBurn(
    sourceCanvas: HTMLCanvasElement,
    point: Point,
    brushSettings: BrushSettings,
    exposure: number, // 0-100
    range: 'shadows' | 'midtones' | 'highlights',
    isDodge: boolean
  ): void {
    if (!retouchCtx.value) return;

    const sourceCtx = sourceCanvas.getContext('2d');
    if (!sourceCtx) return;

    const { size, hardness, opacity, flow, spacing } = brushSettings;
    const brushMask = getBrushMask(size, hardness);

    // Get points along stroke
    const points: Point[] = lastStrokePoint
      ? getStrokePoints(
          lastStrokePoint.x,
          lastStrokePoint.y,
          point.x,
          point.y,
          size * (spacing / 100)
        )
      : [point];

    if (points.length === 0) points.push(point);

    const halfSize = size / 2;
    const amount = (exposure / 100) * (isDodge ? 1 : -1);
    const effectiveOpacity = (opacity / 100) * (flow / 100);

    for (const p of points) {
      const destX = Math.floor(p.x - halfSize);
      const destY = Math.floor(p.y - halfSize);

      // Sample from source (combined image + retouch layer)
      const sourceData = sampleRegion(sourceCtx, destX, destY, size, size);
      const destData = retouchCtx.value!.getImageData(destX, destY, size, size);
      const maskData = brushMask.data;
      const srcPixels = sourceData.data;
      const destPixels = destData.data;

      // Get selection mask for this region
      const selectionMask = getSelectionMaskRegion(destX, destY, size, size);

      for (let i = 0; i < maskData.length; i += 4) {
        const pixelIdx = i / 4;

        // Apply selection mask if present
        const selectionAlpha = selectionMask ? selectionMask[pixelIdx] / 255 : 1;
        if (selectionAlpha === 0) continue;

        const maskAlpha = (maskData[i + 3] / 255) * effectiveOpacity * selectionAlpha;
        if (maskAlpha === 0) continue;

        // Get the current color (prefer retouch layer if has content, else source)
        let r = srcPixels[i];
        let g = srcPixels[i + 1];
        let b = srcPixels[i + 2];

        if (destPixels[i + 3] > 0) {
          // Blend existing retouch data
          const existingAlpha = destPixels[i + 3] / 255;
          r = destPixels[i] * existingAlpha + srcPixels[i] * (1 - existingAlpha);
          g = destPixels[i + 1] * existingAlpha + srcPixels[i + 1] * (1 - existingAlpha);
          b = destPixels[i + 2] * existingAlpha + srcPixels[i + 2] * (1 - existingAlpha);
        }

        // Adjust luminosity
        const adjusted = adjustLuminosity(r, g, b, amount * maskAlpha, range);

        // Write to retouch layer
        const srcA = maskAlpha;
        const dstA = destPixels[i + 3] / 255;
        const outA = srcA + dstA * (1 - srcA);

        if (outA > 0) {
          destPixels[i] = (adjusted.r * srcA + destPixels[i] * dstA * (1 - srcA)) / outA;
          destPixels[i + 1] = (adjusted.g * srcA + destPixels[i + 1] * dstA * (1 - srcA)) / outA;
          destPixels[i + 2] = (adjusted.b * srcA + destPixels[i + 2] * dstA * (1 - srcA)) / outA;
          destPixels[i + 3] = outA * 255;
        }
      }

      retouchCtx.value!.putImageData(destData, destX, destY);
    }

    lastStrokePoint = { ...point };
  }

  /**
   * Apply sponge (saturation) brush at position
   */
  function applySaturationBrush(
    sourceCanvas: HTMLCanvasElement,
    point: Point,
    brushSettings: BrushSettings,
    flow: number, // 0-100
    isSaturate: boolean
  ): void {
    if (!retouchCtx.value) return;

    const sourceCtx = sourceCanvas.getContext('2d');
    if (!sourceCtx) return;

    const { size, hardness, opacity, spacing } = brushSettings;
    const brushMask = getBrushMask(size, hardness);

    // Get points along stroke
    const points: Point[] = lastStrokePoint
      ? getStrokePoints(
          lastStrokePoint.x,
          lastStrokePoint.y,
          point.x,
          point.y,
          size * (spacing / 100)
        )
      : [point];

    if (points.length === 0) points.push(point);

    const halfSize = size / 2;
    const amount = (flow / 100) * (isSaturate ? 1 : -1);
    const effectiveOpacity = opacity / 100;

    for (const p of points) {
      const destX = Math.floor(p.x - halfSize);
      const destY = Math.floor(p.y - halfSize);

      // Sample from source (combined image + retouch layer)
      const sourceData = sampleRegion(sourceCtx, destX, destY, size, size);
      const destData = retouchCtx.value!.getImageData(destX, destY, size, size);
      const maskData = brushMask.data;
      const srcPixels = sourceData.data;
      const destPixels = destData.data;

      // Get selection mask for this region
      const selectionMask = getSelectionMaskRegion(destX, destY, size, size);

      for (let i = 0; i < maskData.length; i += 4) {
        const pixelIdx = i / 4;

        // Apply selection mask if present
        const selectionAlpha = selectionMask ? selectionMask[pixelIdx] / 255 : 1;
        if (selectionAlpha === 0) continue;

        const maskAlpha = (maskData[i + 3] / 255) * effectiveOpacity * selectionAlpha;
        if (maskAlpha === 0) continue;

        // Get the current color (prefer retouch layer if has content, else source)
        let r = srcPixels[i];
        let g = srcPixels[i + 1];
        let b = srcPixels[i + 2];

        if (destPixels[i + 3] > 0) {
          // Blend existing retouch data
          const existingAlpha = destPixels[i + 3] / 255;
          r = destPixels[i] * existingAlpha + srcPixels[i] * (1 - existingAlpha);
          g = destPixels[i + 1] * existingAlpha + srcPixels[i + 1] * (1 - existingAlpha);
          b = destPixels[i + 2] * existingAlpha + srcPixels[i + 2] * (1 - existingAlpha);
        }

        // Adjust saturation
        const adjusted = adjustSaturation(r, g, b, amount * maskAlpha);

        // Write to retouch layer
        const srcA = maskAlpha;
        const dstA = destPixels[i + 3] / 255;
        const outA = srcA + dstA * (1 - srcA);

        if (outA > 0) {
          destPixels[i] = (adjusted.r * srcA + destPixels[i] * dstA * (1 - srcA)) / outA;
          destPixels[i + 1] = (adjusted.g * srcA + destPixels[i + 1] * dstA * (1 - srcA)) / outA;
          destPixels[i + 2] = (adjusted.b * srcA + destPixels[i + 2] * dstA * (1 - srcA)) / outA;
          destPixels[i + 3] = outA * 255;
        }
      }

      retouchCtx.value!.putImageData(destData, destX, destY);
    }

    lastStrokePoint = { ...point };
  }

  /**
   * Get or resize a reusable work canvas for blur/sharpen operations.
   * Uses a small region canvas sized to brushSize + padding instead of full image.
   */
  function getWorkCanvas(neededSize: number): { canvas: HTMLCanvasElement; ctx: CanvasRenderingContext2D } {
    if (!workCanvas || workCanvasSize < neededSize) {
      workCanvas = document.createElement('canvas');
      workCanvas.width = neededSize;
      workCanvas.height = neededSize;
      workCtx = workCanvas.getContext('2d', { willReadFrequently: true })!;
      workCanvasSize = neededSize;
    } else if (workCanvas.width !== neededSize || workCanvas.height !== neededSize) {
      workCanvas.width = neededSize;
      workCanvas.height = neededSize;
    }
    return { canvas: workCanvas, ctx: workCtx! };
  }

  /**
   * Apply blur or sharpen brush at position using a small local-region work canvas
   */
  function applyBlurSharpenBrush(
    sourceCanvas: HTMLCanvasElement,
    point: Point,
    brushSettings: BrushSettings,
    strength: number,
    isBlur: boolean
  ): void {
    if (!retouchCtx.value) return;

    const sourceCtx = sourceCanvas.getContext('2d');
    if (!sourceCtx) return;

    const { size, hardness, spacing } = brushSettings;
    const brushMask = getBrushMask(size, hardness);

    // Get points along stroke
    const points: Point[] = lastStrokePoint
      ? getStrokePoints(
          lastStrokePoint.x,
          lastStrokePoint.y,
          point.x,
          point.y,
          size * (spacing / 100)
        )
      : [point];

    if (points.length === 0) points.push(point);

    const blurRadius = isBlur ? Math.max(1, Math.ceil(strength / 20)) : 1;
    const padding = blurRadius + 2; // Extra padding for filter kernel
    const regionSize = Math.ceil(size) + padding * 2;
    const halfSize = size / 2;

    // Get a reusable work canvas sized to the region (not the full image)
    const { ctx: localCtx } = getWorkCanvas(regionSize);

    for (const p of points) {
      // Calculate the region bounds in image coordinates
      const regionX = Math.max(0, Math.floor(p.x - halfSize) - padding);
      const regionY = Math.max(0, Math.floor(p.y - halfSize) - padding);
      const maxX = Math.min(sourceCanvas.width, Math.ceil(p.x + halfSize) + padding);
      const maxY = Math.min(sourceCanvas.height, Math.ceil(p.y + halfSize) + padding);
      const regionW = maxX - regionX;
      const regionH = maxY - regionY;

      if (regionW <= 0 || regionH <= 0) continue;

      // Draw only the needed region from source + retouch into the small work canvas
      localCtx.clearRect(0, 0, regionW, regionH);
      localCtx.drawImage(sourceCanvas, regionX, regionY, regionW, regionH, 0, 0, regionW, regionH);
      if (retouchCanvas.value) {
        localCtx.drawImage(retouchCanvas.value, regionX, regionY, regionW, regionH, 0, 0, regionW, regionH);
      }

      // Apply blur/sharpen on the local region canvas
      // Adjust point coordinates to be relative to the region
      const localX = p.x - regionX;
      const localY = p.y - regionY;

      if (isBlur) {
        applyLocalBlur(localCtx, localX, localY, size, brushMask, blurRadius);
      } else {
        applyLocalSharpen(localCtx, localX, localY, size, brushMask, strength);
      }

      // Copy the processed region back to retouch layer, respecting selection
      const destX = Math.floor(p.x - halfSize);
      const destY = Math.floor(p.y - halfSize);
      // Read back just the brush-sized area from the local canvas
      const localReadX = Math.floor(localX - halfSize);
      const localReadY = Math.floor(localY - halfSize);
      const processedData = localCtx.getImageData(localReadX, localReadY, size, size);

      // Get selection mask for this region
      const selectionMask = getSelectionMaskRegion(destX, destY, size, size);

      if (selectionMask) {
        const destData = retouchCtx.value!.getImageData(destX, destY, size, size);
        const processedPixels = processedData.data;
        const destPixels = destData.data;

        for (let i = 0; i < processedPixels.length; i += 4) {
          const pixelIdx = i / 4;
          const selectionAlpha = selectionMask[pixelIdx] / 255;
          if (selectionAlpha === 0) continue;

          if (selectionAlpha >= 1) {
            destPixels[i] = processedPixels[i];
            destPixels[i + 1] = processedPixels[i + 1];
            destPixels[i + 2] = processedPixels[i + 2];
            destPixels[i + 3] = processedPixels[i + 3];
          } else {
            destPixels[i] = destPixels[i] * (1 - selectionAlpha) + processedPixels[i] * selectionAlpha;
            destPixels[i + 1] = destPixels[i + 1] * (1 - selectionAlpha) + processedPixels[i + 1] * selectionAlpha;
            destPixels[i + 2] = destPixels[i + 2] * (1 - selectionAlpha) + processedPixels[i + 2] * selectionAlpha;
            destPixels[i + 3] = destPixels[i + 3] * (1 - selectionAlpha) + processedPixels[i + 3] * selectionAlpha;
          }
        }
        retouchCtx.value!.putImageData(destData, destX, destY);
      } else {
        retouchCtx.value!.putImageData(processedData, destX, destY);
      }
    }

    lastStrokePoint = { ...point };
  }

  /**
   * Apply blur brush at position
   */
  function applyBlurBrush(
    sourceCanvas: HTMLCanvasElement,
    point: Point,
    brushSettings: BrushSettings,
    strength: number
  ): void {
    applyBlurSharpenBrush(sourceCanvas, point, brushSettings, strength, true);
  }

  /**
   * Apply sharpen brush at position
   */
  function applySharpenBrush(
    sourceCanvas: HTMLCanvasElement,
    point: Point,
    brushSettings: BrushSettings,
    strength: number
  ): void {
    applyBlurSharpenBrush(sourceCanvas, point, brushSettings, strength, false);
  }

  /**
   * Apply paint brush at position (paints with solid color)
   */
  function applyPaintBrush(
    point: Point,
    brushSettings: BrushSettings,
    color: { r: number; g: number; b: number; a?: number }
  ): void {
    if (!retouchCtx.value) return;

    const { size, hardness, opacity, flow, spacing } = brushSettings;
    const brushMask = getBrushMask(size, hardness);

    // Get points along stroke
    const points: Point[] = lastStrokePoint
      ? getStrokePoints(
          lastStrokePoint.x,
          lastStrokePoint.y,
          point.x,
          point.y,
          size * (spacing / 100)
        )
      : [point];

    if (points.length === 0) points.push(point);

    const halfSize = size / 2;
    const effectiveOpacity = (opacity / 100) * (flow / 100);
    const colorAlpha = color.a ?? 1;
    const brushSize = Math.ceil(size);

    for (const p of points) {
      const destX = Math.floor(p.x - halfSize);
      const destY = Math.floor(p.y - halfSize);

      const destData = retouchCtx.value!.getImageData(destX, destY, brushSize, brushSize);
      const maskData = brushMask.data;
      const destPixels = destData.data;

      // Get selection mask for this region
      const selectionMask = getSelectionMaskRegion(destX, destY, brushSize, brushSize);

      for (let i = 0; i < maskData.length; i += 4) {
        const pixelIdx = i / 4;

        // Apply selection mask if present
        const selectionAlpha = selectionMask ? selectionMask[pixelIdx] / 255 : 1;
        if (selectionAlpha === 0) continue;

        const maskAlpha = (maskData[i + 3] / 255) * effectiveOpacity * colorAlpha * selectionAlpha;
        if (maskAlpha === 0) continue;

        // Alpha compositing: paint over existing
        const srcA = maskAlpha;
        const dstA = destPixels[i + 3] / 255;
        const outA = srcA + dstA * (1 - srcA);

        if (outA > 0) {
          destPixels[i] = (color.r * srcA + destPixels[i] * dstA * (1 - srcA)) / outA;
          destPixels[i + 1] = (color.g * srcA + destPixels[i + 1] * dstA * (1 - srcA)) / outA;
          destPixels[i + 2] = (color.b * srcA + destPixels[i + 2] * dstA * (1 - srcA)) / outA;
          destPixels[i + 3] = outA * 255;
        }
      }

      retouchCtx.value!.putImageData(destData, destX, destY);
    }

    lastStrokePoint = { ...point };
  }

  /**
   * Apply flood fill at position (paint bucket tool)
   */
  function applyFloodFill(
    sourceCanvas: HTMLCanvasElement,
    point: Point,
    color: { r: number; g: number; b: number; a?: number },
    tolerance: number = 32
  ): void {
    if (!retouchCtx.value) return;

    const sourceCtx = sourceCanvas.getContext('2d');
    if (!sourceCtx) return;

    const width = sourceCanvas.width;
    const height = sourceCanvas.height;

    const x = Math.floor(point.x);
    const y = Math.floor(point.y);

    if (x < 0 || x >= width || y < 0 || y >= height) return;

    // Get source image data
    const sourceData = sourceCtx.getImageData(0, 0, width, height);
    const srcPixels = sourceData.data;

    // Get target color at click point
    const startIdx = (y * width + x) * 4;
    const targetR = srcPixels[startIdx];
    const targetG = srcPixels[startIdx + 1];
    const targetB = srcPixels[startIdx + 2];

    // Get retouch layer data
    const retouchData = retouchCtx.value.getImageData(0, 0, width, height);
    const retouchPixels = retouchData.data;

    // Create visited array
    const visited = new Uint8Array(width * height);

    // Flood fill using queue
    const queue: Array<[number, number]> = [[x, y]];
    const colorAlpha = color.a ?? 1;

    function colorMatch(idx: number): boolean {
      const dr = srcPixels[idx] - targetR;
      const dg = srcPixels[idx + 1] - targetG;
      const db = srcPixels[idx + 2] - targetB;
      return Math.sqrt(dr * dr + dg * dg + db * db) <= tolerance * 1.732;
    }

    while (queue.length > 0) {
      const [cx, cy] = queue.shift()!;

      if (cx < 0 || cx >= width || cy < 0 || cy >= height) continue;

      const pixelIdx = cy * width + cx;
      if (visited[pixelIdx]) continue;

      const idx = pixelIdx * 4;
      if (!colorMatch(idx)) continue;

      // Check selection mask
      const selectionAlpha = getSelectionAlpha(cx, cy);
      if (selectionAlpha === 0) continue;

      visited[pixelIdx] = 1;

      // Fill this pixel on retouch layer (blend with selection alpha)
      const finalAlpha = colorAlpha * selectionAlpha;
      retouchPixels[idx] = color.r;
      retouchPixels[idx + 1] = color.g;
      retouchPixels[idx + 2] = color.b;
      retouchPixels[idx + 3] = finalAlpha * 255;

      // Add neighbors
      queue.push([cx + 1, cy], [cx - 1, cy], [cx, cy + 1], [cx, cy - 1]);
    }

    retouchCtx.value.putImageData(retouchData, 0, 0);
  }

  /**
   * Apply patch tool: copy pixels from source region (at offset) to destination using selection mask.
   * The selection mask's alpha channel provides feathered edge blending.
   *
   * @param sourceCanvas - The source image canvas to sample from
   * @param offset - The drag offset (source position relative to destination)
   * @param bounds - Bounding box of the selection
   * @param blendWidth - Additional edge blend radius for softer transitions (0-50)
   */
  function applyPatchTool(
    sourceCanvas: HTMLCanvasElement,
    offset: { x: number; y: number },
    bounds: { x: number; y: number; width: number; height: number },
    blendWidth: number = 15
  ): void {
    if (!retouchCtx.value || !selectionMaskCtx) return;

    const sourceCtx = sourceCanvas.getContext('2d');
    if (!sourceCtx) return;

    applyPatch(sourceCtx, retouchCtx.value, selectionMaskCtx, offset, bounds, blendWidth);
  }

  /**
   * Start a new stroke (reset spacing tracking)
   */
  function startStroke(): void {
    lastStrokePoint = null;
  }

  /**
   * End the current stroke
   */
  function endStroke(): void {
    lastStrokePoint = null;
  }

  return {
    retouchCanvas,
    retouchCtx,
    layerSize,
    cloneOffset,
    initLayer,
    clearLayer,
    loadFromDataUrl,
    toDataUrl,
    toSnapshot,
    loadFromSnapshot,
    setCloneSource,
    applyCloneStamp,
    applySpotHeal,
    applyDodgeBurn,
    applySaturationBrush,
    applyBlurBrush,
    applySharpenBrush,
    applyPaintBrush,
    applyFloodFill,
    applyPatchTool,
    setSelectionMask,
    startStroke,
    endStroke,
  };
}
