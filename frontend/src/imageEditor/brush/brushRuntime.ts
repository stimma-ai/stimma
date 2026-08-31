import type { BrushSettings } from '../ported/geometry'
import type {
  BrushDynamicMapping,
  BrushInputSample,
  BrushPresetDefinition,
  CurvePoint,
  PressureCalibration,
  ResolvedBrushDab,
} from './types'

const DEFAULT_PRESSURE_CURVE: CurvePoint[] = [
  { x: 0, y: 0 },
  { x: 0.25, y: 0.18 },
  { x: 0.7, y: 0.72 },
  { x: 1, y: 1 },
]

export const DEFAULT_PRESSURE_CALIBRATION: PressureCalibration = {
  minimum: 0.015,
  maximum: 0.98,
  curve: DEFAULT_PRESSURE_CURVE,
}

function clamp(value: number, min = 0, max = 1): number {
  return Math.min(max, Math.max(min, Number.isFinite(value) ? value : min))
}

/** Piecewise-linear curves are compact, editable, and deterministic. */
export function evaluateCurve(points: CurvePoint[] | undefined, input: number): number {
  const curve = (points?.length ? points : [{ x: 0, y: 0 }, { x: 1, y: 1 }])
    .filter(point => Number.isFinite(point.x) && Number.isFinite(point.y))
    .map(point => ({ x: clamp(point.x), y: clamp(point.y) }))
    .sort((a, b) => a.x - b.x)
  if (!curve.length) return clamp(input)
  const x = clamp(input)
  if (x <= curve[0].x) return curve[0].y
  for (let index = 1; index < curve.length; index += 1) {
    const right = curve[index]
    if (x > right.x) continue
    const left = curve[index - 1]
    const width = Math.max(1e-9, right.x - left.x)
    return left.y + (right.y - left.y) * ((x - left.x) / width)
  }
  return curve[curve.length - 1].y
}

export function calibratePressure(
  pressure: number,
  calibration: PressureCalibration = DEFAULT_PRESSURE_CALIBRATION,
): number {
  const minimum = clamp(calibration.minimum)
  const maximum = Math.max(minimum + 1e-6, clamp(calibration.maximum))
  const normalized = clamp((pressure - minimum) / (maximum - minimum))
  return evaluateCurve(calibration.curve, normalized)
}

function lerp(a: number, b: number, amount: number): number {
  return a + (b - a) * amount
}

export function interpolateBrushSample(
  from: BrushInputSample,
  to: BrushInputSample,
  amount: number,
): BrushInputSample {
  const t = clamp(amount)
  const directionDelta = ((to.direction - from.direction + 540) % 360) - 180
  return {
    x: lerp(from.x, to.x, t),
    y: lerp(from.y, to.y, t),
    time: lerp(from.time, to.time, t),
    pressure: lerp(from.pressure, to.pressure, t),
    tiltX: lerp(from.tiltX, to.tiltX, t),
    tiltY: lerp(from.tiltY, to.tiltY, t),
    rotation: lerp(from.rotation, to.rotation, t),
    tangentialPressure: lerp(from.tangentialPressure, to.tangentialPressure, t),
    pointer: to.pointer,
    eraser: to.eraser,
    velocity: lerp(from.velocity, to.velocity, t),
    direction: (from.direction + directionDelta * t + 360) % 360,
    distance: lerp(from.distance, to.distance, t),
  }
}

/**
 * Repair browser pressure dropouts while a pen stroke is known to be active.
 *
 * Chromium/Wayland can put zero pressure on otherwise valid coalesced samples
 * between positive-pressure neighbours. Pressure-to-flow brushes render those
 * dabs transparent, producing holes despite a continuous coordinate path.
 * The caller invokes this only between pen pointerdown and pointerup, so zero
 * here is missing axis data rather than the end of the stroke.
 */
export function repairActivePenPressureDropouts(
  samples: BrushInputSample[],
  previousPressure: number | null,
): { samples: BrushInputSample[]; lastPressure: number | null } {
  const repaired = samples.map(sample => ({ ...sample }))
  let lastPressure = previousPressure && previousPressure > 0 ? previousPressure : null
  let index = 0

  while (index < repaired.length) {
    const sample = repaired[index]
    if (sample.pointer !== 'pen' || sample.pressure > 0) {
      if (sample.pointer === 'pen' && sample.pressure > 0) lastPressure = sample.pressure
      index += 1
      continue
    }

    const start = index
    while (
      index < repaired.length
      && repaired[index].pointer === 'pen'
      && repaired[index].pressure === 0
    ) index += 1
    const after = index < repaired.length && repaired[index].pointer === 'pen'
      ? repaired[index].pressure
      : 0

    if (lastPressure !== null && after > 0) {
      const length = index - start
      for (let offset = 0; offset < length; offset += 1) {
        const amount = (offset + 1) / (length + 1)
        repaired[start + offset].pressure = lerp(lastPressure, after, amount)
      }
    } else {
      const fallback = lastPressure ?? (after > 0 ? after : 0)
      if (fallback > 0) {
        for (let cursor = start; cursor < index; cursor += 1) {
          repaired[cursor].pressure = fallback
        }
      }
    }
  }

  for (let cursor = repaired.length - 1; cursor >= 0; cursor -= 1) {
    if (repaired[cursor].pointer === 'pen' && repaired[cursor].pressure > 0) {
      lastPressure = repaired[cursor].pressure
      break
    }
  }
  return { samples: repaired, lastPressure }
}

/** Deterministic PRNG: the same preset/sample stream always produces the same dabs. */
export function seededRandom(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state += 0x6d2b79f5
    let value = state
    value = Math.imul(value ^ (value >>> 15), value | 1)
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61)
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296
  }
}

function dynamicInput(sample: BrushInputSample, input: BrushDynamicMapping['input'], random: number): number {
  switch (input) {
    case 'pressure': return sample.pointer === 'pen' ? sample.pressure : 1
    case 'speed': return 1 - clamp(sample.velocity / 1800)
    case 'tilt': return clamp(Math.hypot(sample.tiltX, sample.tiltY) / 90)
    case 'direction': return ((sample.direction % 360) + 360) % 360 / 360
    case 'distance': return (sample.distance % 1000) / 1000
    case 'random': return random
  }
}

export function resolveBrushDab(
  sample: BrushInputSample,
  settings: BrushSettings,
  preset: BrushPresetDefinition,
  random: number,
): ResolvedBrushDab {
  const tip = preset.tip.kind === 'ellipse'
    ? preset.tip
    : { kind: 'ellipse' as const, aspect: preset.tip.aspect, rotation: preset.tip.rotation }
  const values = {
    size: settings.size,
    opacity: settings.opacity,
    flow: settings.flow,
    rotation: tip.rotation,
    aspect: tip.aspect,
    scatter: 0,
  }

  for (const mapping of preset.dynamics) {
    if (mapping.input === 'pressure' && mapping.target === 'size' && settings.pressureSize === false) continue
    if (
      mapping.input === 'pressure'
      && (mapping.target === 'flow' || mapping.target === 'opacity')
      && settings.pressureOpacity === false
    ) continue
    const input = dynamicInput(sample, mapping.input, random)
    const value = lerp(mapping.min, mapping.max, evaluateCurve(mapping.curve, input))
    if (mapping.target === 'size') values.size *= value
    else if (mapping.target === 'opacity') values.opacity *= value
    else if (mapping.target === 'flow') values.flow *= value
    else values[mapping.target] = value
  }

  // Legacy toggles remain meaningful for old preferences and custom brushes.
  if (!preset.dynamics.some(mapping => mapping.target === 'size') && settings.pressureSize && sample.pointer === 'pen') {
    values.size = settings.size * (0.15 + 0.85 * sample.pressure)
  }
  if (!preset.dynamics.some(mapping => mapping.target === 'flow') && settings.pressureOpacity && sample.pointer === 'pen') {
    values.flow = settings.flow * sample.pressure
  }

  const scatterDistance = values.size * values.scatter * random
  const scatterAngle = random * Math.PI * 2
  return {
    x: sample.x + Math.cos(scatterAngle) * scatterDistance,
    y: sample.y + Math.sin(scatterAngle) * scatterDistance,
    size: Math.max(1, values.size),
    hardness: clamp(settings.hardness / 100) * 100,
    opacity: clamp(values.opacity / 100) * 100,
    flow: clamp(values.flow / 100) * 100,
    aspect: clamp(values.aspect, 0.08, 1),
    rotation: values.rotation,
    ...(preset.tip.kind === 'bitmap' ? { tipAssetId: preset.tip.assetId } : {}),
  }
}

export class BrushStrokeRuntime {
  private readonly settings: BrushSettings
  private readonly preset: BrushPresetDefinition
  private readonly calibration: PressureCalibration
  private previousRaw: BrushInputSample | null = null
  private previousPath: BrushInputSample | null = null
  private previousDabInput: BrushInputSample | null = null
  private distanceToNextDab = 0
  private totalDistance = 0
  private readonly random: () => number

  constructor(
    settings: BrushSettings,
    preset: BrushPresetDefinition,
    calibration: PressureCalibration = DEFAULT_PRESSURE_CALIBRATION,
    seed = preset.previewSeed,
  ) {
    this.settings = settings
    this.preset = preset
    this.calibration = calibration
    this.random = seededRandom(seed)
  }

  private condition(raw: BrushInputSample): BrushInputSample {
    const pressure = raw.pointer === 'pen'
      ? calibratePressure(raw.pressure, this.calibration)
      : 1
    const previous = this.previousRaw
    const elapsed = previous ? Math.max(0.25, raw.time - previous.time) : 1
    const distance = previous ? Math.hypot(raw.x - previous.x, raw.y - previous.y) : 0
    this.totalDistance += distance
    const measuredVelocity = distance * 1000 / elapsed
    const direction = distance > 1e-6 && previous
      ? Math.atan2(raw.y - previous.y, raw.x - previous.x) * 180 / Math.PI
      : previous?.direction ?? raw.direction
    let x = raw.x
    let y = raw.y
    const prior = this.previousPath
    const stabilization = this.preset.stabilization
    if (prior && stabilization.mode !== 'raw') {
      const smoothing = clamp(stabilization.mode === 'smooth'
        ? stabilization.amount
        : stabilization.smoothing)
      const responsiveness = 1 - smoothing * 0.82
      x = lerp(prior.x, x, responsiveness)
      y = lerp(prior.y, y, responsiveness)
      if (stabilization.mode === 'stabilized') {
        const dx = x - prior.x
        const dy = y - prior.y
        const length = Math.hypot(dx, dy)
        if (length <= stabilization.radius) {
          x = prior.x
          y = prior.y
        } else {
          const travel = length - stabilization.radius
          x = prior.x + dx / length * travel
          y = prior.y + dy / length * travel
        }
      }
    }
    const sample = {
      ...raw,
      x,
      y,
      pressure,
      velocity: previous
        ? lerp(this.previousPath?.velocity ?? measuredVelocity, measuredVelocity, 0.35)
        : 0,
      direction,
      distance: this.totalDistance,
    }
    this.previousRaw = { ...raw, pressure, velocity: sample.velocity, direction, distance: this.totalDistance }
    this.previousPath = sample
    return sample
  }

  push(raw: BrushInputSample): ResolvedBrushDab[] {
    const sample = this.condition(raw)
    if (!this.previousDabInput) {
      this.previousDabInput = sample
      const dab = resolveBrushDab(sample, this.settings, this.preset, this.random())
      this.distanceToNextDab = Math.max(0.25, dab.size * this.settings.spacing / 100)
      return [dab]
    }

    const dabs = this.dabsBetween(this.previousDabInput, sample)
    this.previousDabInput = sample
    return dabs
  }

  private dabsBetween(start: BrushInputSample, sample: BrushInputSample): ResolvedBrushDab[] {
    const dx = sample.x - start.x
    const dy = sample.y - start.y
    const length = Math.hypot(dx, dy)
    if (length < 1e-9) return []
    if (length < this.distanceToNextDab) {
      this.distanceToNextDab -= length
      return []
    }

    const dabs: ResolvedBrushDab[] = []
    let travelled = this.distanceToNextDab
    while (travelled <= length + 1e-9) {
      const dabSample = interpolateBrushSample(start, sample, travelled / length)
      const dab = resolveBrushDab(dabSample, this.settings, this.preset, this.random())
      dabs.push(dab)
      travelled += Math.max(0.25, dab.size * this.settings.spacing / 100)
    }
    this.distanceToNextDab = Math.max(0.25, travelled - length)
    return dabs
  }

  /** Pull a stabilizer's visible tail to the physical pen position on release. */
  finish(): ResolvedBrushDab[] {
    const raw = this.previousRaw
    if (!raw || !this.previousPath || this.preset.stabilization.mode !== 'stabilized') return []
    const endpoint = { ...raw, distance: this.totalDistance }
    const dabs = this.dabsBetween(this.previousPath, endpoint)
    this.previousPath = endpoint
    this.previousDabInput = endpoint
    return dabs
  }
}
