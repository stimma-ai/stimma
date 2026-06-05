<template>
  <div v-if="groups.length > 0">
    <div class="flex items-center gap-2 py-2.5">
      <span class="text-[15px] font-semibold text-content tracking-wide">Outputs</span>
      <span class="text-[11px] text-content-muted tabular-nums">{{ populatedCount }} {{ populatedCount === 1 ? 'item' : 'items' }}</span>
    </div>

    <div class="py-3 space-y-3">
      <div
        v-for="group in groups"
        :key="group.key"
        class="rounded-md border border-edge-subtle bg-base overflow-hidden"
      >
        <div class="flex items-center gap-2 px-3 py-2 bg-overlay-subtle border-b border-edge-subtle">
          <span class="text-[13px] font-semibold text-content truncate">{{ group.label }}</span>
          <span class="text-[11px] text-content-muted tabular-nums">{{ groupCountLabel(group) }}</span>
        </div>

        <!-- Text-shaped outputs (llm() strings, code() returning a value) get
             the full-width row stack so multi-line content reads cleanly.
             Media outputs keep the tile grid. Mirrors IterationGroup so the
             Outputs panel and the per-step group treat the same iteration
             the same way. -->
        <div
          v-if="group.contentKind === 'text'"
          class="flex flex-col gap-1.5 p-2"
          :style="groupLayout(group) === 'compact' ? 'max-height: 420px; overflow-y: auto;' : undefined"
        >
          <RecipeIterationRow
            v-for="it in group.iterations"
            :key="it.wrapperKey"
            :iteration="it"
            :render-markdown="group.outputType === 'markdown'"
            @open="openedIteration = $event"
            @invalidate="(k) => $emit('invalidate-equation', k)"
          />
        </div>
        <div
          v-else
          class="grid gap-2 p-2"
          :class="gridColsClass(group)"
          :style="groupLayout(group) === 'compact' ? 'max-height: 420px; overflow-y: auto;' : undefined"
        >
          <IterationCard
            v-for="it in group.iterations"
            :key="it.wrapperKey"
            :iteration="it"
            :size="groupLayout(group) === 'inline' ? 'full' : 'compact'"
            @open="openedIteration = $event"
            @invalidate="(k) => $emit('invalidate-equation', k)"
          />
        </div>
      </div>
    </div>

    <RecipeIterationModal
      :iteration="openedIteration"
      :recipe-id="recipeId"
      @close="openedIteration = null"
      @invalidate-equation="(k) => $emit('invalidate-equation', k)"
      @fix-step-with-agent="(e) => $emit('fix-step-with-agent', e)"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import IterationCard from './IterationCard.vue'
import RecipeIterationRow from './RecipeIterationRow.vue'
import RecipeIterationModal from './RecipeIterationModal.vue'
import {
  buildIterationsForForeach,
  buildSyntheticIteration,
  classifyEquationBlock,
  classifyGroupContentKind,
  type BlockReason,
  type GroupedIteration,
} from '../../composables/useRecipeGrouping'
import type { RecipeEquation } from '../../composables/useRecipesApi'

interface Props {
  equationsByKey: Map<string, RecipeEquation>
}
const props = defineProps<Props>()
defineEmits<{
  (e: 'invalidate-equation', equationKey: string): void
  (e: 'fix-step-with-agent', equation: RecipeEquation): void
}>()

const route = useRoute()
const recipeId = computed<number | null>(() => {
  const raw = route.params.id
  const n = Array.isArray(raw) ? raw[0] : raw
  const parsed = n == null ? NaN : Number(n)
  return Number.isFinite(parsed) ? parsed : null
})

// Same scale thresholds as IterationGroup so the Outputs panel and iteration
// groups render at matching density.
const INLINE_MAX = 12
const COMPACT_MAX = 50

interface OutputGroup {
  key: string
  label: string
  iterations: GroupedIteration[]
  contentKind: 'media' | 'text'
  outputType: string | null
}

function isEquationActionable(eq: RecipeEquation): boolean {
  return eq.dependencies.every((depKey) => {
    const dep = props.equationsByKey.get(depKey)
    return !dep || dep.status === 'completed' || dep.status === 'skipped'
  })
}

const groups = computed<OutputGroup[]>(() => {
  const byKey = new Map<string, OutputGroup>()
  const order: string[] = []

  function getOrCreate(key: string, label: string): OutputGroup {
    let g = byKey.get(key)
    if (!g) {
      g = { key, label, iterations: [], contentKind: 'media', outputType: null }
      byKey.set(key, g)
      order.push(key)
    }
    return g
  }

  for (const eq of props.equationsByKey.values()) {
    if (!eq.is_output) continue
    // Per-iteration child wrappers are surfaced via their parent loop
    // primitive, never as standalone outputs. Both foreach iterations
    // (control_kind=foreach_iteration) and hitl.approve' per-slot wrappers
    // (control_kind=slot) need to be skipped here.
    if (eq.equation_type === 'control'
      && (eq.control_kind === 'foreach_iteration' || eq.control_kind === 'slot')
    ) continue

    // Iterating primitives — foreach and hitl.approve — surface as a group
    // of N iteration tiles in the Outputs panel. Without this branch the
    // wrapper falls through to buildSyntheticIteration and renders its
    // raw `result` list (`[1192,1194,...]`) as a single text tile, which
    // is what was happening for hitl.approve before this case existed.
    const isLoop = eq.equation_type === 'control'
      && (eq.control_kind === 'foreach' || eq.control_kind === 'approve')
    // Loop primitives are typically flagged scaffolding, but they're the
    // declaration we surface for an iterated output — skip the scaffolding
    // filter only for them.
    if (!isLoop && eq.is_scaffolding) continue

    const groupKey = eq.output_name ?? `__unnamed__:${eq.equation_key}`
    const groupLabel = eq.output_name
      ? titleCaseOutputLabel(eq.output_name)
      : (eq.display_name ?? 'Output')
    const group = getOrCreate(groupKey, groupLabel)
    if (!group.outputType && eq.output_type) group.outputType = eq.output_type

    if (isLoop) {
      // buildIterationsForForeach already finds children where
      // isIterationWrapper(child) is true, which includes both
      // foreach_iteration and slot wrappers (see useRecipeGrouping).
      let iters = buildIterationsForForeach(eq, props.equationsByKey, { isEquationActionable })

      // hitl.approve gates each slot's output behind a HITL approve.
      // Pre-approval the candidate's media is set on the tool() child,
      // but it has not been "accepted" yet — surfacing it in Outputs
      // would let unapproved candidates pass through. Mask media on
      // slots whose approve isn't completed-truthy and re-point the
      // tile at the approve equation so its actual status (and block
      // reason, when pending) drives the placeholder. The group's
      // "X of N" count reflects only approved slots. Steps view (HITL
      // approve cells) is unaffected — that's the action surface where
      // the candidate *must* be visible so the user can decide.
      if (eq.control_kind === 'approve') {
        const blockMemo = new Map<string, BlockReason>()
        iters = iters.map((it) => {
          const approveEq = it.equations.find(
            (e) => e.equation_type === 'hitl' && e.hitl_kind === 'approve',
          )
          const isApproved = approveEq != null
            && approveEq.status === 'completed'
            && approveEq.result !== false
          if (isApproved) return it
          // Status is the approve equation's status when present; when the
          // slot hasn't expanded far enough to have an approve yet, fall
          // back to 'pending' so the tile reads "not ready" rather than
          // showing the iteration's rolled-up state (which may include
          // an actively computing producer).
          const status = approveEq?.status ?? 'pending'
          const blockReason = approveEq && status === 'pending'
            ? classifyEquationBlock(approveEq, props.equationsByKey, blockMemo)
            : null
          return {
            ...it,
            primary: approveEq ?? it.primary,
            hasMedia: false,
            status,
            blockReason,
            isQueued: blockReason === 'cap',
          }
        })
      }

      group.iterations.push(...iters)
    } else {
      group.iterations.push(
        buildSyntheticIteration(eq, props.equationsByKey, { isEquationActionable }),
      )
    }
  }

  // Classify each group as text- or media-shaped using the same rule
  // IterationGroup uses (any iteration produced media → media; pure
  // llm()/completed-code() with no media → text). Done after population
  // so the classifier sees every primary in the group.
  for (const g of byKey.values()) {
    g.contentKind = classifyGroupContentKind(g.iterations.map((i) => i.primary))
  }

  return order.map((k) => byKey.get(k)!)
})

// "Populated" = "this output slot has actually delivered a value". For
// media groups that's hasMedia; for text groups (llm() / code() returning
// a string or scalar) hasMedia is always false, so completion of the
// primary is the right signal.
function isIterationPopulated(it: GroupedIteration, kind: 'media' | 'text'): boolean {
  if (kind === 'text') return it.status === 'completed'
  return it.hasMedia
}

const populatedCount = computed(() => {
  let n = 0
  for (const g of groups.value)
    for (const it of g.iterations)
      if (isIterationPopulated(it, g.contentKind)) n++
  return n
})

function groupPopulated(g: OutputGroup): number {
  return g.iterations.reduce(
    (n, it) => n + (isIterationPopulated(it, g.contentKind) ? 1 : 0),
    0,
  )
}
function groupCountLabel(g: OutputGroup): string {
  const total = g.iterations.length
  const pop = groupPopulated(g)
  if (pop === total) return `${total} ${total === 1 ? 'item' : 'items'}`
  return `${pop} of ${total}`
}

function titleCaseOutputLabel(label: string): string {
  const words = label
    .trim()
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .split(' ')
    .filter(Boolean)

  if (words.length === 0) return 'Output'

  return words
    .map((word) => {
      const lower = word.toLowerCase()
      if (/^[a-z]$/.test(lower)) return lower
      if (/^\d+$/.test(lower)) return lower
      return lower[0].toUpperCase() + lower.slice(1)
    })
    .join(' ')
}

function groupLayout(g: OutputGroup): 'inline' | 'compact' | 'summary' {
  const n = g.iterations.length
  if (n <= INLINE_MAX) return 'inline'
  if (n <= COMPACT_MAX) return 'compact'
  return 'summary'
}
function gridColsClass(g: OutputGroup): string {
  switch (groupLayout(g)) {
    case 'inline':  return 'grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6'
    case 'compact': return 'grid-cols-6 sm:grid-cols-8'
    default:        return 'grid-cols-8'
  }
}

const openedIteration = ref<GroupedIteration | null>(null)
</script>
