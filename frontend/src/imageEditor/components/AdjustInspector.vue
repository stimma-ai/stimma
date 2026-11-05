<script setup lang="ts">
/**
 * The selected adjustment step's control surface.
 *
 * Steps are fine-grained now, and the panel only ever shows the one step's own
 * controls: a Light step gets the tone sliders, a Color step the split-tone
 * dials, a strip step (preset or pixel look) gets Amount. The collapsible
 * everything-surface survives only for steps migrated from the snapshot
 * editor, which carry an arbitrary mix of params in one blob.
 *
 * A drag is one undo step, not one per tick, which is what `coalesceKey` on
 * the document's edit recorder is for.
 */
import { computed, ref } from 'vue'
import {
  ADJUST_SECTIONS, adjustControl, effectLookStepOf, levelEditById, lookById,
} from '../stack/adjustSections'
import type { AdjustSliderControl } from '../stack/adjustSections'
import type { ToneCurveHistogram } from '../stack/toneCurve'
import LookControls from './LookControls.vue'
import PhotoAdjustmentControls from './PhotoAdjustmentControls.vue'

const props = defineProps<{
  params: Record<string, any>
  histogram?: ToneCurveHistogram
  disabled?: boolean
  /** Point color only: the canvas eyedropper is currently armed. */
  picking?: boolean
  clipShadows?: boolean
  clipHighlights?: boolean
  /** This step can be converted to a scoped one (it is a level edit). */
  scopeEligible?: boolean
  /** A workspace selection exists to limit to. */
  hasSelection?: boolean
}>()

const emit = defineEmits<{
  change: [Record<string, any>, string]
  commit: []
  /** Point color asks the host view to arm the canvas eyedropper. */
  pick: []
  clip: [{ shadows: boolean; highlights: boolean }]
  /** Convert this whole-image step into one scoped to the selection. */
  limit: []
}>()

function valueOf(control: AdjustSliderControl) {
  const value = props.params?.[control.key]
  return typeof value === 'number' ? value : control.default
}

function setValue(key: string, value: number) {
  emit('change', { [key]: value }, `adjust:${key}`)
}

function setToggle(key: string, value: boolean) {
  emit('change', { [key]: value }, `adjust:${key}`)
}

function setPhotoValue(patch: Record<string, any>, coalesceKey: string) {
  emit('change', patch, coalesceKey)
}

/** A Light / Color / Detail step: its marker names its control set. */
const levelEdit = computed(() =>
  props.params?.section ? levelEditById(props.params.section) ?? null : null
)

/** A Looks step: the strip wrote a bundle and named which look it was. */
const look = computed(() =>
  props.params?.look ? lookById(props.params.look) ?? null : null
)

/**
 * A pixel-look step from the strip: shown as Amount plus the look's own
 * supporting dials. A migrated blob that happens to carry the key never
 * matches and keeps its full surface.
 */
const effectLook = computed(() => {
  if (levelEdit.value || look.value) return null
  return effectLookStepOf(props.params || {}) ?? null
})

const effectControl = computed(() =>
  effectLook.value?.effect ? adjustControl(effectLook.value.effect.key) ?? null : null
)

/** A preset step's only property: how much of it. */
const showsFilterAmount = computed(
  () => !!props.params?.filter && !levelEdit.value
)

/** A step that is ONLY a preset needs nothing else on screen. */
const filterOnly = computed(() =>
  showsFilterAmount.value &&
  Object.keys(props.params || {}).every(key => key === 'filter' || key === 'filterAmount')
)

/** Migrated blob steps keep the old collapsible everything-surface. */
const legacySections = computed(() => {
  if (levelEdit.value || look.value || effectLook.value || filterOnly.value) return null
  return ADJUST_SECTIONS
})

const openSection = ref<string>('levels')
</script>

<template>
  <div class="divide-y divide-edge-subtle">

    <!-- A chosen preset's only property: how much of it. -->
    <section v-if="showsFilterAmount" class="px-3 py-2">
      <label class="flex items-center gap-2 text-xs text-content-tertiary">
        <span class="w-16 shrink-0">Amount</span>
        <input
          type="range" min="0" max="100" step="1" class="flex-1"
          :disabled="disabled"
          :value="params.filterAmount ?? 100"
          @input="emit('change', { filterAmount: Number(($event.target as HTMLInputElement).value) }, 'adjust:filterAmount')"
          @change="emit('commit')"
        />
        <span class="w-8 text-right font-mono tabular-nums">{{ params.filterAmount ?? 100 }}</span>
      </label>
    </section>

    <!-- A pixel look: how much of it, plus the look's own supporting dials. -->
    <section v-else-if="effectLook && effectControl" class="px-3 py-2 space-y-2">
      <label class="flex items-center gap-2 text-xs text-content-tertiary">
        <span class="w-16 shrink-0">Amount</span>
        <input
          type="range" class="flex-1"
          :min="effectControl.min" :max="effectControl.max" :step="effectControl.step"
          :disabled="disabled"
          :value="valueOf(effectControl)"
          @input="setValue(effectControl.key, Number(($event.target as HTMLInputElement).value))"
          @change="emit('commit')"
        />
        <span class="w-8 text-right font-mono tabular-nums">{{ valueOf(effectControl) }}</span>
      </label>
      <label
        v-for="control in effectLook.supporting ?? []"
        :key="control.key"
        class="flex items-center gap-2 text-xs text-content-tertiary"
      >
        <span class="w-16 shrink-0">{{ control.label }}</span>
        <input
          type="range" class="flex-1"
          :min="control.min" :max="control.max" :step="control.step"
          :disabled="disabled"
          :value="valueOf(control)"
          @input="setValue(control.key, Number(($event.target as HTMLInputElement).value))"
          @change="emit('commit')"
        />
        <span class="w-8 text-right font-mono tabular-nums">{{ valueOf(control) }}</span>
      </label>
    </section>

    <!-- A Looks step: the groups the look moved, under their own headers. -->
    <LookControls
      v-if="look"
      :values="params"
      :label="look.label"
      :histogram="histogram"
      :disabled="disabled"
      :picking="picking"
      :clip-shadows="clipShadows"
      :clip-highlights="clipHighlights"
      coalesce-prefix="adjust"
      @change="setPhotoValue"
      @commit="emit('commit')"
      @pick="emit('pick')"
      @clip="emit('clip', $event)"
    />

    <!-- A Light / Color / Detail step: its own sliders, flat — the set is small
         enough that hiding it behind a header would just be a click tax. -->
    <section v-if="levelEdit" class="px-3 py-2">
      <PhotoAdjustmentControls
        :controls="levelEdit.controls"
        :values="params"
        :histogram="histogram"
        :disabled="disabled"
        :presentation="levelEdit.presentation"
        :picking="picking"
        :clip-shadows="clipShadows"
        :clip-highlights="clipHighlights"
        coalesce-prefix="adjust"
        @change="setPhotoValue"
        @commit="emit('commit')"
        @pick="emit('pick')"
        @clip="emit('clip', $event)"
      />
    </section>

    <!-- Migrated blob steps: the full legacy surface. -->
    <template v-if="legacySections">
      <section v-for="section in legacySections" :key="section.id">
        <button
          type="button"
          class="w-full flex items-center gap-2 px-3 py-2 text-left focus-visible:outline-none focus-visible:ring-2 ring-accent/60 rounded-md"
          @click="openSection = openSection === section.id ? '' : section.id"
        >
          <span class="text-xs font-medium text-content-secondary flex-1">{{ section.label }}</span>
          <span
            v-if="section.toggle"
            class="text-[11px] px-1.5 py-0.5 rounded-md"
            :class="params?.[section.toggle.key]
              ? 'bg-selection/20 text-content'
              : 'bg-overlay-subtle text-content-tertiary'"
            @click.stop="setToggle(section.toggle.key, !params?.[section.toggle.key])"
          >
            {{ section.toggle.label }}
          </span>
        </button>

        <div v-if="openSection === section.id" class="px-3 pb-3 space-y-2">
          <label
            v-for="control in section.controls"
            :key="control.key"
            class="flex items-center gap-2"
          >
            <span class="w-28 shrink-0 text-xs text-content-tertiary">{{ control.label }}</span>
            <input
              type="range"
              class="flex-1"
              :min="control.min"
              :max="control.max"
              :step="control.step"
              :disabled="disabled"
              :value="valueOf(control)"
              @input="setValue(control.key, Number(($event.target as HTMLInputElement).value))"
              @change="emit('commit')"
            />
            <span class="w-10 text-right text-xs text-content-tertiary font-mono tabular-nums">
              {{ valueOf(control) }}
            </span>
          </label>
        </div>
      </section>
    </template>

    <!-- Scope: this step covers the whole image; with a live selection it can
         become a scoped step instead, keeping its values. The reverse verb
         lives on the scoped step's own surface. -->
    <section v-if="scopeEligible" class="px-3 py-2 space-y-1.5">
      <h3 class="text-xs font-semibold text-content-secondary">Scope</h3>
      <div class="flex items-center gap-2">
        <span class="flex-1 text-xs text-content-tertiary">Whole image</span>
        <button
          type="button"
          class="px-2 py-1.5 text-xs rounded-md border border-edge-subtle
                 text-content-secondary hover:text-content hover:bg-overlay-subtle
                 disabled:opacity-40 disabled:hover:bg-transparent
                 disabled:hover:text-content-secondary"
          :disabled="!hasSelection"
          :title="hasSelection ? undefined : 'Make a selection first'"
          @click="emit('limit')"
        >
          Limit to selection
        </button>
      </div>
    </section>
  </div>
</template>
