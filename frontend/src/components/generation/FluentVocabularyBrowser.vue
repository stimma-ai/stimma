<template>
  <!-- Dev: the vocabulary lists Fluent picks can be bound to. Tree of lists on the left,
       the chosen list on the right; the context dims the values that don't fit it. On a
       phone the panes stack: the tree, then the list you tap. -->
  <Modal :show="show" size="custom" custom-class="w-[1100px] max-w-[calc(100vw-2rem)]" @close="emit('close')">
    <div class="flex flex-col h-[min(88dvh,820px)]" data-vocab-browser>
      <div class="flex items-center gap-2 px-4 pt-3 pb-2">
        <button
          v-if="isCompact && paneDetail"
          type="button"
          class="-ml-1.5 p-1 rounded-md text-content-tertiary hover:text-content hover:bg-overlay-subtle coarse:min-h-11 coarse:min-w-11 flex items-center justify-center"
          aria-label="Back to lists"
          @click="paneDetail = false"
        >
          <ChevronLeftIcon class="w-icon-nav h-icon-nav" />
        </button>
        <span class="text-[14px] font-semibold text-content">Vocabulary</span>
        <span class="text-[10px] font-medium text-amber-600 dark:text-amber-400 bg-amber-500/15 px-1.5 py-0.5 rounded-md">Dev</span>
        <span v-if="data" class="min-w-0 truncate text-[11px] text-content-muted font-mono tabular-nums">
          {{ data.version }} · {{ data.leaves.length }} lists · {{ totalValues }} values
        </span>
        <span class="flex-1" />
        <button type="button" class="text-[12px] text-content-tertiary hover:text-content px-2 py-1 rounded-md hover:bg-overlay-subtle" :disabled="loading" @click="load">Reload</button>
        <button type="button" class="text-content-tertiary hover:text-content p-1 rounded-md hover:bg-overlay-subtle" aria-label="Close" @click="emit('close')">✕</button>
      </div>

      <div v-if="data" class="flex flex-wrap items-center gap-2 px-4 pb-3">
        <SearchField v-model="query" placeholder="Search lists and values" class="flex-1 min-w-[12rem] compact:basis-full" @escape="query = ''" />
        <label v-for="f in contextFacets" :key="f" class="flex items-center gap-1.5 text-[11px] text-content-tertiary min-w-0 compact:basis-[calc(50%-0.25rem)] compact:grow">
          <span class="font-mono">{{ f }}</span>
          <select
            class="min-w-0 compact:flex-1 h-control coarse:min-h-11 rounded-md bg-field px-2 text-ctl font-mono text-content border border-transparent focus:border-accent outline-none"
            :value="context[f] ?? ''"
            @change="setContext(f, ($event.target as HTMLSelectElement).value)"
          >
            <option v-if="!data.defaults[f]" value="">any</option>
            <option v-for="v in data.facets[f]?.values || []" :key="v" :value="v">{{ v }}{{ v === data.defaults[f] ? ' ·default' : '' }}</option>
          </select>
        </label>
      </div>

      <div v-if="error" class="mx-4 mb-4 rounded-md bg-red-500/10 px-3 py-2 text-[12px] text-red-400">{{ error }}</div>
      <div v-else-if="!data" class="flex-1 flex items-center justify-center gap-2 text-[12px] text-content-secondary">
        <Spinner size="sm" /> Loading vocabulary…
      </div>

      <div v-else class="flex-1 min-h-0 flex border-t border-edge-subtle">
        <!-- Lists -->
        <nav
          v-show="!isCompact || !paneDetail"
          class="w-72 compact:w-full shrink-0 overflow-y-auto overscroll-contain py-2 border-r border-edge-subtle compact:border-r-0"
          aria-label="Vocabulary lists"
        >
          <template v-for="row in treeRows" :key="row.key">
            <button
              v-if="row.kind === 'node'"
              type="button"
              class="w-full flex items-center gap-1.5 pr-3 py-1 coarse:py-2.5 text-left text-xs font-semibold text-content-secondary hover:text-content hover:bg-overlay-subtle"
              :style="{ paddingLeft: `${12 + row.depth * 14}px` }"
              :title="row.node.description"
              :aria-expanded="row.open"
              @click="collapsed = { ...collapsed, [row.node.id]: row.open }"
            >
              <Caret :open="row.open" class="opacity-70" />
              <span class="flex-1 min-w-0 truncate">{{ row.node.label }}</span>
              <span class="font-mono tabular-nums font-normal text-content-muted">{{ row.count }}</span>
            </button>
            <button
              v-else
              type="button"
              :class="['w-full flex items-center gap-2 pr-3 py-1 coarse:py-2.5 text-left text-xs',
                row.leaf.id === selectedId ? 'bg-selection/15 text-content' : 'text-content-secondary hover:text-content hover:bg-overlay-subtle']"
              :style="{ paddingLeft: `${30 + row.depth * 14}px` }"
              :title="row.leaf.id"
              @click="select(row.leaf.id)"
            >
              <span class="flex-1 min-w-0 truncate">{{ row.leaf.label }}</span>
              <LockClosedIcon v-if="row.leaf.closed" class="w-3 h-3 shrink-0 text-content-muted" aria-label="Closed" />
              <span class="font-mono tabular-nums text-content-muted">{{ row.count }}</span>
            </button>
          </template>
          <div v-if="!treeRows.length" class="px-3 py-2 text-xs text-content-muted">No lists match</div>
        </nav>

        <!-- The chosen list -->
        <section
          v-show="!isCompact || paneDetail"
          class="flex-1 min-w-0 overflow-y-auto overscroll-contain px-4 py-3"
        >
          <template v-if="leaf">
            <div class="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <h3 class="text-lg font-semibold text-content">{{ leaf.label }}</h3>
              <span class="font-mono text-[11px] text-content-muted">{{ leaf.id }}</span>
            </div>
            <p v-if="leaf.description" class="mt-1 text-[13px] leading-snug text-content-secondary">{{ leaf.description }}</p>
            <KeyValueList class="mt-3" :rows="facts" />
            <p v-if="leaf.notes" class="mt-2 text-xs leading-snug text-content-tertiary">{{ leaf.notes }}</p>

            <div class="mt-4 mb-1.5 flex items-baseline gap-2">
              <span class="text-xs font-semibold text-content-secondary">Values</span>
              <span class="font-mono tabular-nums text-[11px] text-content-muted">{{ fitCount }} of {{ leaf.values.length }} fit</span>
              <span v-if="valueQueryActive" class="font-mono tabular-nums text-[11px] text-content-muted">· {{ shownValues.length }} match</span>
              <span class="flex-1" />
              <span class="font-mono tabular-nums text-[11px] text-content-muted">
                <template v-for="(t, i) in tierCounts" :key="t.tier">{{ i ? ' · ' : '' }}{{ t.tier }} {{ t.n }}</template>
              </span>
            </div>
            <ul class="divide-y divide-edge-subtle">
              <li
                v-for="v in shownValues"
                :key="v.value.text"
                :class="['py-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-0.5', v.fits ? '' : 'opacity-40']"
                :title="v.fits ? undefined : 'Doesn’t fit this context'"
              >
                <span class="text-[13px] text-content min-w-0 break-words">{{ v.value.text }}</span>
                <span :class="['font-mono text-[10px] px-1.5 py-px rounded-md bg-overlay-subtle', TIER_TEXT[v.value.tier] || 'text-content-tertiary']">{{ v.value.tier }}</span>
                <span v-for="(tag, f) in v.value.tags || {}" :key="f" class="font-mono text-[10px] text-content-muted">
                  {{ f }}: {{ tag === 'any' ? 'any' : tag.join(', ') }}
                </span>
              </li>
            </ul>
          </template>
          <div v-else class="py-8 text-center text-xs text-content-muted">Choose a list</div>
        </section>
      </div>
    </div>
  </Modal>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import axios from 'axios'
import { ChevronLeftIcon, LockClosedIcon } from '@heroicons/vue/24/outline'
import Modal from '../ui/Modal.vue'
import SearchField from '../ui/SearchField.vue'
import KeyValueList from '../ui/KeyValueList.vue'
import Caret from '../ui/Caret.vue'
import Spinner from '../ui/Spinner.vue'
import { getApiBase } from '../../apiConfig'
import { useViewport } from '../../composables/useViewport'
import {
  TIER_ORDER, buildVocabTree, effectiveContext, matchesQuery, valueFits,
  type VocabLeaf, type VocabTreeNode, type VocabValue, type Vocabulary,
} from '../../utils/programVocab'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const { isCompact } = useViewport()

const TIER_TEXT: Record<string, string> = {
  typical: 'text-content-secondary',
  plausible: 'text-content-tertiary',
  unusual: 'text-content-muted',
  generated: 'text-content-muted italic',
}

const data = ref<Vocabulary | null>(null)
const loading = ref(false)
const error = ref('')
const query = ref('')
const selectedId = ref<string | null>(null)
const collapsed = ref<Record<string, boolean>>({})
// The context's own settings; unset facets take the vocabulary's defaults.
const context = ref<Record<string, string>>({})
// Phone: which pane shows.
const paneDetail = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data: got } = await axios.get<Vocabulary>(`${getApiBase()}/prompt-programs/vocabulary`)
    data.value = got
    context.value = { ...Object.fromEntries(Object.entries(got.defaults || {}).filter(([, v]) => v)), ...context.value }
    if (!selectedId.value || !got.leaves.some(l => l.id === selectedId.value)) {
      selectedId.value = tree.value.length ? firstLeaf(tree.value)?.id ?? null : null
    }
  } catch (e: any) {
    error.value = e?.response?.data?.detail?.message || e?.response?.data?.detail || e?.message || 'Couldn’t load the vocabulary.'
  } finally {
    loading.value = false
  }
}
// Fetched once, the first time it opens; Reload fetches again.
watch(() => props.show, (open) => { if (open && !data.value && !loading.value) void load() }, { immediate: true })

const tree = computed(() => data.value ? buildVocabTree(data.value.nodes, data.value.leaves) : [])
const totalValues = computed(() => (data.value?.leaves || []).reduce((s, l) => s + l.values.length, 0))

function firstLeaf(nodes: VocabTreeNode[]): VocabLeaf | null {
  for (const n of nodes) {
    const l = n.leaves[0] || firstLeaf(n.children)
    if (l) return l
  }
  return null
}

const q = computed(() => query.value.trim())
/** Values of a leaf that match the search; null when the leaf matches by name (show all). */
function valueHits(l: VocabLeaf): VocabValue[] | null {
  if (!q.value) return null
  if (matchesQuery(`${l.label} ${l.id}`, q.value)) return null
  return l.values.filter(v => matchesQuery(v.text, q.value))
}
function leafVisible(l: VocabLeaf): boolean {
  const hits = valueHits(l)
  return hits === null || hits.length > 0
}

type TreeRow =
  | { kind: 'node'; key: string; node: VocabTreeNode; depth: number; open: boolean; count: number }
  | { kind: 'leaf'; key: string; leaf: VocabLeaf; depth: number; count: number }

const treeRows = computed<TreeRow[]>(() => {
  // A node's rows (itself, then its open contents) and its count; nothing when no list under it shows.
  const walk = (n: VocabTreeNode, depth: number): { rows: TreeRow[]; count: number } => {
    const open = !!q.value || !collapsed.value[n.id]
    const inner: TreeRow[] = []
    let count = 0
    for (const c of n.children) {
      const sub = walk(c, depth + 1)
      count += sub.count
      inner.push(...sub.rows)
    }
    for (const l of n.leaves) {
      if (!leafVisible(l)) continue
      const c = valueHits(l)?.length ?? l.values.length
      count += c
      inner.push({ kind: 'leaf', key: `l:${l.id}`, leaf: l, depth, count: c })
    }
    if (!inner.length) return { rows: [], count: 0 }
    return { rows: [{ kind: 'node', key: `n:${n.id}`, node: n, depth, open, count }, ...(open ? inner : [])], count }
  }
  return tree.value.flatMap(n => walk(n, 0).rows)
})

// While searching, follow the hits: the chosen list moves to the first match if it has none.
watch(treeRows, (rows) => {
  if (!q.value) return
  const leaves = rows.filter((r): r is Extract<TreeRow, { kind: 'leaf' }> => r.kind === 'leaf')
  if (leaves.length && !leaves.some(r => r.leaf.id === selectedId.value)) selectedId.value = leaves[0].leaf.id
})

function select(id: string) {
  selectedId.value = id
  paneDetail.value = true
}

const leaf = computed(() => data.value?.leaves.find(l => l.id === selectedId.value) || null)

/** Genre and era always, plus every facet the chosen list uses. */
const contextFacets = computed(() => {
  const d = data.value
  if (!d) return []
  const out = new Set(['genre', 'era'].filter(f => d.facets[f]))
  const l = leaf.value
  if (l) {
    for (const f of l.facets) out.add(f)
    for (const f of Object.keys(l.untagged || {})) out.add(f)
    for (const v of l.values) for (const f of Object.keys(v.tags || {})) out.add(f)
  }
  return [...out].filter(f => d.facets[f])
})

function setContext(facet: string, value: string) {
  const next = { ...context.value }
  if (value) next[facet] = value
  else delete next[facet]
  context.value = next
}

const ctx = computed(() => effectiveContext(data.value?.defaults || {}, context.value))
const valueQueryActive = computed(() => !!leaf.value && valueHits(leaf.value) !== null)

const allValues = computed(() => {
  const l = leaf.value
  if (!l) return []
  const order = (t: string) => { const i = TIER_ORDER.indexOf(t as any); return i < 0 ? TIER_ORDER.length : i }
  return l.values
    .map(value => ({ value, fits: valueFits(l, value, ctx.value) }))
    .sort((a, b) => order(a.value.tier) - order(b.value.tier))
})
const shownValues = computed(() => {
  const l = leaf.value
  const hits = l ? valueHits(l) : null
  if (!hits) return allValues.value
  const keep = new Set(hits)
  return allValues.value.filter(v => keep.has(v.value))
})
const fitCount = computed(() => allValues.value.filter(v => v.fits).length)
const tierCounts = computed(() => {
  const counts = new Map<string, number>()
  for (const v of leaf.value?.values || []) counts.set(v.tier, (counts.get(v.tier) || 0) + 1)
  return [...counts.entries()]
    .sort((a, b) => TIER_ORDER.indexOf(a[0] as any) - TIER_ORDER.indexOf(b[0] as any))
    .map(([tier, n]) => ({ tier, n }))
})

const facts = computed(() => {
  const l = leaf.value
  if (!l) return []
  const untagged = Object.entries(l.untagged || {}).map(([f, v]) => `${f}: ${v.join(', ')}`).join(' · ')
  return [
    { label: 'Part of speech', value: l.pos || '—', mono: false },
    { label: 'Frame', value: l.frame || '—' },
    { label: 'List', value: l.closed ? 'Closed (never grows)' : 'Open (model adds ideas)', mono: false },
    ...(l.facets.length ? [{ label: 'Facets', value: l.facets.join(', ') }] : []),
    ...(untagged ? [{ label: 'Untagged fit', value: untagged }] : []),
  ]
})
</script>
