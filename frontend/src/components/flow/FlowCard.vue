<template>
  <CollectionRow
    trailing-width="10.5rem"
    @click="handleClick"
    @contextmenu="$emit('contextmenu', $event, flow)"
  >
    <template #thumb>
      <RowThumb :media-id="heroMediaId" :thumbnail-size="128">
        <svg class="w-icon-nav h-icon-nav" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
        </svg>
      </RowThumb>
    </template>

    <template #title>
      <input
        v-if="editing"
        v-no-autocorrect
        ref="editInputRef"
        v-model="editingName"
        @blur="saveName"
        @keydown.enter="saveName"
        @keydown.esc.prevent="cancelEdit"
        @click.stop
        class="text-sm text-content font-medium bg-surface-raised border border-transparent rounded-md px-2 py-0.5 outline-none focus:border-accent focus-visible:ring-2 ring-accent/40 flex-1 min-w-0"
        placeholder="Name this flow..."
      />
      <span
        v-else-if="flow.name"
        class="line-clamp-2 min-w-0 flex-1 text-[14px] font-medium leading-5 text-content"
      >
        {{ flow.name }}
      </span>
      <span
        v-else
        @click.stop="beginEdit"
        class="line-clamp-2 min-w-0 flex-1 cursor-pointer text-[14px] italic leading-5 text-content-muted hover:text-content-secondary"
      >
        Name this flow...
      </span>
    </template>

    <template v-if="!editing && (parentName || flow.description)" #preview>
      <p class="truncate text-[13px] leading-5 text-content-muted">
        <template v-if="parentName">based on {{ parentName }}</template>
        <template v-else>{{ plainPreview(flow.description) }}</template>
      </p>
    </template>

    <!-- Status: the row's one fact, in the shared trailing column. A flow at
         rest (Done, Idle) is quiet muted text with no dot, so the states that
         want attention stand out: "Your turn" wears the accent and a heavier
         weight, a failure its red, a running or paused flow its dot. -->
    <template v-if="!editing" #trailing>
      <span class="inline-flex min-w-0 items-center gap-1.5 whitespace-nowrap text-[11.5px]" :class="statusTextClass">
        <span v-if="!atRest" class="h-1.5 w-1.5 flex-shrink-0 rounded-full" :class="statusDotClass"></span>
        <span class="truncate">{{ statusText }}</span>
      </span>
    </template>

    <template v-if="!editing" #date>
      {{ flow.updated_at ? formatRelativeShort(flow.updated_at) : '' }}
    </template>
  </CollectionRow>
</template>

<script setup lang="ts">
import { formatRelativeShort } from '../../utils/timeFormat'
import { displayFlowStatus } from '../../utils/flowStatus'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useFlowsApi, type Flow, type FlowEquation } from '../../composables/useFlowsApi'
import { computeFlowOutputs } from '../../composables/useFlowOutputs'
import { useWebSocket } from '../../composables/useWebSocket'
import { useFlowCounts } from '../../composables/useFlowCounts'
import CollectionRow from '../lists/CollectionRow.vue'
import RowThumb from '../lists/RowThumb.vue'
import { useFlowStatus } from '../../composables/useFlowStatus'
import { mapFlowStatus, textClass } from '../../utils/statusColors'
import { plainPreview } from '../lists/previewText'
import { useViewport } from '../../composables/useViewport'

interface Props {
  flow: Flow
  parentName?: string | null
  startEditing?: boolean
}
const props = withDefaults(defineProps<Props>(), { parentName: null, startEditing: false })
const emit = defineEmits<{
  (e: 'open', flow: Flow): void
  (e: 'contextmenu', event: MouseEvent, flow: Flow): void
  (e: 'rename', flow: Flow, newName: string): void
  (e: 'rename-cancelled'): void
}>()

const api = useFlowsApi()
const { on } = useWebSocket()

const { width } = useViewport()
const { label: statusLabel, dotClass: statusDotClass } = useFlowStatus(computed(() => props.flow.id))
const { countFor } = useFlowCounts()
// "Your Turn" is the backend's status value; only its display is sentence case.
const statusText = computed(() => {
  const label = displayFlowStatus(statusLabel.value)
  const pending = countFor(props.flow.id)
  if (width.value === 'narrow' || pending <= 0 || label === 'Error' || label === 'Tool unavailable') return label
  return `${label} · ${pending} pending`
})
const atRest = computed(() => statusLabel.value === 'Done' || statusLabel.value === 'Idle')
const statusTextClass = computed(() => {
  const label = statusLabel.value
  if (label === 'Your Turn') return 'font-semibold text-accent-hi'
  if (atRest.value) return 'text-content-muted'
  if (label === 'Error' || label === 'Tool unavailable') return `font-medium ${textClass(mapFlowStatus(label))}`
  return 'text-content-tertiary'
})

const editing = ref(false)
const editingName = ref('')
const editInputRef = ref<HTMLInputElement | null>(null)

// Output media for the hero thumbnail. Populated by a lazy listEquations
// fetch per row — the flow list endpoint doesn't aggregate output media, so
// each card pulls its own equations and derives outputs via the same
// computeFlowOutputs helper the flow detail view uses.
const outputMediaIds = ref<number[]>([])

const heroMediaId = computed<number | null>(() => outputMediaIds.value[0] ?? null)

let loadSeq = 0
let reloadTimer: ReturnType<typeof setTimeout> | null = null

async function loadOutputs() {
  const id = props.flow.id
  const seq = ++loadSeq
  try {
    const eqs: FlowEquation[] = await api.listEquations(id)
    if (seq !== loadSeq) return
    const byKey = new Map<string, FlowEquation>()
    for (const eq of eqs) byKey.set(eq.equation_key, eq)
    outputMediaIds.value = computeFlowOutputs(byKey).map((o) => o.mediaId)
  } catch {
    if (seq !== loadSeq) return
    outputMediaIds.value = []
  }
}

function scheduleReload() {
  if (reloadTimer) clearTimeout(reloadTimer)
  reloadTimer = setTimeout(() => {
    reloadTimer = null
    loadOutputs()
  }, 250)
}

const unsubs: Array<() => void> = []

watch(
  () => props.startEditing,
  (should) => {
    if (should) beginEdit()
  },
  { immediate: true }
)

// Re-fetch when switching to a different flow instance within the same card.
watch(() => props.flow.id, () => { loadOutputs() })

onMounted(() => {
  loadOutputs()
  // Live updates: each persisted equation status transition fires
  // flow_equation_updated with a flow_id payload. Debounced so a cascade
  // of events from one invalidation coalesces into a single refetch.
  unsubs.push(on('flow_equation_updated', (data: any) => {
    if (data?.flow_id === props.flow.id) scheduleReload()
  }))
})

onUnmounted(() => {
  if (reloadTimer) { clearTimeout(reloadTimer); reloadTimer = null }
  for (const u of unsubs) { try { u() } catch {} }
  unsubs.length = 0
})

function handleClick() {
  if (editing.value) return
  emit('open', props.flow)
}

function beginEdit() {
  editingName.value = props.flow.name || ''
  editing.value = true
  nextTick(() => {
    editInputRef.value?.focus()
    editInputRef.value?.select()
  })
}

function saveName() {
  if (!editing.value) return
  const newName = editingName.value.trim()
  editing.value = false
  if (newName !== (props.flow.name || '')) {
    emit('rename', props.flow, newName)
  } else {
    emit('rename-cancelled')
  }
}

function cancelEdit() {
  editing.value = false
  editingName.value = ''
  emit('rename-cancelled')
}
</script>
