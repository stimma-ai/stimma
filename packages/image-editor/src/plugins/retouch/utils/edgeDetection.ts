/**
 * Edge detection utilities for the magnetic lasso tool.
 * Uses Sobel operator to compute image gradients.
 */

export interface GradientMap {
  width: number;
  height: number;
  /** Gradient magnitude normalized to 0-1 */
  magnitude: Float32Array;
  /** Unit vector X component of gradient direction */
  directionX: Float32Array;
  /** Unit vector Y component of gradient direction */
  directionY: Float32Array;
  /** Maximum magnitude value (for reference) */
  maxMagnitude: number;
}

/**
 * Convert ImageData to grayscale using luminance formula
 */
export function toGrayscale(imageData: ImageData): Uint8Array {
  const { width, height, data } = imageData;
  const gray = new Uint8Array(width * height);

  for (let i = 0; i < gray.length; i++) {
    const idx = i * 4;
    // Standard luminance formula (ITU-R BT.601)
    gray[i] = Math.round(0.299 * data[idx] + 0.587 * data[idx + 1] + 0.114 * data[idx + 2]);
  }

  return gray;
}

/**
 * Compute gradient map using Sobel operator.
 * This computes both gradient magnitude and direction at each pixel.
 *
 * Sobel kernels:
 * Gx = [-1 0 +1]     Gy = [-1 -2 -1]
 *      [-2 0 +2]          [ 0  0  0]
 *      [-1 0 +1]          [+1 +2 +1]
 */
export function computeGradientMap(imageData: ImageData): GradientMap {
  const { width, height } = imageData;
  const gray = toGrayscale(imageData);

  const magnitude = new Float32Array(width * height);
  const directionX = new Float32Array(width * height);
  const directionY = new Float32Array(width * height);

  // Helper to get pixel value with boundary handling (clamp to edge)
  const getPixel = (x: number, y: number): number => {
    x = Math.max(0, Math.min(width - 1, x));
    y = Math.max(0, Math.min(height - 1, y));
    return gray[y * width + x];
  };

  let maxMag = 0;

  // Compute gradients using Sobel operator
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      // Sobel X gradient
      const gx =
        -getPixel(x - 1, y - 1) + getPixel(x + 1, y - 1) +
        -2 * getPixel(x - 1, y) + 2 * getPixel(x + 1, y) +
        -getPixel(x - 1, y + 1) + getPixel(x + 1, y + 1);

      // Sobel Y gradient
      const gy =
        -getPixel(x - 1, y - 1) - 2 * getPixel(x, y - 1) - getPixel(x + 1, y - 1) +
        getPixel(x - 1, y + 1) + 2 * getPixel(x, y + 1) + getPixel(x + 1, y + 1);

      const idx = y * width + x;
      const mag = Math.sqrt(gx * gx + gy * gy);

      magnitude[idx] = mag;
      maxMag = Math.max(maxMag, mag);

      // Store direction as unit vector (perpendicular to gradient for edge direction)
      // Gradient points in direction of steepest increase; edge direction is perpendicular
      if (mag > 0.001) {
        // Edge direction is perpendicular to gradient: rotate 90 degrees
        // gradient = (gx, gy), perpendicular = (-gy, gx) or (gy, -gx)
        directionX[idx] = -gy / mag;
        directionY[idx] = gx / mag;
      } else {
        directionX[idx] = 0;
        directionY[idx] = 0;
      }
    }
  }

  // Normalize magnitude to 0-1
  if (maxMag > 0) {
    for (let i = 0; i < magnitude.length; i++) {
      magnitude[i] /= maxMag;
    }
  }

  return {
    width,
    height,
    magnitude,
    directionX,
    directionY,
    maxMagnitude: maxMag,
  };
}

/**
 * Get gradient magnitude at a point with bilinear interpolation
 */
export function getGradientMagnitude(gradientMap: GradientMap, x: number, y: number): number {
  const { width, height, magnitude } = gradientMap;

  // Clamp to bounds
  x = Math.max(0, Math.min(width - 1, x));
  y = Math.max(0, Math.min(height - 1, y));

  // Bilinear interpolation
  const x0 = Math.floor(x);
  const y0 = Math.floor(y);
  const x1 = Math.min(x0 + 1, width - 1);
  const y1 = Math.min(y0 + 1, height - 1);

  const fx = x - x0;
  const fy = y - y0;

  const v00 = magnitude[y0 * width + x0];
  const v10 = magnitude[y0 * width + x1];
  const v01 = magnitude[y1 * width + x0];
  const v11 = magnitude[y1 * width + x1];

  return (
    v00 * (1 - fx) * (1 - fy) +
    v10 * fx * (1 - fy) +
    v01 * (1 - fx) * fy +
    v11 * fx * fy
  );
}

/**
 * Get gradient direction at a point with bilinear interpolation
 * Returns [dx, dy] unit vector pointing along the edge
 */
export function getGradientDirection(gradientMap: GradientMap, x: number, y: number): [number, number] {
  const { width, height, directionX, directionY } = gradientMap;

  // Clamp to bounds
  x = Math.max(0, Math.min(width - 1, x));
  y = Math.max(0, Math.min(height - 1, y));

  // Bilinear interpolation
  const x0 = Math.floor(x);
  const y0 = Math.floor(y);
  const x1 = Math.min(x0 + 1, width - 1);
  const y1 = Math.min(y0 + 1, height - 1);

  const fx = x - x0;
  const fy = y - y0;

  const dx00 = directionX[y0 * width + x0];
  const dx10 = directionX[y0 * width + x1];
  const dx01 = directionX[y1 * width + x0];
  const dx11 = directionX[y1 * width + x1];

  const dy00 = directionY[y0 * width + x0];
  const dy10 = directionY[y0 * width + x1];
  const dy01 = directionY[y1 * width + x0];
  const dy11 = directionY[y1 * width + x1];

  const dx =
    dx00 * (1 - fx) * (1 - fy) +
    dx10 * fx * (1 - fy) +
    dx01 * (1 - fx) * fy +
    dx11 * fx * fy;

  const dy =
    dy00 * (1 - fx) * (1 - fy) +
    dy10 * fx * (1 - fy) +
    dy01 * (1 - fx) * fy +
    dy11 * fx * fy;

  // Normalize the interpolated direction
  const len = Math.sqrt(dx * dx + dy * dy);
  if (len > 0.001) {
    return [dx / len, dy / len];
  }
  return [0, 0];
}
