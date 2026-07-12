import type { MaskFormat } from '../composables/useToolSchemaFeatures'

function isInpaintPixel(data: Uint8ClampedArray, offset: number, format: MaskFormat): boolean {
  const r = data[offset]
  const g = data[offset + 1]
  const b = data[offset + 2]
  const a = data[offset + 3]

  if (format === 'alpha') return a < 128
  if (format === 'white-black') return r > 128 && g > 128 && b > 128
  return r < 128 && g < 128 && b < 128
}

/** Convert mask pixels between the formats advertised by x-mask-format. */
export function convertMaskPixels(
  source: Uint8ClampedArray,
  sourceFormat: MaskFormat,
  targetFormat: MaskFormat,
): Uint8ClampedArray {
  const output = new Uint8ClampedArray(source.length)

  for (let i = 0; i < source.length; i += 4) {
    const inpaint = isInpaintPixel(source, i, sourceFormat)
    if (targetFormat === 'alpha') {
      output[i] = inpaint ? 255 : 0
      output[i + 1] = inpaint ? 255 : 0
      output[i + 2] = inpaint ? 255 : 0
      output[i + 3] = inpaint ? 0 : 255
    } else {
      const inpaintIsWhite = targetFormat === 'white-black'
      const value = inpaint === inpaintIsWhite ? 255 : 0
      output[i] = value
      output[i + 1] = value
      output[i + 2] = value
      output[i + 3] = 255
    }
  }

  return output
}

/** Convert a PNG data URL while preserving its dimensions. */
export async function convertMaskDataUrl(
  dataUrl: string,
  sourceFormat: MaskFormat,
  targetFormat: MaskFormat,
): Promise<string> {
  if (sourceFormat === targetFormat) return dataUrl

  const image = await new Promise<HTMLImageElement>((resolve, reject) => {
    const element = new Image()
    element.onload = () => resolve(element)
    element.onerror = () => reject(new Error('Failed to decode transferred mask'))
    element.src = dataUrl
  })

  const canvas = document.createElement('canvas')
  canvas.width = image.naturalWidth || image.width
  canvas.height = image.naturalHeight || image.height
  const context = canvas.getContext('2d')
  if (!context) throw new Error('Failed to create mask conversion canvas')

  context.drawImage(image, 0, 0)
  const imageData = context.getImageData(0, 0, canvas.width, canvas.height)
  imageData.data.set(convertMaskPixels(imageData.data, sourceFormat, targetFormat))
  context.putImageData(imageData, 0, 0)
  return canvas.toDataURL('image/png')
}
