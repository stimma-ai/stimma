<template>
  <!-- Shared trace body — used by both EquationTraceRow (steps view) and
       GraphInspectPanel (graph details panel) so the same step always shows
       the same content regardless of where it's surfaced. The component
       owns its trace fetch + polling so consumers just supply the equation
       and flow id. -->
  <div v-if="loading" class="text-[11px] text-content-muted italic">Loading…</div>
  <div v-else-if="loadError" class="text-[11px] text-content-muted italic">
    Couldn't load details ({{ loadError }}).
  </div>
  <template v-else-if="trace">
    <div
      v-if="trace.detail_availability === 'serialized'"
      class="text-[11px] text-content-muted italic"
    >
      Showing saved step details.
    </div>

    <!-- LLM trace -->
    <template v-if="trace.equation_type === 'llm_call'">
      <div v-if="trace.model" class="text-[11px] text-content-muted">
        Model: <span class="text-content font-mono">{{ trace.model }}</span>
      </div>
      <div v-if="trace.system || trace.system_template">
        <div class="text-[11px] uppercase tracking-wide text-content-muted mb-0.5">
          {{ trace.detail_availability === 'serialized' ? 'System template' : 'System' }}
        </div>
        <pre class="text-[11px] whitespace-pre-wrap font-mono bg-overlay-subtle rounded px-2 py-1.5" :class="scrollBlockClass('max-h-48')">{{ trace.system || trace.system_template }}</pre>
      </div>
      <div>
        <div class="text-[11px] uppercase tracking-wide text-content-muted mb-0.5">
          {{ trace.detail_availability === 'serialized' ? 'Prompt template' : 'Prompt' }}
        </div>
        <pre class="text-[11px] whitespace-pre-wrap font-mono bg-overlay-subtle rounded px-2 py-1.5" :class="scrollBlockClass('max-h-64')">{{ trace.prompt || trace.prompt_template || '(empty)' }}</pre>
      </div>
      <div v-if="trace.result !== undefined && trace.result !== null">
        <div class="text-[11px] uppercase tracking-wide text-content-muted mb-0.5">Response</div>
        <pre class="text-[11px] whitespace-pre-wrap font-mono bg-overlay-subtle rounded px-2 py-1.5" :class="scrollBlockClass('max-h-64')">{{ formatResult(trace.result) }}</pre>
      </div>
    </template>

    <!-- Code trace — user-facing treatment only. Title carries the agent
         description; subtitle adds context. Failed-state error block is
         shared at the bottom so retry/fix buttons render once. -->
    <template v-else-if="trace.equation_type === 'code'">
      <div v-if="equation.status === 'computing'" class="text-[11px] text-content-muted italic">
        Preparing…
      </div>
      <div v-else-if="equation.status === 'pending'" class="text-[11px] text-content-muted italic">
        Waiting for upstream steps to finish.
      </div>
      <template v-else>
        <div v-if="codeBodyLine" class="text-[12px] text-content">{{ codeBodyLine }}</div>
        <div
          v-if="codeResultValue !== undefined && codeResultValue !== null"
          class="rounded-md border border-edge-subtle bg-overlay-faint px-3 py-2"
        >
          <div class="text-[10px] uppercase tracking-wide text-content-muted mb-1">Result</div>
          <FlowResultPreview
            :value="codeResultValue"
            :max-lines="10"
            :overflow-mode="props.allowInnerScroll ? 'toggle' : 'none'"
          />
        </div>
      </template>
    </template>

    <!-- Tool call trace — output tile grid. One placeholder per expected
         output (from the definition's `n`), each filled with the produced
         media as it arrives or a status glyph otherwise. -->
    <template v-else-if="trace.equation_type === 'tool_call'">
      <div class="flex flex-wrap gap-2">
        <div
          v-for="i in outputPlaceholderCount"
          :key="i"
          class="w-24 h-24 rounded-md border border-edge-subtle overflow-hidden bg-overlay-subtle flex items-center justify-center"
        >
          <FlowMediaTile
            v-if="toolResultMediaIds[i - 1] != null"
            :media-id="toolResultMediaIds[i - 1]"
            :media-ids="toolResultMediaIds"
            :index="i - 1"
            :thumbnail="true"
            :thumbnail-size="256"
            :contain="true"
            container-class="w-full h-full"
          />
          <div
            v-else-if="equation.status === 'computing' && !isPaused"
            class="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin"
          />
          <span
            v-else-if="equation.status === 'computing' && isPaused"
            class="text-yellow-400/80 text-[13px]"
          >⏸</span>
          <svg
            v-else-if="equation.status === 'failed'"
            class="w-5 h-5 text-red-400" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"
          >
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
          <svg
            v-else
            class="w-4 h-4 text-content-muted/70" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"
          >
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6l4 2m5-2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
      </div>
    </template>

    <!-- Web search trace — image kind shows a thumbnail strip, text kind
         shows compact title/url/snippet rows. -->
    <template v-else-if="trace.equation_type === 'web_search'">
      <div class="text-[11px] text-content-muted flex flex-wrap items-baseline gap-x-1.5">
        <span>{{ webSearchKind === 'images' ? 'Image search' : 'Web search' }}</span>
        <template v-if="webSearchQuery">
          <span>·</span>
          <span class="text-content font-mono break-all">{{ webSearchQuery }}</span>
        </template>
        <template v-if="webSearchResultCount > 0">
          <span>·</span>
          <span>{{ webSearchResultCount }} result{{ webSearchResultCount === 1 ? '' : 's' }}</span>
        </template>
      </div>

      <div
        v-if="webSearchKind === 'images' && webSearchImageResults.length > 0"
        class="flex flex-wrap gap-1.5"
      >
        <a
          v-for="(r, i) in webSearchImageResults"
          :key="i"
          :href="r.source || r.image_url"
          target="_blank"
          rel="noopener noreferrer"
          class="block w-20 h-20 rounded border border-edge-subtle overflow-hidden bg-overlay-subtle hover:border-edge transition-colors"
          :title="r.title || r.source || ''"
        >
          <AppImage
            :src="r.image_url"
            :alt="r.title || ''"
            container-class="w-full h-full"
            img-class="object-cover"
          />
        </a>
      </div>

      <div
        v-else-if="webSearchKind !== 'images' && webSearchTextResults.length > 0"
        class="space-y-1"
      >
        <a
          v-for="(r, i) in webSearchTextResults"
          :key="i"
          :href="r.url"
          target="_blank"
          rel="noopener noreferrer"
          class="block rounded border border-edge-subtle bg-overlay-subtle px-2 py-1.5 hover:bg-overlay-hover transition-colors"
        >
          <div class="text-[11px] font-medium text-content truncate">{{ r.title || r.url }}</div>
          <div v-if="r.url" class="text-[10px] text-content-muted/80 truncate font-mono">{{ r.url }}</div>
          <div
            v-if="r.snippet"
            class="mt-0.5 text-[10.5px] text-content-secondary line-clamp-2 break-words"
          >{{ r.snippet }}</div>
        </a>
      </div>

      <div
        v-else-if="equation.status === 'computing'"
        class="text-[11px] text-content-muted italic"
      >Searching…</div>
      <div
        v-else-if="equation.status === 'pending'"
        class="text-[11px] text-content-muted italic"
      >Waiting for upstream steps to finish.</div>
      <div
        v-else-if="webSearchResultCount === 0 && equation.status === 'completed'"
        class="text-[11px] text-content-muted italic"
      >No results.</div>
    </template>

    <!-- create_set / create_grid: produced composite thumbnail -->
    <template v-else-if="trace.equation_type === 'create_set' || trace.equation_type === 'create_grid'">
      <div v-if="assemblyInfo" class="text-[11px] text-content-muted">
        {{ assemblyInfo }}
      </div>
      <div v-if="toolResultMediaIds.length > 0">
        <div class="text-[11px] uppercase tracking-wide text-content-muted mb-0.5">Result</div>
        <div class="flex flex-wrap gap-2">
          <div
            v-for="mid in toolResultMediaIds"
            :key="mid"
            class="w-32 h-32 rounded-md border border-edge-subtle overflow-hidden bg-overlay-subtle"
          >
            <FlowMediaTile
              :media-id="mid"
              :media-ids="toolResultMediaIds"
              :index="toolResultMediaIds.indexOf(mid)"
              :thumbnail="true"
              :thumbnail-size="256"
              container-class="w-full h-full"
            />
          </div>
        </div>
      </div>
    </template>

    <!-- create_image: composed image -->
    <template v-else-if="trace.equation_type === 'create_image'">
      <div v-if="toolResultMediaIds.length > 0" class="flex flex-wrap gap-2">
        <div
          v-for="mid in toolResultMediaIds"
          :key="mid"
          class="w-48 h-48 rounded-md border border-edge-subtle overflow-hidden bg-overlay-subtle"
        >
          <FlowMediaTile
            :media-id="mid"
            :media-ids="toolResultMediaIds"
            :index="toolResultMediaIds.indexOf(mid)"
            :thumbnail="true"
            :thumbnail-size="512"
            :contain="true"
            container-class="w-full h-full"
          />
        </div>
      </div>
    </template>

    <!-- create_document: markdown preview -->
    <template v-else-if="trace.equation_type === 'create_document'">
      <div v-if="documentFormat" class="text-[11px] text-content-muted">
        Format: <span class="text-content font-mono">{{ documentFormat }}</span>
      </div>
      <div v-if="documentContent">
        <div class="text-[11px] uppercase tracking-wide text-content-muted mb-0.5">Preview</div>
        <pre class="text-[11px] whitespace-pre-wrap font-mono bg-overlay-subtle rounded px-2 py-1.5" :class="scrollBlockClass('max-h-64')">{{ documentContent }}</pre>
      </div>
      <div v-else-if="toolResultMediaIds.length > 0" class="text-[11px] text-content-muted italic">
        Saved as media #{{ toolResultMediaIds[0] }}.
      </div>
    </template>

    <!-- Failed-state tail (shared). Plain "this step failed" message +
         action buttons; raw traceback gated behind devMode. Suppressed in
         hosts that already render their own error treatment + actions
         (see GraphInspectPanel sidebar). -->
    <div
      v-if="showFailedBlock && equation.status === 'failed'"
      class="space-y-2"
    >
      <div class="rounded border border-red-500/30 bg-red-500/5 px-2 py-1.5">
        <div class="text-[11px] font-semibold text-red-400">{{ parsedTraceError?.title || 'This step failed' }}</div>
        <div
          v-if="parsedTraceError?.message"
          class="mt-0.5 whitespace-pre-wrap break-words text-[11px] leading-relaxed text-content-secondary"
        >
          {{ parsedTraceError.message }}
        </div>
      </div>
      <div class="flex items-center gap-1.5">
        <button
          class="text-[11px] px-2 py-0.5 rounded bg-blue-500 text-white hover:bg-blue-600"
          @click.stop="$emit('fix-step-with-agent', equation)"
        >Ask the agent for help</button>
        <button
          class="text-[11px] px-2 py-0.5 rounded bg-overlay-subtle border border-edge-subtle text-content-muted hover:text-content hover:bg-overlay-hover"
          @click.stop="$emit('invalidate-equation', equation.equation_key)"
        >Retry ↻</button>
      </div>
    </div>
    <div
      v-if="devMode && trace.error"
      class="rounded border border-amber-500/40 bg-overlay-light text-[11px] font-mono text-content-secondary"
    >
      <div class="flex items-center gap-2 px-2.5 py-1.5 border-b border-amber-500/30">
        <span class="text-[9px] font-bold uppercase tracking-wider text-amber-600 dark:text-amber-400 bg-amber-500/15 px-1.5 py-0.5 rounded-sm">Dev</span>
        <span class="text-content-muted">raw step error</span>
        <span class="flex-1" />
        <span class="text-content-muted truncate">{{ equation.equation_key }}</span>
      </div>
      <pre class="px-2.5 py-2 whitespace-pre-wrap break-words" :class="scrollBlockClass('max-h-60')">{{ trace.error }}</pre>
    </div>
  </template>
  <div v-else-if="equation.status === 'pending'" class="text-[11px] text-content-muted italic">
    Waiting — details become available once this step starts running.
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import axios from 'axios'
import { getApiBase } from '../../apiConfig'
import type { FlowEquation } from '../../composables/useFlowsApi'
import { parseFlowError } from '../../utils/flowErrors'
import FlowMediaTile from './FlowMediaTile.vue'
import FlowResultPreview from './FlowResultPreview.vue'
import AppImage from '../media/AppImage.vue'

interface Props {
  equation: FlowEquation
  flowId: number | string | null
  isPaused?: boolean
  devMode?: boolean
  // Whether to render the shared failed-state error block + retry/fix
  // buttons. Hosts with their own error treatment (panel sidebar, task
  // cards) pass false to avoid duplication.
  showFailedBlock?: boolean
  // When true, the body actively fetches + polls trace data. Hosts that
  // gate visibility (collapsed accordions) pass false until expanded so
  // closed rows don't fetch on render.
  active?: boolean
  // GraphInspectPanel already owns vertical scrolling; row accordions keep
  // inner caps so expanded rows don't take over the steps view.
  allowInnerScroll?: boolean
}
const props = withDefaults(defineProps<Props>(), {
  isPaused: false,
  devMode: false,
  showFailedBlock: true,
  active: true,
  allowInnerScroll: true,
})

defineEmits<{
  (e: 'invalidate-equation', key: string): void
  (e: 'fix-step-with-agent', equation: FlowEquation): void
}>()

const trace = ref<any | null>(null)
const loading = ref(false)
const loadError = ref<string | null>(null)
const parsedTraceError = computed(() =>
  parseFlowError(trace.value?.error || props.equation.error),
)

function scrollBlockClass(maxHeightClass: string): string {
  return props.allowInnerScroll
    ? `${maxHeightClass} overflow-y-auto custom-scrollbar`
    : ''
}

// ---- Derived per-type ----
const codeBodyLine = computed<string | null>(() => {
  const eq = props.equation
  if (eq.equation_type !== 'code') return null
  if (eq.routing_kind) {
    return eq.description && eq.description.trim() ? eq.description.trim() : null
  }
  return eq.subtitle && eq.subtitle.trim() ? eq.subtitle.trim() : null
})

const codeResultValue = computed<unknown>(() => {
  if (props.equation.equation_type !== 'code') return null
  return trace.value?.result ?? props.equation.result ?? null
})

const outputPlaceholderCount = computed<number>(() => {
  const n = trace.value?.definition?.n
  if (typeof n === 'number' && Number.isFinite(n) && n >= 1) return Math.floor(n)
  return 1
})

const toolResultMediaIds = computed<number[]>(() => {
  const traceMediaIds = trace.value?.result_media_ids
  if (Array.isArray(traceMediaIds) && traceMediaIds.every((v: unknown) => typeof v === 'number')) {
    return traceMediaIds as number[]
  }
  return Array.isArray(props.equation.result_media_ids) ? props.equation.result_media_ids : []
})

interface WebSearchImageResult {
  title?: string | null
  image_url: string
  source?: string | null
  width?: number | null
  height?: number | null
}
interface WebSearchTextResult {
  title?: string | null
  url: string
  snippet?: string | null
}

const webSearchKind = computed<string | null>(() => {
  const k = trace.value?.definition?.kind
  return typeof k === 'string' ? k : null
})

const webSearchQuery = computed<string | null>(() => {
  const t = trace.value
  const candidates = [t?.query, t?.resolved_query, displayableWebSearchTemplate(t?.definition?.query_template)]
  for (const c of candidates) {
    if (typeof c === 'string' && c.trim()) return c.trim()
  }
  return null
})

function displayableWebSearchTemplate(template: unknown): string | null {
  if (typeof template !== 'string') return null
  const trimmed = template.trim()
  if (!trimmed) return null
  // Dynamic web_search(NodeRef) stores "{0}" as its internal template. If the
  // trace cannot resolve the binding, hide the placeholder instead of showing
  // it as though it were the user's search query.
  if (/^\{\d+\}$/.test(trimmed)) return null
  return trimmed
}

const webSearchResultCount = computed<number>(() => {
  const r = trace.value?.result
  return Array.isArray(r) ? r.length : 0
})

const webSearchImageResults = computed<WebSearchImageResult[]>(() => {
  const r = trace.value?.result
  if (!Array.isArray(r)) return []
  return r.filter(
    (x: any) => x && typeof x === 'object' && typeof x.image_url === 'string',
  ) as WebSearchImageResult[]
})

const webSearchTextResults = computed<WebSearchTextResult[]>(() => {
  const r = trace.value?.result
  if (!Array.isArray(r)) return []
  return r.filter(
    (x: any) => x && typeof x === 'object' && typeof x.url === 'string',
  ) as WebSearchTextResult[]
})

const assemblyInfo = computed<string | null>(() => {
  const d = trace.value?.definition
  if (!d || typeof d !== 'object') return null
  const t = trace.value?.equation_type
  if (t === 'create_set') {
    const title = typeof d.title === 'string' && d.title.trim() ? d.title.trim() : null
    const count = toolResultMediaIds.value.length
    const bits: string[] = []
    if (title) bits.push(`"${title}"`)
    if (typeof d.description === 'string' && d.description.trim()) bits.push(d.description.trim())
    if (count) bits.push(`${count} produced`)
    return bits.length ? bits.join(' · ') : null
  }
  if (t === 'create_grid') {
    const rows = typeof d.rows === 'number' ? d.rows : null
    const cols = typeof d.cols === 'number' ? d.cols : null
    const title = typeof d.title === 'string' && d.title.trim() ? d.title.trim() : null
    const bits: string[] = []
    if (title) bits.push(`"${title}"`)
    if (rows != null && cols != null) bits.push(`${rows} × ${cols}`)
    return bits.length ? bits.join(' · ') : null
  }
  return null
})

const documentFormat = computed<string | null>(() => {
  const d = trace.value?.definition
  if (!d || typeof d !== 'object') return null
  return typeof d.format === 'string' ? d.format : null
})

const documentContent = computed<string | null>(() => {
  const d = trace.value?.definition
  if (d && typeof d.static_content === 'string' && d.static_content) {
    return d.static_content.length > 2000
      ? d.static_content.slice(0, 2000) + '…'
      : d.static_content
  }
  const result = trace.value?.result
  if (typeof result === 'string' && result) {
    return result.length > 2000 ? result.slice(0, 2000) + '…' : result
  }
  return null
})

function formatResult(v: any): string {
  if (typeof v === 'string') return v
  try { return JSON.stringify(v, null, 2) } catch { return String(v) }
}

// ---- Trace fetch ----
//
// Skip types whose useful data lives on the equation already (flow_input/
// output, control supernodes, llm_batch fan-out parents) or that have their
// own non-trace UI elsewhere (info markdown, hitl tasks).
const SKIP_TRACE_TYPES = new Set([
  'flow_input', 'flow_output', 'control', 'llm_batch', 'info', 'hitl',
])

async function fetchTrace({ silent = false }: { silent?: boolean } = {}) {
  const eq = props.equation
  if (!eq || props.flowId == null) return
  if (SKIP_TRACE_TYPES.has(eq.equation_type)) { trace.value = null; return }
  if (!silent) {
    loading.value = true
    loadError.value = null
  }
  try {
    const url = `${getApiBase()}/flows/${props.flowId}/equations/${encodeURIComponent(eq.equation_key)}/trace`
    const res = await axios.get(url)
    trace.value = res.data
    if (silent) loadError.value = null
  } catch (err: any) {
    loadError.value = err?.response?.data?.detail || err?.message || 'Failed to load trace'
  } finally {
    if (!silent) loading.value = false
  }
}

let pollTimer: ReturnType<typeof setInterval> | null = null
function startPolling() {
  stopPolling()
  pollTimer = setInterval(() => {
    if (!props.active) { stopPolling(); return }
    if (props.equation.status !== 'computing') { stopPolling(); return }
    fetchTrace({ silent: true })
  }, 2000)
}
function stopPolling() {
  if (pollTimer != null) { clearInterval(pollTimer); pollTimer = null }
}

watch(
  () => [props.active, props.equation.equation_key] as const,
  ([active]) => {
    trace.value = null
    if (active) fetchTrace()
  },
  { immediate: true },
)

watch(
  () => [props.active, props.equation.status] as const,
  ([active, status], prev) => {
    if (!active) { stopPolling(); return }
    if (status === 'computing') startPolling()
    else stopPolling()
    // Pull a final trace when transitioning out of computing so the
    // response/result lands in the body once the engine finishes.
    const prevStatus = prev?.[1]
    if (prevStatus === 'computing' && status !== 'computing') {
      fetchTrace({ silent: true })
    }
  },
)

onBeforeUnmount(() => stopPolling())
</script>
