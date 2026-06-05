import { ref } from 'vue';
import type {
  EditorState,
  ExportOptions,
  ProcessProgress,
  ProcessResult,
} from '@/types';
import { DEFAULT_EXPORT_OPTIONS, FILTER_MATRICES } from '@/constants';
import { createCanvas, getContext } from '@/utils/canvas';
import { canvasToBlob } from '@/utils/image';
import { combineAdjustments, applyColorMatrix, multiplyColorMatrices, applySplitToning, applyGradientMap, applyColorIsolation } from '@/utils/colorMatrix';
import { renderShapes } from '@/utils/shapes';
import { hasEffects, applyEffects } from '@/utils/effects';

/**
 * Image writer/exporter composable
 */
export function useImageWriter() {
  const isProcessing = ref(false);
  const progress = ref<ProcessProgress>({ stage: '', progress: 0 });
  const error = ref<Error | null>(null);

  /**
   * Process and export the edited image
   */
  async function process(
    state: EditorState,
    sourceImage: HTMLImageElement,
    options: Partial<ExportOptions> = {},
    retouchCanvas?: HTMLCanvasElement | null
  ): Promise<ProcessResult> {
    const opts = { ...DEFAULT_EXPORT_OPTIONS, ...options };

    isProcessing.value = true;
    error.value = null;
    progress.value = { stage: 'Preparing', progress: 0 };

    try {
      const imageSize = state.imageSize;
      if (!imageSize) {
        throw new Error('No image loaded');
      }

      // Calculate output size
      let outputWidth = imageSize.width;
      let outputHeight = imageSize.height;

      // Apply crop
      const crop = state.crop;
      const cropRotation = crop.rotation ?? 0;
      outputWidth = Math.round(imageSize.width * crop.width);
      outputHeight = Math.round(imageSize.height * crop.height);

      // Apply target size if specified
      if (state.targetSize) {
        outputWidth = state.targetSize.width;
        outputHeight = state.targetSize.height;
      }

      // Apply max constraints
      if (opts.maxWidth && outputWidth > opts.maxWidth) {
        const scale = opts.maxWidth / outputWidth;
        outputWidth = opts.maxWidth;
        outputHeight = Math.round(outputHeight * scale);
      }
      if (opts.maxHeight && outputHeight > opts.maxHeight) {
        const scale = opts.maxHeight / outputHeight;
        outputHeight = opts.maxHeight;
        outputWidth = Math.round(outputWidth * scale);
      }

      progress.value = { stage: 'Creating canvas', progress: 10 };

      // Create output canvas
      const canvas = createCanvas(outputWidth, outputHeight);
      const ctx = getContext(canvas);

      // Fill background if needed (for JPEG)
      if (opts.format === 'image/jpeg' && opts.backgroundColor) {
        ctx.fillStyle = opts.backgroundColor;
        ctx.fillRect(0, 0, outputWidth, outputHeight);
      }

      progress.value = { stage: 'Applying transforms', progress: 20 };

      // Calculate crop center and dimensions in pixels
      const cropCenterX = crop.x * imageSize.width;
      const cropCenterY = crop.y * imageSize.height;
      const cropWidth = crop.width * imageSize.width;
      const cropHeight = crop.height * imageSize.height;

      // Save context state
      ctx.save();

      // Apply transforms - center output
      ctx.translate(outputWidth / 2, outputHeight / 2);

      // Apply image rotation (fine + 90° increments)
      const totalRotation = state.rotation + (state.rotation90 * Math.PI) / 2;
      if (totalRotation !== 0) {
        ctx.rotate(totalRotation);
      }

      // Apply flip
      const scaleX = state.flipX ? -1 : 1;
      const scaleY = state.flipY ? -1 : 1;
      if (state.flipX || state.flipY) {
        ctx.scale(scaleX, scaleY);
      }

      // Handle dimension swap for 90° rotations
      let drawWidth = outputWidth;
      let drawHeight = outputHeight;
      if (state.rotation90 === 1 || state.rotation90 === 3) {
        drawWidth = outputHeight;
        drawHeight = outputWidth;
      }

      // Now we need to draw the image with crop rotation applied
      // The crop rotation rotates around the crop center
      if (cropRotation !== 0) {
        // Translate so crop center is at origin (in the draw coordinate space)
        // Then rotate by -cropRotation to straighten the crop region
        // Then translate back

        // First, we're currently at output center
        // We want to rotate the image around the crop center
        // The crop center relative to image top-left is (cropCenterX, cropCenterY)
        // In draw space (centered on output), crop center is at:
        //   (cropCenterX - imageSize.width/2, cropCenterY - imageSize.height/2)
        // But we're drawing a cropped portion, so the crop center should map to output center

        // Apply crop rotation around the crop center
        ctx.rotate(-cropRotation);

        // Translate so crop center aligns with output center, then draw
        ctx.translate(-cropCenterX, -cropCenterY);

        // Draw full source image
        ctx.drawImage(sourceImage, 0, 0);

        // Draw retouch layer too
        if (retouchCanvas) {
          ctx.drawImage(retouchCanvas, 0, 0);
        }
      } else {
        // No crop rotation - use original simpler logic
        const cropX = (crop.x - crop.width / 2) * imageSize.width;
        const cropY = (crop.y - crop.height / 2) * imageSize.height;

        // Draw image
        ctx.drawImage(
          sourceImage,
          cropX,
          cropY,
          cropWidth,
          cropHeight,
          -drawWidth / 2,
          -drawHeight / 2,
          drawWidth,
          drawHeight
        );

        // Draw retouch layer with same crop/transform (BEFORE color adjustments)
        if (retouchCanvas) {
          ctx.drawImage(
            retouchCanvas,
            cropX,
            cropY,
            cropWidth,
            cropHeight,
            -drawWidth / 2,
            -drawHeight / 2,
            drawWidth,
            drawHeight
          );
        }
      }

      ctx.restore();

      progress.value = { stage: 'Applying color adjustments', progress: 50 };

      // Apply color adjustments if any
      if (
        state.brightness !== 0 ||
        state.contrast !== 0 ||
        state.saturation !== 0 ||
        state.exposure !== 0 ||
        state.temperature !== 0 ||
        state.gamma !== 1
      ) {
        const matrix = combineAdjustments({
          brightness: state.brightness,
          contrast: state.contrast,
          saturation: state.saturation,
          exposure: state.exposure,
          temperature: state.temperature,
          gamma: state.gamma,
        });

        const imageData = ctx.getImageData(0, 0, outputWidth, outputHeight);
        applyColorMatrix(imageData, matrix);
        ctx.putImageData(imageData, 0, 0);
      }

      // Apply filter if selected
      if (state.filter && FILTER_MATRICES[state.filter]) {
        let matrix = combineAdjustments({
          brightness: 0,
          contrast: 0,
          saturation: 0,
          exposure: 0,
          temperature: 0,
          gamma: 1,
        });
        matrix = multiplyColorMatrices(FILTER_MATRICES[state.filter], matrix);
        const imageData = ctx.getImageData(0, 0, outputWidth, outputHeight);
        applyColorMatrix(imageData, matrix);
        ctx.putImageData(imageData, 0, 0);
      }

      // Apply additional color matrix filter if set
      if (state.colorMatrix) {
        const imageData = ctx.getImageData(0, 0, outputWidth, outputHeight);
        applyColorMatrix(imageData, state.colorMatrix);
        ctx.putImageData(imageData, 0, 0);
      }

      // Apply split toning
      if (state.splitToningEnabled) {
        const imageData = ctx.getImageData(0, 0, outputWidth, outputHeight);
        applySplitToning(
          imageData,
          state.splitToningShadowHue ?? 30,
          state.splitToningShadowSat ?? 0,
          state.splitToningHighlightHue ?? 200,
          state.splitToningHighlightSat ?? 0,
          state.splitToningBalance ?? 0
        );
        ctx.putImageData(imageData, 0, 0);
      }

      // Apply gradient map / duotone
      if (state.gradientMapEnabled && state.gradientMapShadowColor && state.gradientMapHighlightColor) {
        const imageData = ctx.getImageData(0, 0, outputWidth, outputHeight);
        applyGradientMap(
          imageData,
          state.gradientMapShadowColor,
          state.gradientMapHighlightColor,
          state.gradientMapIntensity ?? 100
        );
        ctx.putImageData(imageData, 0, 0);
      }

      // Apply color isolation
      if (state.colorIsolationEnabled) {
        const imageData = ctx.getImageData(0, 0, outputWidth, outputHeight);
        applyColorIsolation(
          imageData,
          state.colorIsolationHue ?? 0,
          state.colorIsolationRange ?? 30,
          state.colorIsolationFeather ?? 20
        );
        ctx.putImageData(imageData, 0, 0);
      }

      // Apply effects
      const effectsState = {
        blur: state.blur ?? 0,
        sharpen: state.sharpen ?? 0,
        noise: state.noise ?? 0,
        glow: state.glow ?? 0,
        pixelate: state.pixelate ?? 0,
        chromaticAberration: state.chromaticAberration ?? 0,
        motionBlur: state.motionBlur ?? 0,
        motionBlurAngle: state.motionBlurAngle ?? 0,
        vignette: state.vignette ?? 0,
        clarity: state.clarity ?? 0,
        // Creative effects
        halftone: state.halftone ?? 0,
        halftoneAngle: state.halftoneAngle ?? 0,
        vhs: state.vhs ?? 0,
        glitch: state.glitch ?? 0,
        glitchBlockSize: state.glitchBlockSize ?? 16,
        ditherEnabled: state.ditherEnabled ?? false,
        ditherPalette: (state.ditherPalette === 'none' ? '8bit' : state.ditherPalette) ?? '8bit',
      };

      if (hasEffects(effectsState)) {
        const effectsCanvas = applyEffects(canvas, effectsState);
        ctx.clearRect(0, 0, outputWidth, outputHeight);
        ctx.drawImage(effectsCanvas, 0, 0);
      }

      progress.value = { stage: 'Rendering annotations', progress: 70 };

      // Render annotations
      if (state.annotations && state.annotations.length > 0) {
        ctx.save();

        // Apply transforms to match the image orientation
        ctx.translate(outputWidth / 2, outputHeight / 2);
        if (totalRotation !== 0) {
          ctx.rotate(totalRotation);
        }
        ctx.scale(state.flipX ? -1 : 1, state.flipY ? -1 : 1);

        // Swap dimensions for 90° rotations
        if (state.rotation90 === 1 || state.rotation90 === 3) {
          ctx.translate(-outputHeight / 2, -outputWidth / 2);
        } else {
          ctx.translate(-outputWidth / 2, -outputHeight / 2);
        }

        // Render shapes in output space
        // Shapes are in normalized 0-1 coordinates, so we need to scale them
        const outputSize = {
          width: (state.rotation90 === 1 || state.rotation90 === 3) ? outputHeight : outputWidth,
          height: (state.rotation90 === 1 || state.rotation90 === 3) ? outputWidth : outputHeight,
        };

        // Adjust shape coordinates for crop
        const adjustedAnnotations = state.annotations.map(shape => {
          const adjusted = { ...shape };
          // Convert from image space (0-1) to cropped space
          if ('x' in adjusted) {
            adjusted.x = (adjusted.x - (crop.x - crop.width / 2)) / crop.width;
          }
          if ('y' in adjusted) {
            adjusted.y = (adjusted.y - (crop.y - crop.height / 2)) / crop.height;
          }
          if ('x1' in adjusted && 'y1' in adjusted && 'x2' in adjusted && 'y2' in adjusted) {
            (adjusted as any).x1 = ((adjusted as any).x1 - (crop.x - crop.width / 2)) / crop.width;
            (adjusted as any).y1 = ((adjusted as any).y1 - (crop.y - crop.height / 2)) / crop.height;
            (adjusted as any).x2 = ((adjusted as any).x2 - (crop.x - crop.width / 2)) / crop.width;
            (adjusted as any).y2 = ((adjusted as any).y2 - (crop.y - crop.height / 2)) / crop.height;
          }
          if ('width' in adjusted) {
            (adjusted as any).width = (adjusted as any).width / crop.width;
          }
          if ('height' in adjusted) {
            (adjusted as any).height = (adjusted as any).height / crop.height;
          }
          if ('rx' in adjusted && 'ry' in adjusted) {
            (adjusted as any).rx = (adjusted as any).rx / crop.width;
            (adjusted as any).ry = (adjusted as any).ry / crop.height;
          }
          if ('points' in adjusted && Array.isArray((adjusted as any).points)) {
            (adjusted as any).points = (adjusted as any).points.map((p: any) => ({
              x: (p.x - (crop.x - crop.width / 2)) / crop.width,
              y: (p.y - (crop.y - crop.height / 2)) / crop.height,
            }));
          }
          return adjusted;
        });

        // For redact shapes, we need to pass the current canvas state as the source
        // Make a snapshot of the canvas before rendering shapes (so redact can sample from it)
        const sourceForRedact = createCanvas(outputSize.width, outputSize.height);
        const sourceCtx = getContext(sourceForRedact);
        sourceCtx.drawImage(canvas, 0, 0);

        renderShapes(ctx, adjustedAnnotations as any, outputSize, sourceForRedact);

        ctx.restore();
      }

      progress.value = { stage: 'Encoding', progress: 80 };

      // Convert to blob
      const blob = await canvasToBlob(canvas, opts.format, opts.quality);

      progress.value = { stage: 'Complete', progress: 100 };
      isProcessing.value = false;

      return {
        dest: blob,
        imageSize: { width: outputWidth, height: outputHeight },
      };
    } catch (e) {
      const err = e instanceof Error ? e : new Error('Export failed');
      error.value = err;
      isProcessing.value = false;
      throw err;
    }
  }

  return {
    isProcessing,
    progress,
    error,
    process,
  };
}

export type ImageWriter = ReturnType<typeof useImageWriter>;
