/**
 * Spatial effects utilities for image processing
 */

import { createCanvas, getContext } from './canvas';

export interface EffectsState {
  blur: number;
  sharpen: number;
  noise: number;
  glow: number;
  pixelate: number;
  chromaticAberration: number;
  motionBlur: number;
  motionBlurAngle: number;
  vignette: number;
  clarity: number;
  // Creative effects
  halftone: number;
  halftoneAngle: number;
  vhs: number;
  glitch: number;
  glitchBlockSize: number;
  ditherEnabled: boolean;
  ditherPalette: 'bw' | '4bit' | '8bit' | 'gameboy' | 'cga';
}

/**
 * Check if any effects need to be applied
 */
export function hasEffects(state: Partial<EffectsState>): boolean {
  return (
    (state.blur ?? 0) > 0 ||
    (state.sharpen ?? 0) > 0 ||
    (state.noise ?? 0) > 0 ||
    (state.glow ?? 0) > 0 ||
    (state.pixelate ?? 0) > 0 ||
    (state.chromaticAberration ?? 0) > 0 ||
    (state.motionBlur ?? 0) > 0 ||
    (state.vignette ?? 0) > 0 ||
    (state.clarity ?? 0) > 0 ||
    (state.halftone ?? 0) > 0 ||
    (state.vhs ?? 0) > 0 ||
    (state.glitch ?? 0) > 0 ||
    (state.ditherEnabled ?? false)
  );
}

/**
 * Apply all effects to a canvas
 */
export function applyEffects(
  canvas: HTMLCanvasElement,
  state: Partial<EffectsState>
): HTMLCanvasElement {
  let currentCanvas = canvas;

  // Apply effects in order that makes visual sense

  // 1. Pixelate (early - affects everything after)
  if ((state.pixelate ?? 0) > 0) {
    currentCanvas = applyPixelate(currentCanvas, state.pixelate!);
  }

  // 2. Clarity (local contrast - before blur effects)
  if ((state.clarity ?? 0) !== 0) {
    currentCanvas = applyClarity(currentCanvas, state.clarity!);
  }

  // 3. Sharpen (before blur so they can be combined)
  if ((state.sharpen ?? 0) > 0) {
    currentCanvas = applySharpen(currentCanvas, state.sharpen!);
  }

  // 4. Blur effects
  if ((state.blur ?? 0) > 0) {
    currentCanvas = applyBlur(currentCanvas, state.blur!);
  }

  if ((state.motionBlur ?? 0) > 0) {
    currentCanvas = applyMotionBlur(currentCanvas, state.motionBlur!, state.motionBlurAngle ?? 0);
  }

  // 5. Glow (after main blur)
  if ((state.glow ?? 0) > 0) {
    currentCanvas = applyGlow(currentCanvas, state.glow!);
  }

  // 6. Chromatic aberration (color effect)
  if ((state.chromaticAberration ?? 0) > 0) {
    currentCanvas = applyChromaticAberration(currentCanvas, state.chromaticAberration!);
  }

  // 7. Noise (late - should be on top)
  if ((state.noise ?? 0) > 0) {
    currentCanvas = applyNoise(currentCanvas, state.noise!);
  }

  // 8. Vignette (last - frames the image)
  if ((state.vignette ?? 0) > 0) {
    currentCanvas = applyVignette(currentCanvas, state.vignette!);
  }

  // 9. Halftone
  if ((state.halftone ?? 0) > 0) {
    currentCanvas = applyHalftone(currentCanvas, state.halftone!, state.halftoneAngle ?? 0);
  }

  // 10. VHS / Analog
  if ((state.vhs ?? 0) > 0) {
    currentCanvas = applyVHS(currentCanvas, state.vhs!);
  }

  // 11. Glitch
  if ((state.glitch ?? 0) > 0) {
    currentCanvas = applyGlitch(currentCanvas, state.glitch!, state.glitchBlockSize ?? 16);
  }

  // 12. Dither (last - affects final color palette)
  if (state.ditherEnabled) {
    currentCanvas = applyDither(currentCanvas, state.ditherPalette ?? '8bit');
  }

  return currentCanvas;
}

/**
 * Apply Gaussian blur using canvas filter
 */
export function applyBlur(canvas: HTMLCanvasElement, amount: number): HTMLCanvasElement {
  const width = canvas.width;
  const height = canvas.height;
  const result = createCanvas(width, height);
  const ctx = getContext(result);

  ctx.filter = `blur(${amount}px)`;
  ctx.drawImage(canvas, 0, 0);

  return result;
}

/**
 * Apply sharpening using unsharp mask technique
 */
export function applySharpen(canvas: HTMLCanvasElement, amount: number): HTMLCanvasElement {
  const width = canvas.width;
  const height = canvas.height;
  const result = createCanvas(width, height);
  const ctx = getContext(result);

  // Draw original
  ctx.drawImage(canvas, 0, 0);

  // Create blurred version
  const blurred = createCanvas(width, height);
  const blurCtx = getContext(blurred);
  blurCtx.filter = 'blur(1px)';
  blurCtx.drawImage(canvas, 0, 0);

  // Get image data
  const originalData = ctx.getImageData(0, 0, width, height);
  const blurredData = blurCtx.getImageData(0, 0, width, height);
  const resultData = ctx.getImageData(0, 0, width, height);

  const strength = amount / 50; // Normalize to reasonable range

  for (let i = 0; i < originalData.data.length; i += 4) {
    // Unsharp mask: original + (original - blurred) * amount
    for (let c = 0; c < 3; c++) {
      const diff = originalData.data[i + c] - blurredData.data[i + c];
      resultData.data[i + c] = Math.max(0, Math.min(255, originalData.data[i + c] + diff * strength));
    }
  }

  ctx.putImageData(resultData, 0, 0);
  return result;
}

/**
 * Apply film grain/noise effect
 */
export function applyNoise(canvas: HTMLCanvasElement, amount: number): HTMLCanvasElement {
  const width = canvas.width;
  const height = canvas.height;
  const result = createCanvas(width, height);
  const ctx = getContext(result);

  ctx.drawImage(canvas, 0, 0);

  const imageData = ctx.getImageData(0, 0, width, height);
  const data = imageData.data;

  const intensity = amount * 2.55; // Scale to 0-255 range

  for (let i = 0; i < data.length; i += 4) {
    const noise = (Math.random() - 0.5) * intensity;
    data[i] = Math.max(0, Math.min(255, data[i] + noise));
    data[i + 1] = Math.max(0, Math.min(255, data[i + 1] + noise));
    data[i + 2] = Math.max(0, Math.min(255, data[i + 2] + noise));
  }

  ctx.putImageData(imageData, 0, 0);
  return result;
}

/**
 * Apply glow/bloom effect
 */
export function applyGlow(canvas: HTMLCanvasElement, amount: number): HTMLCanvasElement {
  const width = canvas.width;
  const height = canvas.height;
  const result = createCanvas(width, height);
  const ctx = getContext(result);

  // Draw original
  ctx.drawImage(canvas, 0, 0);

  // Create bright pass + blur for glow
  const glowCanvas = createCanvas(width, height);
  const glowCtx = getContext(glowCanvas);

  // Extract and blur bright areas
  glowCtx.filter = `blur(${amount * 2}px) brightness(1.5)`;
  glowCtx.drawImage(canvas, 0, 0);

  // Blend glow on top with screen/additive-like effect
  ctx.globalCompositeOperation = 'screen';
  ctx.globalAlpha = amount / 100;
  ctx.drawImage(glowCanvas, 0, 0);
  ctx.globalCompositeOperation = 'source-over';
  ctx.globalAlpha = 1;

  return result;
}

/**
 * Apply pixelate/mosaic effect
 */
export function applyPixelate(canvas: HTMLCanvasElement, amount: number): HTMLCanvasElement {
  const width = canvas.width;
  const height = canvas.height;

  // Pixel size based on amount (2-50 pixels)
  const pixelSize = Math.max(2, Math.floor(amount / 2));

  const smallWidth = Math.max(1, Math.floor(width / pixelSize));
  const smallHeight = Math.max(1, Math.floor(height / pixelSize));

  // Scale down
  const small = createCanvas(smallWidth, smallHeight);
  const smallCtx = getContext(small);
  smallCtx.imageSmoothingEnabled = false;
  smallCtx.drawImage(canvas, 0, 0, smallWidth, smallHeight);

  // Scale back up with no smoothing
  const result = createCanvas(width, height);
  const ctx = getContext(result);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(small, 0, 0, width, height);

  return result;
}

/**
 * Apply chromatic aberration (RGB channel offset)
 */
export function applyChromaticAberration(canvas: HTMLCanvasElement, amount: number): HTMLCanvasElement {
  const width = canvas.width;
  const height = canvas.height;
  const result = createCanvas(width, height);
  const ctx = getContext(result);

  const sourceCtx = canvas.getContext('2d')!;
  const sourceData = sourceCtx.getImageData(0, 0, width, height);
  const resultData = ctx.createImageData(width, height);

  const offset = Math.floor(amount / 5); // Offset in pixels

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;

      // Red channel - offset left
      const rxSrc = Math.max(0, Math.min(width - 1, x - offset));
      const ri = (y * width + rxSrc) * 4;
      resultData.data[i] = sourceData.data[ri];

      // Green channel - no offset
      resultData.data[i + 1] = sourceData.data[i + 1];

      // Blue channel - offset right
      const bxSrc = Math.max(0, Math.min(width - 1, x + offset));
      const bi = (y * width + bxSrc) * 4;
      resultData.data[i + 2] = sourceData.data[bi + 2];

      // Alpha - average or use original
      resultData.data[i + 3] = sourceData.data[i + 3];
    }
  }

  ctx.putImageData(resultData, 0, 0);
  return result;
}

/**
 * Apply directional motion blur
 */
export function applyMotionBlur(canvas: HTMLCanvasElement, amount: number, angle: number): HTMLCanvasElement {
  const width = canvas.width;
  const height = canvas.height;
  const result = createCanvas(width, height);
  const ctx = getContext(result);

  // Convert angle to radians (-180 to 180 -> -PI to PI)
  const radians = (angle * Math.PI) / 180;
  const dx = Math.cos(radians);
  const dy = Math.sin(radians);

  // Number of samples based on amount
  const samples = Math.max(3, Math.floor(amount / 3));
  const maxOffset = amount / 2;

  ctx.globalAlpha = 1 / samples;

  for (let i = 0; i < samples; i++) {
    const t = (i / (samples - 1)) - 0.5; // -0.5 to 0.5
    const offsetX = dx * t * maxOffset * 2;
    const offsetY = dy * t * maxOffset * 2;
    ctx.drawImage(canvas, offsetX, offsetY);
  }

  ctx.globalAlpha = 1;

  return result;
}

/**
 * Apply vignette effect (darken edges)
 */
export function applyVignette(canvas: HTMLCanvasElement, amount: number): HTMLCanvasElement {
  const width = canvas.width;
  const height = canvas.height;
  const result = createCanvas(width, height);
  const ctx = getContext(result);

  ctx.drawImage(canvas, 0, 0);

  // Create radial gradient for vignette
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.sqrt(centerX * centerX + centerY * centerY);

  const gradient = ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, radius);

  // Inner area is transparent, outer is dark
  const strength = amount / 100;
  gradient.addColorStop(0, 'rgba(0,0,0,0)');
  gradient.addColorStop(0.5, 'rgba(0,0,0,0)');
  gradient.addColorStop(1, `rgba(0,0,0,${strength})`);

  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);

  return result;
}

/**
 * Apply clarity (local contrast enhancement)
 */
export function applyClarity(canvas: HTMLCanvasElement, amount: number): HTMLCanvasElement {
  const width = canvas.width;
  const height = canvas.height;
  const result = createCanvas(width, height);
  const ctx = getContext(result);

  // Draw original
  ctx.drawImage(canvas, 0, 0);

  // Create heavily blurred version (low frequency)
  const blurred = createCanvas(width, height);
  const blurCtx = getContext(blurred);
  blurCtx.filter = 'blur(20px)';
  blurCtx.drawImage(canvas, 0, 0);

  // Get image data
  const originalData = ctx.getImageData(0, 0, width, height);
  const blurredData = blurCtx.getImageData(0, 0, width, height);

  const strength = amount / 100;

  for (let i = 0; i < originalData.data.length; i += 4) {
    for (let c = 0; c < 3; c++) {
      // High-pass: original - blurred (local details)
      // Add back to original weighted by strength
      const highPass = originalData.data[i + c] - blurredData.data[i + c];
      originalData.data[i + c] = Math.max(0, Math.min(255,
        originalData.data[i + c] + highPass * strength
      ));
    }
  }

  ctx.putImageData(originalData, 0, 0);
  return result;
}

/**
 * Apply halftone effect (CMYK-style dot pattern)
 */
export function applyHalftone(canvas: HTMLCanvasElement, amount: number, angle: number = 0): HTMLCanvasElement {
  const width = canvas.width;
  const height = canvas.height;
  const result = createCanvas(width, height);
  const ctx = getContext(result);

  const sourceCtx = canvas.getContext('2d')!;
  const sourceData = sourceCtx.getImageData(0, 0, width, height);

  // Dot size based on amount (2-20 pixels)
  const dotSize = Math.max(2, Math.floor(2 + (amount / 100) * 18));
  const halfDot = dotSize / 2;

  // Angle in radians
  const rad = (angle * Math.PI) / 180;
  const cos = Math.cos(rad);
  const sin = Math.sin(rad);

  // Fill with white background
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, width, height);

  // Process in grid cells
  for (let y = -dotSize; y < height + dotSize; y += dotSize) {
    for (let x = -dotSize; x < width + dotSize; x += dotSize) {
      // Apply rotation to get sample position
      const cx = x + halfDot;
      const cy = y + halfDot;

      // Rotate coordinates
      const rx = Math.floor(cos * (cx - width/2) - sin * (cy - height/2) + width/2);
      const ry = Math.floor(sin * (cx - width/2) + cos * (cy - height/2) + height/2);

      // Sample the source image
      if (rx >= 0 && rx < width && ry >= 0 && ry < height) {
        const i = (ry * width + rx) * 4;
        const r = sourceData.data[i];
        const g = sourceData.data[i + 1];
        const b = sourceData.data[i + 2];

        // Calculate luminance
        const lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;

        // Dot radius based on darkness (darker = bigger dot)
        const radius = halfDot * (1 - lum) * 0.9;

        if (radius > 0.5) {
          ctx.beginPath();
          ctx.arc(cx, cy, radius, 0, Math.PI * 2);
          ctx.fillStyle = `rgb(${r}, ${g}, ${b})`;
          ctx.fill();
        }
      }
    }
  }

  return result;
}

/**
 * Apply VHS / Analog effect
 * Includes horizontal distortion, color bleed, and tracking lines
 */
export function applyVHS(canvas: HTMLCanvasElement, amount: number): HTMLCanvasElement {
  const width = canvas.width;
  const height = canvas.height;
  const result = createCanvas(width, height);
  const ctx = getContext(result);

  const sourceCtx = canvas.getContext('2d')!;
  const sourceData = sourceCtx.getImageData(0, 0, width, height);
  const resultData = ctx.createImageData(width, height);

  const intensity = amount / 100;

  // Pre-calculate random seeds for consistent noise
  const scanlineNoise: number[] = [];
  for (let y = 0; y < height; y++) {
    scanlineNoise[y] = (Math.random() - 0.5) * 2;
  }

  for (let y = 0; y < height; y++) {
    // Horizontal distortion (wobble)
    const wobble = Math.sin(y * 0.1 + Math.random() * 0.5) * intensity * 5;
    const jitter = scanlineNoise[y] * intensity * 3;

    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;

      // Apply horizontal offset with wobble
      const srcX = Math.floor(x + wobble + jitter);
      const clampedX = Math.max(0, Math.min(width - 1, srcX));

      // Color channel separation (chromatic aberration style)
      const redOffset = Math.floor(intensity * 4);
      const blueOffset = -Math.floor(intensity * 4);

      const srcR = Math.max(0, Math.min(width - 1, clampedX + redOffset));
      const srcB = Math.max(0, Math.min(width - 1, clampedX + blueOffset));

      const iR = (y * width + srcR) * 4;
      const iG = (y * width + clampedX) * 4;
      const iB = (y * width + srcB) * 4;

      resultData.data[i] = sourceData.data[iR];
      resultData.data[i + 1] = sourceData.data[iG + 1];
      resultData.data[i + 2] = sourceData.data[iB + 2];
      resultData.data[i + 3] = 255;
    }
  }

  ctx.putImageData(resultData, 0, 0);

  // Add scanlines
  ctx.globalAlpha = intensity * 0.3;
  for (let y = 0; y < height; y += 2) {
    ctx.fillStyle = 'rgba(0, 0, 0, 0.3)';
    ctx.fillRect(0, y, width, 1);
  }

  // Add random tracking glitches
  ctx.globalAlpha = intensity * 0.5;
  const numGlitches = Math.floor(intensity * 5);
  for (let i = 0; i < numGlitches; i++) {
    const glitchY = Math.floor(Math.random() * height);
    const glitchHeight = Math.floor(Math.random() * 10 + 2);
    ctx.fillStyle = 'rgba(255, 255, 255, 0.5)';
    ctx.fillRect(0, glitchY, width, glitchHeight);
  }

  ctx.globalAlpha = 1;

  // Add slight blur for tape degradation effect
  if (intensity > 0.3) {
    const blurred = createCanvas(width, height);
    const blurCtx = getContext(blurred);
    blurCtx.filter = `blur(${intensity * 0.5}px)`;
    blurCtx.drawImage(result, 0, 0);
    ctx.globalAlpha = intensity * 0.3;
    ctx.drawImage(blurred, 0, 0);
    ctx.globalAlpha = 1;
  }

  return result;
}

/**
 * Apply glitch effect
 * Random RGB channel displacement in blocks
 */
export function applyGlitch(canvas: HTMLCanvasElement, amount: number, blockSize: number = 16): HTMLCanvasElement {
  const width = canvas.width;
  const height = canvas.height;
  const result = createCanvas(width, height);
  const ctx = getContext(result);

  // Draw original first
  ctx.drawImage(canvas, 0, 0);

  const sourceCtx = canvas.getContext('2d')!;
  const sourceData = sourceCtx.getImageData(0, 0, width, height);
  const resultData = ctx.getImageData(0, 0, width, height);

  const intensity = amount / 100;
  const numBlocks = Math.floor(intensity * 20) + 1;

  // Create glitch blocks
  for (let b = 0; b < numBlocks; b++) {
    // Random block position and size
    const blockY = Math.floor(Math.random() * height);
    const blockHeight = Math.floor(Math.random() * blockSize * 2) + blockSize;
    const blockWidth = Math.floor(Math.random() * (width * 0.8)) + width * 0.2;
    const blockX = Math.floor(Math.random() * (width - blockWidth));

    // Random channel offsets
    const rOffset = Math.floor((Math.random() - 0.5) * intensity * 30);
    const gOffset = Math.floor((Math.random() - 0.5) * intensity * 30);
    const bOffset = Math.floor((Math.random() - 0.5) * intensity * 30);

    // Apply to block
    for (let y = blockY; y < Math.min(blockY + blockHeight, height); y++) {
      for (let x = blockX; x < Math.min(blockX + blockWidth, width); x++) {
        const i = (y * width + x) * 4;

        // Get offset source positions
        const srcR = Math.max(0, Math.min(width - 1, x + rOffset));
        const srcG = Math.max(0, Math.min(width - 1, x + gOffset));
        const srcB = Math.max(0, Math.min(width - 1, x + bOffset));

        const iR = (y * width + srcR) * 4;
        const iG = (y * width + srcG) * 4;
        const iB = (y * width + srcB) * 4;

        resultData.data[i] = sourceData.data[iR];
        resultData.data[i + 1] = sourceData.data[iG + 1];
        resultData.data[i + 2] = sourceData.data[iB + 2];
      }
    }
  }

  // Add some horizontal line shifts
  const numShifts = Math.floor(intensity * 10);
  for (let s = 0; s < numShifts; s++) {
    const shiftY = Math.floor(Math.random() * height);
    const shiftHeight = Math.floor(Math.random() * 5) + 1;
    const shiftAmount = Math.floor((Math.random() - 0.5) * intensity * 50);

    for (let y = shiftY; y < Math.min(shiftY + shiftHeight, height); y++) {
      for (let x = 0; x < width; x++) {
        const destI = (y * width + x) * 4;
        const srcX = Math.max(0, Math.min(width - 1, x + shiftAmount));
        const srcI = (y * width + srcX) * 4;

        resultData.data[destI] = sourceData.data[srcI];
        resultData.data[destI + 1] = sourceData.data[srcI + 1];
        resultData.data[destI + 2] = sourceData.data[srcI + 2];
      }
    }
  }

  ctx.putImageData(resultData, 0, 0);
  return result;
}

/**
 * Color palettes for dithering
 */
const DITHER_PALETTES: Record<string, number[][]> = {
  bw: [
    [0, 0, 0],
    [255, 255, 255],
  ],
  gameboy: [
    [15, 56, 15],
    [48, 98, 48],
    [139, 172, 15],
    [155, 188, 15],
  ],
  cga: [
    [0, 0, 0],
    [0, 170, 170],
    [170, 0, 170],
    [170, 170, 170],
  ],
  '4bit': [
    [0, 0, 0],
    [128, 0, 0],
    [0, 128, 0],
    [128, 128, 0],
    [0, 0, 128],
    [128, 0, 128],
    [0, 128, 128],
    [192, 192, 192],
    [128, 128, 128],
    [255, 0, 0],
    [0, 255, 0],
    [255, 255, 0],
    [0, 0, 255],
    [255, 0, 255],
    [0, 255, 255],
    [255, 255, 255],
  ],
  '8bit': (() => {
    // Generate 256-color palette (6x6x6 color cube + grayscale)
    const palette: number[][] = [];
    // 6x6x6 color cube
    for (let r = 0; r < 6; r++) {
      for (let g = 0; g < 6; g++) {
        for (let b = 0; b < 6; b++) {
          palette.push([r * 51, g * 51, b * 51]);
        }
      }
    }
    // Grayscale ramp
    for (let i = 0; i < 24; i++) {
      const v = Math.round(i * 10.625);
      palette.push([v, v, v]);
    }
    return palette;
  })(),
};

/**
 * Find closest color in palette
 */
function findClosestColor(r: number, g: number, b: number, palette: number[][]): number[] {
  let minDist = Infinity;
  let closest = palette[0];

  for (const color of palette) {
    const dr = r - color[0];
    const dg = g - color[1];
    const db = b - color[2];
    const dist = dr * dr + dg * dg + db * db;

    if (dist < minDist) {
      minDist = dist;
      closest = color;
    }
  }

  return closest;
}

/**
 * Apply dithering effect (Floyd-Steinberg)
 */
export function applyDither(
  canvas: HTMLCanvasElement,
  paletteType: 'bw' | '4bit' | '8bit' | 'gameboy' | 'cga'
): HTMLCanvasElement {
  const width = canvas.width;
  const height = canvas.height;
  const result = createCanvas(width, height);
  const ctx = getContext(result);

  ctx.drawImage(canvas, 0, 0);
  const imageData = ctx.getImageData(0, 0, width, height);
  const data = imageData.data;

  const palette = DITHER_PALETTES[paletteType] || DITHER_PALETTES['8bit'];

  // Create a copy of the data for error diffusion
  const pixels: number[][] = [];
  for (let y = 0; y < height; y++) {
    pixels[y] = [];
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      pixels[y][x * 3] = data[i];
      pixels[y][x * 3 + 1] = data[i + 1];
      pixels[y][x * 3 + 2] = data[i + 2];
    }
  }

  // Floyd-Steinberg dithering
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const oldR = pixels[y][x * 3];
      const oldG = pixels[y][x * 3 + 1];
      const oldB = pixels[y][x * 3 + 2];

      // Find closest palette color
      const newColor = findClosestColor(oldR, oldG, oldB, palette);

      // Set the new color
      const i = (y * width + x) * 4;
      data[i] = newColor[0];
      data[i + 1] = newColor[1];
      data[i + 2] = newColor[2];

      // Calculate quantization error
      const errR = oldR - newColor[0];
      const errG = oldG - newColor[1];
      const errB = oldB - newColor[2];

      // Distribute error to neighboring pixels
      // Right: 7/16
      if (x + 1 < width) {
        pixels[y][(x + 1) * 3] += errR * 7 / 16;
        pixels[y][(x + 1) * 3 + 1] += errG * 7 / 16;
        pixels[y][(x + 1) * 3 + 2] += errB * 7 / 16;
      }
      // Bottom-left: 3/16
      if (y + 1 < height && x - 1 >= 0) {
        pixels[y + 1][(x - 1) * 3] += errR * 3 / 16;
        pixels[y + 1][(x - 1) * 3 + 1] += errG * 3 / 16;
        pixels[y + 1][(x - 1) * 3 + 2] += errB * 3 / 16;
      }
      // Bottom: 5/16
      if (y + 1 < height) {
        pixels[y + 1][x * 3] += errR * 5 / 16;
        pixels[y + 1][x * 3 + 1] += errG * 5 / 16;
        pixels[y + 1][x * 3 + 2] += errB * 5 / 16;
      }
      // Bottom-right: 1/16
      if (y + 1 < height && x + 1 < width) {
        pixels[y + 1][(x + 1) * 3] += errR * 1 / 16;
        pixels[y + 1][(x + 1) * 3 + 1] += errG * 1 / 16;
        pixels[y + 1][(x + 1) * 3 + 2] += errB * 1 / 16;
      }
    }
  }

  ctx.putImageData(imageData, 0, 0);
  return result;
}
