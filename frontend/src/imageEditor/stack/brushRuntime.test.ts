import assert from 'node:assert/strict'
import test from 'node:test'

import {
  BrushStrokeRuntime,
  calibratePressure,
  evaluateCurve,
  repairActivePenPressureDropouts,
  resolveBrushDab,
  seededRandom,
} from '../brush/brushRuntime.ts'
import {
  BRUSH_PRESETS,
  brushPreset,
  isBrushPresetDefinition,
  settingsForPreset,
} from '../brush/brushPresets.ts'
import type { BrushInputSample, BrushPresetDefinition } from '../brush/types.ts'
import { brushTipAlpha } from '../brush/tipMask.ts'

const rawPreset: BrushPresetDefinition = {
  formatVersion: 1,
  id: 'test.raw',
  name: 'Raw',
  category: 'Basics',
  base: { size: 10, hardness: 100, opacity: 100, flow: 100, spacing: 50 },
  tip: { kind: 'ellipse', aspect: 1, rotation: 0 },
  dynamics: [],
  stabilization: { mode: 'raw' },
  previewSeed: 7,
}

function sample(x: number, pressure = 1, time = x * 2): BrushInputSample {
  return {
    x, y: 0, time, pressure,
    tiltX: 0, tiltY: 0, rotation: 0, tangentialPressure: 0,
    pointer: 'pen', eraser: false,
    velocity: 0, direction: 0, distance: 0,
  }
}

test('pressure calibration applies dead zone, maximum and an editable curve', () => {
  const calibration = {
    minimum: 0.1,
    maximum: 0.9,
    curve: [{ x: 0, y: 0 }, { x: 0.5, y: 0.25 }, { x: 1, y: 1 }],
  }
  assert.equal(calibratePressure(0.05, calibration), 0)
  assert.equal(calibratePressure(0.5, calibration), 0.25)
  assert.equal(calibratePressure(1, calibration), 1)
  assert.equal(evaluateCurve(calibration.curve, 0.75), 0.625)
})

test('straight raw strokes are independent of browser event density', () => {
  const settings = settingsForPreset(rawPreset)
  function draw(xs: number[]) {
    const runtime = new BrushStrokeRuntime(settings, rawPreset)
    return xs.flatMap(x => runtime.push(sample(x))).map(dab => [dab.x, dab.y])
  }
  assert.deepEqual(draw([0, 1, 2, 3, 4, 5, 10, 15, 20]), draw([0, 10, 20]))
  assert.deepEqual(draw([0, 10, 20]), [[0, 0], [5, 0], [10, 0], [15, 0], [20, 0]])
})

test('pressure dynamics are interpolated per dab and ignored for mouse samples', () => {
  const preset = brushPreset('stimma.ink.clean-taper')
  const settings = settingsForPreset(preset)
  const pen = new BrushStrokeRuntime(settings, preset)
  const penDabs = [
    ...pen.push(sample(0, 0.1)),
    ...pen.push(sample(30, 1)),
  ]
  assert.ok(penDabs[0].size < penDabs.at(-1)!.size)

  const mouseSample = { ...sample(0, 0), pointer: 'mouse' as const }
  const mouseDab = resolveBrushDab(mouseSample, settings, preset, 0.5)
  assert.equal(mouseDab.size, settings.size)
})

test('active pen pressure dropouts interpolate between valid neighbours', () => {
  const repaired = repairActivePenPressureDropouts([
    sample(0, 0.8),
    sample(1, 0),
    sample(2, 0),
    sample(3, 0.5),
  ], null)
  assert.deepEqual(
    repaired.samples.map(point => Number(point.pressure.toFixed(2))),
    [0.8, 0.7, 0.6, 0.5],
  )
  assert.equal(repaired.lastPressure, 0.5)
})

test('dropouts spanning event batches hold the last active pressure', () => {
  const repaired = repairActivePenPressureDropouts([
    sample(1, 0),
    sample(2, 0),
  ], 0.65)
  assert.deepEqual(repaired.samples.map(point => point.pressure), [0.65, 0.65])
  assert.equal(repaired.lastPressure, 0.65)
})

test('mouse pressure and a pen stroke with no valid pressure remain untouched', () => {
  const mouse = { ...sample(0, 0), pointer: 'mouse' as const }
  const repaired = repairActivePenPressureDropouts([mouse, sample(1, 0)], null)
  assert.deepEqual(repaired.samples.map(point => point.pressure), [0, 0])
  assert.equal(repaired.lastPressure, null)
})

test('seeded random dynamics replay exactly and differ under another seed', () => {
  const preset = brushPreset('stimma.texture.spatter')
  const settings = settingsForPreset(preset)
  function draw(seed: number) {
    const runtime = new BrushStrokeRuntime(settings, preset, undefined, seed)
    return [0, 20, 40, 60].flatMap(x => runtime.push(sample(x)))
  }
  assert.deepEqual(draw(44), draw(44))
  assert.notDeepEqual(draw(44), draw(45))
  const randomA = seededRandom(10)
  const randomB = seededRandom(10)
  assert.deepEqual([randomA(), randomA()], [randomB(), randomB()])
})

test('the starter catalog is versioned, unique and spans the promised everyday families', () => {
  assert.equal(new Set(BRUSH_PRESETS.map(preset => preset.id)).size, BRUSH_PRESETS.length)
  assert.ok(BRUSH_PRESETS.every(isBrushPresetDefinition))
  assert.ok(BRUSH_PRESETS.length >= 12)
  for (const category of ['Basics', 'Ink', 'Pencil', 'Marker', 'Airbrush', 'Texture', 'Eraser']) {
    assert.ok(BRUSH_PRESETS.some(preset => preset.category === category), category)
  }
})

test('the authoritative raster tip is genuinely oblong and rotates its silhouette', () => {
  assert.equal(brushTipAlpha(0.8, 0, 100, 0.25, 0), 1)
  assert.equal(brushTipAlpha(0, 0.3, 100, 0.25, 0), 0)
  assert.equal(brushTipAlpha(0, 0.8, 100, 0.25, 90), 1)
  assert.equal(brushTipAlpha(0.3, 0, 100, 0.25, 90), 0)
})

test('fixed nibs do not swivel around corners with stroke direction', () => {
  for (const id of ['stimma.ink.dry-nib', 'stimma.pencil.broad', 'stimma.marker.chisel']) {
    assert.equal(
      brushPreset(id).dynamics.some(mapping => mapping.target === 'rotation' && mapping.input === 'direction'),
      false,
      id,
    )
  }
})

test('broad pencil preview and raster share the same oblong aspect', () => {
  const preset = brushPreset('stimma.pencil.broad')
  const settings = settingsForPreset(preset)
  const dab = resolveBrushDab(sample(0, 0.7), settings, preset, 0.5)
  assert.equal(dab.aspect, preset.tip.aspect)
  assert.ok(dab.aspect <= 0.25)
})

test('stabilized strokes stay finite and resolve their physical tail on release', () => {
  const preset = brushPreset('stimma.ink.clean-taper')
  const runtime = new BrushStrokeRuntime(settingsForPreset(preset), preset)
  runtime.push(sample(0, 0.5, 10))
  const moving = runtime.push(sample(40, 0.8, 10))
  const tail = runtime.finish()
  assert.ok(moving.length > 0)
  assert.ok(tail.length > 0)
  assert.ok([...moving, ...tail].every(dab => Object.values(dab).every(Number.isFinite)))
})
