import assert from 'node:assert/strict'
import test from 'node:test'

import {
  applyPhotographicAdjustments,
  hasGradingAdjustments,
  hasMixerAdjustments,
  hasPhotographicAdjustments,
  hasPointColorAdjustments,
  mixerValueAtHue,
} from './photoAdjustments.ts'

function pixel(r: number, g: number, b: number) {
  return { data: new Uint8ClampedArray([r, g, b, 255]) } as ImageData
}

test('new tonal and color controls participate in adjustment identity', () => {
  assert.equal(hasPhotographicAdjustments({}), false)
  assert.equal(hasPhotographicAdjustments({ highlights: 1 }), true)
  assert.equal(hasPhotographicAdjustments({ colorizeAmount: 1 }), true)
  assert.equal(hasPhotographicAdjustments({ colorizeHue: 120 }), false)
  assert.equal(hasPhotographicAdjustments({ vibrance: 1 }), true)
  assert.equal(
    hasPhotographicAdjustments({
      curve: {
        rgb: [[0, 0], [0.5, 0.4], [1, 1]],
        red: [[0, 0], [1, 1]],
        green: [[0, 0], [1, 1]],
        blue: [[0, 0], [1, 1]],
      },
    }),
    true,
  )
  assert.equal(hasPhotographicAdjustments({ dehaze: 1 }), true)
})

test('highlight adjustment is weighted toward bright pixels', () => {
  const dark = pixel(40, 40, 40)
  const bright = pixel(220, 220, 220)
  applyPhotographicAdjustments(dark, { highlights: 100 })
  applyPhotographicAdjustments(bright, { highlights: 100 })
  assert.ok(bright.data[0] - 220 > dark.data[0] - 40)
})

test('point color rotates a selected red while retaining saturation', () => {
  const red = pixel(255, 0, 0)
  applyPhotographicAdjustments(red, {
    pointHue: 0, pointSat: 100, pointLum: 50, pointHueShift: 120,
  })
  assert.ok(red.data[1] > 240)
  assert.ok(red.data[0] < 15)
  assert.ok(red.data[2] < 15)
})

test('mixer, point color and grading participate in adjustment identity', () => {
  assert.equal(hasMixerAdjustments({}), false)
  assert.equal(hasMixerAdjustments({ mixerSatOrange: -20 }), true)
  assert.equal(hasPointColorAdjustments({ pointHue: 200, pointRange: 80 }), false)
  assert.equal(hasPointColorAdjustments({ pointHueShift: 10 }), true)
  assert.equal(hasGradingAdjustments({ gradeShadowHue: 220, gradeBlend: 80 }), false)
  assert.equal(hasGradingAdjustments({ gradeShadowSat: 10 }), true)
  assert.equal(hasPhotographicAdjustments({ mixerLumBlue: 5 }), true)
  assert.equal(hasPhotographicAdjustments({ pointSatShift: 5 }), true)
  assert.equal(hasPhotographicAdjustments({ gradeHighlightLum: 5 }), true)
})

test('mixer band weights interpolate between neighbouring centers', () => {
  const values = [100, 0, 0, 0, 0, 0, 0, 0]
  assert.equal(mixerValueAtHue(0, values), 100)
  assert.equal(mixerValueAtHue(15, values), 50)
  assert.equal(mixerValueAtHue(30, values), 0)
  // Wrap: magenta (330) back toward red (360 = 0).
  assert.equal(mixerValueAtHue(345, values), 50)
  assert.equal(mixerValueAtHue(120, values), 0)
})

test('mixer moves only pixels in the targeted band', () => {
  const orange = pixel(230, 140, 40)
  const blue = pixel(40, 90, 230)
  const gray = pixel(128, 128, 128)
  const params = { mixerSatOrange: -100 }
  const chroma = (p: ImageData) =>
    Math.max(p.data[0], p.data[1], p.data[2]) - Math.min(p.data[0], p.data[1], p.data[2])
  const orangeBefore = chroma(orange)
  const blueBefore = chroma(blue)
  applyPhotographicAdjustments(orange, params)
  applyPhotographicAdjustments(blue, params)
  applyPhotographicAdjustments(gray, params)
  assert.ok(chroma(orange) < orangeBefore * 0.4, 'orange pixel should desaturate')
  assert.ok(Math.abs(chroma(blue) - blueBefore) <= 6, 'blue pixel should hold')
  assert.equal(chroma(gray), 0, 'gray pixel should be untouched')
})

test('point color shifts the picked color and leaves distant hues alone', () => {
  const brandRed = pixel(193, 68, 46)
  const sky = pixel(80, 140, 220)
  // Picked reference ≈ the brand red's own HSL: hue 9, sat 61%, lum 47%.
  const params = {
    pointHue: 9, pointSat: 61, pointLum: 47,
    pointHueShift: 40, pointRange: 50,
  }
  applyPhotographicAdjustments(brandRed, params)
  applyPhotographicAdjustments(sky, params)
  // A +40° shift moves the red toward orange: green channel rises.
  assert.ok(brandRed.data[1] > 90, 'picked color should rotate toward orange')
  assert.ok(Math.abs(sky.data[2] - 220) <= 3, 'distant hue should hold')
})

test('grading tints shadows and highlights independently', () => {
  const shadow = pixel(30, 30, 30)
  const highlight = pixel(225, 225, 225)
  // Teal shadows, warm highlights — the classic look.
  const params = {
    gradeShadowHue: 190, gradeShadowSat: 80,
    gradeHighlightHue: 40, gradeHighlightSat: 80,
  }
  applyPhotographicAdjustments(shadow, params)
  applyPhotographicAdjustments(highlight, params)
  assert.ok(shadow.data[2] > shadow.data[0], 'shadows should cool')
  assert.ok(highlight.data[0] > highlight.data[2], 'highlights should warm')
})

test('grading luminance lifts its zone only', () => {
  const shadow = pixel(30, 30, 30)
  const highlight = pixel(225, 225, 225)
  const params = { gradeShadowLum: 100 }
  applyPhotographicAdjustments(shadow, params)
  applyPhotographicAdjustments(highlight, params)
  assert.ok(shadow.data[0] > 40, 'shadows should lift')
  assert.ok(Math.abs(highlight.data[0] - 225) <= 3, 'highlights should hold')
})

test('vibrance favours muted colors and a master curve remaps channels', () => {
  const muted = pixel(150, 120, 110)
  const originalSpread = muted.data[0] - muted.data[2]
  applyPhotographicAdjustments(muted, {
    vibrance: 100,
    curve: {
      rgb: [[0, 0], [0.25, 0.18], [0.5, 0.48], [0.75, 0.82], [1, 1]],
      red: [[0, 0], [1, 1]],
      green: [[0, 0], [1, 1]],
      blue: [[0, 0], [1, 1]],
    },
  })
  assert.ok(muted.data[0] - muted.data[2] > originalSpread)
  assert.notEqual(muted.data[0], 150)
})
