<template>
  <Modal
    :show="show"
    size="custom"
    custom-class="w-full max-w-5xl mx-4 my-8 max-h-[90vh] flex flex-col"
    @close="cancel"
  >
    <template #header>
      <div class="flex items-start gap-3">
        <div class="flex-1 min-w-0">
          <h3 class="text-[14px] font-semibold text-content">{{ titleText }}</h3>
          <p
            v-if="instructions"
            class="text-[12px] text-content-secondary mt-1 whitespace-pre-wrap"
          >{{ instructions }}</p>
        </div>
        <span
          class="flex-shrink-0 inline-flex items-center rounded-full border border-edge-subtle bg-surface-raised px-2.5 py-1 text-[11px] font-medium text-content-secondary"
        >{{ progressText }}</span>
      </div>
    </template>

    <!-- Body: candidate grid -->
    <div class="flex-1 overflow-y-auto px-4 py-3">
      <div
        v-if="normalized.length === 0"
        class="flex items-center justify-center py-8 text-[12px] text-content-muted italic"
      >No candidates available.</div>
      <div
        v-else
        class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2"
      >
        <HitlActionCard
          v-for="c in normalized"
          :key="c.key"
          :media-id="c.mediaId"
          :media-url="c.mediaUrl"
          :mode="count === 1 ? 'select-single' : 'select-multi'"
          :state="isPicked(c) ? 'selected' : 'idle'"
          :label="c.label"
          @select="toggle(c)"
        />
      </div>
    </div>

    <template #footer>
      <span class="text-[11px] text-content-muted mr-auto">
        {{ footerHint }}
      </span>
      <Button variant="secondary" size="sm" @click="cancel">Cancel</Button>
      <Button variant="primary" size="sm" :disabled="!ready" @click="confirm">{{ confirmLabel }}</Button>
    </template>
  </Modal>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import Modal from '../ui/Modal.vue'
import Button from '../ui/Button.vue'
import HitlActionCard from './HitlActionCard.vue'
import {
  normalizeCandidate,
  buildSelectedIdSet,
  isCandidatePicked,
  valuesEquivalent,
  type NormalizedCandidate,
} from '../../utils/hitlCandidates'

interface Props {
  show: boolean
  candidates: any[]
  count: number
  initialSelection?: any[]
  instructions?: string
  title?: string
  confirmLabel?: string
}
const props = withDefaults(defineProps<Props>(), {
  initialSelection: () => [],
  instructions: '',
  title: '',
  confirmLabel: 'Done',
})

const emit = defineEmits<{
  (e: 'cancel'): void
  // Resolution shape: scalar when count === 1, array otherwise. Mirrors the
  // backend hitl.select output shape (ListShape vs scalar element).
  (e: 'confirm', resolution: any): void
}>()

const draftValues = ref<any[]>([])

const normalized = computed<NormalizedCandidate[]>(() =>
  props.candidates.map((c, i) => normalizeCandidate(c, i)),
)

const pickedIds = computed(() => buildSelectedIdSet(draftValues.value))

function isPicked(c: NormalizedCandidate): boolean {
  return isCandidatePicked(c, pickedIds.value)
}

const ready = computed(() => draftValues.value.length === props.count)

const titleText = computed(() => props.title || (props.count === 1 ? 'Pick one' : `Pick ${props.count}`))

const progressText = computed(() => `${draftValues.value.length} / ${props.count}`)

const footerHint = computed(() => {
  if (normalized.value.length === 0) return ''
  if (props.count === 1) return `${normalized.value.length} candidates`
  return `${draftValues.value.length} of ${props.count} picked · ${normalized.value.length} candidates`
})

function toggle(c: NormalizedCandidate) {
  const current = [...draftValues.value]
  // count===1: clicking commits the pick (replaces current); we don't auto-
  // submit because the user may want to change their mind before clicking
  // Done. The single-click-commits behavior of the inline grid was tied to
  // the inline rendering; in a sheet, an explicit confirm is clearer.
  if (props.count === 1) {
    if (valuesEquivalent(current, [c.value])) return
    draftValues.value = [c.value]
    return
  }
  const idx = current.findIndex((v) => valuesEquivalent([v], [c.value]))
  if (idx >= 0) {
    current.splice(idx, 1)
    draftValues.value = current
  } else if (current.length < props.count) {
    current.push(c.value)
    draftValues.value = current
  }
}

function confirm() {
  if (!ready.value) return
  const resolution = props.count === 1 ? draftValues.value[0] : [...draftValues.value]
  emit('confirm', resolution)
}

function cancel() {
  emit('cancel')
}

// Reset the draft to the initial selection each time the sheet opens or the
// initial selection changes. Avoids stale picks when the user closes + reopens
// the sheet on a different equation.
watch(() => [props.show, props.initialSelection], () => {
  if (props.show) {
    draftValues.value = [...props.initialSelection]
  }
}, { immediate: true, deep: true })
</script>
