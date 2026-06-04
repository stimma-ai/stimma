import type { ImageSource, Size } from '@/types';
import { RENDER_CONFIG } from '@/constants';

/**
 * Load an image from various sources
 */
export async function loadImage(
  source: ImageSource
): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';

    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('Failed to load image'));

    if (source instanceof HTMLImageElement) {
      // Already an image element
      if (source.complete && source.naturalWidth > 0) {
        resolve(source);
      } else {
        img.src = source.src;
      }
    } else if (source instanceof HTMLCanvasElement) {
      // Canvas - convert to data URL
      img.src = source.toDataURL();
    } else if (source instanceof ImageBitmap) {
      // ImageBitmap - draw to canvas and convert
      const canvas = document.createElement('canvas');
      canvas.width = source.width;
      canvas.height = source.height;
      const ctx = canvas.getContext('2d')!;
      ctx.drawImage(source, 0, 0);
      img.src = canvas.toDataURL();
    } else if (source instanceof File || source instanceof Blob) {
      // Blob/File - create object URL
      const url = URL.createObjectURL(source);
      img.onload = () => {
        URL.revokeObjectURL(url);
        resolve(img);
      };
      img.onerror = () => {
        URL.revokeObjectURL(url);
        reject(new Error('Failed to load image from blob'));
      };
      img.src = url;
    } else if (typeof source === 'string') {
      // URL or data URL
      img.src = source;
    } else {
      reject(new Error('Invalid image source'));
    }
  });
}

/**
 * Get image dimensions from source
 */
export function getImageSize(
  image: HTMLImageElement | HTMLCanvasElement | ImageBitmap
): Size {
  if (image instanceof HTMLImageElement) {
    return {
      width: image.naturalWidth,
      height: image.naturalHeight,
    };
  } else {
    return {
      width: image.width,
      height: image.height,
    };
  }
}

/**
 * Create a preview-sized canvas from an image
 */
export function createPreviewCanvas(
  image: HTMLImageElement | HTMLCanvasElement | ImageBitmap,
  maxSize: number = RENDER_CONFIG.maxPreviewSize
): HTMLCanvasElement {
  const size = getImageSize(image);
  let width = size.width;
  let height = size.height;

  // Scale down if larger than max size
  if (width > maxSize || height > maxSize) {
    const scale = maxSize / Math.max(width, height);
    width = Math.round(width * scale);
    height = Math.round(height * scale);
  }

  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;

  const ctx = canvas.getContext('2d')!;
  ctx.drawImage(image, 0, 0, width, height);

  return canvas;
}

/**
 * Read EXIF orientation from image data
 * Returns orientation 1-8 or 1 if not found
 */
export async function readExifOrientation(blob: Blob): Promise<number> {
  try {
    const buffer = await blob.slice(0, 65536).arrayBuffer();
    const view = new DataView(buffer);

    // Check for JPEG
    if (view.getUint16(0) !== 0xffd8) {
      return 1;
    }

    let offset = 2;
    while (offset < view.byteLength - 4) {
      const marker = view.getUint16(offset);

      // APP1 marker (EXIF)
      if (marker === 0xffe1) {
        const exifOffset = offset + 4;

        // Check for "Exif\0\0"
        if (
          view.getUint32(exifOffset) === 0x45786966 &&
          view.getUint16(exifOffset + 4) === 0x0000
        ) {
          const tiffOffset = exifOffset + 6;
          const littleEndian = view.getUint16(tiffOffset) === 0x4949;

          const ifdOffset = view.getUint32(tiffOffset + 4, littleEndian);
          const numEntries = view.getUint16(
            tiffOffset + ifdOffset,
            littleEndian
          );

          for (let i = 0; i < numEntries; i++) {
            const entryOffset = tiffOffset + ifdOffset + 2 + i * 12;
            const tag = view.getUint16(entryOffset, littleEndian);

            // Orientation tag
            if (tag === 0x0112) {
              return view.getUint16(entryOffset + 8, littleEndian);
            }
          }
        }
      }

      offset += 2 + view.getUint16(offset + 2);
    }
  } catch {
    // Ignore errors, return default orientation
  }

  return 1;
}

/**
 * Apply EXIF orientation to canvas
 */
export function applyExifOrientation(
  image: HTMLImageElement,
  orientation: number
): HTMLCanvasElement {
  const { naturalWidth: w, naturalHeight: h } = image;

  // Orientation values that swap width/height
  const swapDimensions = orientation >= 5 && orientation <= 8;
  const width = swapDimensions ? h : w;
  const height = swapDimensions ? w : h;

  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;

  const ctx = canvas.getContext('2d')!;

  // Apply transform based on orientation
  switch (orientation) {
    case 2:
      ctx.transform(-1, 0, 0, 1, w, 0);
      break;
    case 3:
      ctx.transform(-1, 0, 0, -1, w, h);
      break;
    case 4:
      ctx.transform(1, 0, 0, -1, 0, h);
      break;
    case 5:
      ctx.transform(0, 1, 1, 0, 0, 0);
      break;
    case 6:
      ctx.transform(0, 1, -1, 0, h, 0);
      break;
    case 7:
      ctx.transform(0, -1, -1, 0, h, w);
      break;
    case 8:
      ctx.transform(0, -1, 1, 0, 0, w);
      break;
    default:
      // No transformation needed for orientation 1
      break;
  }

  ctx.drawImage(image, 0, 0);

  return canvas;
}

/**
 * Convert canvas to blob
 */
export function canvasToBlob(
  canvas: HTMLCanvasElement,
  type: string = 'image/jpeg',
  quality: number = 0.92
): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) {
          resolve(blob);
        } else {
          reject(new Error('Failed to create blob from canvas'));
        }
      },
      type,
      quality
    );
  });
}

/**
 * Generate a unique ID for shapes
 */
export function generateId(): string {
  return Math.random().toString(36).substring(2, 11);
}

/**
 * RGBA color type for palette extraction
 */
interface RGBAColor {
  r: number;
  g: number;
  b: number;
  a: number;
}

/**
 * Extract dominant colors from an image using k-means clustering
 * Returns up to `count` distinct colors sorted by prominence
 */
export function extractImagePalette(
  image: HTMLImageElement | HTMLCanvasElement,
  count: number = 6
): RGBAColor[] {
  // Create a small canvas for sampling (performance)
  const sampleSize = 100;
  const canvas = document.createElement('canvas');
  canvas.width = sampleSize;
  canvas.height = sampleSize;
  const ctx = canvas.getContext('2d')!;

  // Draw image scaled down
  ctx.drawImage(image, 0, 0, sampleSize, sampleSize);

  // Get image data
  const imageData = ctx.getImageData(0, 0, sampleSize, sampleSize);
  const pixels = imageData.data;

  // Collect pixel colors (skip transparent pixels)
  const colors: [number, number, number][] = [];
  for (let i = 0; i < pixels.length; i += 4) {
    const a = pixels[i + 3];
    if (a < 128) continue; // Skip mostly transparent pixels

    const r = pixels[i];
    const g = pixels[i + 1];
    const b = pixels[i + 2];

    // Skip very dark or very light colors (already have black/white in static palette)
    const brightness = (r + g + b) / 3;
    if (brightness < 30 || brightness > 225) continue;

    colors.push([r, g, b]);
  }

  if (colors.length === 0) {
    return [];
  }

  // Simple k-means clustering
  const k = Math.min(count * 2, colors.length); // Get more clusters, then pick best
  const clusters = kMeansClustering(colors, k, 10);

  // Sort by cluster size (prominence) and pick top colors
  const sortedClusters = clusters
    .filter(c => c.count > 0)
    .sort((a, b) => b.count - a.count);

  // Filter similar colors and pick distinct ones
  const result: RGBAColor[] = [];
  for (const cluster of sortedClusters) {
    if (result.length >= count) break;

    // Check if this color is distinct enough from existing results
    const isDistinct = result.every(existing => {
      const dr = existing.r - cluster.center[0];
      const dg = existing.g - cluster.center[1];
      const db = existing.b - cluster.center[2];
      const distance = Math.sqrt(dr * dr + dg * dg + db * db);
      return distance > 50; // Minimum color distance threshold
    });

    if (isDistinct) {
      result.push({
        r: Math.round(cluster.center[0]),
        g: Math.round(cluster.center[1]),
        b: Math.round(cluster.center[2]),
        a: 1,
      });
    }
  }

  return result;
}

/**
 * K-means clustering for colors
 */
function kMeansClustering(
  colors: [number, number, number][],
  k: number,
  iterations: number
): { center: [number, number, number]; count: number }[] {
  // Initialize centroids randomly from the input colors
  const centroids: [number, number, number][] = [];
  const usedIndices = new Set<number>();

  while (centroids.length < k && usedIndices.size < colors.length) {
    const idx = Math.floor(Math.random() * colors.length);
    if (!usedIndices.has(idx)) {
      usedIndices.add(idx);
      centroids.push([...colors[idx]]);
    }
  }

  // If we don't have enough unique colors, pad with what we have
  while (centroids.length < k) {
    centroids.push([...centroids[0]]);
  }

  // Iterative refinement
  for (let iter = 0; iter < iterations; iter++) {
    // Assign colors to nearest centroid
    const assignments: number[][] = centroids.map(() => []);

    for (let i = 0; i < colors.length; i++) {
      let minDist = Infinity;
      let closest = 0;

      for (let j = 0; j < centroids.length; j++) {
        const dr = colors[i][0] - centroids[j][0];
        const dg = colors[i][1] - centroids[j][1];
        const db = colors[i][2] - centroids[j][2];
        const dist = dr * dr + dg * dg + db * db;

        if (dist < minDist) {
          minDist = dist;
          closest = j;
        }
      }

      assignments[closest].push(i);
    }

    // Update centroids
    for (let j = 0; j < centroids.length; j++) {
      if (assignments[j].length === 0) continue;

      let sumR = 0, sumG = 0, sumB = 0;
      for (const idx of assignments[j]) {
        sumR += colors[idx][0];
        sumG += colors[idx][1];
        sumB += colors[idx][2];
      }

      centroids[j][0] = sumR / assignments[j].length;
      centroids[j][1] = sumG / assignments[j].length;
      centroids[j][2] = sumB / assignments[j].length;
    }
  }

  // Count final assignments
  const counts: number[] = centroids.map(() => 0);
  for (const color of colors) {
    let minDist = Infinity;
    let closest = 0;

    for (let j = 0; j < centroids.length; j++) {
      const dr = color[0] - centroids[j][0];
      const dg = color[1] - centroids[j][1];
      const db = color[2] - centroids[j][2];
      const dist = dr * dr + dg * dg + db * db;

      if (dist < minDist) {
        minDist = dist;
        closest = j;
      }
    }

    counts[closest]++;
  }

  return centroids.map((center, i) => ({
    center,
    count: counts[i],
  }));
}
