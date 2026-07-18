<template>
  <div
    class="phase-node"
    :class="isTopLevelPhase ? 'border-t border-edge-subtle pt-3 first:border-t-0 first:pt-0' : ''"
  >
    <!-- Header row. Always-expanded: no chevron, no click toggle. Structure =
         indentation + a status rail, never a nested box (STANDARDS §3.1):
         mono phase index + title + StatusDot, mono rollup right. -->
    <div
      v-if="node.name || depth > 0"
      class="relative flex items-baseline gap-2.5 group"
      :class="[
        isTopLevelPhase ? 'pb-2' : 'py-1.5 px-2 rounded',
        phaseIsEchoed ? 'ring-1 ring-blue-500/40 bg-blue-500/5' : '',
      ]"
    >
      <span
        v-if="isTopLevelPhase && phaseIndex != null"
        class="flex-shrink-0 font-mono text-[10px] text-content-muted"
      >PHASE {{ phaseIndex }}</span>
      <span
        class="text-content truncate"
        :class="isTopLevelPhase ? 'text-[13.5px] font-semibold' : 'text-[14px] font-semibold'"
      >{{ displayName }}</span>

      <StatusDot :bucket="phaseStatusBucket" :pulse="phaseStatus.kind === 'tasks' || phaseStatus.kind === 'running'" />

      <!-- Phase status label — kept for the states that need more than a
           color (Running / Your Turn / Error / Waiting); "Done" is
           intentionally silent since the dot + duration already say it. -->
      <span
        v-if="phaseStatus.kind === 'running'"
        class="flex-shrink-0 flex items-center gap-1 text-[10.5px] font-medium text-blue-500"
      >
        <span v-if="isPaused" class="text-[11px] text-amber-500">⏸</span>
        <span>Running</span>
      </span>
      <span
        v-else-if="phaseStatus.kind === 'tasks'"
        class="flex-shrink-0 text-[10.5px] font-medium text-purple-500"
      >Your Turn</span>
      <span
        v-else-if="phaseStatus.kind === 'error'"
        class="flex-shrink-0 text-[10.5px] font-medium text-red-500"
      >{{ phaseStatus.label }}</span>
      <span
        v-else-if="phaseStatus.kind === 'waiting'"
        class="flex-shrink-0 text-[10.5px] font-medium text-content-muted"
      >Waiting</span>

      <span class="flex-1"></span>

      <!-- Right-aligned metadata columns. Ratio shows progress across steps
           ("3/3", "1/4"); duration is total wall-clock; re-run is always
           visible so users don't have to hover-hunt to retry. -->
      <span
        v-if="phaseRatioLabel"
        class="flex-shrink-0 font-mono text-[11px] text-content-tertiary tabular-nums"
      >{{ phaseRatioLabel }}</span>
      <span
        v-if="phaseDurationLabel"
        class="flex-shrink-0 font-mono text-[11px] text-content-tertiary tabular-nums w-14 text-right"
      >{{ phaseDurationLabel }}</span>
      <FlowRefButton
        :ref-key="phaseRefKey"
        kind="phase"
        :label="displayName"
      />
      <button
        class="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded-md text-content-muted hover:text-content hover:bg-overlay-hover"
        title="Re-run all steps in this section"
        @click.stop="$emit('invalidate-phase', node.path)"
      >
        <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
        </svg>
      </button>

      <!-- Progress bar when this phase is actively running. Rides the bottom
           edge of the header so a user scanning down the card stack sees
           motion without any extra chrome. -->
      <div
        v-if="phaseStatus.kind === 'running' && phaseProgressFraction != null"
        class="absolute left-0 bottom-0 h-0.5 bg-blue-500 transition-[width] duration-500"
        :style="{ width: (phaseProgressFraction * 100) + '%' }"
      />
    </div>

    <!-- Contents — phases are always expanded. Steps sit on a rail: 2px
         border indented under the phase header (STANDARDS §3.1), never a
         nested box. -->
    <div
      :class="isTopLevelPhase
        ? 'border-l-2 border-edge-subtle ml-1 pl-4'
        : (depth > 0 ? 'ml-4 pl-3' : '')"
    >

        <!-- Unified step list: info, LLM, code, tool, and HITL live in one
             ordered stream. Foreach iterations collapse into a single
             IterationGroup so N=4 (or N=400) reads as one unit. Top-level
             phases get rows separated by subtle dividers (no gaps); nested
             phases keep the legacy spaced-list layout. -->
        <div
          v-if="showDirectContent && stepItems.length > 0"
          :class="isTopLevelPhase ? 'divide-y divide-edge-subtle' : 'space-y-1.5 py-2'"
        >
          <template v-for="item in stepItems" :key="stepItemKey(item)">

            <!-- Loop group — one row per foreach()/hitl.approve sub-step.
                 Producer sub-steps render with tile cells; HITL approve
                 sub-steps render with approve cells (cellMode prop on
                 the group). Auto-expand and lock-open follow the
                 group's actionable aggregate, so HITL rows lock open
                 while pending approvals exist. -->
            <IterationGroup
              v-if="item.kind === 'group'"
              :group="item"
              :flow-id="flowId"
              :is-paused="isPaused"
              :dev-mode="devMode"
              :tasks-by-equation-key="tasksByEquationKey"
              @invalidate-equation="(k) => $emit('invalidate-equation', k)"
              @fix-step-with-agent="(e) => $emit('fix-step-with-agent', e)"
              @resolve-task="(t, r) => $emit('resolve-task', t, r)"
            />

            <template v-else-if="item.kind === 'equation'">
            <template v-for="eq in [item.eq]" :key="eq.equation_key">

            <!-- Info row — flat, no nested box; the phase rail already frames it. -->
            <div
              v-if="eq.equation_type === 'info'"
              class="group"
              :class="isEqEchoed(eq) ? 'ring-1 ring-blue-500/40 bg-blue-500/5 rounded' : ''"
            >
              <div
                role="button"
                tabindex="0"
                class="w-full flex items-center gap-2.5 px-2.5 py-1.5 text-[12px] text-left cursor-pointer"
                @click="toggleInfoExpanded(eq)"
                @keydown.enter.prevent="toggleInfoExpanded(eq)"
                @keydown.space.prevent="toggleInfoExpanded(eq)"
              >
                <span
                  v-if="eq.status === 'computing' && !isPaused"
                  class="w-3 h-3 border-2 border-teal-400 border-t-transparent rounded-full animate-spin flex-shrink-0"
                />
                <span v-else-if="eq.status === 'computing' && isPaused" class="text-amber-400/80 text-[11px] flex-shrink-0">⏸</span>
                <svg
                  v-else-if="eq.status === 'completed'"
                  class="w-4 h-4 text-green-500 flex-shrink-0"
                  fill="currentColor" viewBox="0 0 24 24"
                >
                  <path fill-rule="evenodd" clip-rule="evenodd" d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10zm4.03-12.97a.75.75 0 00-1.06-1.06l-4.72 4.72-2.22-2.22a.75.75 0 10-1.06 1.06l2.75 2.75a.75.75 0 001.06 0l5.25-5.25z" />
                </svg>
                <svg
                  v-else-if="eq.status === 'failed'"
                  class="w-3.5 h-3.5 text-red-400 flex-shrink-0"
                  fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor"
                >
                  <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
                <svg
                  v-else-if="eq.status === 'skipped'"
                  class="w-3.5 h-3.5 text-content-muted/60 flex-shrink-0"
                  fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor"
                >
                  <path stroke-linecap="round" stroke-linejoin="round" d="M5 12h14" />
                </svg>
                <span v-else class="w-2 h-2 rounded-full border border-content-muted/40 flex-shrink-0" />

                <div class="flex-1 min-w-0 flex flex-col justify-center">
                  <span class="truncate text-[13px] leading-tight text-content">{{ eq.display_name }}</span>
                  <span
                    v-if="eq.description"
                    class="truncate text-[11px] leading-tight text-content-muted"
                  >{{ eq.description }}</span>
                </div>

                <span
                  class="flex-shrink-0 font-mono text-[10.5px] font-semibold uppercase tracking-wide tabular-nums w-[72px] text-right"
                  :class="equationStatusColor(eq)"
                >{{ equationStatusLabel(eq) || '' }}</span>
                <span
                  class="flex-shrink-0 font-mono text-[11px] text-content-tertiary tabular-nums w-14 text-right"
                >{{ equationDurationLabel(eq) || '' }}</span>
                <FlowRefButton
                  :ref-key="eq.equation_key"
                  kind="equation"
                  :label="eq.display_name || 'Info'"
                  :breadcrumb="eqBreadcrumb(eq)"
                />
                <button
                  v-if="eq.status === 'completed' || eq.status === 'failed'"
                  type="button"
                  class="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded-md text-content-muted hover:text-content hover:bg-overlay-hover"
                  title="Re-run this step"
                  @click.stop="$emit('invalidate-equation', eq.equation_key)"
                >
                  <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
                  </svg>
                </button>
                <span v-else class="flex-shrink-0 w-6 h-6" aria-hidden="true" />
              </div>

              <!-- Expanded = the ONE wash inset, deepest level only (§3.1). -->
              <Transition name="flow-expand">
              <div v-if="isInfoExpanded(eq)">
              <div class="bg-overlay-faint rounded-md p-2 my-1 space-y-2">
                <div
                  v-if="eq.status === 'completed' && infoMarkdown(eq)"
                  class="info-prose text-[12.5px] text-content leading-relaxed break-words select-text"
                  v-html="infoMarkdown(eq)"
                />
                <div v-else-if="eq.status === 'computing'" class="text-[11px] text-content-muted italic">
                  Preparing…
                </div>
                <div v-else-if="eq.status === 'pending'" class="text-[11px] text-content-muted italic">
                  Waiting for upstream steps to finish.
                </div>
                <div v-else-if="eq.status === 'failed'" class="space-y-2">
                  <div class="text-[11px] text-red-400">This step failed.</div>
                  <div class="flex items-center gap-1.5">
                    <button
                      class="text-[11px] px-2 py-0.5 rounded-md bg-accent text-white hover:bg-accent/90"
                      @click.stop="$emit('fix-step-with-agent', eq)"
                    >Ask the agent for help</button>
                    <button
                      class="text-[11px] px-2 py-0.5 rounded-md bg-overlay-subtle text-content-muted hover:text-content hover:bg-overlay-hover"
                      @click.stop="$emit('invalidate-equation', eq.equation_key)"
                    >Retry ↻</button>
                  </div>
                </div>

                <div
                  v-if="eq.result_media_ids && eq.result_media_ids.length > 0"
                  class="flex flex-wrap gap-1.5 pt-0.5"
                >
                  <div
                    v-for="mid in eq.result_media_ids"
                    :key="mid"
                    class="w-14 h-14 rounded-md border border-edge-subtle overflow-hidden"
                  >
                    <FlowMediaTile
                      :media-id="mid"
                      :media-ids="eq.result_media_ids"
                      :index="eq.result_media_ids.indexOf(mid)"
                      :thumbnail="true"
                      :thumbnail-size="128"
                      :contain="!isCompositeEquation(eq)"
                      container-class="w-full h-full"
                    />
                  </div>
                </div>

                <div
                  v-if="devMode && eq.error"
                  class="rounded border border-amber-500/40 bg-overlay-light text-[11px] font-mono text-content-secondary"
                >
                  <div class="flex items-center gap-2 px-2.5 py-1.5 border-b border-amber-500/30">
                    <span class="text-[9px] font-bold uppercase tracking-wider text-amber-600 dark:text-amber-400 bg-amber-500/15 px-1.5 py-0.5 rounded-sm">Dev</span>
                    <span class="text-content-muted">raw step error</span>
                    <span class="flex-1" />
                    <span class="text-content-muted truncate">{{ eq.equation_key }}</span>
                  </div>
                  <pre class="px-2.5 py-2 whitespace-pre-wrap break-words select-text">{{ eq.error }}</pre>
                </div>
              </div>
              </div>
              </Transition>
            </div>

            <!-- LLM / tool / code / control call — trace row -->
            <EquationTraceRow
              v-else-if="eq.equation_type !== 'hitl'"
              :equation="eq"
              :is-paused="isPaused"
              :dev-mode="devMode"
              :equations-by-key="equationsByKey"
              @invalidate-equation="(k) => $emit('invalidate-equation', k)"
              @fix-step-with-agent="(e) => $emit('fix-step-with-agent', e)"
            />

            <!-- HITL row — same chrome as trace rows (status icon, title,
                 status label, chevron). Expanded content depends on kind +
                 status. -->
            <!-- HITL row — flat, same chrome as an info row. The actionable
                 ("Your Turn") state doesn't raise the row itself; TaskCard
                 below is the one raised surface for the actual controls
                 (STANDARDS §3.1: elevation = actionability, two containments
                 total in the tree). -->
            <div
              v-else
              class="group"
              :class="isEqEchoed(eq) ? 'ring-1 ring-blue-500/40 bg-blue-500/5 rounded' : ''"
            >
              <div
                :role="isHitlLockedOpen(eq) ? undefined : 'button'"
                :tabindex="isHitlLockedOpen(eq) ? undefined : 0"
                class="w-full flex items-center gap-2.5 px-2.5 py-1.5 text-[12px] text-left"
                :class="isHitlLockedOpen(eq) ? 'cursor-default' : 'cursor-pointer'"
                @click="toggleHitlExpanded(eq)"
                @keydown.enter.prevent="toggleHitlExpanded(eq)"
                @keydown.space.prevent="toggleHitlExpanded(eq)"
              >
                <!-- Status icon — matches EquationTraceRow -->
                <svg
                  v-if="eq.status === 'completed'"
                  class="w-4 h-4 text-green-500 flex-shrink-0"
                  fill="currentColor" viewBox="0 0 24 24"
                >
                  <path fill-rule="evenodd" clip-rule="evenodd" d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10zm4.03-12.97a.75.75 0 00-1.06-1.06l-4.72 4.72-2.22-2.22a.75.75 0 10-1.06 1.06l2.75 2.75a.75.75 0 001.06 0l5.25-5.25z" />
                </svg>
                <StatusDot
                  v-else-if="isEquationActionable(eq) && getTasksForEquation(eq.equation_key).length > 0"
                  bucket="awaiting"
                  pulse
                />
                <span
                  v-else-if="isEquationActionable(eq)"
                  class="w-3 h-3 border-2 border-blue-400 border-t-transparent rounded-full animate-spin flex-shrink-0"
                />
                <span v-else class="w-2 h-2 rounded-full border border-content-muted/40 flex-shrink-0" />

                <!-- Title + optional subtitle. Actionable HITL reads as
                     "Your Turn" / "Pick one"; other states are single-line. -->
                <div class="flex-1 min-w-0 flex flex-col justify-center">
                  <span class="truncate text-[13px] leading-tight text-content">{{ hitlTitle(eq) }}</span>
                  <span
                    v-if="hitlSubtitle(eq)"
                    class="truncate text-[11px] leading-tight text-content-muted"
                  >{{ hitlSubtitle(eq) }}</span>
                </div>

                <span
                  class="flex-shrink-0 font-mono text-[10.5px] font-semibold uppercase tracking-wide tabular-nums w-[72px] text-right"
                  :class="equationStatusColor(eq)"
                >{{ equationStatusLabel(eq) || '' }}</span>
                <span
                  class="flex-shrink-0 font-mono text-[11px] text-content-tertiary tabular-nums w-14 text-right"
                >{{ equationDurationLabel(eq) || '' }}</span>
                <FlowRefButton
                  :ref-key="eq.equation_key"
                  kind="equation"
                  :label="hitlTitle(eq)"
                  :breadcrumb="eqBreadcrumb(eq)"
                />
                <button
                  v-if="eq.status === 'completed' || eq.status === 'failed'"
                  type="button"
                  class="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded-md text-content-muted hover:text-content hover:bg-overlay-hover"
                  title="Re-run this step"
                  @click.stop="$emit('invalidate-equation', eq.equation_key)"
                >
                  <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
                  </svg>
                </button>
                <span v-else class="flex-shrink-0 w-6 h-6" aria-hidden="true" />
              </div>

              <!-- Expanded content. Actionable-with-task defers all elevation
                   to TaskCard (the one raised surface); every other state
                   uses the standard wash inset. -->
              <Transition name="flow-expand">
              <div v-if="isHitlExpanded(eq)">
              <div
                :class="(isEquationActionable(eq) && getTasksForEquation(eq.equation_key).length > 0)
                  ? 'my-1 space-y-2'
                  : 'bg-overlay-faint rounded-md p-2 my-1 space-y-2'"
              >
                <!-- Completed: show kind-specific details -->
                <template v-if="eq.status === 'completed'">
                  <CompletedSelectPanel
                    v-if="eq.hitl_kind === 'select'"
                    :equation="eq"
                    :flow-id="flowId"
                    @reselect="(r) => $emit('reselect-equation', eq.equation_key, r)"
                  />
                  <div
                    v-else-if="eq.hitl_kind === 'approve'"
                    class="text-[12px] text-content"
                  >
                    {{ eq.result === false ? 'Rejected' : 'Approved' }}
                  </div>
                  <div
                    v-else
                    class="text-[12px] text-content-muted italic"
                  >No details recorded.</div>
                  <div v-if="eq.hitl_kind !== 'select'" class="flex justify-end">
                    <button
                      type="button"
                      class="text-[11px] px-2 py-0.5 rounded-md bg-overlay-subtle text-content-muted hover:text-content hover:bg-overlay-hover transition-colors"
                      title="Redo this step — clears downstream and re-asks"
                      @click.stop="$emit('invalidate-equation', eq.equation_key)"
                    >Redo ↻</button>
                  </div>
                </template>

                <!-- Actionable with task -->
                <template v-else-if="isEquationActionable(eq) && getTasksForEquation(eq.equation_key).length > 0">
                  <TaskCard
                    v-for="task in getTasksForEquation(eq.equation_key)"
                    :key="task.task_id"
                    :task="task"
                    :focused="focusedTaskId === task.task_id"
                    :dev-mode="devMode"
                    :ref="(el) => registerTaskRef(task.task_id, el as any)"
                    @resolve="(t, r) => $emit('resolve-task', t, r)"
                    @resolve-error="(t, a, v) => $emit('resolve-error-task', t, a, v)"
                    @focus="(t) => $emit('focus-task', t)"
                    @edit-flow="(t) => $emit('edit-flow', t)"
                    @fix-step-with-agent="() => $emit('fix-step-with-agent', eq)"
                  />
                </template>

                <!-- Actionable, task not yet spawned -->
                <div v-else-if="isEquationActionable(eq)" class="text-[12px] text-content-muted italic">
                  Preparing…
                </div>

                <!-- Blocked -->
                <div v-else class="text-[12px] text-content-muted italic">
                  Waiting for upstream steps to finish.
                </div>
              </div>
              </div>
              </Transition>
            </div>

            </template>
            </template>

          </template>
        </div>

      <!-- Child phase nodes — wrap in a spaced stack at root depth so top-
           level phase cards sit apart rather than abutting each other.
           Children whose entire subtree is hidden (e.g. a phase containing
           only `code()` plumbing) are filtered out and skipped by the "01 /
           02 / 03" numbering, so users don't see empty cards or gaps in the
           sequence. A failed logic/code step flips its phase back to
           visible via phaseHasVisibleContent(). -->
      <div
        v-if="visibleChildren.length > 0"
        :class="depth === 0 ? 'space-y-3' : ''"
      >
      <PhaseNode
        v-for="(child, childIdx) in visibleChildren"
        :key="child.path.join('/')"
        :node="child"
        :depth="depth + 1"
        :phase-index="depth === 0 ? childIdx + 1 : null"
        :equations-by-key="equationsByKey"
        :tasks-by-equation-key="tasksByEquationKey"
        :focused-task-id="focusedTaskId"
        :execution-state="executionState"
        :dev-mode="devMode"
        @fix-step-with-agent="(e) => $emit('fix-step-with-agent', e)"
        @invalidate-phase="(p) => $emit('invalidate-phase', p)"
        @invalidate-equation="(k) => $emit('invalidate-equation', k)"
        @reselect-equation="(k, r) => $emit('reselect-equation', k, r)"
        @resolve-task="(t, r) => $emit('resolve-task', t, r)"
        @resolve-error-task="(t, a, v) => $emit('resolve-error-task', t, a, v)"
        @focus-task="(t) => $emit('focus-task', t)"
        @edit-flow="(t) => $emit('edit-flow', t)"
        @register-task-ref="(id, el) => $emit('register-task-ref', id, el)"
      />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import TaskCard from './TaskCard.vue'
import EquationTraceRow from './EquationTraceRow.vue'
import CompletedSelectPanel from './CompletedSelectPanel.vue'
import FlowMediaTile from './FlowMediaTile.vue'
import IterationGroup from './IterationGroup.vue'
import FlowRefButton from './FlowRefButton.vue'
import { useRoute } from 'vue-router'
import type { PhaseNode as PhaseNodeType, FlowEquation, FlowTask } from '../../composables/useFlowsApi'
import type { StepItem } from '../../composables/useFlowGrouping'
import { useFlowExpandState } from '../../composables/useFlowExpandState'
import { useFlowReferences, injectFlowChatIdRef } from '../../composables/useFlowReferences'
import { renderSafeMarkdown } from '../../utils/sanitizeHtml'
import { equationDurationMs, formatEquationDurationMs } from '../../utils/equationDuration'
import StatusDot from '../ui/StatusDot.vue'
import { textClass, mapEquationStatus, type StatusBucket } from '../../utils/statusColors'

interface Props {
  node: PhaseNodeType
  depth?: number
  // 1-based position of this phase within its parent's children list. Only
  // threaded for top-level phases (children of the root); drives the "01 /
  // 02 / 03" prefix in the phase card header.
  phaseIndex?: number | null
  equationsByKey: Map<string, FlowEquation>
  tasksByEquationKey: Map<string, FlowTask[]>
  focusedTaskId?: string | null
  executionState?: string
  devMode?: boolean
}
const props = withDefaults(defineProps<Props>(), {
  depth: 0, phaseIndex: null, focusedTaskId: null, executionState: 'idle', devMode: false,
})

// Top-level phases (direct children of the flow root) render as cards with
// a contrasting header; deeper nested phases keep the flat indent style.
const isTopLevelPhase = computed(() => props.depth === 1)
const emit = defineEmits<{
  (e: 'invalidate-phase', path: string[]): void
  (e: 'invalidate-equation', key: string): void
  (e: 'reselect-equation', key: string, resolution: any): void
  (e: 'resolve-task', task: FlowTask, resolution: any): void
  (e: 'resolve-error-task', task: FlowTask, action: string, value?: any): void
  (e: 'focus-task', task: FlowTask): void
  (e: 'edit-flow', task: FlowTask): void
  (e: 'register-task-ref', taskId: string, el: any): void
  (e: 'fix-step-with-agent', equation: FlowEquation): void
}>()

const route = useRoute()
const flowId = computed(() => {
  const raw = route.params.id
  const n = Array.isArray(raw) ? raw[0] : raw
  const parsed = n == null ? NaN : Number(n)
  return Number.isFinite(parsed) ? parsed : null
})

// Phase and row refs: the phase header, info rows, and HITL rows each expose
// a "Reference in chat" button in their trailing action cluster. The phase's
// refKey is the joined phase path so equation-keyed rows and phase-keyed rows
// stay in distinct namespaces. Row echo: when the user hovers the matching
// chip in the context tray, rings the source row so they can confirm what
// each chip points at.
const flowRefs = useFlowReferences(injectFlowChatIdRef())
const phaseRefKey = computed<string>(() => {
  const p = props.node.path || []
  return p.length > 0 ? `phase:${p.join('/')}` : 'phase:root'
})
const phaseIsEchoed = computed<boolean>(() =>
  flowRefs.hoveredRefKey.value === phaseRefKey.value,
)
function isEqEchoed(eq: FlowEquation): boolean {
  return flowRefs.hoveredRefKey.value === eq.equation_key
}
// Label for an equation row's breadcrumb — the immediate parent phase name.
function eqBreadcrumb(eq: FlowEquation): string {
  const p = eq.phase_path || []
  return p.length > 0 ? p[p.length - 1] : ''
}

// Composite media (grid / set) render with the standard library-browser
// cover treatment on their pre-computed square composite thumbnail.
// Everything else (images, videos, documents) uses contain so the frame
// isn't cropped by the tile.
function isCompositeEquation(eq: FlowEquation): boolean {
  return eq.equation_type === 'create_grid' || eq.equation_type === 'create_set'
}

const displayName = computed(() => props.node.name || 'Flow')
const summary = computed(() => props.node.status_summary || {})
const isPaused = computed(() => props.executionState === 'paused')

// A HITL equation is actionable only if all its upstream dependencies are completed.
function isEquationActionable(eq: FlowEquation): boolean {
  return eq.dependencies.every(depKey => {
    const dep = props.equationsByKey.get(depKey)
    return !dep || dep.status === 'completed' || dep.status === 'skipped'
  })
}

// "Your turn" means a HITL task whose deps are actually done — not just
// "some task exists in the subtree". Without this check a downstream phase
// whose HITL was pre-spawned (or an upstream HITL blocked behind a still-
// computing LLM) mis-advertises "Your turn" when the user genuinely can't
// act yet.
function hasActionableTaskInSubtree(n: PhaseNodeType): boolean {
  for (const key of n.equation_keys || []) {
    const eq = props.equationsByKey.get(key)
    if (!eq || eq.equation_type !== 'hitl') continue
    if (eq.status === 'completed' || eq.status === 'skipped') continue
    const tasks = props.tasksByEquationKey.get(key) || []
    if (tasks.length === 0) continue
    if (!isEquationActionable(eq)) continue
    return true
  }
  for (const child of n.children || []) {
    if (hasActionableTaskInSubtree(child)) return true
  }
  return false
}
const hasActionableTask = computed(() => hasActionableTaskInSubtree(props.node))

// Phase-level status chip (replaces the icon soup).
// Priority:
//   1. error  — surface failures first; user must intervene
//   2. active — something is actually running right now (LLM / tool / code)
//   3. tasks  — an actionable HITL is ready for the user
//   4. waiting — pending / blocked but nothing running
//   5. done
// Vocabulary mirrors useFlowStatus: Error > Your Turn > Running > Waiting > Done.
// `Running` keeps its spinner-only treatment (no inline label) so the existing
// "Using LLM…" hint sits next to the spinner rather than fighting a redundant chip.
const phaseStatus = computed(() => {
  const s = summary.value
  const failed = (s['failed'] || 0) as number
  const computing = (s['computing'] || 0) as number
  const pending = (s['pending'] || 0) as number
  const awaiting = (s['awaiting_input'] || 0) as number
  const waitingTool = (s['waiting_for_tool'] || 0) as number
  const completed = (s['completed'] || 0) as number
  if (failed > 0) return { kind: 'error', label: failed === 1 ? 'Error' : `${failed} errors` }
  if (awaiting > 0 || hasActionableTask.value) return { kind: 'tasks', label: 'Your Turn' }
  if (computing > 0) return { kind: 'running', label: '' }
  if (pending > 0) return { kind: 'waiting', label: 'Waiting' }
  if (waitingTool > 0) return { kind: 'waiting', label: 'Waiting for tool' }
  if (completed > 0) return { kind: 'done', label: 'Done' }
  return { kind: 'empty', label: '' }
})

// StatusDot bucket for the phase header dot (STANDARDS §1.9).
const phaseStatusBucket = computed<StatusBucket>(() => {
  switch (phaseStatus.value.kind) {
    case 'error':   return 'failed'
    case 'tasks':   return 'awaiting'
    case 'running': return 'running'
    case 'waiting': return 'warning'
    case 'done':    return 'done'
    default:        return 'queued'
  }
})

// True if anything in this phase's subtree would actually render. Mirrors
// the hide-unless-failed rules used by orderedVisibleEquationsForPhase /
// directEquations: scaffolding and `code()` plumbing disappear, info rows
// don't appear until they have a body. A failed logic/code step keeps its
// phase visible so errors never get swallowed. Phases whose entire subtree
// is hidden are dropped from the tree and the top-level numbering.
function phaseHasVisibleContent(n: PhaseNodeType): boolean {
  if ((n.steps || []).length > 0) return true
  for (const key of n.equation_keys || []) {
    const eq = props.equationsByKey.get(key)
    if (!eq) continue
    if (eq.is_scaffolding && eq.status !== 'failed') continue
    if (eq.equation_type === 'code' && eq.status !== 'failed') continue
    if (eq.equation_type === 'info' && eq.status !== 'completed') continue
    return true
  }
  for (const child of n.children || []) {
    if (phaseHasVisibleContent(child)) return true
  }
  return false
}

const visibleChildren = computed<PhaseNodeType[]>(() =>
  (props.node.children || []).filter(phaseHasVisibleContent),
)

// Walk the phase subtree and collect equations in definition order, skipping
// scaffolding (flow_input and control wrappers) so the subtitle reflects
// real user-visible work, not plumbing.
function collectSubtreeEquations(n: PhaseNodeType): FlowEquation[] {
  const out: FlowEquation[] = []
  for (const key of n.equation_keys || []) {
    const eq = props.equationsByKey.get(key)
    if (eq && !eq.is_scaffolding) out.push(eq)
  }
  for (const child of n.children || []) {
    out.push(...collectSubtreeEquations(child))
  }
  return out
}

function phasePathEquals(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false
  }
  return true
}

function orderedVisibleEquationsForPhase(path: string[]): FlowEquation[] {
  const allInPhase = Array.from(props.equationsByKey.values()).filter((eq) =>
    phasePathEquals(eq.phase_path || [], path),
  )
  const keys = new Set(allInPhase.map((e) => e.equation_key))
  const indexOf = new Map<string, number>()
  allInPhase.forEach((e, i) => indexOf.set(e.equation_key, i))

  const inDegree = new Map<string, number>()
  const outEdges = new Map<string, string[]>()
  for (const eq of allInPhase) {
    inDegree.set(eq.equation_key, 0)
    outEdges.set(eq.equation_key, [])
  }
  for (const eq of allInPhase) {
    for (const dep of eq.dependencies || []) {
      if (keys.has(dep)) {
        outEdges.get(dep)!.push(eq.equation_key)
        inDegree.set(eq.equation_key, (inDegree.get(eq.equation_key) || 0) + 1)
        continue
      }
      // Dep lives outside this phase (e.g. a foreach wrapper tagged with a
      // sibling phase while its iteration rows live here). Fall back to any
      // phase-local descendants of that dep — they stand in for the missing
      // node for ordering, so a HITL that consumes the wrapper still lands
      // after the iterations that produced its input.
      const prefix = dep + '/'
      for (const other of allInPhase) {
        if (!other.equation_key.startsWith(prefix)) continue
        outEdges.get(other.equation_key)!.push(eq.equation_key)
        inDegree.set(eq.equation_key, (inDegree.get(eq.equation_key) || 0) + 1)
      }
    }
  }

  const ready: string[] = []
  for (const eq of allInPhase) {
    if ((inDegree.get(eq.equation_key) || 0) === 0) ready.push(eq.equation_key)
  }
  ready.sort((a, b) => (indexOf.get(a)! - indexOf.get(b)!))

  const orderedAll: FlowEquation[] = []
  const byKey = new Map(allInPhase.map((e) => [e.equation_key, e]))
  while (ready.length) {
    const k = ready.shift()!
    orderedAll.push(byKey.get(k)!)
    for (const next of outEdges.get(k) || []) {
      const d = (inDegree.get(next) || 0) - 1
      inDegree.set(next, d)
      if (d === 0) {
        const idx = indexOf.get(next)!
        let i = 0
        while (i < ready.length && indexOf.get(ready[i])! < idx) i++
        ready.splice(i, 0, next)
      }
    }
  }
  if (orderedAll.length < allInPhase.length) {
    for (const eq of allInPhase) if (!orderedAll.includes(eq)) orderedAll.push(eq)
  }
  return orderedAll.filter((eq) => {
    if (eq.is_scaffolding && eq.status !== 'failed') return false
    if (eq.equation_type === 'code' && eq.status !== 'failed') return false
    // Info rows are narrative — render only once the body is emitted. An
    // empty info card has no value, and pending/computing placeholders
    // clutter the step list.
    if (eq.equation_type === 'info' && eq.status !== 'completed') return false
    return true
  })
}

function stepItemsForNode(node: PhaseNodeType): StepItem[] {
  return ((node.steps || []) as StepItem[])
}

function countCompletedStepItem(item: StepItem): number {
  if (item.kind === 'group') return item.aggregate.completed
  return item.eq.status === 'completed' || item.eq.status === 'skipped' ? 1 : 0
}

function countTotalStepItem(item: StepItem): number {
  if (item.kind === 'group') return item.aggregate.total
  return 1
}

function countSubtreeVisibleSteps(node: PhaseNodeType): { completed: number; total: number } {
  const stepItems = stepItemsForNode(node)
  let completed = stepItems.reduce((n, item) => n + countCompletedStepItem(item), 0)
  let total = stepItems.reduce((n, item) => n + countTotalStepItem(item), 0)
  for (const child of node.children || []) {
    const sub = countSubtreeVisibleSteps(child)
    completed += sub.completed
    total += sub.total
  }
  return { completed, total }
}
const phaseTotals = computed(() => {
  if (!isTopLevelPhase.value) return null
  return countSubtreeVisibleSteps(props.node)
})
const phaseRatioLabel = computed<string | null>(() => {
  const t = phaseTotals.value
  if (!t || t.total === 0) return null
  return `${t.completed}/${t.total}`
})
const phaseProgressFraction = computed<number | null>(() => {
  const t = phaseTotals.value
  if (!t || t.total === 0) return null
  return Math.min(1, Math.max(0, t.completed / t.total))
})

// Phase duration displayed on the right of the phase card header. Sums only
// rows whose duration is meaningful enough to show individually, matching the
// graph/detail view rules.
const phaseDurationLabel = computed<string | null>(() => {
  if (!isTopLevelPhase.value) return null
  const phasePath = props.node.path || []
  let total = 0
  let any = false
  for (const eq of props.equationsByKey.values()) {
    const ms = equationDurationMs(eq)
    if (ms == null) continue
    const p = eq.phase_path || []
    if (p.length < phasePath.length) continue
    let match = true
    for (let i = 0; i < phasePath.length; i++) {
      if (p[i] !== phasePath[i]) { match = false; break }
    }
    if (!match) continue
    total += ms
    any = true
  }
  if (!any) return null
  return formatEquationDurationMs(total)
})

// Label shown next to the phase header spinner when computing. Picks the
// first in-flight non-scaffolding equation so the user sees "Using LLM…"
// instead of an anonymous spinner — mirrors the ChatView
// "Thinking…Generating…" pattern.
const activeEquationLabel = computed<string | null>(() => {
  for (const eq of collectSubtreeEquations(props.node)) {
    if (eq.status === 'computing') return eq.display_name || 'Running'
  }
  return null
})

// Suppress direct equation rendering at root depth when named phases exist —
// orphaned equations (outside any `with phase()` block) should not pile up above phases.
const showDirectContent = computed(() =>
  props.depth > 0 || props.node.children.length === 0
)

// Direct equations of this phase node, already filtered and looked up.
// `code` (Compute) equations are graph-view plumbing — keep them out of the
// linear steps list unless they failed (so errors remain visible).
const directEquations = computed<FlowEquation[]>(() => {
  const keys = props.node.equation_keys || []
  const out: FlowEquation[] = []
  for (const key of keys) {
    const eq = props.equationsByKey.get(key)
    if (!eq) continue
    if (eq.is_scaffolding && eq.status !== 'failed') continue
    if (eq.equation_type === 'code' && eq.status !== 'failed') continue
    out.push(eq)
  }
  return out
})

function infoMarkdown(eq: FlowEquation): string {
  const r = eq.result
  if (typeof r !== 'string' || !r) return ''
  try {
    return renderSafeMarkdown(r)
  } catch {
    return r
  }
}

// Topological sort over the phase's full equation set, broken ties by the
// original definition order. Hidden scaffolding / compute nodes participate
// in ordering and are filtered only after the sort, so visible rows follow
// the actual graph rather than a reduced visible-only projection.
const directEquationsOrdered = computed<FlowEquation[]>(() =>
  orderedVisibleEquationsForPhase(props.node.path || []),
)

const orderedSteps = computed<FlowEquation[]>(() => directEquationsOrdered.value)

// Ordered StepItems: individual equations in topo order, with foreach
// iteration children collapsed into group items. The group item carries
// its own iterations list; the rest of the template renders it via
// IterationGroup.vue so this component only handles ungrouped equations.
const stepItems = computed<StepItem[]>(() =>
  stepItemsForNode(props.node)
)

function stepItemKey(item: StepItem): string {
  if (item.kind === 'group') return `group:${item.groupKey}`
  return `eq:${item.eq.equation_key}`
}

// Sticky row-expand state — survives phase-tree rebuilds from program
// edits (previously local refs got dropped on unmount, so the user's
// expanded rows silently re-collapsed when the agent touched the flow).
const expandState = useFlowExpandState(flowId)

// Info rows default to expanded in every state except `pending` (where the
// body is "Waiting for upstream…" — little value in showing that preemptively).
// Failed and computing rows stay expanded so the user sees errors / progress
// without an extra click.
function infoDefaultExpanded(eq: FlowEquation): boolean {
  return eq.status !== 'pending'
}
function isInfoExpanded(eq: FlowEquation): boolean {
  return expandState.isExpanded('info', eq.equation_key, infoDefaultExpanded(eq))
}
function toggleInfoExpanded(eq: FlowEquation) {
  expandState.toggle('info', eq.equation_key, isInfoExpanded(eq))
}
// Shared row-column helpers: uppercase status label + color, and duration.
// Info rows and HITL rows both render the same right-column set. Color comes
// from statusColors.ts (STANDARDS §1.9) via mapEquationStatus — never an
// inline status→color switch.
function equationStatusLabel(eq: FlowEquation): string | null {
  switch (eq.status) {
    case 'completed':      return null
    case 'computing':      return 'Running'
    case 'failed':         return 'Failed'
    case 'awaiting_input': return isEquationActionable(eq) && getTasksForEquation(eq.equation_key).length > 0 ? 'Your Turn' : null
    case 'waiting_for_tool': return 'Waiting for tool'
    case 'skipped':        return 'Skipped'
    case 'invalidated':    return 'Stale'
    case 'pending':        return isEquationActionable(eq) ? 'Queued' : null
    default:               return null
  }
}
function equationStatusColor(eq: FlowEquation): string {
  return textClass(mapEquationStatus(eq.status))
}
function equationDurationLabel(eq: FlowEquation): string | null {
  const ms = equationDurationMs(eq)
  return formatEquationDurationMs(ms)
}

function getTasksForEquation(key: string): FlowTask[] {
  return props.tasksByEquationKey.get(key) || []
}
function registerTaskRef(taskId: string, el: any) {
  emit('register-task-ref', taskId, el)
}

// ---------- HITL row state and chrome ----------

// Actionable HITL defaults to expanded (so the user can act without an extra
// click), completed and blocked default to collapsed. State lives in the
// sticky expand store so it survives phase-tree rebuilds.
// HITL rows auto-expand only when they're *ready* for the user — i.e.
// upstream is done and a task has spawned. Completed selections / approvals
// collapse into a summary row (the upstream iteration group's thumbnail
// strip already shows the media, so expanding would double-render). Blocked
// HITL rows stay collapsed because promising a grid the user can't act on
// is noise.
function hitlDefaultExpanded(eq: FlowEquation): boolean {
  return eq.status !== 'completed' && isEquationActionable(eq)
}
// "Your Turn" rows are locked open — the user can't collapse the only
// surface where their pending action lives, otherwise tasks silently
// disappear behind a chevron and stall the flow. Same condition that
// produces the "Your Turn" label, so lock and label move together.
function isHitlLockedOpen(eq: FlowEquation): boolean {
  return eq.status !== 'completed' && isEquationActionable(eq)
}
function isHitlExpanded(eq: FlowEquation): boolean {
  if (isHitlLockedOpen(eq)) return true
  return expandState.isExpanded('hitl', eq.equation_key, hitlDefaultExpanded(eq))
}
function toggleHitlExpanded(eq: FlowEquation) {
  if (isHitlLockedOpen(eq)) return
  expandState.toggle('hitl', eq.equation_key, isHitlExpanded(eq))
}

// Local fallbacks when the backend didn't supply a display_name. Must match
// the backend's _display_name_for_equation so the label reads the same way
// everywhere it shows up.
function hitlKindLabel(kind: string | null | undefined): string {
  switch (kind) {
    case 'select':    return 'Pick one'
    case 'approve':   return 'Approve'
    default:          return 'Human step'
  }
}

// Actionable HITL rows read as "Your Turn" with the action label as a
// subtitle; blocked rows still have pending upstream deps so promising a
// turn is misleading. Completed rows get a past-tense summary.
function hitlTitle(eq: FlowEquation): string {
  if (eq.status === 'completed') return completedHitlLabel(eq)
  if (isEquationActionable(eq)) return 'Your Turn'
  return eq.display_name || hitlKindLabel(eq.hitl_kind)
}

function hitlSubtitle(eq: FlowEquation): string | null {
  if (eq.status === 'completed') return null
  if (!isEquationActionable(eq)) return null
  return eq.display_name || hitlKindLabel(eq.hitl_kind)
}

// Past-tense summary for a completed HITL equation. Drives the row label so
// users see "You selected 2 images" instead of a generic "Human step ✓".
function completedHitlLabel(eq: FlowEquation): string {
  const kind = eq.hitl_kind
  if (kind === 'select') {
    const n = (eq.result_media_ids?.length ?? 0)
      || (Array.isArray(eq.result) ? eq.result.length : 0)
      || (eq.result != null ? 1 : 0)
    if (n <= 0) return 'You made a selection'
    if (n === 1) return 'You selected 1 image'
    return `You selected ${n} images`
  }
  if (kind === 'approve') {
    return eq.result === false ? 'You rejected the image' : 'You approved the image'
  }
  return eq.display_name || 'Human step'
}
</script>

<style scoped>
.info-prose :deep(p) { margin: 0; }
.info-prose :deep(p + p) { margin-top: 0.5em; }
.info-prose :deep(strong) { font-weight: 600; }
.info-prose :deep(em) { font-style: italic; }
.info-prose :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.9em;
  padding: 0.1em 0.3em;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.08);
}
.info-prose :deep(a) { color: rgb(96, 165, 250); text-decoration: underline; }
.info-prose :deep(ul), .info-prose :deep(ol) { margin: 0.25em 0; padding-left: 1.25em; }
.info-prose :deep(li) { margin: 0.1em 0; }
.info-prose :deep(h1), .info-prose :deep(h2), .info-prose :deep(h3) {
  font-weight: 600;
  font-size: 1.05em;
  margin: 0.25em 0;
}
</style>
