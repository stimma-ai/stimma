/**
 * Color Matrix Operations
 *
 * Color matrices are 5x4 arrays applied as:
 * [R', G', B', A'] = matrix × [R, G, B, A, 1]
 */

/**
 * Identity matrix (no change)
 */
export function identityMatrix(): number[] {
  return [
    1, 0, 0, 0, 0,
    0, 1, 0, 0, 0,
    0, 0, 1, 0, 0,
    0, 0, 0, 1, 0,
  ];
}

/**
 * Multiply two color matrices
 *
 * Color matrices are 4x5 (stored as 20 elements), representing:
 * | m0  m1  m2  m3  m4  |   | R |   | R' |
 * | m5  m6  m7  m8  m9  | × | G | = | G' |
 * | m10 m11 m12 m13 m14 |   | B |   | B' |
 * | m15 m16 m17 m18 m19 |   | A |   | A' |
 *                           | 1 |
 *
 * For composition, we treat them as 5x5 with implicit last row [0,0,0,0,1]
 */
export function multiplyColorMatrices(a: number[], b: number[]): number[] {
  const result = new Array(20).fill(0);

  for (let row = 0; row < 4; row++) {
    for (let col = 0; col < 5; col++) {
      let sum = 0;
      for (let i = 0; i < 5; i++) {
        // Get value from matrix a at [row, i]
        // For i < 4, use the actual value; for i = 4, use implicit 5th column (always 0 for rows 0-3)
        const aVal = i < 4 ? a[row * 5 + i] : 0;

        // Get value from matrix b at [i, col]
        // For i < 4, use actual value; for i = 4, use implicit 5th row [0,0,0,0,1]
        let bVal: number;
        if (i < 4) {
          bVal = b[i * 5 + col];
        } else {
          // Implicit 5th row of b is [0, 0, 0, 0, 1]
          bVal = col === 4 ? 1 : 0;
        }

        sum += aVal * bVal;
      }
      result[row * 5 + col] = sum;
    }
  }

  // Add the offset column from a (the 5th column carries through)
  for (let row = 0; row < 4; row++) {
    result[row * 5 + 4] += a[row * 5 + 4];
  }

  return result;
}

/**
 * Brightness: -100 to +100 → offset -255 to +255
 */
export function brightnessMatrix(value: number): number[] {
  const b = (value / 100) * 255;
  return [
    1, 0, 0, 0, b,
    0, 1, 0, 0, b,
    0, 0, 1, 0, b,
    0, 0, 0, 1, 0,
  ];
}

/**
 * Contrast: -100 to +100 → scale 0 to 2
 */
export function contrastMatrix(value: number): number[] {
  const c = 1 + value / 100;
  const o = 128 * (1 - c);
  return [
    c, 0, 0, 0, o,
    0, c, 0, 0, o,
    0, 0, c, 0, o,
    0, 0, 0, 1, 0,
  ];
}

/**
 * Saturation: -100 to +100 → scale 0 to 2
 */
export function saturationMatrix(value: number): number[] {
  const s = 1 + value / 100;
  // Luminance coefficients (ITU-R BT.709)
  const lr = 0.2126;
  const lg = 0.7152;
  const lb = 0.0722;

  const sr = (1 - s) * lr;
  const sg = (1 - s) * lg;
  const sb = (1 - s) * lb;

  return [
    sr + s, sg, sb, 0, 0,
    sr, sg + s, sb, 0, 0,
    sr, sg, sb + s, 0, 0,
    0, 0, 0, 1, 0,
  ];
}

/**
 * Exposure: -100 to +100 → multiplier 0.5 to 2
 */
export function exposureMatrix(value: number): number[] {
  // Map -100..100 to 0.5..2
  const e = Math.pow(2, value / 100);
  return [
    e, 0, 0, 0, 0,
    0, e, 0, 0, 0,
    0, 0, e, 0, 0,
    0, 0, 0, 1, 0,
  ];
}

/**
 * Temperature: -100 (cool) to +100 (warm)
 */
export function temperatureMatrix(value: number): number[] {
  // Simple approximation: shift red/blue balance
  const t = value / 100;
  const rShift = t > 0 ? t * 30 : 0;
  const bShift = t < 0 ? -t * 30 : 0;

  return [
    1, 0, 0, 0, rShift,
    0, 1, 0, 0, 0,
    0, 0, 1, 0, bShift,
    0, 0, 0, 1, 0,
  ];
}

/**
 * Gamma correction: 0.2 to 2.2
 * Note: Gamma cannot be done with a simple matrix, this is an approximation
 */
export function gammaMatrix(value: number): number[] {
  // Approximate gamma with contrast-like adjustment
  const g = 1 / value;
  const o = 128 * (1 - g);
  return [
    g, 0, 0, 0, o,
    0, g, 0, 0, o,
    0, 0, g, 0, o,
    0, 0, 0, 1, 0,
  ];
}

/**
 * Sepia tone filter
 */
export function sepiaMatrix(intensity: number = 1): number[] {
  const i = intensity;
  const ni = 1 - i;

  return [
    ni + i * 0.393, i * 0.769, i * 0.189, 0, 0,
    i * 0.349, ni + i * 0.686, i * 0.168, 0, 0,
    i * 0.272, i * 0.534, ni + i * 0.131, 0, 0,
    0, 0, 0, 1, 0,
  ];
}

/**
 * Grayscale filter
 */
export function grayscaleMatrix(intensity: number = 1): number[] {
  const i = intensity;
  const ni = 1 - i;

  const lr = 0.2126;
  const lg = 0.7152;
  const lb = 0.0722;

  return [
    ni + i * lr, i * lg, i * lb, 0, 0,
    i * lr, ni + i * lg, i * lb, 0, 0,
    i * lr, i * lg, ni + i * lb, 0, 0,
    0, 0, 0, 1, 0,
  ];
}

/**
 * Invert colors
 */
export function invertMatrix(): number[] {
  return [
    -1, 0, 0, 0, 255,
    0, -1, 0, 0, 255,
    0, 0, -1, 0, 255,
    0, 0, 0, 1, 0,
  ];
}

/**
 * Combine multiple adjustment values into a single matrix
 */
export function combineAdjustments(adjustments: {
  brightness?: number;
  contrast?: number;
  saturation?: number;
  exposure?: number;
  temperature?: number;
  gamma?: number;
}): number[] {
  let matrix = identityMatrix();

  if (adjustments.brightness !== undefined && adjustments.brightness !== 0) {
    matrix = multiplyColorMatrices(matrix, brightnessMatrix(adjustments.brightness));
  }

  if (adjustments.contrast !== undefined && adjustments.contrast !== 0) {
    matrix = multiplyColorMatrices(matrix, contrastMatrix(adjustments.contrast));
  }

  if (adjustments.saturation !== undefined && adjustments.saturation !== 0) {
    matrix = multiplyColorMatrices(matrix, saturationMatrix(adjustments.saturation));
  }

  if (adjustments.exposure !== undefined && adjustments.exposure !== 0) {
    matrix = multiplyColorMatrices(matrix, exposureMatrix(adjustments.exposure));
  }

  if (adjustments.temperature !== undefined && adjustments.temperature !== 0) {
    matrix = multiplyColorMatrices(matrix, temperatureMatrix(adjustments.temperature));
  }

  if (adjustments.gamma !== undefined && adjustments.gamma !== 1) {
    matrix = multiplyColorMatrices(matrix, gammaMatrix(adjustments.gamma));
  }

  return matrix;
}

/**
 * Apply color matrix to image data
 */
export function applyColorMatrix(
  imageData: ImageData,
  matrix: number[]
): ImageData {
  const data = imageData.data;

  for (let i = 0; i < data.length; i += 4) {
    const r = data[i];
    const g = data[i + 1];
    const b = data[i + 2];
    const a = data[i + 3];

    data[i] = Math.min(
      255,
      Math.max(
        0,
        matrix[0] * r +
          matrix[1] * g +
          matrix[2] * b +
          matrix[3] * a +
          matrix[4]
      )
    );
    data[i + 1] = Math.min(
      255,
      Math.max(
        0,
        matrix[5] * r +
          matrix[6] * g +
          matrix[7] * b +
          matrix[8] * a +
          matrix[9]
      )
    );
    data[i + 2] = Math.min(
      255,
      Math.max(
        0,
        matrix[10] * r +
          matrix[11] * g +
          matrix[12] * b +
          matrix[13] * a +
          matrix[14]
      )
    );
    data[i + 3] = Math.min(
      255,
      Math.max(
        0,
        matrix[15] * r +
          matrix[16] * g +
          matrix[17] * b +
          matrix[18] * a +
          matrix[19]
      )
    );
  }

  return imageData;
}

/**
 * Convert HSL to RGB
 */
function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  h = h / 360;
  s = s / 100;
  l = l / 100;

  let r: number, g: number, b: number;

  if (s === 0) {
    r = g = b = l;
  } else {
    const hue2rgb = (p: number, q: number, t: number) => {
      if (t < 0) t += 1;
      if (t > 1) t -= 1;
      if (t < 1 / 6) return p + (q - p) * 6 * t;
      if (t < 1 / 2) return q;
      if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
      return p;
    };

    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;
    r = hue2rgb(p, q, h + 1 / 3);
    g = hue2rgb(p, q, h);
    b = hue2rgb(p, q, h - 1 / 3);
  }

  return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)];
}

/**
 * Convert RGB to HSL
 */
function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
  r /= 255;
  g /= 255;
  b /= 255;

  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  let h = 0;
  let s = 0;
  const l = (max + min) / 2;

  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r:
        h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
        break;
      case g:
        h = ((b - r) / d + 2) / 6;
        break;
      case b:
        h = ((r - g) / d + 4) / 6;
        break;
    }
  }

  return [h * 360, s * 100, l * 100];
}

/**
 * Calculate luminance from RGB (ITU-R BT.709)
 */
function getLuminance(r: number, g: number, b: number): number {
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
}

/**
 * Apply split toning effect
 * Adds color tints to shadows and highlights separately
 */
export function applySplitToning(
  imageData: ImageData,
  shadowHue: number,
  shadowSat: number,
  highlightHue: number,
  highlightSat: number,
  balance: number = 0
): ImageData {
  const data = imageData.data;

  // Convert hue/sat to RGB colors at 50% lightness
  const shadowRgb = hslToRgb(shadowHue, shadowSat, 50);
  const highlightRgb = hslToRgb(highlightHue, highlightSat, 50);

  // Normalize saturation to 0-1
  const shadowIntensity = shadowSat / 100;
  const highlightIntensity = highlightSat / 100;

  // Balance shifts the midpoint (-100 = all shadow, +100 = all highlight)
  const balanceOffset = balance / 200; // -0.5 to 0.5

  for (let i = 0; i < data.length; i += 4) {
    const r = data[i];
    const g = data[i + 1];
    const b = data[i + 2];

    // Get luminance to determine shadow vs highlight
    const lum = getLuminance(r, g, b);

    // Calculate shadow and highlight weights with balance
    const midpoint = 0.5 + balanceOffset;
    let shadowWeight = 0;
    let highlightWeight = 0;

    if (lum < midpoint) {
      // Shadow region
      shadowWeight = 1 - (lum / midpoint);
    } else {
      // Highlight region
      highlightWeight = (lum - midpoint) / (1 - midpoint);
    }

    // Apply shadow tint
    const sr = r + (shadowRgb[0] - 128) * shadowWeight * shadowIntensity;
    const sg = g + (shadowRgb[1] - 128) * shadowWeight * shadowIntensity;
    const sb = b + (shadowRgb[2] - 128) * shadowWeight * shadowIntensity;

    // Apply highlight tint
    data[i] = Math.min(255, Math.max(0, sr + (highlightRgb[0] - 128) * highlightWeight * highlightIntensity));
    data[i + 1] = Math.min(255, Math.max(0, sg + (highlightRgb[1] - 128) * highlightWeight * highlightIntensity));
    data[i + 2] = Math.min(255, Math.max(0, sb + (highlightRgb[2] - 128) * highlightWeight * highlightIntensity));
  }

  return imageData;
}

/**
 * Apply gradient map / duotone effect
 * Maps image luminance to a two-color gradient
 */
export function applyGradientMap(
  imageData: ImageData,
  shadowColor: { r: number; g: number; b: number },
  highlightColor: { r: number; g: number; b: number },
  intensity: number = 100
): ImageData {
  const data = imageData.data;
  const blend = intensity / 100;

  for (let i = 0; i < data.length; i += 4) {
    const r = data[i];
    const g = data[i + 1];
    const b = data[i + 2];

    // Get luminance as the mapping value
    const lum = getLuminance(r, g, b);

    // Interpolate between shadow and highlight colors based on luminance
    const mappedR = shadowColor.r + (highlightColor.r - shadowColor.r) * lum;
    const mappedG = shadowColor.g + (highlightColor.g - shadowColor.g) * lum;
    const mappedB = shadowColor.b + (highlightColor.b - shadowColor.b) * lum;

    // Blend with original based on intensity
    data[i] = Math.round(r * (1 - blend) + mappedR * blend);
    data[i + 1] = Math.round(g * (1 - blend) + mappedG * blend);
    data[i + 2] = Math.round(b * (1 - blend) + mappedB * blend);
  }

  return imageData;
}

/**
 * Apply color isolation effect ("Sin City" effect)
 * Keeps a selected hue range in color, desaturates everything else
 */
export function applyColorIsolation(
  imageData: ImageData,
  targetHue: number,        // 0-360
  hueRange: number,         // 0-180 degrees of hue to keep
  feather: number = 20      // 0-100 transition softness
): ImageData {
  const data = imageData.data;
  const featherDegrees = (feather / 100) * 60; // Max 60 degrees of feathering

  for (let i = 0; i < data.length; i += 4) {
    const r = data[i];
    const g = data[i + 1];
    const b = data[i + 2];

    // Convert to HSL (only need hue for color isolation)
    const [h] = rgbToHsl(r, g, b);

    // Calculate hue distance (wrapping around 360)
    let hueDiff = Math.abs(h - targetHue);
    if (hueDiff > 180) hueDiff = 360 - hueDiff;

    // Calculate saturation preservation factor
    let satFactor = 0;
    if (hueDiff <= hueRange) {
      // Fully within range - keep full saturation
      satFactor = 1;
    } else if (hueDiff <= hueRange + featherDegrees) {
      // In feather zone - gradual transition
      satFactor = 1 - (hueDiff - hueRange) / featherDegrees;
    }
    // else satFactor stays 0 - fully desaturate

    if (satFactor < 1) {
      // Apply partial or full desaturation
      const gray = 0.2126 * r + 0.7152 * g + 0.0722 * b;
      data[i] = Math.round(r * satFactor + gray * (1 - satFactor));
      data[i + 1] = Math.round(g * satFactor + gray * (1 - satFactor));
      data[i + 2] = Math.round(b * satFactor + gray * (1 - satFactor));
    }
  }

  return imageData;
}
