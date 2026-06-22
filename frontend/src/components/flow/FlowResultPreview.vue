<template>
  <!-- Friendly text rendering for any equation `result` value. The
       common case for hitl.approve / llm() is a dict with a single
       text-bearing field (`{prompt: "..."}`), which we collapse to
       just the value. Multi-key dicts list the remaining fields under
       the primary so the user can still see them without reading raw
       JSON. Anything we can't parse falls back to a stringified blob,
       but that path should be rare in practice. -->
  <div class="text-[12.5px] leading-snug text-content">
    <template v-if="primary.kind === 'empty'">
      <span class="text-content-muted">—</span>
    </template>

    <template v-else-if="primary.kind === 'string'">
      <div
        v-if="renderMarkdown"
        class="flow-result-markdown break-words"
        :class="bodyTruncationClass"
        :style="bodyMaxHeightStyle"
        ref="bodyEl"
        v-html="renderedMarkdown"
      />
      <div
        v-else
        class="whitespace-pre-wrap break-words"
        :class="bodyTruncationClass"
        :style="bodyMaxHeightStyle"
        ref="bodyEl"
      >{{ primary.text }}</div>
      <button
        v-if="canExpand"
        type="button"
        class="mt-1 text-[11px] text-content-muted hover:text-content"
        @click.stop="expanded = !expanded"
      >{{ expanded ? 'Show less' : 'Show more' }}</button>
    </template>

    <template v-else>
      <!-- Structured value (dict / array / scalar). Render the primary
           field if we found one; then a small key-value list for the
           rest. Long values inside the list are truncated to one line. -->
      <div
        v-if="primary.kind === 'object' && primary.text && renderMarkdown"
        class="flow-result-markdown break-words"
        :class="bodyTruncationClass"
        :style="bodyMaxHeightStyle"
        ref="bodyEl"
        v-html="renderedMarkdown"
      />
      <div
        v-else-if="primary.kind === 'object' && primary.text"
        class="whitespace-pre-wrap break-words"
        :class="bodyTruncationClass"
        :style="bodyMaxHeightStyle"
        ref="bodyEl"
      >{{ primary.text }}</div>
      <button
        v-if="primary.kind === 'object' && primary.text && canExpand"
        type="button"
        class="mt-1 text-[11px] text-content-muted hover:text-content"
        @click.stop="expanded = !expanded"
      >{{ expanded ? 'Show less' : 'Show more' }}</button>

      <dl
        v-if="extras.length"
        class="mt-1.5 space-y-0.5 text-[11.5px]"
      >
        <div
          v-for="(item, i) in extras"
          :key="i"
          class="flex items-baseline gap-2"
        >
          <dt class="text-content-muted shrink-0 max-w-[8rem] truncate">{{ item.key }}</dt>
          <dd class="text-content min-w-0 truncate">{{ item.value }}</dd>
        </div>
      </dl>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUpdated, nextTick } from 'vue'
import { renderSafeMarkdown } from '../../utils/sanitizeHtml'

interface Props {
  value: unknown
  renderMarkdown?: boolean
  // Cap at which the body collapses behind a "Show more" toggle.
  // Measured in CSS line-height multiples, not characters — long
  // single-paragraph LLM outputs benefit from the line cap, short
  // many-line ones don't get cut prematurely.
  maxLines?: number
  overflowMode?: 'toggle' | 'none'
}
const props = withDefaults(defineProps<Props>(), {
  maxLines: 12,
  renderMarkdown: false,
  overflowMode: 'toggle',
})

// Primary field heuristic. Order matters: `prompt` first because it's
// the dominant pattern for hitl.approve / image-gen flows; the rest
// catch generic LLM/tool outputs. Keys are checked case-insensitively.
const PRIMARY_KEYS = [
  'prompt', 'text', 'content', 'message', 'value', 'description',
  'output', 'response', 'answer', 'result', 'body', 'caption',
  'title', 'name',
]

interface PrimaryString { kind: 'string'; text: string }
interface PrimaryObject { kind: 'object'; text: string }
interface PrimaryEmpty  { kind: 'empty' }
type Primary = PrimaryString | PrimaryObject | PrimaryEmpty

function findPrimaryKey(obj: Record<string, unknown>): string | null {
  const lcKeys = new Map<string, string>()
  for (const k of Object.keys(obj)) lcKeys.set(k.toLowerCase(), k)
  for (const want of PRIMARY_KEYS) {
    const actual = lcKeys.get(want)
    if (actual && typeof obj[actual] === 'string' && (obj[actual] as string).trim().length > 0) {
      return actual
    }
  }
  return null
}

function stringify(v: unknown): string {
  if (v == null) return ''
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  try { return JSON.stringify(v) } catch { return String(v) }
}

const primary = computed<Primary>(() => {
  const v = props.value
  if (v == null) return { kind: 'empty' }
  if (typeof v === 'string') {
    const t = v.trim()
    return t.length === 0 ? { kind: 'empty' } : { kind: 'string', text: v }
  }
  if (typeof v === 'number' || typeof v === 'boolean') {
    return { kind: 'string', text: String(v) }
  }
  if (Array.isArray(v)) {
    if (v.length === 0) return { kind: 'empty' }
    // Array of strings: bullet-style. Array of objects: count + first
    // item preview. Either way, surface as the primary so the row
    // reads at a glance.
    const allStrings = v.every((x) => typeof x === 'string')
    if (allStrings) {
      return { kind: 'object', text: (v as string[]).map((s) => `• ${s}`).join('\n') }
    }
    return { kind: 'object', text: `${v.length} item${v.length === 1 ? '' : 's'}` }
  }
  if (typeof v === 'object') {
    const obj = v as Record<string, unknown>
    const pk = findPrimaryKey(obj)
    if (pk) return { kind: 'object', text: stringify(obj[pk]) }
    // No primary key — render compact JSON as a fallback so the user
    // can still see the data, just not pretty.
    const json = stringify(obj)
    return { kind: 'object', text: json.length > 280 ? json.slice(0, 280) + '…' : json }
  }
  return { kind: 'string', text: String(v) }
})

const extras = computed<{ key: string; value: string }[]>(() => {
  const v = props.value
  if (v == null || typeof v !== 'object' || Array.isArray(v)) return []
  const obj = v as Record<string, unknown>
  const pk = findPrimaryKey(obj)
  const out: { key: string; value: string }[] = []
  for (const k of Object.keys(obj)) {
    if (k === pk) continue
    const sv = stringify(obj[k])
    if (sv.trim().length === 0) continue
    out.push({ key: k, value: sv })
  }
  return out
})

// Show-more behavior — measured against rendered height vs. the
// max-lines line-height cap. We check after render and on updates so
// dynamic content (LLM streaming results into a complete state)
// re-evaluates whether the toggle is needed.
const expanded = ref(false)
const overflows = ref(false)
const bodyEl = ref<HTMLElement | null>(null)

const lineHeightPx = 18 // matches text-[12.5px] leading-snug ≈ 1.45 * 12.5
const cappedHeightPx = computed(() => props.maxLines * lineHeightPx)

const bodyMaxHeightStyle = computed<string | undefined>(() =>
  expanded.value || props.overflowMode === 'none'
    ? undefined
    : `max-height: ${cappedHeightPx.value}px;`,
)
const bodyTruncationClass = computed(() => {
  if (props.overflowMode === 'none') return ''
  return expanded.value ? '' : 'overflow-hidden'
})

const canExpand = computed(() => props.overflowMode === 'toggle' && overflows.value)

const renderMarkdown = computed(() =>
  props.renderMarkdown && (primary.value.kind === 'string' || primary.value.kind === 'object'),
)
const renderedMarkdown = computed(() => {
  const text = primary.value.kind === 'empty' ? '' : primary.value.text
  return renderSafeMarkdown(text)
})

function measure() {
  const el = bodyEl.value
  if (!el) { overflows.value = false; return }
  // scrollHeight reflects the natural (uncapped) height; compare to
  // the capped pixel height to decide if the toggle is needed.
  overflows.value = el.scrollHeight > cappedHeightPx.value + 1
}

onMounted(() => { nextTick(measure) })
onUpdated(() => { nextTick(measure) })
</script>

<style scoped>
.flow-result-markdown :deep(p) {
  margin: 0 0 0.65em;
}
.flow-result-markdown :deep(p:last-child) {
  margin-bottom: 0;
}
.flow-result-markdown :deep(strong) {
  font-weight: 700;
}
.flow-result-markdown :deep(ul),
.flow-result-markdown :deep(ol) {
  margin: 0.5em 0;
  padding-left: 1.35em;
}
.flow-result-markdown :deep(ul) {
  list-style: disc;
}
.flow-result-markdown :deep(ol) {
  list-style: decimal;
}
.flow-result-markdown :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.92em;
}
</style>
