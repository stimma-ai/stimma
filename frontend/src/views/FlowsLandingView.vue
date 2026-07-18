<template>
  <div class="h-full flex flex-col bg-base">
    <!-- Header -->
    <div class="flex items-center justify-between px-6 py-5 border-b border-edge-subtle">
      <h1 class="text-xl font-semibold leading-none text-content">Flows</h1>

      <div class="flex items-center gap-3">
        <button
          class="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-content-tertiary transition-colors hover:bg-overlay-subtle hover:text-content-secondary"
          @click="createFlow"
        >
          <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          <span>New</span>
        </button>
        <div class="relative">
          <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-content-muted" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
          </svg>
          <input v-no-autocorrect
            v-model="searchQuery"
            type="text"
            placeholder="Search flows..."
            class="bg-overlay-subtle border border-edge-subtle rounded-lg pl-9 pr-3 py-1.5 text-sm text-content-secondary placeholder-white/30 focus:outline-none focus:border-accent w-48"
          />
        </div>
      </div>
    </div>

    <!-- Content -->
    <div class="flex-1 overflow-y-auto">
      <ConnectionError v-if="loadError" @retry="load" />

      <div v-else-if="loading" class="flex items-center justify-center h-32 text-content-muted">
        Loading flows…
      </div>

      <template v-else>
        <!-- Toolbar: count · sort -->
        <div class="flex items-center gap-3 px-6 py-3 border-b border-edge-subtle text-[12px]">
          <span class="text-content-muted">
            {{ displayed.length }} of {{ flows.length }} {{ flows.length === 1 ? 'flow' : 'flows' }}
          </span>
          <div class="flex-1" />
          <div class="flex items-center gap-1.5 text-content-muted">
            <span>Sort</span>
            <select
              v-model="sortKey"
              class="bg-overlay-subtle border border-edge-subtle rounded px-2 py-1 text-content-secondary focus:outline-none focus:border-accent"
            >
              <option value="updated">Recently updated</option>
              <option value="name">Name</option>
              <option value="status">Status</option>
            </select>
          </div>
        </div>

        <!-- Unified list -->
        <div v-if="displayed.length === 0" class="px-6 py-16 text-center">
          <template v-if="flows.length === 0">
            <div class="mx-auto max-w-md space-y-2">
              <p class="text-content-secondary text-sm">No flows yet.</p>
              <p class="text-content-muted text-xs leading-relaxed">
                Flows are repeatable creative workflows — define inputs once, then run them again with different settings to generate new assets.
              </p>
              <button
                class="mt-4 inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm text-content-secondary bg-overlay-subtle border border-edge-subtle transition-colors hover:bg-overlay hover:text-content"
                @click="createFlow"
              >
                <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
                </svg>
                <span>New flow</span>
              </button>
            </div>
          </template>
          <template v-else>
            <p class="text-content-muted text-sm">No flows match your search.</p>
          </template>
        </div>
        <div v-else class="py-2">
          <FlowCard
            v-for="r in displayed"
            :key="r.id"
            :flow="r"
            :parent-name="parentName(r)"
            :start-editing="renamingId === r.id"
            @open="openFlow"
            @contextmenu="handleCardContextMenu"
            @rename="handleInlineRename"
            @rename-cancelled="renamingId = null"
          />
        </div>
      </template>
    </div>

    <EntityContextMenu
      @open="handleContextMenuOpen"
      @delete="handleContextMenuDelete"
      @rename="handleContextMenuRename"
      @move-to-project="handleContextMenuMoveToProject"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted , watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import FlowCard from '../components/flow/FlowCard.vue'
import ConnectionError from '../components/ConnectionError.vue'
import EntityContextMenu from '../components/EntityContextMenu.vue'
import { useFlowsApi, type Flow } from '../composables/useFlowsApi'
import { useFlowCounts } from '../composables/useFlowCounts'
import { deriveFlowStatusLabel, type FlowStatusLabel } from '../composables/useFlowStatus'
import { useWebSocket } from '../composables/useWebSocket'
import { useEntityContextMenu } from '../composables/useEntityContextMenu'
import { useToasts } from '../composables/useToasts'

type SortKey = 'updated' | 'name' | 'status'

const router = useRouter()
const api = useFlowsApi()
const { stateFor: flowState, summaryFor: flowSummary, hasLoadErrorFor: flowHasLoadError } = useFlowCounts()
const { on } = useWebSocket()
const entityContextMenu = useEntityContextMenu()
const { addToast } = useToasts()

const props = defineProps<{ projectId?: number | null }>()

const flows = ref<Flow[]>([])
const loading = ref(false)
const loadError = ref<string | null>(null)
const searchQuery = ref('')

// Global search "View all" handoff: seed the local filter from ?q= so the
// omnibox's per-type result caps never hide matches for good.
const route = useRoute()
watch(() => route.query.q, (q) => {
  if (typeof q === 'string' && q) searchQuery.value = q
}, { immediate: true })
const renamingId = ref<number | null>(null)
const sortKey = ref<SortKey>('updated')
const unsubs: Array<() => void> = []

async function load() {
  loading.value = true
  loadError.value = null
  try {
    const params = props.projectId ? { project_id: props.projectId } : {}
    flows.value = await api.listFlows(params)
  } catch (err: any) {
    loadError.value = err?.message || 'Failed to load flows'
  } finally {
    loading.value = false
  }
}

function statusLabelFor(r: Flow): FlowStatusLabel {
  return deriveFlowStatusLabel(flowState(r.id), flowSummary(r.id), flowHasLoadError(r.id))
}

// Sort priority mirrors the FlowStatusPill workflow order so a "Status"
// sort surfaces what needs attention first: your turn > error > running >
// paused > idle > done. Lower = earlier in the list.
const STATUS_ORDER: Record<FlowStatusLabel, number> = {
  'Your Turn': 0,
  'Error':     1,
  'Running':   2,
  'Paused':    3,
  'Idle':      4,
  'Done':      5,
}

const displayed = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  let list = flows.value.filter(r => {
    if (q) {
      const hay = ((r.name || '') + ' ' + (r.description || '')).toLowerCase()
      if (!hay.includes(q)) return false
    }
    return true
  })
  list = [...list]
  switch (sortKey.value) {
    case 'name':
      list.sort((a, b) => (a.name || '').localeCompare(b.name || '') || a.id - b.id)
      break
    case 'status':
      list.sort((a, b) => {
        const sa = STATUS_ORDER[statusLabelFor(a)]
        const sb = STATUS_ORDER[statusLabelFor(b)]
        if (sa !== sb) return sa - sb
        return (b.updated_at || '').localeCompare(a.updated_at || '')
      })
      break
    case 'updated':
    default:
      list.sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''))
      break
  }
  return list
})

function parentName(r: Flow): string | null {
  if (!r.parent_id) return null
  const parent = flows.value.find(x => x.id === r.parent_id)
  return parent?.name || `Flow #${r.parent_id}`
}

function openFlow(r: Flow) {
  router.push({ name: 'flow', params: { id: String(r.id) } })
}

function handleCardContextMenu(event: MouseEvent, flow: Flow) {
  entityContextMenu.show({
    event,
    entityType: 'flow',
    entityId: flow.id,
    entityName: flow.name || 'Untitled',
    projectId: flow.project_id ?? null,
    isSelected: false,
    selectedCount: 0,
  })
}

function handleContextMenuOpen(_entityType: string, entityId: number) {
  const r = flows.value.find(x => x.id === entityId)
  if (r) openFlow(r)
}

function handleContextMenuDelete(_entityType: string, entityId: number) {
  performDelete(entityId)
}

function handleContextMenuRename(_entityType: string, entityId: number) {
  renamingId.value = entityId
}

async function handleContextMenuMoveToProject(_entityType: string, entityId: number, projectId: number | null) {
  try {
    const updated = await api.updateFlow(entityId, { project_id: projectId })
    const idx = flows.value.findIndex(r => r.id === entityId)
    if (idx >= 0) flows.value[idx] = updated
    // If list is scoped to a project and flow moved out, drop it.
    if (props.projectId && updated.project_id !== props.projectId) {
      flows.value = flows.value.filter(r => r.id !== entityId)
    }
  } catch (err) {
    console.error('Failed to move flow to project:', err)
  }
}

async function handleInlineRename(flow: Flow, newName: string) {
  renamingId.value = null
  try {
    const updated = await api.updateFlow(flow.id, { name: newName })
    const idx = flows.value.findIndex(r => r.id === flow.id)
    if (idx >= 0) flows.value[idx] = updated
  } catch (err) {
    console.error('Failed to rename flow:', err)
  }
}

async function performDelete(id: number) {
  const removed = flows.value.find(r => r.id === id)
  if (!removed) return
  flows.value = flows.value.filter(r => r.id !== id)

  try {
    await api.deleteFlow(id)
  } catch (err) {
    console.error('Failed to delete flow:', err)
    flows.value = [removed, ...flows.value]
    addToast('Failed to delete flow', 'error', 5000)
    return
  }

  addToast('Deleted 1 flow', 'info', 5000, {
    label: 'Undo',
    onClick: async () => {
      if (!flows.value.find(r => r.id === id)) {
        flows.value = [removed, ...flows.value]
      }
      try {
        await api.restoreFlow(id)
      } catch (err) {
        console.error('Failed to restore flow:', err)
        flows.value = flows.value.filter(r => r.id !== id)
        addToast('Failed to restore flow', 'error', 5000)
      }
    }
  })
}

function matchesScope(flow: any): boolean {
  if (!props.projectId) return true
  return flow?.project_id === props.projectId
}

async function createFlow() {
  try {
    const body: any = {}
    if (props.projectId) body.project_id = props.projectId
    const r = await api.createFlow(body)
    router.push({ name: 'flow', params: { id: String(r.id) } })
  } catch (err) {
    console.error('Failed to create flow:', err)
  }
}

onMounted(() => {
  load()
  unsubs.push(on('flow_created', (data: any) => {
    const r = data?.flow
    if (!r || !matchesScope(r)) return
    if (!flows.value.find(x => x.id === r.id)) flows.value = [r, ...flows.value]
  }))
  unsubs.push(on('flow_updated', (data: any) => {
    const r = data?.flow
    if (!r) return
    const idx = flows.value.findIndex(x => x.id === r.id)
    if (!matchesScope(r)) {
      if (idx >= 0) flows.value.splice(idx, 1)
      return
    }
    if (idx >= 0) flows.value[idx] = r
    else flows.value = [r, ...flows.value]
  }))
  unsubs.push(on('flow_deleted', (data: any) => {
    const rid = data?.flow_id
    if (rid != null) flows.value = flows.value.filter(r => r.id !== rid)
  }))
  unsubs.push(on('flow_restored', (data: any) => {
    const r = data?.flow
    if (!r || !matchesScope(r)) return
    if (!flows.value.find(x => x.id === r.id)) flows.value = [r, ...flows.value]
  }))
  unsubs.push(on('websocket_reconnected', () => load()))
})

onUnmounted(() => {
  for (const u of unsubs) { try { u() } catch {} }
  unsubs.length = 0
})
</script>
