<template>
  <div class="group relative" :class="[rowBorderClass, isEchoed ? 'ring-1 ring-blue-500/40 bg-blue-500/5' : '']">
    <div
      role="button"
      tabindex="0"
      class="w-full flex items-center gap-2.5 px-2.5 py-1.5 text-[12px] text-left cursor-pointer"
      @click="toggle"
      @keydown.enter.prevent="toggle"
      @keydown.space.prevent="toggle"
    >
      <!-- Status icon — carries the full state vocabulary (no separate
           right-rail label). Each non-pending status has its own glyph + color
           so a row can be triaged from the leftmost column alone. -->
      <span
        v-if="equation.status === 'computing' && !isPaused"
        class="w-3 h-3 border-2 border-blue-400 border-t-transparent rounded-full animate-spin flex-shrink-0"
        :title="'Running'"
      />
      <span
        v-else-if="equation.status === 'computing' && isPaused"
        class="text-yellow-400/80 text-[11px] flex-shrink-0"
        :title="'Paused'"
      >⏸</span>
      <svg
        v-else-if="equation.status === 'completed'"
        class="w-4 h-4 text-green-500 flex-shrink-0"
        fill="currentColor" viewBox="0 0 24 24"
      >
        <title>Done</title>
        <path fill-rule="evenodd" clip-rule="evenodd" d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10zm4.03-12.97a.75.75 0 00-1.06-1.06l-4.72 4.72-2.22-2.22a.75.75 0 10-1.06 1.06l2.75 2.75a.75.75 0 001.06 0l5.25-5.25z" />
      </svg>
      <svg
        v-else-if="equation.status === 'failed'"
        class="w-3.5 h-3.5 text-red-400 flex-shrink-0"
        fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor"
      >
        <title>Failed</title>
        <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
      </svg>
      <span
        v-else-if="equation.status === 'awaiting_input'"
        class="w-2.5 h-2.5 rounded-full bg-purple-500 flex-shrink-0 animate-pulse-soft"
        :title="'Your Turn'"
      />
      <svg
        v-else-if="equation.status === 'invalidated'"
        class="w-3.5 h-3.5 text-yellow-500 flex-shrink-0"
        fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"
      >
        <title>Stale — needs re-run</title>
        <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
      </svg>
      <svg
        v-else-if="equation.status === 'pending' && isQueued"
        class="w-3.5 h-3.5 text-content-muted flex-shrink-0"
        fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"
      >
        <title>Queued</title>
        <circle cx="12" cy="12" r="9" stroke-linecap="round" stroke-linejoin="round" />
        <path stroke-linecap="round" stroke-linejoin="round" d="M12 7v5l3 2" />
      </svg>
      <svg
        v-else-if="equation.status === 'skipped'"
        class="w-3.5 h-3.5 text-content-muted/60 flex-shrink-0"
        fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor"
      >
        <title>Skipped</title>
        <path stroke-linecap="round" stroke-linejoin="round" d="M5 12h14" />
      </svg>
      <span
        v-else
        class="w-2 h-2 rounded-full border border-content-muted/40 flex-shrink-0"
        :title="'Pending'"
      />

      <!-- Title + low-emphasis runtime pill. Title is the *action*
           ("Generate Image"); the model + provider live in a small muted
           pill so power users can sanity-check without the row reading as a
           model identifier. Routing/code rows that have a real subtitle
           still render it on a second line. -->
      <div class="flex-1 min-w-0 flex flex-col justify-center">
        <div class="flex items-baseline gap-2 min-w-0">
          <span class="truncate text-[13px] leading-tight text-content">{{ title }}</span>
          <span
            v-if="runtimePill"
            class="flex-shrink-0 truncate text-[10px] leading-none rounded px-1.5 py-0.5 bg-overlay-faint text-content-muted"
          >
            <span v-if="runtimeModelLabel">{{ runtimeModelLabel }}</span>
            <span v-if="runtimeModelLabel && runtimeProviderLabel"> · </span>
            <span
              v-if="runtimeProviderLabel"
              :class="isStimmaCloud ? 'stimma-cloud-text font-medium' : ''"
            >{{ runtimeProviderLabel }}</span>
          </span>
        </div>
        <span
          v-if="secondLineSubtitle"
          class="truncate text-[11px] leading-tight text-content-muted"
        >{{ secondLineSubtitle }}</span>
      </div>

      <!-- Collapsed-state thumbnail strip: up to 3 result media tiles so a
           completed image-producing row shows its output in the header.
           Tiles overlap slightly (stacked-avatar feel) so a multi-output row
           reads as a cohesive preview, not a rigid chip strip. Suppressed
           once expanded (the body renders them full-size). Always rendered
           at a fixed width so the status column lines up row-to-row — mirrors
           IterationGroup's header layout. -->
      <div
        v-if="!expanded"
        class="hidden sm:flex flex-shrink-0 items-center justify-end w-32"
      >
        <div
          v-for="(mid, i) in headerMediaIds"
          :key="mid"
          class="w-6 h-6 rounded-md border border-surface overflow-hidden ring-1 ring-edge-subtle"
          :class="i > 0 ? '-ml-1.5' : ''"
          :style="{ zIndex: headerMediaIds.length - i }"
        >
          <FlowMediaTile
            :media-id="mid"
            :media-ids="resultMediaIds"
            :index="resultMediaIds.indexOf(mid)"
            :thumbnail="true"
            :thumbnail-size="128"
            container-class="w-full h-full"
            img-class="w-full h-full object-cover"
          />
        </div>
        <span
          v-if="resultMediaIds.length > headerMediaIds.length"
          class="flex items-center text-[10px] text-content-muted px-0.5"
        >+{{ resultMediaIds.length - headerMediaIds.length }}</span>
      </div>

      <!-- Right-aligned: duration + re-run button. The status label column
           that used to sit here was removed once each status got its own
           leftmost icon (purple pulse for Your Turn, clock for Queued, etc.),
           so the right rail no longer carries redundant text. -->
      <span
        class="flex-shrink-0 text-[11.5px] text-content-muted tabular-nums w-14 text-right"
      >{{ durationLabel || '' }}</span>
      <FlowRefButton
        :ref-key="equation.equation_key"
        kind="equation"
        :label="title"
        :breadcrumb="parentPhaseName"
      />
      <button
        v-if="equation.status === 'completed' || equation.status === 'failed'"
        type="button"
        class="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded-md bg-base text-content-muted hover:text-content hover:bg-overlay-hover"
        title="Re-run this step"
        @click.stop="$emit('invalidate-equation', equation.equation_key)"
      >
        <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
        </svg>
      </button>
      <!-- Pad the right column when no re-run button renders so rows stay
           vertically aligned across pending / running / completed states. -->
      <span
        v-else
        class="flex-shrink-0 w-6 h-6"
        aria-hidden="true"
      />
    </div>

    <Transition name="flow-expand">
      <div v-if="expanded">
        <div class="border-t px-3 py-2 space-y-2" :class="expandedBorderClass">
          <EquationTraceBody
            :equation="equation"
            :flow-id="flowId"
            :is-paused="isPaused"
            :dev-mode="devMode"
            :active="expanded"
            @invalidate-equation="(k) => $emit('invalidate-equation', k)"
            @fix-step-with-agent="(eq) => $emit('fix-step-with-agent', eq)"
          />
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import type { FlowEquation } from '../../composables/useFlowsApi'
import { useProvidersApi } from '../../composables/useProvidersApi'
import { useFlowExpandState } from '../../composables/useFlowExpandState'
import FlowMediaTile from './FlowMediaTile.vue'
import EquationTraceBody from './EquationTraceBody.vue'
import { TASK_TYPE_LABELS } from '../../utils/taskTypeIcons'
import { STIMMA_CLOUD_PROVIDER_ID } from '../../utils/stimmaCloud'
import { equationIsReadyToSchedule } from '../../composables/useFlowGrouping'
import FlowRefButton from './FlowRefButton.vue'
import { useFlowReferences, injectFlowChatIdRef } from '../../composables/useFlowReferences'
import { shouldShowEquationDuration } from '../../utils/equationDuration'

interface Props {
  equation: FlowEquation
  isPaused?: boolean
  devMode?: boolean
  // Full map of equations in the flow, used to distinguish pending rows
  // that are ready-but-waiting-on-the-concurrency-cap ("Queued") from rows
  // still blocked on upstream work.
  equationsByKey?: Map<string, FlowEquation> | null
}
const props = withDefaults(defineProps<Props>(), { isPaused: false, devMode: false, equationsByKey: null })
defineEmits<{
  (e: 'invalidate-equation', key: string): void
  (e: 'fix-step-with-agent', equation: FlowEquation): void
}>()

const route = useRoute()
const flowId = computed(() => {
  const raw = route.params.id
  const n = Array.isArray(raw) ? raw[0] : raw
  const parsed = n == null ? NaN : Number(n)
  return Number.isFinite(parsed) ? parsed : null
})

// Row echo: when the user hovers this row's chip in the context tray, light
// the row up briefly so they can confirm what the chip points at.
const flowRefs = useFlowReferences(injectFlowChatIdRef())
const isEchoed = computed<boolean>(() =>
  flowRefs.hoveredRefKey.value === props.equation.equation_key,
)
const parentPhaseName = computed<string>(() => {
  const p = props.equation.phase_path || []
  return p.length > 0 ? p[p.length - 1] : ''
})
// Expand state lives in the sticky store so it survives phase-tree rebuilds
// (previously a local ref that got wiped whenever the program changed).
const expandState = useFlowExpandState(flowId)
// Defaults: only failed rows start expanded (so errors are visible without a
// click). Computing rows stay collapsed — they bounce in and out of the
// computing state as the flow runs, and auto-expanding on that transition
// produced a flicker across the steps list. Everything else also stays
// collapsed and relies on the header thumbnail / text preview.
const traceDefaultExpanded = computed<boolean>(() =>
  props.equation.status === 'failed',
)
const expanded = computed<boolean>(() =>
  expandState.isExpanded('trace', props.equation.equation_key, traceDefaultExpanded.value),
)

// Resolve tool metadata (display name, provider) from the providers cache.
// Populates lazily — the cache is shared across the view, so the first row
// triggers a single fetch and everyone else reuses it.
const { cachedTools, cachedProviders, fetchProvidersAndTools } = useProvidersApi()
onMounted(() => {
  if (props.equation.equation_type === 'tool_call' && props.equation.tool_id) {
    fetchProvidersAndTools().catch(() => {})
  }
})

const resolvedTool = computed(() => {
  const tid = props.equation.tool_id
  if (!tid) return null
  return cachedTools.value.find((t) => t.full_tool_id === tid) || null
})

const providerIdFromTool = computed<string | null>(() => {
  const tid = props.equation.tool_id
  if (!tid) return null
  const first = tid.split(':')[0]
  return first || null
})

const providerName = computed<string | null>(() => {
  if (resolvedTool.value) return resolvedTool.value.provider_name
  const pid = providerIdFromTool.value
  if (!pid) return null
  const p = cachedProviders.value.find((pr) => pr.provider_id === pid)
  return p?.provider_name || pid
})

const isStimmaCloud = computed(() => providerIdFromTool.value === STIMMA_CLOUD_PROVIDER_ID)

// Friendly model name (the tool catalog name) — the string that *used* to be
// the row title. Now demoted into the runtime pill.
const toolModelName = computed<string | null>(() => {
  if (resolvedTool.value) return resolvedTool.value.name
  const tid = props.equation.tool_id
  if (tid) {
    const parts = tid.split(':').filter(Boolean)
    if (parts.length >= 2) {
      return parts[1].split('-').map((w) => w ? w[0].toUpperCase() + w.slice(1) : w).join(' ')
    }
  }
  return null
})

// Action label for tool rows — "Generate Image" instead of "Flux.2 Klein 9B".
// task_type is required at the DSL layer (flow_dsl.primitives.tool()
// rejects calls without it), so we read it straight from the equation. The
// fallback to model name covers utility / web tools whose task_type isn't
// in the friendly-label catalog.
const toolActionLabel = computed<string>(() => {
  const tt = props.equation.task_type
  if (tt) {
    const label = TASK_TYPE_LABELS[tt]
    if (label && label !== 'Utility') return label
  }
  return toolModelName.value || props.equation.display_name || 'Tool'
})

const title = computed<string>(() => {
  switch (props.equation.equation_type) {
    case 'tool_call': return toolActionLabel.value
    case 'llm_call':  return props.equation.display_name || 'LLM'
    // Routing helpers are code equations with first-class display names
    // ("Filter Items", "Choose Value"). Plain code rows still prefer the
    // agent-authored description as their title.
    case 'code':
      if (props.equation.routing_kind) return props.equation.display_name || 'Code'
      return (props.equation.description && props.equation.description.trim())
        || props.equation.display_name
        || 'Code'
    default:          return props.equation.display_name || 'Step'
  }
})

// Inline runtime pill — shown only for tool_call rows so power users can see
// which model + provider produced the row without it dominating the title.
// Suppressed when the title already echoes the model (e.g. utility tools that
// fell back to the catalog name).
const runtimePill = computed<string | null>(() => {
  if (props.equation.equation_type !== 'tool_call') return null
  if (!runtimeModelLabel.value && !runtimeProviderLabel.value) return null
  return [runtimeModelLabel.value, runtimeProviderLabel.value].filter(Boolean).join(' · ')
})

const runtimeModelLabel = computed<string | null>(() => {
  const model = toolModelName.value
  if (!model || model === title.value) return null
  return model
})

const runtimeProviderLabel = computed<string | null>(() => {
  const provider = providerName.value
  if (!provider) return null
  return provider
})

// Second-line subtitle (only used by code() rows, which historically showed
// an agent-authored subtitle below the description). Tool rows now use the
// inline pill instead, so this is null for them.
const secondLineSubtitle = computed<string | null>(() => {
  if (props.equation.equation_type === 'code') {
    if (props.equation.routing_kind) {
      const d = props.equation.description
      return d && d.trim() ? d.trim() : null
    }
    const s = props.equation.subtitle
    return s && s.trim() ? s.trim() : null
  }
  return null
})

// Result media surfaced in the collapsed header — up to 3 tiles. Reads
// straight from the equation's result_media_ids (no trace fetch required)
// so the preview is free on initial render.
const resultMediaIds = computed<number[]>(() =>
  Array.isArray(props.equation.result_media_ids) ? props.equation.result_media_ids : [],
)
const headerMediaIds = computed<number[]>(() => {
  if (props.equation.status !== 'completed') return []
  return resultMediaIds.value.slice(0, 3)
})

// Duration shown as a faint "224ms" / "1.4s" / "2m 3s" near the caret. Only
// for completed steps — for running steps the elapsed time is noisy and the
// spinner already communicates "it's still going".
const durationLabel = computed<string | null>(() => {
  const { created_at, completed_at, status, execution_duration_ms, compute_duration_ms, equation_type } = props.equation
  if (status !== 'completed') return null
  if (!shouldShowEquationDuration(equation_type)) return null
  let ms: number | null = null
  // For tool_call equations we prefer compute_duration_ms — the tool's
  // self-reported pure compute time, excluding queue wait at the tool side.
  // Other equation types (llm, code, hitl, control) have no queue-wait
  // problem so the engine's execution_duration_ms is the right number.
  if (
    equation_type === 'tool_call'
    && typeof compute_duration_ms === 'number'
    && Number.isFinite(compute_duration_ms)
    && compute_duration_ms >= 0
  ) {
    ms = compute_duration_ms
  } else if (typeof execution_duration_ms === 'number' && Number.isFinite(execution_duration_ms) && execution_duration_ms >= 0) {
    ms = execution_duration_ms
  } else if (created_at && completed_at) {
    const t0 = Date.parse(created_at)
    const t1 = Date.parse(completed_at)
    if (isFinite(t0) && isFinite(t1) && t1 >= t0) ms = t1 - t0
  }
  if (ms == null) return null
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`
  const mins = Math.floor(ms / 60_000)
  const secs = Math.round((ms % 60_000) / 1000)
  return secs ? `${mins}m ${secs}s` : `${mins}m`
})

// Distinguishes a pending row that's eligible to run right now (waiting on
// the concurrency cap) from one still blocked on upstream work — the leftmost
// status icon picks a clock vs. hollow ring on this signal.
const isQueued = computed<boolean>(() => {
  if (props.equation.status !== 'pending') return false
  if (!props.equationsByKey) return false
  return equationIsReadyToSchedule(props.equation, props.equationsByKey)
})

// Status tint painted on the row background; the surrounding phase card
// provides the border + rounding so rows no longer carry their own outline.
const rowBorderClass = computed(() => {
  switch (props.equation.status) {
    case 'failed':    return 'bg-red-500/5'
    case 'computing': return 'bg-blue-500/5'
    default:          return ''
  }
})

const expandedBorderClass = computed(() => {
  switch (props.equation.status) {
    case 'failed':    return 'border-red-500/20'
    case 'computing': return 'border-blue-500/20'
    default:          return 'border-edge-subtle'
  }
})

function toggle() {
  expandState.toggle('trace', props.equation.equation_key, expanded.value)
}
</script>
