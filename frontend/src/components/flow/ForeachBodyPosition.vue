<template>
  <div class="relative group" :style="{ width: NODE_W + 'px' }">
    <div
      v-if="selected"
      class="absolute -inset-1 rounded-[14px] ring-2 ring-selection pointer-events-none z-10"
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
        :icon="visual.icon"
        :tile-class="visual.tileClass"
        :title="resolvedTitle"
        :subtitle="runtimeSubtitle ? null : resolvedSubtitle"
        :status-label="statusLabel"
        :actionable="cardStatus === 'awaiting_input'"
        :hero="hasHeroMedia"
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
              class="w-full h-full flex gap-px rounded-[2px] overflow-hidden bg-matte"
            >
              <MediaImage
                v-for="(mid, i) in sampledMediaIds"
                :key="i + '-' + mid"
                :media-id="mid"
                :thumbnail="true"
                :thumbnail-size="256"
                :draggable="false"
                container-class="flex-1 min-w-0 h-full bg-matte"
                img-class="w-full h-full object-cover"
              />
              <div
                v-if="totalMediaCount > sampledMediaIds.length"
                class="flex-none w-9 h-full flex items-center justify-center bg-overlay-subtle"
              >
                <span class="text-[10.5px] font-mono tabular-nums text-content-muted">+{{ totalMediaCount - sampledMediaIds.length }}</span>
              </div>
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
            <MediaImage
              v-if="focusedMediaIds.length === 1"
              :media-id="focusedMediaIds[0]"
              :thumbnail="true"
              :thumbnail-size="512"
              thumbnail-mode="fit"
              :contain="true"
              :draggable="false"
              container-class="w-full h-full rounded-[2px] overflow-hidden bg-matte"
              img-class="w-full h-full object-contain"
            />
            <div
              v-else-if="focusedMediaIds.length > 1"
              class="w-full h-full flex gap-px rounded-[2px] overflow-hidden bg-matte"
            >
              <MediaImage
                v-for="(mid, i) in focusedMediaIds.slice(0, 4)"
                :key="i + '-' + mid"
                :media-id="mid"
                :thumbnail="true"
                :thumbnail-size="256"
                :draggable="false"
                container-class="flex-1 min-w-0 h-full bg-matte"
                img-class="w-full h-full object-cover"
              />
              <div
                v-if="focusedMediaIds.length > 4"
                class="flex-none w-9 h-full flex items-center justify-center bg-overlay-subtle"
              >
                <span class="text-[10.5px] font-mono tabular-nums text-content-muted">+{{ focusedMediaIds.length - 4 }}</span>
              </div>
            </div>
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
import { flowNodeVisual } from '../../utils/flowNodeVisuals'
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
const NODE_H = 176

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
  if (props.position.subtitle) return props.position.subtitle
  // Chips are retired; the sentence-case type word fills in, unless it
  // would just echo the title.
  return visual.value.label === resolvedTitle.value ? null : visual.value.label
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
const SAMPLE_CAP = 3
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

// Aggregate count chips for the View-All middle-area display. One chip per
// non-zero status, ordered by urgency so the eye lands on actionable counts.
const aggregateChips = computed(() => {
  const c = counts.value
  const out: { label: string; count: number; class: string; dotClass: string }[] = []
  if (c.failed > 0)         out.push({ label: 'failed',  count: c.failed,         class: 'border-flow-fail-soft bg-flow-fail-tint text-flow-fail-strong',  dotClass: 'bg-flow-fail-strong' })
  if (c.awaiting_input > 0) out.push({ label: 'waiting', count: c.awaiting_input, class: 'border-flow-await-soft bg-flow-await-tint text-flow-await-strong', dotClass: 'bg-flow-await-strong' })
  if (c.computing > 0)      out.push({ label: 'running', count: c.computing,      class: 'border-flow-run-soft bg-flow-run-tint text-flow-run-strong',       dotClass: 'bg-flow-run-strong flow-dot-pulse' })
  if (c.pending > 0)        out.push({ label: 'queued',  count: c.pending,        class: 'border-edge-subtle bg-overlay-subtle text-content-muted',                 dotClass: 'bg-content-muted/40' })
  if (c.completed > 0)      out.push({ label: 'done',    count: c.completed,      class: 'border-flow-done-soft bg-flow-done-tint text-flow-done-strong',    dotClass: 'bg-flow-done-strong' })
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
    case 'computing':      return 'Running'
    case 'completed':      return ''
    case 'failed':         return "Didn't finish"
    case 'pending':        return 'Waiting its turn'
    case 'awaiting_input': return 'Your turn'
    case 'skipped':        return 'Skipped'
    case 'invalidated':    return 'Out of date'
    case null:             return props.position.optional ? 'Not in this iteration' : '—'
    default:               return String(focusedStatus.value)
  }
})

const statusLabel = computed(() => {
  // Aggregate view: the chip row / media strip already carries the counts —
  // repeating them in the footer was the "1 done" dead band.
  return props.focusedIdx !== null ? focusedStatusLabel.value : ''
})

const hasHeroMedia = computed(() =>
  props.focusedIdx === null
    ? sampledMediaIds.value.length > 0
    : focusedMediaIds.value.length > 0,
)

// Type icon tile — shared vocabulary with EquationGraph's nodes.
const visual = computed(() =>
  flowNodeVisual(props.position.equation_type, { taskType: props.position.task_type }),
)

defineExpose({ NODE_W, NODE_H })
</script>

<style scoped>
/* Aggregate chips render in this component's scope, so the dot-pulse class
   needs a local definition (Vue scoped styles don't leak into slot content
   from EquationNodeCard). Same animation keyframe — keeps the running chip's
   dot in lockstep with the card's footer dot. */
@keyframes flow-dot-pulse {
  0%, 100% { transform: scale(1);   opacity: 1; }
  50%      { transform: scale(0.7); opacity: 0.5; }
}
.flow-dot-pulse { animation: flow-dot-pulse 1.4s ease-in-out infinite; }
</style>
