import { ref, shallowRef } from 'vue';
import type { ImageSource, LoadProgress, LoadResult, Size } from '@/types';
import {
  loadImage,
  getImageSize,
  readExifOrientation,
  applyExifOrientation,
  createPreviewCanvas,
} from '@/utils/image';

/**
 * Image loader composable
 */
export function useImageLoader() {
  const isLoading = ref(false);
  const error = ref<Error | null>(null);
  const progress = ref<LoadProgress>({ loaded: 0, total: 0 });

  // Use shallowRef for image elements to avoid deep reactivity
  const sourceImage = shallowRef<HTMLImageElement | null>(null);
  const previewCanvas = shallowRef<HTMLCanvasElement | null>(null);
  const imageSize = ref<Size | null>(null);

  /**
   * Load an image from various sources
   */
  async function load(
    source: ImageSource,
    _onProgress?: (p: LoadProgress) => void
  ): Promise<LoadResult> {
    isLoading.value = true;
    error.value = null;
    progress.value = { loaded: 0, total: 0 };

    try {
      // Reset current image
      sourceImage.value = null;
      previewCanvas.value = null;
      imageSize.value = null;

      // Handle progress for URL-based sources
      if (typeof source === 'string' && !source.startsWith('data:')) {
        // Could add fetch with progress here for URLs
        // For now, just load directly
      }

      // Load the image
      const img = await loadImage(source);

      // Check for EXIF orientation if source is a File/Blob
      let orientation = 1;
      if (source instanceof File || source instanceof Blob) {
        orientation = await readExifOrientation(source);
      }

      // Apply EXIF orientation if needed
      let finalImage: HTMLImageElement | HTMLCanvasElement = img;
      if (orientation !== 1) {
        finalImage = applyExifOrientation(img, orientation);
      }

      // Get final size
      const size = getImageSize(finalImage);
      imageSize.value = size;

      // Store source image
      if (finalImage instanceof HTMLImageElement) {
        sourceImage.value = finalImage;
      } else {
        // If we had to apply EXIF, create an image from the canvas
        const newImg = new Image();
        await new Promise<void>((resolve, reject) => {
          newImg.onload = () => resolve();
          newImg.onerror = reject;
          newImg.src = finalImage.toDataURL();
        });
        sourceImage.value = newImg;
      }

      // Create preview canvas for rendering
      previewCanvas.value = createPreviewCanvas(
        sourceImage.value as HTMLImageElement
      );

      isLoading.value = false;

      const result: LoadResult = {
        imageSize: size,
        src: source,
      };

      return result;
    } catch (e) {
      const err = e instanceof Error ? e : new Error('Failed to load image');
      error.value = err;
      isLoading.value = false;
      throw err;
    }
  }

  /**
   * Clear loaded image
   */
  function clear() {
    sourceImage.value = null;
    previewCanvas.value = null;
    imageSize.value = null;
    error.value = null;
    isLoading.value = false;
  }

  return {
    isLoading,
    error,
    progress,
    sourceImage,
    previewCanvas,
    imageSize,
    load,
    clear,
  };
}

export type ImageLoader = ReturnType<typeof useImageLoader>;
