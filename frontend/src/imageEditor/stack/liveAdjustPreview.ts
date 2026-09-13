/**
 * Viewport-resolution GPU preview for photographic sliders.
 *
 * The document compositor remains authoritative. During a drag this applies
 * only the delta from the pixels already on screen, which preserves every
 * other edit without replaying the stack. Pointer-up commits the composition and
 * performs one full-resolution render.
 */

import {
  photoAdjustmentRenderParams,
} from './adjustSections.ts'
import {
  MIXER_BAND_HUES,
  mixerBandValues,
} from './photoAdjustments.ts'
import {
  TONE_CURVE_LUT_SIZE,
  toneCurveChannelLut,
} from './toneCurve.ts'

export type AdjustmentValues = Record<string, any>

/**
 * Masked blur cannot use the GPU delta approximation without changing scope
 * semantics: the shader samples across the whole viewport before its final
 * mask mix, while the authoritative renderer composites an adjusted region.
 * Route spatial blur drags through the scaled document compositor instead.
 */
export function maskedAdjustmentNeedsCompositorPreview(
  patch: Record<string, unknown>,
): boolean {
  return 'opacity' in patch || 'feather_px' in patch || 'blur' in patch
}

const VERTEX_SHADER = `
attribute vec2 a_position;
varying vec2 v_uv;
void main() {
  v_uv = a_position * 0.5 + 0.5;
  gl_Position = vec4(a_position, 0.0, 1.0);
}
`

function curveDeltaShaderFunction(
  name: string,
  uniform: string,
) {
  const segments = Array.from({ length: TONE_CURVE_LUT_SIZE - 1 }, (_, index) => {
    const condition = index < TONE_CURVE_LUT_SIZE - 2
      ? `if (scaled < ${index + 1}.0) `
      : ''
    return `  ${condition}return mix(${uniform}[${index}], ${uniform}[${index + 1}], scaled - ${index}.0);`
  })
  return `
float ${name}(float inputValue) {
  float scaled = clamp(inputValue, 0.0, 1.0) * ${TONE_CURVE_LUT_SIZE - 1}.0;
${segments.join('\n')}
}
`
}

/**
 * Per-band Mixer weights, generated from the shared band centers so the GPU
 * partition is the CPU's: triangles between neighbouring centers, wrapped at
 * red, weights summing to one.
 */
const MIXER_VALUE_GLSL = (() => {
  const components = ['x', 'y', 'z', 'w']
  const terms = MIXER_BAND_HUES.map((center, index) => {
    const previous = MIXER_BAND_HUES[(index + 7) % 8]
    const next = MIXER_BAND_HUES[(index + 1) % 8]
    const leftWidth = ((center - previous) + 360) % 360
    const rightWidth = ((next - center) + 360) % 360
    const vector = index < 4 ? 'v1' : 'v2'
    const component = components[index % 4]
    return `  d = mod(hueDeg - ${center.toFixed(1)} + 180.0, 360.0) - 180.0;\n`
      + `  total += clamp(1.0 - max(-d / ${leftWidth.toFixed(1)}, d / ${rightWidth.toFixed(1)}), 0.0, 1.0) * ${vector}.${component};`
  })
  return `
float mixerValue(float hueDeg, vec4 v1, vec4 v2) {
  float total = 0.0;
  float d;
${terms.join('\n')}
  return total;
}
`
})()

const FRAGMENT_SHADER = `
precision highp float;
uniform sampler2D u_source;
uniform sampler2D u_mask;
uniform vec2 u_texel;
uniform float u_masked;
uniform float u_mask_strength;
uniform vec4 u_tone1;
uniform vec4 u_tone2;
uniform vec4 u_color1;
uniform vec4 u_color2;
uniform vec4 u_color3;
uniform vec4 u_detail1;
uniform vec2 u_detail2;
uniform float u_curve_delta_red[${TONE_CURVE_LUT_SIZE}];
uniform float u_curve_delta_green[${TONE_CURVE_LUT_SIZE}];
uniform float u_curve_delta_blue[${TONE_CURVE_LUT_SIZE}];
uniform vec4 u_sharpen1;
uniform vec4 u_sharpen2;
uniform vec4 u_nr1;
uniform vec4 u_nr2;
uniform vec4 u_nr3;
uniform vec4 u_grain1;
uniform vec2 u_grain2;
uniform vec4 u_mix_hue1;
uniform vec4 u_mix_hue2;
uniform vec4 u_mix_sat1;
uniform vec4 u_mix_sat2;
uniform vec4 u_mix_lum1;
uniform vec4 u_mix_lum2;
uniform vec4 u_point1;
uniform vec4 u_point2;
uniform vec4 u_point3;
uniform vec4 u_point4;
uniform vec4 u_grade1;
uniform vec4 u_grade2;
uniform vec4 u_grade3;
uniform vec4 u_grade4;
uniform vec4 u_grade5;
uniform vec4 u_grade6;
varying vec2 v_uv;

float luminance(vec3 color) {
  return dot(color, vec3(0.2126, 0.7152, 0.0722));
}

vec3 rgb2hsv(vec3 c) {
  vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
  vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
  vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
  float d = q.x - min(q.w, q.y);
  float e = 1.0e-10;
  return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
}

vec3 hsv2rgb(vec3 c) {
  vec3 p = abs(fract(c.xxx + vec3(0.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
  return c.z * mix(vec3(1.0), clamp(p - 1.0, 0.0, 1.0), c.y);
}

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}

${curveDeltaShaderFunction('curveDeltaRed', 'u_curve_delta_red')}
${curveDeltaShaderFunction('curveDeltaGreen', 'u_curve_delta_green')}
${curveDeltaShaderFunction('curveDeltaBlue', 'u_curve_delta_blue')}
${MIXER_VALUE_GLSL}

// Point color as an absolute application: preview takes apply(current) minus
// apply(base) so a drag on any knob moves the pixels already on screen.
// ref = [hueDeg, sat, lum, rangeDeg]; shift = [hueShiftDeg, satShift, lumShift, 0].
vec3 pointApply(vec3 source, vec4 ref, vec4 shift) {
  vec3 hsv = rgb2hsv(clamp(source, 0.0, 1.0));
  float l = hsv.z * (1.0 - hsv.y * 0.5);
  float denom = min(l, 1.0 - l);
  float sl = denom <= 1.0e-4 ? 0.0 : (hsv.z - l) / denom;
  float hueDeg = hsv.x * 360.0;
  float d = mod(hueDeg - ref.x + 180.0, 360.0) - 180.0;
  float hw = ref.y < 0.05
    ? 1.0
    : smoothstep(0.0, 1.0, clamp(1.0 - abs(d) / ref.w, 0.0, 1.0));
  float sw = smoothstep(0.0, 1.0, clamp(1.0 - abs(sl - ref.y) / 0.7, 0.0, 1.0));
  float lw = smoothstep(0.0, 1.0, clamp(1.0 - abs(l - ref.z) / 0.7, 0.0, 1.0));
  float w = hw * sw * lw;
  hueDeg += shift.x * w;
  sl = clamp(sl * (1.0 + shift.y * w), 0.0, 1.0);
  l += shift.z * w * (shift.z > 0.0 ? (1.0 - l) : l) * 0.6;
  l = clamp(l, 0.0, 1.0);
  float v = l + sl * min(l, 1.0 - l);
  float sv = v <= 1.0e-4 ? 0.0 : 2.0 * (1.0 - l / v);
  return hsv2rgb(vec3(fract(hueDeg / 360.0), sv, v));
}

// Three-zone grading. g1 = [shadowHue01, midHue01, highHue01, blend];
// g2 = [shadowSat, midSat, highSat, balance]; g3 = [shadowLum, midLum, highLum, 0].
vec3 gradeApply(vec3 source, vec4 g1, vec4 g2, vec4 g3) {
  float luma = luminance(clamp(source, 0.0, 1.0));
  float midpoint = 0.5 + g2.w * 0.2;
  float softness = 0.12 + g1.w * 0.33;
  float lowCross = midpoint - 0.17;
  float highCross = midpoint + 0.17;
  float sw = 1.0 - smoothstep(lowCross - softness, lowCross + softness, luma);
  float hw = smoothstep(highCross - softness, highCross + softness, luma);
  float mw = clamp(1.0 - sw - hw, 0.0, 1.0);
  vec3 result = source;
  result += (hsv2rgb(vec3(g1.x, 1.0, 1.0)) - 0.5) * g2.x * 0.3 * sw;
  result += (hsv2rgb(vec3(g1.y, 1.0, 1.0)) - 0.5) * g2.y * 0.3 * mw;
  result += (hsv2rgb(vec3(g1.z, 1.0, 1.0)) - 0.5) * g2.z * 0.3 * hw;
  result += vec3((g3.x * sw + g3.y * mw + g3.z * hw) * 0.25);
  return result;
}

vec3 signedMix(vec3 original, vec3 target, float amount) {
  return amount >= 0.0
    ? mix(original, target, clamp(amount, 0.0, 1.0))
    : original + (original - target) * min(1.0, -amount);
}

float grainAt(vec2 coordinate, float size, float roughness) {
  float cell = 1.0 + size * 7.0;
  float coarse = hash(floor(coordinate / cell));
  float fine = hash(coordinate);
  return mix(coarse, fine, roughness);
}

void main() {
  vec4 source = texture2D(u_source, v_uv);
  vec3 color = source.rgb;

  vec2 one = u_texel;
  vec3 nearSoft = (
    texture2D(u_source, v_uv + vec2(one.x, 0.0)).rgb +
    texture2D(u_source, v_uv - vec2(one.x, 0.0)).rgb +
    texture2D(u_source, v_uv + vec2(0.0, one.y)).rgb +
    texture2D(u_source, v_uv - vec2(0.0, one.y)).rgb
  ) * 0.25;
  vec2 wide = one * 6.0;
  vec3 wideSoft = (
    texture2D(u_source, v_uv + vec2(wide.x, 0.0)).rgb +
    texture2D(u_source, v_uv - vec2(wide.x, 0.0)).rgb +
    texture2D(u_source, v_uv + vec2(0.0, wide.y)).rgb +
    texture2D(u_source, v_uv - vec2(0.0, wide.y)).rgb
  ) * 0.25;

  // texture and clarity
  color += (source.rgb - nearSoft) * u_detail1.x * 0.9;
  color += (source.rgb - wideSoft) * u_detail1.y * 0.75;

  // Moiré and color-noise reduction smooth chroma while retaining luminance.
  float sourceLuma = luminance(color);
  float nearLuma = luminance(nearSoft);
  vec3 chromaSoft = vec3(sourceLuma) + nearSoft - vec3(nearLuma);
  color = signedMix(color, chromaSoft, u_color3.z * 0.75);
  float colorNrCurrent = u_nr2.z * (1.0 - u_nr3.x * 0.45) * (1.0 + u_nr3.z * 0.25);
  float colorNrBase = u_nr2.w * (1.0 - u_nr3.y * 0.45) * (1.0 + u_nr3.w * 0.25);
  color = signedMix(color, chromaSoft, (colorNrCurrent - colorNrBase) * 0.75);

  // Luminance noise reduction. Supporting controls alter edge protection and
  // local-contrast restoration without requiring a second preview path.
  float nrCurrent = u_nr1.x * (1.0 - u_nr1.z * 0.45);
  float nrBase = u_nr1.y * (1.0 - u_nr1.w * 0.45);
  color = signedMix(color, nearSoft, (nrCurrent - nrBase) * 0.75);
  color += (color - nearSoft) * (u_nr2.x - u_nr2.y) * 0.35;

  // Sharpening previews current minus baseline, so Amount, Radius, Detail and
  // Masking all remain responsive even when only a supporting control moves.
  vec3 currentSoft = mix(nearSoft, wideSoft, u_sharpen1.z);
  vec3 baseSoft = mix(nearSoft, wideSoft, u_sharpen1.w);
  vec3 currentHigh = mix(source.rgb - currentSoft, source.rgb - nearSoft, u_sharpen2.x);
  vec3 baseHigh = mix(source.rgb - baseSoft, source.rgb - nearSoft, u_sharpen2.y);
  float edge = clamp(length(source.rgb - nearSoft) * 3.0, 0.0, 1.0);
  float currentThreshold = u_sharpen2.z * 0.75;
  float baseThreshold = u_sharpen2.w * 0.75;
  float currentMask = u_sharpen2.z <= 0.0
    ? 1.0
    : smoothstep(currentThreshold, min(0.99, currentThreshold + 0.25), edge);
  float baseMask = u_sharpen2.w <= 0.0
    ? 1.0
    : smoothstep(baseThreshold, min(0.99, baseThreshold + 0.25), edge);
  color += currentHigh * u_sharpen1.x * 1.4 * currentMask;
  color -= baseHigh * u_sharpen1.y * 1.4 * baseMask;

  // Blur uses a wider eight-tap footprint at viewport resolution.
  float blurMix = clamp(u_detail2.x, 0.0, 1.0);
  vec2 blurStep = one * (1.0 + blurMix * 14.0);
  vec3 blurColor = (
    texture2D(u_source, v_uv + vec2(blurStep.x, 0.0)).rgb +
    texture2D(u_source, v_uv - vec2(blurStep.x, 0.0)).rgb +
    texture2D(u_source, v_uv + vec2(0.0, blurStep.y)).rgb +
    texture2D(u_source, v_uv - vec2(0.0, blurStep.y)).rgb +
    texture2D(u_source, v_uv + blurStep).rgb +
    texture2D(u_source, v_uv - blurStep).rgb +
    texture2D(u_source, v_uv + vec2(blurStep.x, -blurStep.y)).rgb +
    texture2D(u_source, v_uv + vec2(-blurStep.x, blurStep.y)).rgb
  ) * 0.125;
  color = mix(color, blurColor, blurMix);

  // exposure, brightness, contrast, gamma ratio
  color *= pow(2.0, u_tone1.x);
  color += u_tone1.y;
  color = (color - 0.5) * (1.0 + u_tone1.z) + 0.5;
  color = pow(max(color, vec3(0.0)), vec3(1.0 / max(0.1, u_tone1.w)));

  float luma = luminance(color);
  float tonal =
    u_tone2.x * smoothstep(0.45, 1.0, luma) * 0.35 +
    u_tone2.y * (1.0 - smoothstep(0.0, 0.55, luma)) * 0.35 +
    u_tone2.z * smoothstep(0.72, 1.0, luma) * 0.28 +
    u_tone2.w * (1.0 - smoothstep(0.0, 0.28, luma)) * 0.28;
  color += tonal;

  // temperature, tint, saturation
  color.r += max(u_color1.x, 0.0) * 0.18;
  color.b += max(-u_color1.x, 0.0) * 0.18;
  color.rb += max(u_color1.y, 0.0) * 0.14;
  color.g += max(-u_color1.y, 0.0) * 0.14;
  luma = luminance(color);
  color = vec3(luma) + (color - vec3(luma)) * (1.0 + u_color1.z);

  // colorize hue, colorize amount, dehaze, grain
  float dehaze = u_color2.z;
  color = (color - 0.5) * (1.0 + dehaze * 0.55) + 0.5 - dehaze * 0.03;
  luma = luminance(color);
  color = vec3(luma) + (color - vec3(luma)) * (1.0 + dehaze * 0.35);

  color += vec3(
    curveDeltaRed(color.r),
    curveDeltaGreen(color.g),
    curveDeltaBlue(color.b)
  );

  // Vibrance favours muted colors and preserves luminance.
  luma = luminance(color);
  float chroma = max(max(color.r, color.g), color.b) - min(min(color.r, color.g), color.b);
  float vibranceScale = u_color3.x > 0.0
    ? 1.0 + u_color3.x * (1.0 - clamp(chroma, 0.0, 1.0)) * 1.35
    : 1.0 + u_color3.x;
  color = vec3(luma) + (color - vec3(luma)) * vibranceScale;

  // Purple/green fringe suppression.
  float maximum = max(max(color.r, color.g), color.b);
  float minimum = min(min(color.r, color.g), color.b);
  float saturation = maximum <= 0.0 ? 0.0 : (maximum - minimum) / maximum;
  float purple = max(0.0, (color.r + color.b) * 0.5 - color.g);
  float green = max(0.0, color.g - (color.r + color.b) * 0.5);
  float fringe = clamp(max(purple, green) * saturation * 2.0, 0.0, 1.0);
  color = signedMix(color, vec3(luminance(color)), u_color3.y * fringe);

  // Mixer: per-hue H/S/L deltas, gray-guarded like the CPU path.
  vec3 mixerHsv = rgb2hsv(clamp(color, 0.0, 1.0));
  float mixerHueDeg = mixerHsv.x * 360.0;
  float mixerGuard = smoothstep(0.04, 0.16, mixerHsv.y);
  float mixerHueDelta = mixerValue(mixerHueDeg, u_mix_hue1, u_mix_hue2) * mixerGuard;
  float mixerSatDelta = mixerValue(mixerHueDeg, u_mix_sat1, u_mix_sat2) * mixerGuard;
  float mixerLumDelta = mixerValue(mixerHueDeg, u_mix_lum1, u_mix_lum2) * mixerGuard;
  mixerHsv.x = fract(mixerHsv.x + mixerHueDelta * 30.0 / 360.0);
  mixerHsv.y = clamp(mixerHsv.y * (1.0 + mixerSatDelta), 0.0, 1.0);
  color = hsv2rgb(mixerHsv);
  color += mixerLumDelta * (mixerLumDelta > 0.0 ? (vec3(1.0) - color) : color) * 0.5;

  // Point color and grading preview as apply(current) - apply(base).
  color += pointApply(color, u_point1, u_point2) - pointApply(color, u_point3, u_point4);
  color += gradeApply(color, u_grade1, u_grade2, u_grade3)
    - gradeApply(color, u_grade4, u_grade5, u_grade6);

  luma = luminance(color);
  vec3 tintColor = hsv2rgb(vec3(fract(u_color2.x / 360.0), 0.72, max(0.12, luma)));
  color = mix(color, tintColor, clamp(u_color2.y, 0.0, 1.0));

  float currentGrain = grainAt(
    gl_FragCoord.xy,
    u_grain1.z,
    u_grain2.x
  ) - 0.5;
  float baseGrain = grainAt(
    gl_FragCoord.xy,
    u_grain1.w,
    u_grain2.y
  ) - 0.5;
  color += (currentGrain * u_grain1.x - baseGrain * u_grain1.y) * 0.18;

  float mask = mix(1.0, max(
    texture2D(u_mask, v_uv).a,
    texture2D(u_mask, v_uv).r
  ), u_masked) * u_mask_strength;
  gl_FragColor = vec4(mix(source.rgb, clamp(color, 0.0, 1.0), mask), source.a);
}
`

function compile(gl: WebGLRenderingContext, kind: number, source: string) {
  const shader = gl.createShader(kind)
  if (!shader) throw new Error('Could not create adjustment preview shader.')
  gl.shaderSource(shader, source)
  gl.compileShader(shader)
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    throw new Error(gl.getShaderInfoLog(shader) || 'Could not compile adjustment preview shader.')
  }
  return shader
}

function value(values: AdjustmentValues, key: string, fallback = 0) {
  const candidate = values[key]
  return typeof candidate === 'number' ? candidate : fallback
}

function delta(current: AdjustmentValues, base: AdjustmentValues, key: string, scale = 100) {
  return (value(current, key) - value(base, key)) / scale
}

export interface LiveAdjustUniforms {
  tone1: number[]
  tone2: number[]
  color1: number[]
  color2: number[]
  color3: number[]
  detail1: number[]
  detail2: number[]
  curveDeltaRed: number[]
  curveDeltaGreen: number[]
  curveDeltaBlue: number[]
  sharpen1: number[]
  sharpen2: number[]
  nr1: number[]
  nr2: number[]
  nr3: number[]
  grain1: number[]
  grain2: number[]
  mixHue1: number[]
  mixHue2: number[]
  mixSat1: number[]
  mixSat2: number[]
  mixLum1: number[]
  mixLum2: number[]
  point1: number[]
  point2: number[]
  point3: number[]
  point4: number[]
  grade1: number[]
  grade2: number[]
  grade3: number[]
  grade4: number[]
  grade5: number[]
  grade6: number[]
}

/**
 * Pure uniform projection used by the shader and parity tests. Normalizing
 * through the shared schema makes preview defaults identical to both
 * authoritative render surfaces.
 */
export function buildLiveAdjustUniforms(
  currentValues: AdjustmentValues,
  baseValues: AdjustmentValues,
): LiveAdjustUniforms {
  const current = photoAdjustmentRenderParams(currentValues)
  const base = photoAdjustmentRenderParams(baseValues)
  const currentGamma = Math.max(0.1, value(current, 'gamma', 1))
  const baseGamma = Math.max(0.1, value(base, 'gamma', 1))
  const curveDelta = (channel: 'red' | 'green' | 'blue') => {
    const currentCurve = toneCurveChannelLut(current.curve, channel)
    const baseCurve = toneCurveChannelLut(base.curve, channel)
    return currentCurve.map((point, index) => point - baseCurve[index])
  }
  return {
    tone1: [
      delta(current, base, 'exposure'),
      delta(current, base, 'brightness'),
      delta(current, base, 'contrast'),
      currentGamma / baseGamma,
    ],
    tone2: [
      delta(current, base, 'highlights'),
      delta(current, base, 'shadows'),
      delta(current, base, 'whites'),
      delta(current, base, 'blacks'),
    ],
    color1: [
      delta(current, base, 'temperature'),
      delta(current, base, 'tint'),
      delta(current, base, 'saturation'),
      0,
    ],
    color2: [
      value(current, 'colorizeHue'),
      Math.max(0, delta(current, base, 'colorizeAmount')),
      delta(current, base, 'dehaze'),
      0,
    ],
    color3: [
      delta(current, base, 'vibrance'),
      delta(current, base, 'defringe'),
      delta(current, base, 'moire'),
      0,
    ],
    detail1: [
      delta(current, base, 'texture'),
      delta(current, base, 'clarity'),
      0,
      0,
    ],
    detail2: [
      Math.max(0, delta(current, base, 'blur', 40)),
      0,
    ],
    curveDeltaRed: curveDelta('red'),
    curveDeltaGreen: curveDelta('green'),
    curveDeltaBlue: curveDelta('blue'),
    sharpen1: [
      value(current, 'sharpen') / 100,
      value(base, 'sharpen') / 100,
      (value(current, 'sharpenRadius', 1) - 0.5) / 2.5,
      (value(base, 'sharpenRadius', 1) - 0.5) / 2.5,
    ],
    sharpen2: [
      value(current, 'sharpenDetail') / 100,
      value(base, 'sharpenDetail') / 100,
      value(current, 'sharpenMasking') / 100,
      value(base, 'sharpenMasking') / 100,
    ],
    nr1: [
      value(current, 'noiseReduction') / 100,
      value(base, 'noiseReduction') / 100,
      value(current, 'noiseReductionDetail') / 100,
      value(base, 'noiseReductionDetail') / 100,
    ],
    nr2: [
      value(current, 'noiseReductionContrast') / 100,
      value(base, 'noiseReductionContrast') / 100,
      value(current, 'colorNoiseReduction') / 100,
      value(base, 'colorNoiseReduction') / 100,
    ],
    nr3: [
      value(current, 'colorNoiseReductionDetail') / 100,
      value(base, 'colorNoiseReductionDetail') / 100,
      value(current, 'colorNoiseReductionSmoothness') / 100,
      value(base, 'colorNoiseReductionSmoothness') / 100,
    ],
    grain1: [
      value(current, 'noise') / 100,
      value(base, 'noise') / 100,
      value(current, 'grainSize') / 100,
      value(base, 'grainSize') / 100,
    ],
    grain2: [
      value(current, 'grainRoughness', 50) / 100,
      value(base, 'grainRoughness', 50) / 100,
    ],
    ...mixerUniforms(current, base),
    point1: pointReference(current),
    point2: pointShifts(current),
    point3: pointReference(base),
    point4: pointShifts(base),
    grade1: gradeHues(current),
    grade2: gradeSats(current),
    grade3: gradeLums(current),
    grade4: gradeHues(base),
    grade5: gradeSats(base),
    grade6: gradeLums(base),
  }
}

function mixerUniforms(current: AdjustmentValues, base: AdjustmentValues) {
  const deltas = (mode: 'Hue' | 'Sat' | 'Lum') => {
    const currentBands = mixerBandValues(current, mode)
    const baseBands = mixerBandValues(base, mode)
    return currentBands.map((band, index) => (band - baseBands[index]) / 100)
  }
  const hue = deltas('Hue')
  const sat = deltas('Sat')
  const lum = deltas('Lum')
  return {
    mixHue1: hue.slice(0, 4),
    mixHue2: hue.slice(4),
    mixSat1: sat.slice(0, 4),
    mixSat2: sat.slice(4),
    mixLum1: lum.slice(0, 4),
    mixLum2: lum.slice(4),
  }
}

function pointReference(values: AdjustmentValues) {
  return [
    value(values, 'pointHue'),
    value(values, 'pointSat') / 100,
    value(values, 'pointLum') / 100,
    12 + value(values, 'pointRange', 50) * 0.78,
  ]
}

function pointShifts(values: AdjustmentValues) {
  return [
    value(values, 'pointHueShift'),
    value(values, 'pointSatShift') / 100,
    value(values, 'pointLumShift') / 100,
    0,
  ]
}

function gradeHues(values: AdjustmentValues) {
  return [
    value(values, 'gradeShadowHue') / 360,
    value(values, 'gradeMidHue') / 360,
    value(values, 'gradeHighlightHue') / 360,
    value(values, 'gradeBlend', 50) / 100,
  ]
}

function gradeSats(values: AdjustmentValues) {
  return [
    value(values, 'gradeShadowSat') / 100,
    value(values, 'gradeMidSat') / 100,
    value(values, 'gradeHighlightSat') / 100,
    value(values, 'gradeBalance') / 100,
  ]
}

function gradeLums(values: AdjustmentValues) {
  return [
    value(values, 'gradeShadowLum') / 100,
    value(values, 'gradeMidLum') / 100,
    value(values, 'gradeHighlightLum') / 100,
    0,
  ]
}

export class LiveAdjustPreview {
  readonly canvas = document.createElement('canvas')
  private gl: WebGLRenderingContext | null = null
  private program: WebGLProgram | null = null
  private positionBuffer: WebGLBuffer | null = null
  private sourceTexture: WebGLTexture | null = null
  private maskTexture: WebGLTexture | null = null
  private base: AdjustmentValues = {}
  private masked = false

  begin(
    source: HTMLCanvasElement,
    base: AdjustmentValues,
    options: {
      mask?: HTMLCanvasElement | null
      width: number
      height: number
      maxPixels?: number
      maskStrength?: number
    },
  ): boolean {
    const requestedWidth = Math.max(1, Math.round(options.width))
    const requestedHeight = Math.max(1, Math.round(options.height))
    const maxPixels = options.maxPixels ?? 2_000_000
    const scale = Math.min(1, Math.sqrt(maxPixels / (requestedWidth * requestedHeight)))
    const width = Math.max(1, Math.round(requestedWidth * scale))
    const height = Math.max(1, Math.round(requestedHeight * scale))
    if (this.canvas.width !== width) this.canvas.width = width
    if (this.canvas.height !== height) this.canvas.height = height
    this.base = { ...base }
    this.masked = !!options.mask

    let gl = this.gl
    if (!gl) {
      gl = this.canvas.getContext('webgl', {
        alpha: false,
        antialias: false,
        premultipliedAlpha: false,
        preserveDrawingBuffer: true,
      })
      if (!gl) return false
      this.gl = gl
    }

    try {
      let program = this.program
      if (!program) {
        program = gl.createProgram()
        if (!program) return false
        this.program = program
        const vertexShader = compile(gl, gl.VERTEX_SHADER, VERTEX_SHADER)
        const fragmentShader = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER)
        gl.attachShader(program, vertexShader)
        gl.attachShader(program, fragmentShader)
        gl.linkProgram(program)
        gl.deleteShader(vertexShader)
        gl.deleteShader(fragmentShader)
        if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
          throw new Error(gl.getProgramInfoLog(program) || 'Could not link adjustment preview shader.')
        }

        const buffer = gl.createBuffer()
        if (!buffer) throw new Error('Could not allocate adjustment preview vertex buffer.')
        this.positionBuffer = buffer
        gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
        gl.bufferData(
          gl.ARRAY_BUFFER,
          new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]),
          gl.STATIC_DRAW,
        )
        const position = gl.getAttribLocation(program, 'a_position')
        gl.enableVertexAttribArray(position)
        gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0)
      }
      gl.useProgram(program)

      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, 1)
      if (this.sourceTexture) gl.deleteTexture(this.sourceTexture)
      if (this.maskTexture) gl.deleteTexture(this.maskTexture)
      this.sourceTexture = this.uploadTexture(source, 0, width, height)
      const white = document.createElement('canvas')
      white.width = 1
      white.height = 1
      const whiteContext = white.getContext('2d')!
      whiteContext.fillStyle = '#fff'
      whiteContext.fillRect(0, 0, 1, 1)
      this.maskTexture = this.uploadTexture(options.mask ?? white, 1, width, height)
      gl.uniform1i(gl.getUniformLocation(program, 'u_source'), 0)
      gl.uniform1i(gl.getUniformLocation(program, 'u_mask'), 1)
      gl.uniform2f(gl.getUniformLocation(program, 'u_texel'), 1 / width, 1 / height)
      gl.uniform1f(gl.getUniformLocation(program, 'u_masked'), this.masked ? 1 : 0)
      gl.uniform1f(
        gl.getUniformLocation(program, 'u_mask_strength'),
        options.maskStrength ?? 1,
      )
      gl.viewport(0, 0, width, height)
      return true
    } catch (error) {
      console.warn('[imageStack] GPU adjustment preview unavailable', error)
      this.dispose()
      return false
    }
  }

  private uploadTexture(
    source: CanvasImageSource,
    unit: number,
    width: number,
    height: number,
  ) {
    const gl = this.gl!
    const staging = document.createElement('canvas')
    staging.width = width
    staging.height = height
    staging.getContext('2d')!.drawImage(source, 0, 0, width, height)
    const texture = gl.createTexture()
    if (!texture) throw new Error('Could not allocate adjustment preview texture.')
    gl.activeTexture(gl.TEXTURE0 + unit)
    gl.bindTexture(gl.TEXTURE_2D, texture)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
    gl.texImage2D(
      gl.TEXTURE_2D,
      0,
      gl.RGBA,
      gl.RGBA,
      gl.UNSIGNED_BYTE,
      staging,
    )
    return texture
  }

  render(current: AdjustmentValues): HTMLCanvasElement | null {
    const gl = this.gl
    const program = this.program
    if (!gl || !program) return null
    gl.useProgram(program)

    const uniforms = buildLiveAdjustUniforms(current, this.base)
    const set4 = (name: string, values: number[]) =>
      gl.uniform4fv(gl.getUniformLocation(program, name), values)
    const set2 = (name: string, values: number[]) =>
      gl.uniform2fv(gl.getUniformLocation(program, name), values)
    set4('u_tone1', uniforms.tone1)
    set4('u_tone2', uniforms.tone2)
    set4('u_color1', uniforms.color1)
    set4('u_color2', uniforms.color2)
    set4('u_color3', uniforms.color3)
    set4('u_detail1', uniforms.detail1)
    set2('u_detail2', uniforms.detail2)
    gl.uniform1fv(
      gl.getUniformLocation(program, 'u_curve_delta_red[0]'),
      uniforms.curveDeltaRed,
    )
    gl.uniform1fv(
      gl.getUniformLocation(program, 'u_curve_delta_green[0]'),
      uniforms.curveDeltaGreen,
    )
    gl.uniform1fv(
      gl.getUniformLocation(program, 'u_curve_delta_blue[0]'),
      uniforms.curveDeltaBlue,
    )
    set4('u_sharpen1', uniforms.sharpen1)
    set4('u_sharpen2', uniforms.sharpen2)
    set4('u_nr1', uniforms.nr1)
    set4('u_nr2', uniforms.nr2)
    set4('u_nr3', uniforms.nr3)
    set4('u_grain1', uniforms.grain1)
    set2('u_grain2', uniforms.grain2)
    set4('u_mix_hue1', uniforms.mixHue1)
    set4('u_mix_hue2', uniforms.mixHue2)
    set4('u_mix_sat1', uniforms.mixSat1)
    set4('u_mix_sat2', uniforms.mixSat2)
    set4('u_mix_lum1', uniforms.mixLum1)
    set4('u_mix_lum2', uniforms.mixLum2)
    set4('u_point1', uniforms.point1)
    set4('u_point2', uniforms.point2)
    set4('u_point3', uniforms.point3)
    set4('u_point4', uniforms.point4)
    set4('u_grade1', uniforms.grade1)
    set4('u_grade2', uniforms.grade2)
    set4('u_grade3', uniforms.grade3)
    set4('u_grade4', uniforms.grade4)
    set4('u_grade5', uniforms.grade5)
    set4('u_grade6', uniforms.grade6)
    gl.drawArrays(gl.TRIANGLES, 0, 6)
    gl.flush()
    return this.canvas
  }

  dispose() {
    const gl = this.gl
    if (gl) {
      if (this.sourceTexture) gl.deleteTexture(this.sourceTexture)
      if (this.maskTexture) gl.deleteTexture(this.maskTexture)
      if (this.positionBuffer) gl.deleteBuffer(this.positionBuffer)
      if (this.program) gl.deleteProgram(this.program)
    }
    this.gl = null
    this.program = null
    this.positionBuffer = null
    this.sourceTexture = null
    this.maskTexture = null
  }
}
