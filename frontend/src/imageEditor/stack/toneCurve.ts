export type ToneCurveChannel = 'rgb' | 'red' | 'green' | 'blue'
export type ToneCurvePoint = [input: number, output: number]

export interface ToneCurve {
  rgb: ToneCurvePoint[]
  red: ToneCurvePoint[]
  green: ToneCurvePoint[]
  blue: ToneCurvePoint[]
}

export interface ToneCurveHistogram {
  luminance: number[]
  red: number[]
  green: number[]
  blue: number[]
}

export const TONE_CURVE_CHANNELS: ToneCurveChannel[] = ['rgb', 'red', 'green', 'blue']
export const TONE_CURVE_LUT_SIZE = 17

/** The starting shapes a curve control offers, per channel. */
export const TONE_CURVE_PRESETS: Record<'linear' | 'medium' | 'strong', ToneCurvePoint[]> = {
  linear: [[0, 0], [1, 1]],
  medium: [[0, 0], [0.25, 0.20], [0.5, 0.5], [0.75, 0.80], [1, 1]],
  strong: [[0, 0], [0.25, 0.14], [0.5, 0.5], [0.75, 0.86], [1, 1]],
}

const IDENTITY_POINTS: ToneCurvePoint[] = [[0, 0], [1, 1]]

export function defaultToneCurve(): ToneCurve {
  return {
    rgb: IDENTITY_POINTS.map(point => [...point]),
    red: IDENTITY_POINTS.map(point => [...point]),
    green: IDENTITY_POINTS.map(point => [...point]),
    blue: IDENTITY_POINTS.map(point => [...point]),
  } as ToneCurve
}

export const DEFAULT_TONE_CURVE: ToneCurve = defaultToneCurve()

function clamp01(value: number) {
  return Math.max(0, Math.min(1, value))
}

function normalizedPoints(candidate: unknown): ToneCurvePoint[] {
  if (!Array.isArray(candidate)) return IDENTITY_POINTS.map(point => [...point])
  const points = candidate
    .filter(point =>
      Array.isArray(point)
      && point.length === 2
      && Number.isFinite(Number(point[0]))
      && Number.isFinite(Number(point[1])),
    )
    .map(point => [clamp01(Number(point[0])), clamp01(Number(point[1]))] as ToneCurvePoint)
    .sort((a, b) => a[0] - b[0])

  if (points.length < 2) return IDENTITY_POINTS.map(point => [...point])
  const unique = points.filter((point, index) =>
    index === 0 || point[0] - points[index - 1][0] >= 0.002,
  ).slice(0, 16)
  if (unique.length < 2) return IDENTITY_POINTS.map(point => [...point])
  unique[0][0] = 0
  unique[unique.length - 1][0] = 1
  return unique
}

export function toneCurveValueOf(candidate: unknown): ToneCurve {
  if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) {
    return defaultToneCurve()
  }
  const value = candidate as Partial<Record<ToneCurveChannel, unknown>>
  return {
    rgb: normalizedPoints(value.rgb),
    red: normalizedPoints(value.red),
    green: normalizedPoints(value.green),
    blue: normalizedPoints(value.blue),
  }
}

export function isIdentityToneCurve(candidate: unknown): boolean {
  const curve = toneCurveValueOf(candidate)
  return TONE_CURVE_CHANNELS.every(channel => {
    const points = curve[channel]
    return points.length === 2
      && Math.abs(points[0][0]) < 1e-6
      && Math.abs(points[0][1]) < 1e-6
      && Math.abs(points[1][0] - 1) < 1e-6
      && Math.abs(points[1][1] - 1) < 1e-6
  })
}

/**
 * Monotone cubic Hermite interpolation. It gives the point curve Lightroom's
 * smooth feel without ringing past a control point or inventing clipped tones.
 */
export function toneCurvePointValue(value: number, candidate: unknown): number {
  const points = normalizedPoints(candidate)
  const x = clamp01(value)
  let segment = points.length - 2
  for (let index = 0; index < points.length - 1; index++) {
    if (x <= points[index + 1][0]) {
      segment = index
      break
    }
  }

  const widths = points.slice(0, -1).map((point, index) =>
    Math.max(0.002, points[index + 1][0] - point[0]),
  )
  const slopes = widths.map((width, index) =>
    (points[index + 1][1] - points[index][1]) / width,
  )
  const tangents = points.map((_, index) => {
    if (index === 0) return slopes[0]
    if (index === points.length - 1) return slopes[slopes.length - 1]
    const left = slopes[index - 1]
    const right = slopes[index]
    if (left === 0 || right === 0 || Math.sign(left) !== Math.sign(right)) return 0
    return (left + right) / 2
  })

  // Fritsch–Carlson limiting keeps each segment inside its two outputs.
  for (let index = 0; index < slopes.length; index++) {
    if (slopes[index] === 0) {
      tangents[index] = 0
      tangents[index + 1] = 0
      continue
    }
    const a = tangents[index] / slopes[index]
    const b = tangents[index + 1] / slopes[index]
    const magnitude = Math.hypot(a, b)
    if (magnitude > 3) {
      const scale = 3 / magnitude
      tangents[index] = scale * a * slopes[index]
      tangents[index + 1] = scale * b * slopes[index]
    }
  }

  const [x0, y0] = points[segment]
  const [x1, y1] = points[segment + 1]
  const width = x1 - x0
  const t = width <= 0 ? 0 : (x - x0) / width
  const t2 = t * t
  const t3 = t2 * t
  return clamp01(
    (2 * t3 - 3 * t2 + 1) * y0
    + (t3 - 2 * t2 + t) * width * tangents[segment]
    + (-2 * t3 + 3 * t2) * y1
    + (t3 - t2) * width * tangents[segment + 1],
  )
}

export function toneCurveChannelValue(
  value: number,
  candidate: unknown,
  channel: Exclude<ToneCurveChannel, 'rgb'>,
): number {
  const curve = toneCurveValueOf(candidate)
  const master = toneCurvePointValue(value, curve.rgb)
  return toneCurvePointValue(master, curve[channel])
}

export function toneCurveChannelLut(
  candidate: unknown,
  channel: Exclude<ToneCurveChannel, 'rgb'>,
  size = TONE_CURVE_LUT_SIZE,
): number[] {
  const length = Math.max(2, Math.round(size))
  return Array.from({ length }, (_, index) =>
    toneCurveChannelValue(index / (length - 1), candidate, channel),
  )
}

function normalizeHistogram(bins: number[]) {
  const peak = Math.max(1, ...bins)
  return bins.map(value => Math.sqrt(value / peak))
}

export function toneCurveHistogramFromImageData(
  data: ImageData,
  binCount = 64,
): ToneCurveHistogram {
  const red = Array<number>(binCount).fill(0)
  const green = Array<number>(binCount).fill(0)
  const blue = Array<number>(binCount).fill(0)
  const luminance = Array<number>(binCount).fill(0)
  for (let index = 0; index < data.data.length; index += 4) {
    if (data.data[index + 3] === 0) continue
    const r = data.data[index]
    const g = data.data[index + 1]
    const b = data.data[index + 2]
    red[Math.min(binCount - 1, Math.floor(r / 256 * binCount))]++
    green[Math.min(binCount - 1, Math.floor(g / 256 * binCount))]++
    blue[Math.min(binCount - 1, Math.floor(b / 256 * binCount))]++
    const y = r * 0.2126 + g * 0.7152 + b * 0.0722
    luminance[Math.min(binCount - 1, Math.floor(y / 256 * binCount))]++
  }
  return {
    luminance: normalizeHistogram(luminance),
    red: normalizeHistogram(red),
    green: normalizeHistogram(green),
    blue: normalizeHistogram(blue),
  }
}

export function toneCurveHistogramFromCanvas(
  source: HTMLCanvasElement,
): ToneCurveHistogram | undefined {
  if (!source.width || !source.height) return undefined
  const sample = document.createElement('canvas')
  const scale = Math.min(1, 256 / Math.max(source.width, source.height))
  sample.width = Math.max(1, Math.round(source.width * scale))
  sample.height = Math.max(1, Math.round(source.height * scale))
  const context = sample.getContext('2d', { willReadFrequently: true })
  if (!context) return undefined
  context.drawImage(source, 0, 0, sample.width, sample.height)
  return toneCurveHistogramFromImageData(
    context.getImageData(0, 0, sample.width, sample.height),
  )
}
