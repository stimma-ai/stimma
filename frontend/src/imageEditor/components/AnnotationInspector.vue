<script setup lang="ts">
/**
 * The selected annotation's properties.
 *
 * An annotation IS mutable later — its color, its weight, its glow, its text
 * — so by the placement rule everything here belongs in the inspector rather
 * than the toolbar. The toolbar only carries what is consumed at the moment of
 * the gesture: which tool, and the color the next one starts with.
 *
 * Colors use the ported picker, so the annotation surface offers the same
 * spectrum, palette and eyedropper as everywhere else.
 */
import { computed } from 'vue'
import PaintPicker from './PaintPicker.vue'
import ToolbarPopover from './ToolbarPopover.vue'
import ToolIcon from './ToolIcon.vue'
import type { Shape } from '../ported/shapeTypes'
import type { RgbaColor } from '../ported/geometry'
import { TEXT_STYLES, textStyleOfShape, textStylePatch } from '../stack/textStyles'
import type { TextStyleId } from '../stack/textStyles'
import { paintCss } from '../stack/paints'

const props = defineProps<{
  shape: Shape | null
  /** Full canvas object selection; shape remains the primary/fallback. */
  shapes?: Shape[]
  /** Colors sampled from the image, offered alongside the fixed swatches. */
  palette?: RgbaColor[]
}>()

const emit = defineEmits<{
  change: [Record<string, any>, continuous?: boolean]
  commit: []
  remove: []
}>()

const selection = computed<Shape[]>(() =>
  props.shapes?.length ? props.shapes : (props.shape ? [props.shape] : [])
)
const primary = computed<Shape | null>(() => props.shape ?? selection.value[0] ?? null)
const any = computed(() => primary.value as any)
const isMultiple = computed(() => selection.value.length > 1)

function equalValue(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

function isMixedValue(read: (shape: any) => unknown): boolean {
  if (selection.value.length < 2) return false
  const first = read(selection.value[0] as any)
  return selection.value.slice(1).some(shape => !equalValue(read(shape as any), first))
}

function fieldMixed(key: string): boolean {
  return isMixedValue(shape => shape[key])
}

/** The families every OS ships, so nothing here depends on a webfont. */
const FONTS = [
  { id: 'Inter, system-ui, sans-serif', label: 'Sans' },
  { id: 'Georgia, "Times New Roman", serif', label: 'Serif' },
  { id: 'ui-monospace, Menlo, Consolas, monospace', label: 'Mono' },
  { id: '"Comic Sans MS", "Chalkboard SE", cursive', label: 'Casual' },
  { id: 'Impact, "Haettenschweiler", sans-serif', label: 'Poster' },
]

/** A well previews whatever paint it holds, gradient included. */
function wellCss(paint: any) {
  return paintCss(paint)
}

/** Text scale, derived from the box against its measured natural size. */
const textScale = computed(() => {
  const shape = any.value
  if (!shape?.baseHeight) return 1
  return shape.height / shape.baseHeight
})

function setTextScale(scale: number) {
  if (isMultiple.value) return
  const shape = any.value
  if (!shape?.baseHeight) return
  emit('change', { width: shape.baseWidth * scale, height: shape.baseHeight * scale }, true)
}

/** Which controls this kind of shape actually has. */
const STROKE_TYPES = new Set(['rectangle', 'ellipse', 'line', 'curved-arrow', 'path'])
const isText = computed(() =>
  !!selection.value.length && selection.value.every(shape => shape.type === 'text')
)
const hasShapeEffect = computed(() =>
  !!selection.value.length && selection.value.every(shape => shape.type !== 'text')
)
const hasStroke = computed(() =>
  isText.value ||
  (!!selection.value.length && selection.value.every(shape => STROKE_TYPES.has(shape.type)))
)
const hasStrokeWeight = computed(() =>
  !!selection.value.length && selection.value.every(shape => STROKE_TYPES.has(shape.type))
)
const hasFill = computed(() =>
  !!selection.value.length &&
  selection.value.every(shape => shape.type === 'rectangle' || shape.type === 'ellipse')
)
const isPath = computed(() =>
  !!selection.value.length && selection.value.every(shape => shape.type === 'path')
)
const isLine = computed(() =>
  !!selection.value.length &&
  selection.value.every(shape => shape.type === 'line' || shape.type === 'curved-arrow')
)
const isRect = computed(() =>
  !!selection.value.length && selection.value.every(shape => shape.type === 'rectangle')
)
const selectionTitle = computed(() => {
  if (isMultiple.value) return `${selection.value.length} annotations`
  return primary.value?.type.replace('-', ' ') ?? 'Annotation'
})
const strokeKey = computed(() => isText.value ? 'textColor' : 'strokeColor')
const strokeMixed = computed(() => isMixedValue(shape => shape[strokeKey.value]))
const fillMixed = computed(() => fieldMixed('backgroundColor'))
const allowStrokeGradient = computed(() =>
  selection.value.every(shape => shape.type !== 'path')
)

/**
 * How the stroke is laid down, as opposed to what color it is.
 *
 * A pen stroke has a character — how hard its edge is, how much paint each
 * stamp lays, how far apart the stamps fall, and how much they wander. The old
 * editor exposed all of it and a Path without it is just a colored line.
 */
const PATH_STYLE = [
  { key: 'hardness', label: 'Hardness', min: 0, max: 100, step: 1, fallback: 100 },
  { key: 'flow', label: 'Flow', min: 1, max: 100, step: 1, fallback: 100 },
  { key: 'spacing', label: 'Spacing', min: 1, max: 100, step: 1, fallback: 25 },
  { key: 'jitter', label: 'Jitter', min: 0, max: 100, step: 1, fallback: 0 },
  { key: 'scatter', label: 'Scatter', min: 0, max: 100, step: 1, fallback: 0 },
]

/** Ends, so an arrow can be an arrow at either end or neither. */
const LINE_ENDS = [
  { id: 'none', label: 'None' },
  { id: 'arrow', label: 'Arrow' },
  { id: 'arrow-solid', label: 'Solid arrow' },
  { id: 'circle', label: 'Circle' },
  { id: 'circle-solid', label: 'Solid circle' },
  { id: 'square', label: 'Square' },
  { id: 'square-solid', label: 'Solid square' },
  { id: 'bar', label: 'Bar' },
]

function numberOr(key: string, fallback: number): number {
  const value = any.value?.[key]
  return typeof value === 'number' ? value : fallback
}

/**
 * Effects, in the vocabulary each kind of shape actually has.
 *
 * Text has presets, not a checkbox: "Pill" is a background box with no effect
 * and "Outline" is an effect with no box, so a boolean could name neither and
 * unchecking it stranded the text in a style the toolbar could not have made.
 * Everything else has the universal one. Gradient is absent from both lists on
 * purpose — it is a color, picked in the wells above.
 */
const SHAPE_EFFECTS: { id: 'none' | 'neon'; label: string }[] = [
  { id: 'none', label: 'None' },
  { id: 'neon', label: 'Neon' },
]

const textStyle = computed<TextStyleId>(() => textStyleOfShape(any.value))
const textStyleMixed = computed(() =>
  isMixedValue(shape => textStyleOfShape(shape))
)

function setTextStyle(style: TextStyleId) {
  emit('change', textStylePatch(style, { glowIntensity: any.value?.glowIntensity }))
}

const shapeEffect = computed<'none' | 'neon'>(() => any.value?.style?.effect ?? 'none')
const shapeEffectMixed = computed(() =>
  isMixedValue(shape => shape.style?.effect ?? 'none')
)

function setShapeEffect(effect: 'none' | 'neon') {
  if (effect === 'none') {
    emit('change', { style: undefined })
    return
  }
  emit('change', {
    style: {
      ...(any.value?.style || {}),
      effect,
      glowIntensity: any.value?.style?.glowIntensity ?? 60,
    },
  })
}

/** Whether a glow slider is live, in either vocabulary. */
const glowOn = computed(() =>
  isText.value
    ? selection.value.every(shape => textStyleOfShape(shape as any) === 'neon')
    : selection.value.every(shape => (shape as any).style?.effect === 'neon')
)

function setGlowIntensity(value: number) {
  if (isText.value) emit('change', { glowIntensity: value }, true)
  else emit(
    'change',
    { style: { ...(any.value?.style || {}), effect: 'neon', glowIntensity: value } },
    true,
  )
}

const glowIntensity = computed(() =>
  (isText.value ? any.value?.glowIntensity : any.value?.style?.glowIntensity) ?? 60
)
const glowIntensityMixed = computed(() =>
  isMixedValue(shape =>
    isText.value ? shape.glowIntensity : shape.style?.glowIntensity
  )
)
const opacityMixed = computed(() => fieldMixed('opacity'))
</script>

<template>
  <div v-if="primary" class="divide-y divide-edge-subtle">
    <header class="px-3 py-2 flex items-center gap-2">
      <h3 class="text-sm text-content flex-1" :class="{ capitalize: !isMultiple }">
        {{ selectionTitle }}
      </h3>
      <button
        type="button"
        class="p-1 rounded-md text-content-tertiary hover:text-red-400 hover:bg-overlay-subtle"
        :aria-label="isMultiple ? `Delete ${selection.length} annotations` : 'Delete annotation'"
        @click="emit('remove')"
      >
        <ToolIcon name="trash" />
      </button>
    </header>

    <section v-if="isText" class="px-3 py-2 space-y-2">
      <textarea
        v-if="!isMultiple"
        class="w-full px-2 py-1.5 text-sm rounded-md bg-surface-raised text-content resize-none focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
        rows="2"
        :value="any.text"
        @input="emit('change', { text: ($event.target as HTMLTextAreaElement).value }, true)"
        @change="emit('commit')"
      />
      <select
        class="w-full px-2 py-1.5 text-xs rounded-md bg-surface-raised text-content focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
        :value="fieldMixed('fontFamily') ? '' : any.fontFamily"
        @change="emit('change', { fontFamily: ($event.target as HTMLSelectElement).value })"
      >
        <option v-if="fieldMixed('fontFamily')" value="" disabled>Mixed</option>
        <option v-for="font in FONTS" :key="font.id" :value="font.id" :style="{ fontFamily: font.id }">
          {{ font.label }}
        </option>
      </select>

      <div class="flex items-center gap-1">
        <button
          type="button"
          class="px-2 py-1 text-[11px] rounded-md font-bold"
          :class="!fieldMixed('fontWeight') && any.fontWeight === 'bold'
            ? 'bg-selection/20 text-content'
            : 'text-content-secondary hover:text-content hover:bg-overlay-subtle'"
          aria-label="Bold"
          @click="emit('change', {
            fontWeight: fieldMixed('fontWeight') || any.fontWeight !== 'bold' ? 'bold' : 'normal'
          })"
        >
          <ToolIcon name="bold" />
        </button>
        <button
          type="button"
          class="px-2 py-1 text-[11px] rounded-md"
          :class="!fieldMixed('fontStyle') && any.fontStyle === 'italic'
            ? 'bg-selection/20 text-content'
            : 'text-content-secondary hover:text-content hover:bg-overlay-subtle'"
          aria-label="Italic"
          @click="emit('change', {
            fontStyle: fieldMixed('fontStyle') || any.fontStyle !== 'italic' ? 'italic' : 'normal'
          })"
        >
          <ToolIcon name="italic" />
        </button>
        <span class="w-px h-4 bg-edge-subtle mx-1" />
        <button
          v-for="align in [
            { id: 'left', icon: 'alignLeft' },
            { id: 'center', icon: 'alignCenter' },
            { id: 'right', icon: 'alignRight' },
          ]"
          :key="align.id"
          type="button"
          class="px-2 py-1 rounded-md"
          :class="!fieldMixed('textAlign') && any.textAlign === align.id
            ? 'bg-selection/20 text-content'
            : 'text-content-secondary hover:text-content hover:bg-overlay-subtle'"
          :aria-label="align.id"
          @click="emit('change', { textAlign: align.id })"
        >
          <ToolIcon :name="(align.icon as any)" />
        </button>
      </div>

      <label v-if="!isMultiple" class="flex items-center gap-2 text-xs text-content-tertiary">
        Size
        <input
          type="range" min="0.2" max="4" step="0.05" class="flex-1"
          :value="textScale"
          @input="setTextScale(Number(($event.target as HTMLInputElement).value))"
          @change="emit('commit')"
        />
        <span class="w-8 text-right font-mono tabular-nums">{{ textScale.toFixed(1) }}×</span>
      </label>
    </section>

    <section v-if="hasStroke" class="px-3 py-2 space-y-2">
      <div class="flex items-center gap-2">
        <span class="text-[11px] text-content-tertiary flex-1">{{ isText ? 'Text' : 'Stroke' }}</span>
        <span v-if="strokeMixed" class="text-[11px] text-content-muted">Mixed</span>
        <ToolbarPopover label="" :width="292">
          <template #trigger>
            <span class="color-well">
              <span :style="{ background: wellCss(isText ? any.textColor : any.strokeColor) }" />
            </span>
          </template>
          <PaintPicker
            :model-value="isText ? any.textColor : any.strokeColor"
            :image-palette="palette"
            :allow-gradient="allowStrokeGradient"
            @update:model-value="emit('change', isText ? { textColor: $event } : { strokeColor: $event })"
          />
        </ToolbarPopover>
      </div>
      <label v-if="hasStrokeWeight" class="flex items-center gap-2 text-xs text-content-tertiary">
        Weight
        <input
          type="range" min="1" max="60" class="flex-1"
          :value="any.strokeWidth ?? 8"
          @input="emit(
            'change',
            { strokeWidth: Number(($event.target as HTMLInputElement).value) },
            true,
          )"
          @change="emit('commit')"
        />
        <span class="w-10 text-right font-mono tabular-nums">
          {{ fieldMixed('strokeWidth') ? 'Mixed' : Math.round(any.strokeWidth ?? 8) }}
        </span>
      </label>
    </section>

    <!-- Stroke style: how the line is laid down, not what color it is. -->
    <section v-if="isPath" class="px-3 py-2 space-y-2">
      <label
        v-for="control in PATH_STYLE"
        :key="control.key"
        class="flex items-center gap-2 text-xs text-content-tertiary"
      >
        <span class="w-16 shrink-0">{{ control.label }}</span>
        <input
          type="range"
          class="flex-1"
          :min="control.min" :max="control.max" :step="control.step"
          :value="numberOr(control.key, control.fallback)"
          @input="emit(
            'change',
            { [control.key]: Number(($event.target as HTMLInputElement).value) },
            true,
          )"
          @change="emit('commit')"
        />
        <span class="w-10 text-right font-mono tabular-nums">
          {{ fieldMixed(control.key) ? 'Mixed' : numberOr(control.key, control.fallback) }}
        </span>
      </label>
    </section>

    <section v-if="isLine" class="px-3 py-2 space-y-2">
      <label class="flex items-center gap-2 text-xs text-content-tertiary">
        <span class="w-16 shrink-0">Start</span>
        <select
          class="flex-1 px-2 py-1 text-xs rounded-md bg-surface-raised text-content focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
          :value="fieldMixed('lineStart') ? '' : (any.lineStart ?? 'none')"
          @change="emit('change', { lineStart: ($event.target as HTMLSelectElement).value })"
        >
          <option v-if="fieldMixed('lineStart')" value="" disabled>Mixed</option>
          <option v-for="end in LINE_ENDS" :key="end.id" :value="end.id">{{ end.label }}</option>
        </select>
      </label>
      <label class="flex items-center gap-2 text-xs text-content-tertiary">
        <span class="w-16 shrink-0">End</span>
        <select
          class="flex-1 px-2 py-1 text-xs rounded-md bg-surface-raised text-content focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
          :value="fieldMixed('lineEnd') ? '' : (any.lineEnd ?? 'none')"
          @change="emit('change', { lineEnd: ($event.target as HTMLSelectElement).value })"
        >
          <option v-if="fieldMixed('lineEnd')" value="" disabled>Mixed</option>
          <option v-for="end in LINE_ENDS" :key="end.id" :value="end.id">{{ end.label }}</option>
        </select>
      </label>
    </section>

    <section v-if="isRect" class="px-3 py-2">
      <label class="flex items-center gap-2 text-xs text-content-tertiary">
        <span class="w-16 shrink-0">Corners</span>
        <input
          type="range" min="0" max="80" step="1" class="flex-1"
          :value="numberOr('cornerRadius', 0)"
          @input="emit(
            'change',
            { cornerRadius: Number(($event.target as HTMLInputElement).value) },
            true,
          )"
          @change="emit('commit')"
        />
        <span class="w-10 text-right font-mono tabular-nums">
          {{ fieldMixed('cornerRadius') ? 'Mixed' : numberOr('cornerRadius', 0) }}
        </span>
      </label>
    </section>

    <section v-if="hasFill || isText" class="px-3 py-2 space-y-2">
      <div class="flex items-center gap-2">
        <span class="text-[11px] text-content-tertiary flex-1">{{ isText ? 'Background' : 'Fill' }}</span>
        <span v-if="fillMixed" class="text-[11px] text-content-muted">Mixed</span>
        <ToolbarPopover label="" :width="292">
          <template #trigger>
            <span class="color-well">
              <span :style="{ background: wellCss(any.backgroundColor) }" />
            </span>
          </template>
          <PaintPicker
            :model-value="any.backgroundColor ?? null"
            :image-palette="palette"
            :allow-gradient="!isPath"
            allow-null
            @update:model-value="emit('change', { backgroundColor: $event ?? undefined })"
          />
        </ToolbarPopover>
      </div>
    </section>

    <section class="px-3 py-2 space-y-2">
      <!-- Style, in the same words the toolbar used to arm the tool. -->
      <div v-if="isText || hasShapeEffect" class="space-y-1.5">
        <span class="block text-[11px] text-content-tertiary">{{ isText ? 'Style' : 'Effect' }}</span>
        <div class="flex flex-wrap gap-1">
          <template v-if="isText">
            <button
              v-for="style in TEXT_STYLES"
              :key="style.id"
              type="button"
              class="px-2 py-1 text-[11px] rounded-md transition-colors"
              :class="!textStyleMixed && textStyle === style.id
                ? 'bg-selection/15 text-content'
                : 'text-content-secondary hover:text-content hover:bg-overlay-subtle'"
              @click="setTextStyle(style.id)"
            >
              {{ style.label }}
            </button>
          </template>
          <template v-else>
            <button
              v-for="fx in SHAPE_EFFECTS"
              :key="fx.id"
              type="button"
              class="px-2 py-1 text-[11px] rounded-md transition-colors"
              :class="!shapeEffectMixed && shapeEffect === fx.id
                ? 'bg-selection/15 text-content'
                : 'text-content-secondary hover:text-content hover:bg-overlay-subtle'"
              @click="setShapeEffect(fx.id)"
            >
              {{ fx.label }}
            </button>
          </template>
        </div>
      </div>

      <label v-if="glowOn" class="flex items-center gap-2 text-xs text-content-tertiary">
        Glow
        <input
          type="range" min="0" max="100" class="flex-1"
          :value="glowIntensity"
          @input="setGlowIntensity(Number(($event.target as HTMLInputElement).value))"
          @change="emit('commit')"
        />
        <span class="w-10 text-right font-mono tabular-nums">
          {{ glowIntensityMixed ? 'Mixed' : glowIntensity }}
        </span>
      </label>
      <label class="flex items-center gap-2 text-xs text-content-tertiary">
        Opacity
        <input
          type="range" min="0" max="1" step="0.05" class="flex-1"
          :value="any.opacity ?? 1"
          @input="emit(
            'change',
            { opacity: Number(($event.target as HTMLInputElement).value) },
            true,
          )"
          @change="emit('commit')"
        />
        <span v-if="opacityMixed" class="w-10 text-right font-mono tabular-nums">Mixed</span>
      </label>
    </section>
  </div>
</template>

<style scoped>
/*
 * A color well, not a dot. Wide enough to read the color at a glance and
 * backed by a checkerboard so "no fill" is visibly no fill rather than
 * whatever the panel behind it happens to be.
 */
.color-well {
  width: 34px;
  height: 20px;
  border-radius: 4px;
  border: 1px solid rgb(var(--color-text-primary-rgb) / 0.18);
  overflow: hidden;
  display: block;
  background-image:
    linear-gradient(45deg, rgb(var(--color-text-primary-rgb) / 0.14) 25%, transparent 25%),
    linear-gradient(-45deg, rgb(var(--color-text-primary-rgb) / 0.14) 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, rgb(var(--color-text-primary-rgb) / 0.14) 75%),
    linear-gradient(-45deg, transparent 75%, rgb(var(--color-text-primary-rgb) / 0.14) 75%);
  background-size: 8px 8px;
  background-position: 0 0, 0 4px, 4px -4px, -4px 0;
}

.color-well > span {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
