/**
 * Apply a box blur to an image region
 */
export function applyBoxBlur(
  imageData: ImageData,
  radius: number
): ImageData {
  const { width, height, data } = imageData;
  const result = new ImageData(width, height);
  const resultData = result.data;

  // Copy alpha channel
  for (let i = 3; i < data.length; i += 4) {
    resultData[i] = data[i];
  }

  // Horizontal pass
  const temp = new Uint8ClampedArray(data.length);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      let r = 0, g = 0, b = 0;
      let count = 0;

      for (let kx = -radius; kx <= radius; kx++) {
        const sx = Math.min(Math.max(x + kx, 0), width - 1);
        const idx = (y * width + sx) * 4;
        r += data[idx];
        g += data[idx + 1];
        b += data[idx + 2];
        count++;
      }

      const idx = (y * width + x) * 4;
      temp[idx] = r / count;
      temp[idx + 1] = g / count;
      temp[idx + 2] = b / count;
      temp[idx + 3] = data[idx + 3];
    }
  }

  // Vertical pass
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      let r = 0, g = 0, b = 0;
      let count = 0;

      for (let ky = -radius; ky <= radius; ky++) {
        const sy = Math.min(Math.max(y + ky, 0), height - 1);
        const idx = (sy * width + x) * 4;
        r += temp[idx];
        g += temp[idx + 1];
        b += temp[idx + 2];
        count++;
      }

      const idx = (y * width + x) * 4;
      resultData[idx] = r / count;
      resultData[idx + 1] = g / count;
      resultData[idx + 2] = b / count;
      resultData[idx + 3] = data[idx + 3];
    }
  }

  return result;
}

/**
 * Apply unsharp mask (sharpening) to an image region
 */
export function applyUnsharpMask(
  imageData: ImageData,
  amount: number, // 0-100
  radius: number = 1
): ImageData {
  const { width, height, data } = imageData;
  const result = new ImageData(width, height);
  const resultData = result.data;

  // First, create a blurred version
  const blurred = applyBoxBlur(imageData, radius);
  const blurredData = blurred.data;

  // Amount as a multiplier (0-2)
  const strength = amount / 50;

  for (let i = 0; i < data.length; i += 4) {
    // Unsharp mask: original + (original - blurred) * amount
    resultData[i] = Math.min(255, Math.max(0,
      data[i] + (data[i] - blurredData[i]) * strength
    ));
    resultData[i + 1] = Math.min(255, Math.max(0,
      data[i + 1] + (data[i + 1] - blurredData[i + 1]) * strength
    ));
    resultData[i + 2] = Math.min(255, Math.max(0,
      data[i + 2] + (data[i + 2] - blurredData[i + 2]) * strength
    ));
    resultData[i + 3] = data[i + 3];
  }

  return result;
}

/**
 * Apply blur to a circular brush region on a canvas
 */
export function applyLocalBlur(
  ctx: CanvasRenderingContext2D,
  centerX: number,
  centerY: number,
  brushSize: number,
  brushMask: ImageData,
  blurRadius: number
): void {
  const halfSize = brushSize / 2;
  const x = Math.max(0, Math.floor(centerX - halfSize));
  const y = Math.max(0, Math.floor(centerY - halfSize));
  const size = brushSize;

  // Get the region
  const region = ctx.getImageData(x, y, size, size);
  const originalData = new Uint8ClampedArray(region.data);

  // Apply blur
  const blurred = applyBoxBlur(region, blurRadius);

  // Blend with brush mask
  const maskData = brushMask.data;
  const resultData = region.data;
  const blurredData = blurred.data;

  for (let i = 0; i < maskData.length; i += 4) {
    const maskAlpha = maskData[i + 3] / 255;
    if (maskAlpha > 0) {
      resultData[i] = originalData[i] * (1 - maskAlpha) + blurredData[i] * maskAlpha;
      resultData[i + 1] = originalData[i + 1] * (1 - maskAlpha) + blurredData[i + 1] * maskAlpha;
      resultData[i + 2] = originalData[i + 2] * (1 - maskAlpha) + blurredData[i + 2] * maskAlpha;
    }
  }

  ctx.putImageData(region, x, y);
}

/**
 * Apply sharpen to a circular brush region on a canvas
 */
export function applyLocalSharpen(
  ctx: CanvasRenderingContext2D,
  centerX: number,
  centerY: number,
  brushSize: number,
  brushMask: ImageData,
  amount: number
): void {
  const halfSize = brushSize / 2;
  const x = Math.max(0, Math.floor(centerX - halfSize));
  const y = Math.max(0, Math.floor(centerY - halfSize));
  const size = brushSize;

  // Get the region
  const region = ctx.getImageData(x, y, size, size);
  const originalData = new Uint8ClampedArray(region.data);

  // Apply sharpen
  const sharpened = applyUnsharpMask(region, amount);

  // Blend with brush mask
  const maskData = brushMask.data;
  const resultData = region.data;
  const sharpenedData = sharpened.data;

  for (let i = 0; i < maskData.length; i += 4) {
    const maskAlpha = maskData[i + 3] / 255;
    if (maskAlpha > 0) {
      resultData[i] = originalData[i] * (1 - maskAlpha) + sharpenedData[i] * maskAlpha;
      resultData[i + 1] = originalData[i + 1] * (1 - maskAlpha) + sharpenedData[i + 1] * maskAlpha;
      resultData[i + 2] = originalData[i + 2] * (1 - maskAlpha) + sharpenedData[i + 2] * maskAlpha;
    }
  }

  ctx.putImageData(region, x, y);
}
