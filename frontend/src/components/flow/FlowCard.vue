<template>
  <div
    class="flex items-center gap-4 px-6 py-3 transition-colors cursor-pointer hover:bg-overlay-subtle"
    @click="handleClick"
    @contextmenu="$emit('contextmenu', $event, flow)"
  >
    <!-- Thumbnail / status -->
    <div
      v-if="heroMediaId != null"
      class="flex-shrink-0 w-10 h-10 rounded-media overflow-hidden bg-matte"
    >
      <MediaImage
        :media-id="heroMediaId"
        :thumbnail="true"
        :thumbnail-size="128"
        :draggable="false"
        :enable-context-menu="false"
        container-class="w-full h-full"
        img-class="w-full h-full object-cover"
      />
    </div>
    <div v-else class="flex-shrink-0 w-10 h-10 rounded-media bg-matte flex items-center justify-center">
      <svg class="w-5 h-5 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
      </svg>
    </div>

    <!-- Name + parent; time/outputs share the same two lines -->
    <div class="flex-1 min-w-0">
      <div class="flex items-center gap-3">
        <template v-if="editing">
          <input
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
        </template>
        <template v-else>
          <span
            v-if="flow.name"
            class="text-[14px] text-content font-medium truncate"
          >
            {{ flow.name }}
          </span>
          <span
            v-else
            @click.stop="beginEdit"
            class="text-[14px] text-content-muted italic truncate cursor-pointer hover:text-content-secondary"
          >
            Name this flow...
          </span>
          <FlowStatusPill
            :flow-id="flow.id"
            show-pending
            text-class="text-[11.5px] text-content-muted whitespace-nowrap"
          />
          <span class="flex-1"></span>
          <span v-if="flow.updated_at" class="flex-shrink-0 text-xs font-mono tabular-nums text-content-tertiary whitespace-nowrap">
            {{ formatRelative(flow.updated_at) }}
          </span>
        </template>
      </div>
      <div v-if="!editing" class="flex items-center gap-3 mt-1">
        <div v-if="parentName" class="flex-1 min-w-0 text-[12px] text-content-muted truncate">
          based on {{ parentName }}
        </div>
        <div v-else-if="flow.description" class="flex-1 min-w-0 text-[12px] text-content-muted truncate">
          {{ flow.description }}
        </div>
        <span v-else class="flex-1"></span>

        <!-- Output asset strip: up to 3 tiles overlap stacked-avatar style,
             mirrors the collapsed-header treatment in EquationTraceRow /
             IterationGroup so a flow row reads as a live preview of its
             surfaced outputs, not just a generic bolt glyph. -->
        <div
          v-if="stripMediaIds.length > 0"
          class="hidden sm:flex flex-shrink-0 items-center justify-end"
        >
          <div
            v-for="(mid, i) in stripMediaIds"
            :key="mid"
            class="w-7 h-7 rounded-media border border-surface overflow-hidden bg-matte"
            :class="i > 0 ? '-ml-2' : ''"
            :style="{ zIndex: stripMediaIds.length - i }"
          >
            <MediaImage
              :media-id="mid"
              :thumbnail="true"
              :thumbnail-size="128"
              :draggable="false"
              :enable-context-menu="false"
              container-class="w-full h-full"
              img-class="w-full h-full object-cover"
            />
          </div>
          <span
            v-if="extraCount > 0"
            class="ml-1.5 text-[10.5px] font-mono text-content-muted tabular-nums"
          >+{{ extraCount }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useFlowsApi, type Flow, type FlowEquation } from '../../composables/useFlowsApi'
import { computeFlowOutputs } from '../../composables/useFlowOutputs'
import { useWebSocket } from '../../composables/useWebSocket'
import FlowStatusPill from './FlowStatusPill.vue'
import { MediaImage } from '../media'

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

const editing = ref(false)
const editingName = ref('')
const editInputRef = ref<HTMLInputElement | null>(null)

// Output media for the hero avatar + strip. Populated by a lazy listEquations
// fetch per row — the flow list endpoint doesn't aggregate output media, so
// each card pulls its own equations and derives outputs via the same
// computeFlowOutputs helper the flow detail view uses.
const outputMediaIds = ref<number[]>([])

const heroMediaId = computed<number | null>(() => outputMediaIds.value[0] ?? null)
const stripMediaIds = computed<number[]>(() => outputMediaIds.value.slice(1, 4))
const extraCount = computed<number>(() =>
  Math.max(0, outputMediaIds.value.length - 1 - stripMediaIds.value.length)
)

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

function formatRelative(ts: string): string {
  const d = new Date(ts)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return 'now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)}d`
  const opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' }
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = '2-digit'
  return d.toLocaleDateString(undefined, opts)
}
</script>
