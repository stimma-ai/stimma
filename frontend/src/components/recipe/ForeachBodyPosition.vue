<template>
  <div class="relative group" :style="{ width: NODE_W + 'px' }">
    <div
      v-if="selected"
      class="absolute -inset-1 rounded-lg ring-2 ring-blue-400 pointer-events-none z-10"
    />
    <div
      role="button"
      tabindex="0"
      :style="{ height: NODE_H + 'px', opacity: position.optional ? 0.95 : undefined }"
      @click.stop="$emit('select')"
      @keydown.enter.prevent="$emit('select')"
      @keydown.space.prevent="$emit('select')"
    >
      <EquationNodeCard
        :status="cardStatus"
        :chip-label="typeChipLabel"
        :chip-class="typeChipClass"
        :title="resolvedTitle"
        :subtitle="runtimeSubtitle ? null : resolvedSubtitle"
        :status-label="statusLabel"
        :actionable="cardStatus === 'awaiting_input'"
      >
        <template v-if="runtimeSubtitle" #subtitle>
          <span v-if="runtimeModelLabel">{{ runtimeModelLabel }}</span>
          <span v-if="runtimeModelLabel && runtimeProviderLabel"> · </span>
          <span
            v-if="runtimeProviderLabel"
            :class="isStimmaCloud ? 'stimma-cloud-text font-medium' : ''"
          >{{ runtimeProviderLabel }}</span>
        </template>

        <template #header-right>
          <span
            v-if="position.optional"
            class="flex-shrink-0 text-[9.5px] uppercase tracking-wide text-content-muted/80 italic mt-[1px]"
            :title="`Applied in ${position.presentCount} of ${position.iterStatuses.length} iterations`"
          >optional</span>
        </template>

        <template #body>
          <!-- Aggregate (no iteration focused): sampled thumbnails or count
               chips. The legitimate divergence from a single-equation node:
               this card is summarizing N iterations at once. -->
          <template v-if="focusedIdx === null">
            <div
              v-if="sampledMediaIds.length > 0"
              class="flex items-center w-full"
            >
              <div
                v-for="(mid, i) in sampledMediaIds"
                :key="i + '-' + mid"
                class="relative flex-shrink-0 w-10 h-10 rounded border border-edge-subtle overflow-hidden bg-overlay-subtle"
                :style="{ marginLeft: i === 0 ? '0' : '-14px', zIndex: sampledMediaIds.length - i }"
              >
                <MediaImage
                  :media-id="mid"
                  :thumbnail="true"
                  :thumbnail-size="64"
                  :draggable="false"
                  container-class="w-full h-full"
                  img-class="w-full h-full object-cover"
                />
              </div>
              <span
                v-if="totalMediaCount > sampledMediaIds.length"
                class="ml-2 text-[10px] text-content-muted tabular-nums"
              >+{{ totalMediaCount - sampledMediaIds.length }}</span>
            </div>
            <div
              v-else
              class="w-full flex flex-wrap items-center gap-1.5 text-[10.5px]"
            >
              <span
                v-for="chip in aggregateChips"
                :key="chip.label"
                class="flex items-center gap-1 px-1.5 py-0.5 rounded-full border"
                :class="chip.class"
              >
                <span class="w-1.5 h-1.5 rounded-full" :class="chip.dotClass" />
                <span class="tabular-nums">{{ chip.count }}</span>
                <span>{{ chip.label }}</span>
              </span>
              <span v-if="aggregateChips.length === 0" class="text-content-muted">—</span>
            </div>
          </template>

          <!-- Focused iteration: same body treatment as a normal equation
               node — media thumbnails when present, failed hint on failure,
               nothing otherwise. The header already says what this step is;
               we don't repeat it here. -->
          <template v-else>
            <div v-if="focusedMediaIds.length > 0" class="flex items-center gap-1">
              <div
                v-for="(mid, i) in focusedMediaIds.slice(0, 4)"
                :key="i + '-' + mid"
                class="w-8 h-8 flex-shrink-0 rounded overflow-hidden border border-edge-subtle"
              >
                <MediaImage
                  :media-id="mid"
                  :thumbnail="true"
                  :thumbnail-size="64"
                  :draggable="false"
                  container-class="w-full h-full"
                  img-class="w-full h-full object-cover"
                />
              </div>
              <span
                v-if="focusedMediaIds.length > 4"
                class="text-[10px] text-content-muted"
              >+{{ focusedMediaIds.length - 4 }}</span>
            </div>
            <div
              v-else-if="focusedStatus === 'failed'"
              class="text-[10px] leading-tight line-clamp-2 self-start text-recipe-fail-strong"
            >This step failed.</div>
            <div
              v-else-if="focusedStatus === null"
              class="text-[10px] text-content-muted/70 italic self-start"
            >not in this iteration</div>
          </template>
        </template>

        <template #footer-actions>
          <button
            v-if="focusedIdx !== null && focusedInvalidateKey && (focusedStatus === 'completed' || focusedStatus === 'failed' || focusedStatus === 'invalidated')"
            type="button"
            class="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded border border-transparent text-content-muted hover:text-content hover:bg-overlay-hover hover:border-edge-subtle transition-colors opacity-50 group-hover:opacity-100"
            title="Re-run this step"
            @click.stop="$emit('invalidate-iteration', focusedInvalidateKey)"
          >
            <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
            </svg>
          </button>
        </template>
      </EquationNodeCard>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { MediaImage } from '../media'
import EquationNodeCard from './EquationNodeCard.vue'
import type { BodyPosition } from '../../composables/useForeachSuperNodes'
import { useProvidersApi } from '../../composables/useProvidersApi'
import { TASK_TYPE_LABELS } from '../../utils/taskTypeIcons'
import { STIMMA_CLOUD_PROVIDER_ID } from '../../utils/stimmaCloud'

interface Props {
  position: BodyPosition
  focusedIdx: number | null
  iterLabel?: string | null
  maxRibbonSegments?: number
  selected?: boolean
}
const props = withDefaults(defineProps<Props>(), {
  iterLabel: null,
  maxRibbonSegments: 120,
  selected: false,
})

defineEmits<{
  // Re-run this body position's equation in the focused iteration. Parent
  // forwards to the graph view so the same invalidate plumbing handles it.
  (e: 'invalidate-iteration', equationKey: string): void
  // User clicked the body-position card. Parent picks the most-actionable
  // iteration for this position and drills the inspect panel into it.
  (e: 'select'): void
}>()

const NODE_W = 240
const NODE_H = 120

// Tool + provider display-name resolution (mirrors EquationGraph). Without
// this, tool_call positions show the backend-slugified "comfyui — flux klein
// 9b" instead of the human-readable "Flux Klein 9B" / "ComfyUI".
const { cachedTools, cachedProviders, fetchProvidersAndTools } = useProvidersApi()
onMounted(() => { fetchProvidersAndTools().catch(() => {}) })

function resolveTool(toolId: string | null | undefined) {
  if (!toolId) return null
  return cachedTools.value.find((t) => t.full_tool_id === toolId) || null
}

const resolvedToolName = computed<string | null>(() => {
  if (props.position.equation_type !== 'tool_call') return null
  const tool = resolveTool(props.position.tool_id)
  if (tool) return tool.name
  const tid = props.position.tool_id
  if (tid) {
    const parts = tid.split(':').filter(Boolean)
    if (parts.length >= 2) {
      return parts[1]
        .split('-')
        .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
        .join(' ')
    }
  }
  return null
})

const resolvedProviderName = computed<string | null>(() => {
  if (props.position.equation_type !== 'tool_call') return null
  const tool = resolveTool(props.position.tool_id)
  if (tool) return tool.provider_name || null
  const tid = props.position.tool_id
  if (tid) {
    const pid = tid.split(':')[0] || null
    if (pid) {
      const p = cachedProviders.value.find((pr) => pr.provider_id === pid)
      return p?.provider_name || pid
    }
  }
  return null
})

const providerId = computed<string | null>(() => {
  const tid = props.position.tool_id
  if (!tid) return null
  return tid.split(':')[0] || null
})

const isStimmaCloud = computed(() => providerId.value === STIMMA_CLOUD_PROVIDER_ID)

const resolvedTitle = computed<string>(() => {
  if (props.position.equation_type === 'tool_call') {
    const tt = props.position.task_type
    if (tt && tt !== 'utility') {
      const known = TASK_TYPE_LABELS[tt]
      if (known) return known
      return tt.split('-').map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w)).join(' ')
    }
    return resolvedToolName.value || props.position.title
  }
  return props.position.title
})

const resolvedSubtitle = computed<string | null>(() => {
  if (props.position.equation_type === 'tool_call') {
    // Title carries the action ("Generate Image"); subtitle deemphasizes the
    // implementation ("Flux.2 Klein 9B · ComfyUI"). Drop the tool name from
    // the subtitle when the title already echoes it.
    const name = resolvedToolName.value
    const provider = resolvedProviderName.value
    if (resolvedTitle.value === name) return provider
    if (name && provider && name !== provider) return `${name} · ${provider}`
    return name || provider
  }
  return props.position.subtitle
})

const runtimeSubtitle = computed<string | null>(() => {
  if (props.position.equation_type !== 'tool_call') return null
  if (!runtimeModelLabel.value && !runtimeProviderLabel.value) return null
  return [runtimeModelLabel.value, runtimeProviderLabel.value].filter(Boolean).join(' · ')
})

const runtimeModelLabel = computed<string | null>(() => {
  const name = resolvedToolName.value
  if (!name || resolvedTitle.value === name) return null
  return name
})

const runtimeProviderLabel = computed<string | null>(() => {
  const provider = resolvedProviderName.value
  if (!provider) return null
  return provider
})

// Sampled media thumbs for aggregate view. Evenly spaced across iterations
// that have media, capped at SAMPLE_CAP tiles. Empty if nothing produced media.
const SAMPLE_CAP = 6
const sampledMediaIds = computed<number[]>(() => {
  const media = props.position.iterMediaIds
  const withMedia: number[] = []
  for (let i = 0; i < media.length; i++) {
    const mids = media[i]
    if (mids && mids.length > 0) withMedia.push(mids[0])
  }
  if (withMedia.length === 0) return []
  if (withMedia.length <= SAMPLE_CAP) return withMedia
  const step = withMedia.length / SAMPLE_CAP
  const out: number[] = []
  for (let i = 0; i < SAMPLE_CAP; i++) {
    out.push(withMedia[Math.floor(i * step)])
  }
  return out
})
const totalMediaCount = computed(() => {
  const media = props.position.iterMediaIds
  let n = 0
  for (let i = 0; i < media.length; i++) {
    if (media[i] && media[i].length > 0) n++
  }
  return n
})

function aggregateCounts(statuses: (string | null)[]): Record<string, number> {
  const counts: Record<string, number> = {
    pending: 0, computing: 0, completed: 0,
    failed: 0, awaiting_input: 0, skipped: 0, invalidated: 0,
  }
  for (const s of statuses) {
    if (s === null || s === undefined) continue
    counts[s] = (counts[s] ?? 0) + 1
  }
  return counts
}

const counts = computed(() => aggregateCounts(props.position.iterStatuses))

// Aggregate "rollup" status used for the card chrome when no iteration is
// focused. Mirrors the urgency hierarchy from rollupAt() in the parent
// super-node: anything failing wins, then waiting, then running.
type RollupStatus = 'failed' | 'awaiting_input' | 'computing' | 'pending' | 'completed' | 'skipped' | 'none'
const rollupStatus = computed<RollupStatus>(() => {
  const c = counts.value
  if (c.failed > 0) return 'failed'
  if (c.awaiting_input > 0) return 'awaiting_input'
  if (c.computing > 0) return 'computing'
  if (c.pending > 0) return 'pending'
  if (c.completed > 0) return 'completed'
  if (c.skipped > 0) return 'skipped'
  return 'none'
})

const summaryLabel = computed(() => {
  const c = counts.value
  const parts: string[] = []
  if (c.failed > 0) parts.push(`${c.failed} err`)
  if (c.awaiting_input > 0) parts.push(`${c.awaiting_input} waiting`)
  if (c.computing > 0) parts.push(`${c.computing} running`)
  if (c.pending > 0) parts.push(`${c.pending} pending`)
  if (c.completed > 0) parts.push(`${c.completed} ok`)
  if (parts.length === 0) return props.position.optional ? '— not applied' : '—'
  return parts.join(' · ')
})

// Aggregate count chips for the View-All middle-area display. One chip per
// non-zero status, ordered by urgency so the eye lands on actionable counts.
const aggregateChips = computed(() => {
  const c = counts.value
  const out: { label: string; count: number; class: string; dotClass: string }[] = []
  if (c.failed > 0)         out.push({ label: 'failed',  count: c.failed,         class: 'border-recipe-fail-soft bg-recipe-fail-tint text-recipe-fail-strong',  dotClass: 'bg-recipe-fail-strong' })
  if (c.awaiting_input > 0) out.push({ label: 'waiting', count: c.awaiting_input, class: 'border-recipe-await-soft bg-recipe-await-tint text-recipe-await-strong', dotClass: 'bg-recipe-await-strong' })
  if (c.computing > 0)      out.push({ label: 'running', count: c.computing,      class: 'border-recipe-run-soft bg-recipe-run-tint text-recipe-run-strong',       dotClass: 'bg-recipe-run-strong recipe-dot-pulse' })
  if (c.pending > 0)        out.push({ label: 'queued',  count: c.pending,        class: 'border-edge-subtle bg-overlay-subtle text-content-muted',                 dotClass: 'bg-content-muted/40' })
  if (c.completed > 0)      out.push({ label: 'done',    count: c.completed,      class: 'border-recipe-done-soft bg-recipe-done-tint text-recipe-done-strong',    dotClass: 'bg-recipe-done-strong' })
  if (c.skipped > 0)        out.push({ label: 'skipped', count: c.skipped,        class: 'border-edge-subtle bg-overlay-subtle text-content-muted/80',              dotClass: 'bg-content-muted/30' })
  return out
})

// --- Focused view ---
const focusedStatus = computed<string | null>(() => {
  if (props.focusedIdx === null) return null
  return props.position.iterStatuses[props.focusedIdx] ?? null
})

const focusedMediaIds = computed<number[]>(() => {
  const idx = props.focusedIdx
  if (idx === null) return []
  return props.position.iterMediaIds[idx] ?? []
})

// Equation key for the focused iteration's body-position equation. Drives the
// inline rerun button so the user can re-run a single iteration's step
// without leaving the graph.
const focusedInvalidateKey = computed<string | null>(() => {
  const idx = props.focusedIdx
  if (idx === null) return null
  return props.position.iterEquationKeys[idx] ?? null
})

// Status fed to the shared card shell. The aggregate "none" case (no
// iterations have run yet) maps to a neutral-pending card.
const cardStatus = computed<string | null>(() => {
  if (props.focusedIdx !== null) return focusedStatus.value
  return rollupStatus.value === 'none' ? 'pending' : rollupStatus.value
})

const focusedStatusLabel = computed(() => {
  switch (focusedStatus.value) {
    case 'computing':      return 'running'
    case 'completed':      return 'done'
    case 'failed':         return 'failed'
    case 'pending':        return 'queued'
    case 'awaiting_input': return 'your turn'
    case 'skipped':        return 'skipped'
    case 'invalidated':    return 'stale'
    case null:             return props.position.optional ? 'not in this iteration' : '—'
    default:               return String(focusedStatus.value)
  }
})

const statusLabel = computed(() => {
  return props.focusedIdx !== null ? focusedStatusLabel.value : summaryLabel.value
})

// Type chip — same vocabulary as EquationGraph's chips.
const typeChipClass = computed<string>(() => {
  switch (props.position.equation_type) {
    case 'tool_call':       return 'bg-recipe-tool-tint text-recipe-tool-strong'
    case 'llm_call':
    case 'llm_batch':
    case 'llm_slot':        return 'bg-recipe-llm-tint text-recipe-llm-strong'
    case 'code':            return 'bg-recipe-code-tint text-recipe-code-strong'
    case 'hitl':            return 'bg-recipe-hitl-tint text-recipe-hitl-strong'
    case 'info':            return 'bg-recipe-info-tint text-recipe-info-strong'
    case 'recipe_input':    return 'bg-recipe-input-tint text-recipe-input-strong'
    case 'recipe_output':   return 'bg-recipe-output-tint text-recipe-output-strong'
    case 'control':         return 'bg-recipe-control-tint text-recipe-control-strong'
    case 'create_set':
    case 'create_grid':
    case 'create_document': return 'bg-recipe-create-tint text-recipe-create-strong'
    case 'web_search':
    case 'fetch_media':     return 'bg-recipe-tool-tint text-recipe-tool-strong'
    default: return 'bg-overlay-subtle text-content-muted'
  }
})

const typeChipLabel = computed<string>(() => {
  switch (props.position.equation_type) {
    case 'tool_call':     return 'TOOL'
    case 'llm_call':
    case 'llm_batch':
    case 'llm_slot':      return 'LLM'
    case 'code':          return 'CODE'
    case 'hitl':          return 'HUMAN'
    case 'info':          return 'NOTE'
    case 'recipe_input':  return 'INPUT'
    case 'recipe_output': return 'OUTPUT'
    case 'control':       return 'LOOP'
    case 'create_set':    return 'SET'
    case 'create_grid':   return 'GRID'
    case 'create_document': return 'DOC'
    case 'web_search':    return 'SEARCH'
    case 'fetch_media':   return 'FETCH'
    default: return 'STEP'
  }
})

defineExpose({ NODE_W, NODE_H })
</script>

<style scoped>
/* Aggregate chips render in this component's scope, so the dot-pulse class
   needs a local definition (Vue scoped styles don't leak into slot content
   from EquationNodeCard). Same animation keyframe — keeps the running chip's
   dot in lockstep with the card's footer dot. */
@keyframes recipe-dot-pulse {
  0%, 100% { transform: scale(1);   opacity: 1; }
  50%      { transform: scale(0.7); opacity: 0.5; }
}
.recipe-dot-pulse { animation: recipe-dot-pulse 1.4s ease-in-out infinite; }
</style>
