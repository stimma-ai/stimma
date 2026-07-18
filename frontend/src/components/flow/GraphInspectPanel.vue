<template>
  <!-- Footer panel — always docked at the bottom of the graph viewport.
       Single fluid content area + a thin actions sidebar on the right.
       The 3-column grid we tried before left empty columns whenever the
       selection didn't have something for every slot; this one collapses
       cleanly because the content adapts to type. -->
  <div
    class="absolute left-0 right-0 bottom-0 bg-surface border-t border-edge shadow-2xl flex flex-col z-20"
    :class="isPanelEchoed ? 'ring-1 ring-inset ring-blue-500/40' : ''"
    :style="{ height: `${height}px` }"
  >
    <div
      class="absolute -top-1 left-0 right-0 h-2 cursor-row-resize select-none hover:bg-blue-500/30 active:bg-blue-500/50 transition-colors"
      title="Resize details panel"
      @mousedown.stop.prevent="$emit('resize-start', $event)"
    />
    <!-- Header strip -->
    <div class="flex items-center gap-2.5 px-4 py-2 border-b border-edge-subtle flex-shrink-0">
      <div class="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0" :class="iconBgClass">
        <svg class="w-3.5 h-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" :d="iconPath" />
        </svg>
      </div>
      <div class="flex-1 min-w-0">
        <div class="flex items-center gap-2 min-w-0">
          <div class="truncate text-[14px] font-semibold text-content">{{ title }}</div>
          <span
            v-if="statusLabel"
            class="flex-shrink-0 text-[10.5px] font-semibold uppercase tracking-wide tabular-nums px-1.5 py-0.5 rounded"
            :class="statusBadgeClass"
          >{{ statusLabel }}</span>
          <span v-if="durationLabel" class="flex-shrink-0 text-[11px] text-content-muted tabular-nums">{{ durationLabel }}</span>
        </div>
        <div
          v-if="headerSubtitle"
          class="truncate text-[11.5px] text-content-secondary leading-tight"
          :title="headerSubtitle"
        >{{ headerSubtitle }}</div>
        <div v-if="breadcrumbParts.length" class="truncate text-[11px] text-content-muted leading-tight">
          <template v-for="(part, idx) in breadcrumbParts" :key="`${idx}:${part.text}`">
            <span v-if="idx > 0"> · </span>
            <span :class="part.stimmaCloud ? 'stimma-cloud-text font-medium' : ''">{{ part.text }}</span>
          </template>
        </div>
      </div>
      <FlowRefButton
        v-if="refTarget"
        :ref-key="refTarget.key"
        :kind="refTarget.kind"
        :label="title"
        :breadcrumb="breadcrumb"
      />
      <button
        class="w-6 h-6 flex items-center justify-center rounded text-content-muted hover:text-content hover:bg-overlay-subtle"
        title="Close (Esc)"
        @click="$emit('close')"
      >
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>

    <!-- Body: content (fluid) + actions sidebar (fixed) -->
    <div class="flex-1 min-h-0 flex">
      <!-- Content area -->
      <div
        class="flex-1 min-w-0 px-5 py-3"
        :class="fitMediaPreview ? 'overflow-hidden flex flex-col gap-3' : 'overflow-y-auto custom-scrollbar space-y-3'"
      >
        <!-- Error block (non-error-task failures) -->
        <div v-if="errorMessage && !errorTask" class="rounded border border-red-500/30 bg-red-500/5 px-3 py-2">
          <div class="text-[12.5px] font-semibold text-red-400">{{ errorMessage.title }}</div>
          <div
            v-if="errorMessage.body"
            class="mt-1 whitespace-pre-wrap break-words text-[12px] leading-relaxed text-content-secondary"
          >{{ errorMessage.body }}</div>
        </div>

        <!-- Error task: TaskCard handles retry/skip/edit-flow -->
        <TaskCard
          v-if="errorTask"
          :task="errorTask"
          :dev-mode="devMode"
          :allow-inner-scroll="false"
          @resolve="(t, r) => $emit('resolve-task', t, r)"
          @resolve-error="(t, a, v) => $emit('resolve-error-task', t, a, v)"
          @edit-flow="(t) => $emit('edit-flow', t)"
          @fix-step-with-agent="(t) => $emit('fix-step-with-agent', { equation_key: t.equation_key, display_name: title })"
        />

        <!-- HITL select / configure: TaskCard renders the form -->
        <TaskCard
          v-else-if="hitlTask && hitlTask.task_type !== 'approve'"
          :task="hitlTask"
          :dev-mode="devMode"
          :allow-inner-scroll="false"
          @resolve="(t, r) => $emit('resolve-task', t, r)"
          @resolve-error="(t, a, v) => $emit('resolve-error-task', t, a, v)"
          @edit-flow="(t) => $emit('edit-flow', t)"
          @fix-step-with-agent="(t) => $emit('fix-step-with-agent', { equation_key: t.equation_key, display_name: title })"
        />

        <!-- ============= Slot iteration: text or media candidate ============= -->
        <template v-else-if="focusedSlotIteration">
          <div v-if="slotCandidateMediaIds.length > 0" class="grid gap-2 grid-cols-1">
            <div
              v-for="mid in slotCandidateMediaIds"
              :key="mid"
              class="rounded-md border border-edge-subtle overflow-hidden bg-overlay-subtle aspect-square max-w-[260px]"
            >
              <FlowMediaTile
                :media-id="mid"
                :media-ids="slotCandidateMediaIds"
                :index="slotCandidateMediaIds.indexOf(mid)"
                :thumbnail="true"
                :thumbnail-size="384"
                :contain="true"
                container-class="w-full h-full"
              />
            </div>
          </div>
          <div v-else-if="slotCandidateValue !== undefined && slotCandidateValue !== null" class="rounded-md border border-edge-subtle bg-overlay-faint px-3 py-2">
            <FlowResultPreview :value="slotCandidateValue" :max-lines="10" overflow-mode="none" />
          </div>
          <div v-else class="text-[12px] text-content-muted italic">
            {{ slotPlaceholderText }}
          </div>
        </template>

        <!-- ============= Standalone HITL approve (text or media) ============= -->
        <template v-else-if="standaloneHitlApprove">
          <div v-if="standaloneHitlApprove.mediaId" class="rounded-md border border-edge-subtle overflow-hidden bg-overlay-subtle aspect-square max-w-[260px]">
            <FlowMediaTile
              :media-id="standaloneHitlApprove.mediaId"
              :media-ids="[standaloneHitlApprove.mediaId]"
              :thumbnail="true"
              :thumbnail-size="384"
              :contain="true"
              container-class="w-full h-full"
            />
          </div>
          <div v-else-if="standaloneHitlApprove.value !== undefined" class="rounded-md border border-edge-subtle bg-overlay-faint px-3 py-2">
            <FlowResultPreview :value="standaloneHitlApprove.value" :max-lines="10" overflow-mode="none" />
          </div>
        </template>

        <!-- ============= Flow input: editable single-field form ============= -->
        <!-- Mirrors the steps-view input card's edit affordance so selecting
             an input node in the graph offers parity with the input card.
             Revert/Apply ride at the top of the form (same shoulder bar
             treatment the steps-view input card uses), so the controls don't
             jump around as the field grows. -->
        <template v-else-if="focusEquation?.equation_type === 'flow_input' && singleFieldSchema">
          <div v-if="panelInputDirty" class="flex items-center justify-end gap-1.5">
            <button
              type="button"
              class="text-[11px] px-2 py-1 rounded border border-edge-subtle text-content-secondary hover:bg-overlay-subtle disabled:opacity-40"
              :disabled="submittingInputs"
              title="Discard unsaved input changes"
              @click="panelInputFormRef?.discardChanges()"
            >Revert</button>
            <button
              type="button"
              class="text-[11px] px-2 py-1 rounded-md bg-accent text-white hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed"
              :disabled="!panelInputValid || submittingInputs"
              title="Apply this input value to the flow"
              @click="panelInputFormRef?.applyChanges()"
            >{{ submittingInputs ? 'Applying…' : 'Apply' }}</button>
          </div>
          <FlowInputForm
            ref="panelInputFormRef"
            :schema="singleFieldSchema"
            :initial-values="inputValues"
            :applying="submittingInputs"
            :default-prompt-lines="5"
            @submit="onPanelInputSubmit"
            @update:dirty="panelInputDirty = $event"
            @update:valid="panelInputValid = $event"
          />
        </template>

        <!-- ============= Flow input (fallback) / output: render value ============= -->
        <!-- Used when the schema isn't editable here (literal_list, schema
             not yet loaded) and for output nodes (always read-only). -->
        <template v-else-if="focusEquation && (focusEquation.equation_type === 'flow_input' || focusEquation.equation_type === 'flow_output')">
          <div v-if="previewMediaIds.length > 0" class="grid gap-2" :class="previewGridClass">
            <div
              v-for="mid in previewMediaIds"
              :key="mid"
              class="rounded-md border border-edge-subtle overflow-hidden bg-overlay-subtle aspect-square"
            >
              <FlowMediaTile
                :media-id="mid"
                :media-ids="previewMediaIds"
                :index="previewMediaIds.indexOf(mid)"
                :thumbnail="true"
                :thumbnail-size="384"
                :contain="true"
                container-class="w-full h-full"
              />
            </div>
          </div>
          <div v-else-if="inputValue !== undefined && inputValue !== null" class="rounded-md border border-edge-subtle bg-overlay-faint px-3 py-2">
            <FlowResultPreview :value="inputValue" :max-lines="14" overflow-mode="none" />
          </div>
          <div v-else class="text-[12px] text-content-muted italic">
            No value yet.
          </div>
        </template>

        <!-- ============= Info: rendered markdown + upstream media ============= -->
        <template v-else-if="focusEquation?.equation_type === 'info'">
          <div v-if="infoMarkdown" class="rounded-md border border-edge-subtle bg-overlay-faint px-3 py-2">
            <div
              class="info-prose text-[12.5px] leading-relaxed text-content break-words select-text"
              v-html="infoMarkdown"
            />
          </div>
          <div v-else-if="focusEquation.status === 'computing'" class="text-[12px] text-content-muted italic">
            Preparing…
          </div>
          <div v-else-if="focusEquation.status === 'pending'" class="text-[12px] text-content-muted italic">
            Waiting for upstream steps to finish.
          </div>
          <div v-if="previewMediaIds.length > 0" class="grid gap-2 grid-cols-3">
            <div
              v-for="mid in previewMediaIds"
              :key="mid"
              class="rounded-md border border-edge-subtle overflow-hidden bg-overlay-subtle aspect-square"
            >
              <FlowMediaTile
                :media-id="mid"
                :media-ids="previewMediaIds"
                :index="previewMediaIds.indexOf(mid)"
                :thumbnail="true"
                :thumbnail-size="256"
                container-class="w-full h-full"
              />
            </div>
          </div>
        </template>

        <!-- ============= Tool call with media: panel's rich fit-grid ============= -->
        <!-- When a tool_call has produced media we keep the panel's larger,
             height-filling grid because the panel has the vertical real
             estate to inspect outputs that the steps row doesn't. For
             tool_calls without media (web_search, in-flight, etc.) we fall
             through to EquationTraceBody so the panel shows the same
             search results / output placeholders the steps view does. -->
        <template v-else-if="focusEquation?.equation_type === 'tool_call' && previewMediaIds.length > 0">
          <div
            class="grid gap-2 flex-1 min-h-0 w-full"
            :class="fitMediaPreview ? '' : previewGridClass"
            :style="fitMediaPreview ? mediaFitGridStyle : undefined"
          >
            <div
              v-for="mid in previewMediaIds"
              :key="mid"
              class="rounded-md border border-edge-subtle overflow-hidden bg-transparent min-h-0"
              :class="fitMediaPreview ? 'w-full h-full' : 'aspect-square'"
            >
              <FlowMediaTile
                :media-id="mid"
                :media-ids="previewMediaIds"
                :index="previewMediaIds.indexOf(mid)"
                :thumbnail="true"
                :thumbnail-size="384"
                :contain="true"
                container-class="w-full h-full bg-transparent"
              />
            </div>
          </div>
        </template>

        <!-- ============= Set / grid with media: panel's larger grid ============= -->
        <template v-else-if="(focusEquation?.equation_type === 'create_set' || focusEquation?.equation_type === 'create_grid') && previewMediaIds.length > 0">
          <div class="grid gap-2 grid-cols-3">
            <div
              v-for="mid in previewMediaIds"
              :key="mid"
              class="rounded-md border border-edge-subtle overflow-hidden bg-overlay-subtle aspect-square"
            >
              <FlowMediaTile
                :media-id="mid"
                :media-ids="previewMediaIds"
                :index="previewMediaIds.indexOf(mid)"
                :thumbnail="true"
                :thumbnail-size="256"
                container-class="w-full h-full"
              />
            </div>
          </div>
        </template>

        <!-- ============= Body-rendered step types ============= -->
        <!-- Shared trace body covers tool_call (incl. web_search / create_*
             trace subtypes), llm_call, and code so the panel and the steps
             view show the same content for the same step. The panel's
             sidebar already provides retry / fix-with-agent actions, so the
             body's inline failed-state buttons are suppressed; the panel
             renders its own errorMessage block above when needed. -->
        <EquationTraceBody
          v-else-if="bodyRenderableType"
          :equation="focusEquation!"
          :flow-id="flowId"
          :dev-mode="devMode"
          :show-failed-block="false"
          :allow-inner-scroll="false"
          @invalidate-equation="(k) => $emit('invalidate-equation', k)"
          @fix-step-with-agent="(eq) => $emit('fix-step-with-agent', { equation_key: eq.equation_key, display_name: title })"
        />

        <!-- ============= Super-node summary ============= -->
        <template v-else-if="superNode && focusedIterIdx == null">
          <div class="flex flex-wrap gap-1.5">
            <span
              v-for="b in statusBuckets"
              :key="b.label"
              class="inline-flex items-center gap-1 text-[11.5px] px-2 py-0.5 rounded-full border"
              :class="b.chipClass"
            >
              <span class="w-1.5 h-1.5 rounded-full" :class="b.dotClass" />
              <span class="tabular-nums">{{ b.count }}</span>
              <span>{{ b.label }}</span>
            </span>
          </div>
          <div v-if="totalDurationLabel" class="text-[11.5px] text-content-muted">
            Total compute time: <span class="text-content tabular-nums">{{ totalDurationLabel }}</span>
          </div>
          <div v-if="failedIterIdxs.length > 0">
            <div class="text-xs font-semibold text-content-secondary mb-1">Failed iterations</div>
            <div class="flex flex-wrap gap-1">
              <button
                v-for="idx in failedIterIdxs"
                :key="idx"
                class="text-[11px] px-2 py-0.5 rounded bg-red-500/10 border border-red-500/40 text-red-400 hover:bg-red-500/20"
                @click="$emit('focus-iteration', superNode!.foreachKey, idx)"
              >#{{ idx + 1 }}</button>
            </div>
          </div>
          <div v-if="actionableIterIdxs.length > 0">
            <div class="text-xs font-semibold text-content-secondary mb-1">Awaiting your input</div>
            <div class="flex flex-wrap gap-1">
              <button
                v-for="idx in actionableIterIdxs"
                :key="idx"
                class="text-[11px] px-2 py-0.5 rounded bg-purple-500/10 border border-purple-500/40 text-purple-400 hover:bg-purple-500/20"
                @click="$emit('focus-iteration', superNode!.foreachKey, idx)"
              >#{{ idx + 1 }}</button>
            </div>
          </div>
        </template>

        <!-- ============= Pending / computing placeholder ============= -->
        <div
          v-else-if="focusEquation && (focusEquation.status === 'pending' || focusEquation.status === 'computing')"
          class="text-[12px] text-content-muted italic"
        >
          {{ focusEquation.status === 'pending' ? 'Waiting for upstream steps to finish.' : 'Running… details will appear here when this step finishes.' }}
        </div>

        <div v-else class="text-[12px] text-content-muted italic">
          {{ hasSelection ? `Nothing to show for this ${selectionKind}.` : 'Select a step in the workflow to see details here.' }}
        </div>

        <!-- devMode raw error -->
        <div
          v-if="devMode && rawErrorText"
          class="rounded border border-amber-500/40 bg-overlay-light text-[11px] font-mono text-content-secondary"
        >
          <div class="flex items-center gap-2 px-2.5 py-1.5 border-b border-amber-500/30">
            <span class="text-[9px] font-bold uppercase tracking-wider text-amber-600 dark:text-amber-400 bg-amber-500/15 px-1.5 py-0.5 rounded-sm">Dev</span>
            <span class="text-content-muted">raw step error</span>
            <span class="flex-1" />
            <span class="text-content-muted truncate">{{ focusEquation?.equation_key || '' }}</span>
          </div>
          <pre class="px-2.5 py-2 whitespace-pre-wrap break-words select-text">{{ rawErrorText }}</pre>
        </div>
      </div>

      <!-- Actions sidebar -->
      <div class="w-[240px] flex-shrink-0 border-l border-edge-subtle px-4 py-3 overflow-y-auto custom-scrollbar space-y-2">
        <div v-if="actionButtons.length === 0" class="text-[11.5px] text-content-muted italic">
          No actions for this {{ selectionKind }}.
        </div>
        <button
          v-for="b in actionButtons"
          :key="b.key"
          type="button"
          :class="b.class"
          @click="b.onClick"
        >
          <span class="flex items-center justify-center gap-1.5">
            <svg v-if="b.iconPath" class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" :d="b.iconPath" />
            </svg>
            <span>{{ b.label }}</span>
          </span>
        </button>
      </div>
    </div>
  </div>

  <GenerationDetailsModal
    :show="showGenerationDetailsModal"
    title="Generation details"
    :header-icon-path="iconPath"
    :header-icon-bg-class="iconBgClass"
    :tool-title="detailsToolTitle"
    :provider-label="detailsProviderLabel"
    :provider-is-stimma-cloud="detailsProviderIsStimmaCloud"
    :duration-label="durationLabel"
    :status-text="detailsStatusText"
    :status-dot-class="detailsStatusDotClass"
    :status-text-class="detailsStatusTextClass"
    :preview-media-ids="previewMediaIds"
    :preview-placeholder="detailsPreviewPlaceholder"
    :loading-inputs="detailsLoading"
    :prominent-inputs="detailsProminentInputs"
    :compact-inputs="detailsCompactInputs"
    :error-details="focusEquation?.error || ''"
    :raw-json="detailsRawJson"
    :can-rerun="!!focusEquation"
    @close="showGenerationDetailsModal = false"
    @rerun="focusEquation && $emit('invalidate-equation', focusEquation.equation_key)"
  />
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import axios from 'axios'
import { getApiBase } from '../../apiConfig'
import type { FlowEquation, FlowTask } from '../../composables/useFlowsApi'
import { useProvidersApi } from '../../composables/useProvidersApi'
import { renderSafeMarkdown } from '../../utils/sanitizeHtml'
import {
  getTaskTypeGradientClass,
  getTaskTypeIconPath,
  DEFAULT_TASK_TYPE_GRADIENT_CLASS,
  DEFAULT_TASK_TYPE_ICON_PATH,
} from '../../utils/taskTypeIcons'
import { parseFlowError } from '../../utils/flowErrors'
import type { ForeachSuperNodeData } from '../../composables/useForeachSuperNodes'
import {
  buildIterationsForForeach,
  candidateProducerForSlot,
  type GroupedIteration,
} from '../../composables/useFlowGrouping'
import EquationTraceBody from './EquationTraceBody.vue'
import FlowMediaTile from './FlowMediaTile.vue'
import FlowRefButton from './FlowRefButton.vue'
import FlowResultPreview from './FlowResultPreview.vue'
import TaskCard from './TaskCard.vue'
import GenerationDetailsModal, { type InputEntry } from '../generation/GenerationDetailsModal.vue'
import FlowInputForm from './FlowInputForm.vue'
import { useFlowReferences, injectFlowChatIdRef } from '../../composables/useFlowReferences'
import { shouldShowEquationDuration } from '../../utils/equationDuration'
import { STIMMA_CLOUD_PROVIDER_ID } from '../../utils/stimmaCloud'

interface Props {
  equation: FlowEquation | null
  superNode: ForeachSuperNodeData | null
  focusedIterIdx: number | null
  tasks: FlowTask[]
  equationsByKey: Map<string, FlowEquation>
  flowId: number | string | null
  // Flow-level input schema + current values, forwarded so the panel can
  // offer a one-field editable form when a flow_input node is selected —
  // matching the steps-view input card's edit affordance.
  inputSchema?: Record<string, any> | null
  inputValues?: Record<string, any> | null
  submittingInputs?: boolean
  height?: number
  devMode?: boolean
}
const props = withDefaults(defineProps<Props>(), {
  height: 360,
  devMode: false,
  inputSchema: null,
  inputValues: null,
  submittingInputs: false,
})

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'invalidate-equation', key: string): void
  (e: 'fix-step-with-agent', equation: { equation_key: string; display_name?: string | null }): void
  (e: 'resolve-task', task: FlowTask, resolution: any): void
  (e: 'resolve-error-task', task: FlowTask, action: string, value?: any): void
  (e: 'edit-flow', task: FlowTask): void
  (e: 'focus-iteration', superKey: string, iterIdx: number): void
  (e: 'resize-start', event: MouseEvent): void
  // Partial values map (one key, the selected input field). FlowView
  // merges it onto the existing flow.inputs blob — the form here only
  // sees one field, so emitting a full blob would clobber the others.
  (e: 'update-inputs', partial: Record<string, any>): void
}>()

const { cachedTools, cachedProviders, fetchProvidersAndTools } = useProvidersApi()
onMounted(() => { fetchProvidersAndTools().catch(() => {}) })

// Hover-echo: when the user hovers a flow-ref chip in the chat context
// tray, light up the panel so they can confirm what the chip points at —
// same affordance the steps-view rows give. Match against refTarget so the
// key resolution stays in lockstep with the panel's own FlowRefButton.
const flowRefs = useFlowReferences(injectFlowChatIdRef())
const isPanelEchoed = computed<boolean>(() => {
  const target = refTarget.value
  if (!target) return false
  return flowRefs.hoveredRefKey.value === target.key
})

// ---- Selection resolution ----
const focusEquation = computed<FlowEquation | null>(() => {
  if (props.superNode && props.focusedIterIdx != null) {
    return props.superNode.flatIterations[props.focusedIterIdx]?.primary
      ?? props.equation
  }
  return props.equation
})
const hasSelection = computed<boolean>(() => !!focusEquation.value || !!props.superNode)

const isApproveSuper = computed<boolean>(() => {
  const sn = props.superNode
  if (!sn) return false
  return sn.foreach.equation_type === 'control' && sn.foreach.control_kind === 'approve'
})

const focusedSlotIteration = computed<GroupedIteration | null>(() => {
  if (!isApproveSuper.value || !props.superNode || props.focusedIterIdx == null) return null
  const iters = buildIterationsForForeach(props.superNode.foreach, props.equationsByKey)
  return iters[props.focusedIterIdx] ?? null
})

const slotCandidate = computed<FlowEquation | null>(() => {
  if (!focusedSlotIteration.value) return null
  return candidateProducerForSlot(focusedSlotIteration.value)
})
const slotCandidateMediaIds = computed<number[]>(() => {
  const c = slotCandidate.value
  return c?.result_media_ids && c.result_media_ids.length > 0 ? c.result_media_ids : []
})
const slotCandidateValue = computed<unknown>(() => {
  const c = slotCandidate.value
  return c?.result
})
const slotApproveEquation = computed<FlowEquation | null>(() => {
  const it = focusedSlotIteration.value
  if (!it) return null
  return it.equations.find((e) => e.equation_type === 'hitl' && e.hitl_kind === 'approve') ?? null
})
const slotPendingApproveTask = computed<FlowTask | null>(() => {
  const eq = slotApproveEquation.value
  if (!eq) return null
  return props.tasks.find(
    (t) => t.equation_key === eq.equation_key && t.status === 'pending' && t.task_type === 'approve',
  ) ?? null
})
type SlotState = 'awaiting' | 'approved' | 'pending' | 'failed' | 'computing'
const slotState = computed<SlotState>(() => {
  const it = focusedSlotIteration.value
  if (!it) return 'pending'
  if (it.hasError) return 'failed'
  if (slotPendingApproveTask.value) return 'awaiting'
  const ae = slotApproveEquation.value
  if (ae?.status === 'completed' && ae.result !== false) return 'approved'
  if (it.status === 'computing') return 'computing'
  return 'pending'
})
const slotPlaceholderText = computed<string>(() => {
  switch (slotState.value) {
    case 'computing': return 'Generating candidate…'
    case 'failed':    return 'Generation failed.'
    case 'pending':   return 'Waiting for upstream.'
    default:          return 'No candidate yet.'
  }
})

const selectionKind = computed<string>(() => {
  if (!hasSelection.value) return 'selection'
  if (props.superNode && props.focusedIterIdx == null) return 'loop'
  if (focusedSlotIteration.value) return 'slot'
  if (props.superNode && props.focusedIterIdx != null) return 'iteration'
  return 'step'
})

// ---- Tasks scoped to the focused equation ----
const hitlTask = computed<FlowTask | null>(() => {
  const eq = focusEquation.value
  if (!eq || eq.equation_type !== 'hitl' || eq.status !== 'awaiting_input') return null
  return props.tasks.find((t) => t.equation_key === eq.equation_key && t.status === 'pending') || null
})
const errorTask = computed<FlowTask | null>(() => {
  const eq = focusEquation.value
  if (!eq || eq.status !== 'failed') return null
  return props.tasks.find(
    (t) => t.equation_key === eq.equation_key
      && t.status === 'pending'
      && (t.task_type === 'error' || t.task_type === 'waiting_for_tool'),
  ) || null
})

// Standalone HITL approve content (not in a hitl.approve). For the candidate
// upstream, we look at the approve equation's bound payload (media id) or
// fall back to the result of any sibling producer in the same parent scope.
interface StandaloneHitlApprove {
  state: 'awaiting' | 'approved'
  mediaId: number | null
  value: unknown
}
const standaloneHitlApprove = computed<StandaloneHitlApprove | null>(() => {
  const eq = focusEquation.value
  if (!eq || eq.equation_type !== 'hitl' || eq.hitl_kind !== 'approve') return null
  if (focusedSlotIteration.value) return null  // hitl.approve has its own treatment
  if (eq.status === 'awaiting_input' && hitlTask.value) {
    const payload: any = hitlTask.value.payload || {}
    const mid = payload.media_id ?? payload.mediaId ?? payload.asset?.media_id ?? payload.asset
    return {
      state: 'awaiting',
      mediaId: typeof mid === 'number' ? mid : null,
      value: payload.value ?? payload.text ?? payload.preview ?? null,
    }
  }
  if (eq.status === 'completed' && eq.result === true) {
    return { state: 'approved', mediaId: null, value: null }
  }
  return null
})

// ---- Header chrome ----
function resolveTool(toolId: string | null | undefined) {
  if (!toolId) return null
  return cachedTools.value.find((t) => t.full_tool_id === toolId) || null
}
function resolveProviderName(toolId: string | null | undefined): string | null {
  const tool = resolveTool(toolId)
  if (tool) return tool.provider_name
  if (!toolId) return null
  const pid = toolId.split(':')[0] || null
  if (!pid) return null
  return cachedProviders.value.find((pr) => pr.provider_id === pid)?.provider_name || pid
}
function providerIdFromToolId(toolId: string | null | undefined): string | null {
  if (!toolId) return null
  return toolId.split(':')[0] || null
}
function isStimmaCloudToolId(toolId: string | null | undefined): boolean {
  return providerIdFromToolId(toolId) === STIMMA_CLOUD_PROVIDER_ID
}
function toolTitle(eq: FlowEquation): string {
  const tool = resolveTool(eq.tool_id)
  if (tool) return tool.name
  if (eq.tool_id) {
    const parts = eq.tool_id.split(':').filter(Boolean)
    if (parts.length >= 2) {
      return parts[1].split('-').map((w) => w ? w[0].toUpperCase() + w.slice(1) : w).join(' ')
    }
  }
  return eq.display_name || 'Tool'
}
function hitlKindLabel(kind: string | null | undefined): string {
  switch (kind) {
    case 'select':    return 'Pick one'
    case 'approve':   return 'Approve'
    default:          return 'Human step'
  }
}

const title = computed<string>(() => {
  if (props.superNode && props.focusedIterIdx == null) {
    const dn = props.superNode.foreach.display_name
    const generic = new Set(['Loop', 'Pick', 'LLM', 'Gather Results'])
    if (dn && !generic.has(dn)) return dn
    const n = props.superNode.iterCount
    const eq = props.superNode.foreach
    if (eq.equation_type === 'llm_batch') return `LLM · ${n} variants`
    if (eq.equation_type === 'control' && eq.control_kind === 'approve') return `Pick · ${n} slots`
    return `Loop · ${n} items`
  }
  if (focusedSlotIteration.value) {
    return `Slot ${(props.focusedIterIdx ?? 0) + 1} of ${props.superNode?.iterCount ?? '?'}`
  }
  const eq = focusEquation.value
  if (!eq) return 'Select a step'
  if (props.superNode && props.focusedIterIdx != null) {
    return `${equationTitle(eq)} · iter ${props.focusedIterIdx + 1}`
  }
  return equationTitle(eq)
})

function equationTitle(eq: FlowEquation): string {
  switch (eq.equation_type) {
    case 'tool_call': return toolTitle(eq)
    case 'llm_call':
    case 'llm_batch':
    case 'llm_slot':  return eq.display_name || 'LLM'
    case 'code':
      if (eq.routing_kind) return eq.display_name || 'Code'
      return (eq.description && eq.description.trim()) || eq.display_name || 'Code'
    case 'hitl':
      if (eq.status === 'awaiting_input') return 'Your turn'
      return eq.display_name || hitlKindLabel(eq.hitl_kind)
    case 'info':         return eq.display_name || 'Note'
    case 'flow_input': return eq.display_name || 'Input'
    case 'flow_output': return eq.display_name || 'Output'
    default: return eq.display_name || 'Step'
  }
}

const breadcrumb = computed<string>(() =>
  breadcrumbParts.value.map((part) => part.text).join(' · '),
)

const breadcrumbParts = computed<Array<{ text: string; stimmaCloud?: boolean }>>(() => {
  const eq = focusEquation.value || props.superNode?.foreach
  const phasePath = eq?.phase_path || []
  const parts: Array<{ text: string; stimmaCloud?: boolean }> = []
  if (phasePath.length) parts.push({ text: phasePath.join(' / ') })
  if (props.superNode && props.focusedIterIdx == null) {
    parts.push({ text: `${props.superNode.iterCount} iterations` })
  } else if (focusedSlotIteration.value) {
    parts.push({ text: 'Approve gate' })
  } else if (props.superNode && props.focusedIterIdx != null) {
    parts.push({ text: `iteration ${props.focusedIterIdx + 1} of ${props.superNode.iterCount}` })
  } else if (focusEquation.value?.equation_type === 'tool_call' && focusEquation.value.tool_id) {
    const provider = resolveProviderName(focusEquation.value.tool_id)
    if (provider) parts.push({ text: provider, stimmaCloud: isStimmaCloudToolId(focusEquation.value.tool_id) })
  }
  return parts
})

// Header subtitle: mirrors EquationTraceRow's secondLineSubtitle so the
// inspect panel shows the same agent-authored description that code rows
// surface in the steps view. Tool rows already encode model/provider in the
// breadcrumb, so we leave them alone here.
const headerSubtitle = computed<string | null>(() => {
  const eq = focusEquation.value
  if (!eq || eq.equation_type !== 'code') return null
  if (eq.routing_kind) {
    // Routing-kind code titles from display_name ("Filter Items"); description
    // is the second line.
    const d = eq.description
    return d && d.trim() ? d.trim() : null
  }
  // Plain code titles already use description; subtitle is the second line.
  const s = eq.subtitle
  return s && s.trim() ? s.trim() : null
})

const refTarget = computed<{ kind: 'equation' | 'iteration'; key: string } | null>(() => {
  if (focusedSlotIteration.value?.wrapperKey) {
    return { kind: 'iteration', key: focusedSlotIteration.value.wrapperKey }
  }
  if (props.superNode && props.focusedIterIdx == null) {
    return { kind: 'equation', key: props.superNode.foreachKey }
  }
  if (focusEquation.value) {
    return { kind: 'equation', key: focusEquation.value.equation_key }
  }
  return null
})

// ---- Status badge ----
const statusLabel = computed<string | null>(() => {
  if (props.superNode && props.focusedIterIdx == null) {
    const stats = statusBuckets.value
    if (stats.length === 0) return 'EMPTY'
    if (stats.find((s) => s.label === 'Failed')) return 'HAS FAILURES'
    if (stats.find((s) => s.label === 'Your turn')) return 'YOUR TURN'
    if (stats.find((s) => s.label === 'Running')) return 'RUNNING'
    if (stats.find((s) => s.label === 'Done')?.count === props.superNode!.iterCount) return 'DONE'
    return 'PENDING'
  }
  if (focusedSlotIteration.value) {
    switch (slotState.value) {
      case 'awaiting':   return 'YOUR TURN'
      case 'approved':   return 'APPROVED'
      case 'computing':  return 'RUNNING'
      case 'failed':     return 'FAILED'
      default:           return 'PENDING'
    }
  }
  switch (focusEquation.value?.status) {
    case 'completed':      return 'DONE'
    case 'computing':      return 'RUNNING'
    case 'failed':         return 'FAILED'
    case 'awaiting_input': return 'YOUR TURN'
    case 'skipped':        return 'SKIPPED'
    case 'invalidated':    return 'STALE'
    case 'pending':        return 'QUEUED'
    default:               return null
  }
})

const statusBadgeClass = computed<string>(() => {
  const l = statusLabel.value
  switch (l) {
    case 'DONE':
    case 'APPROVED':     return 'bg-green-500/15 text-green-400'
    case 'RUNNING':      return 'bg-blue-500/15 text-blue-400'
    case 'FAILED':
    case 'HAS FAILURES': return 'bg-red-500/15 text-red-400'
    case 'YOUR TURN':    return 'bg-purple-500/15 text-purple-400'
    case 'STALE':        return 'bg-yellow-500/15 text-yellow-400'
    default:             return 'bg-overlay-subtle text-content-muted'
  }
})

const iconBgClass = computed<string>(() => {
  if (props.superNode && props.focusedIterIdx == null) {
    return 'bg-gradient-to-br from-amber-500/80 to-amber-700/80'
  }
  const eq = focusEquation.value
  switch (eq?.equation_type) {
    case 'tool_call': return getTaskTypeGradientClass(eq.task_type || '')
    case 'llm_call':
    case 'llm_batch':
    case 'llm_slot':  return 'bg-gradient-to-br from-blue-500/80 to-blue-700/80'
    case 'code':      return 'bg-gradient-to-br from-emerald-500/80 to-emerald-700/80'
    case 'hitl':      return 'bg-gradient-to-br from-purple-500/80 to-purple-700/80'
    case 'info':      return 'bg-gradient-to-br from-teal-500/80 to-teal-700/80'
    case 'flow_input': return 'bg-gradient-to-br from-zinc-500/80 to-zinc-700/80'
    case 'flow_output': return 'bg-gradient-to-br from-pink-500/80 to-pink-700/80'
    case 'control':   return 'bg-gradient-to-br from-amber-500/80 to-amber-700/80'
    default:          return DEFAULT_TASK_TYPE_GRADIENT_CLASS
  }
})

const LLM_ICON = 'M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456z'
const CODE_ICON = 'M17.25 6.75L22.5 12l-5.25 5.25M6.75 17.25L1.5 12l5.25-5.25M14.25 3.75L9.75 20.25'
const HITL_ICON = 'M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z'
const INFO_ICON = 'M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z'
const INPUT_ICON = 'M9 8.25H7.5a2.25 2.25 0 00-2.25 2.25v9a2.25 2.25 0 002.25 2.25h9a2.25 2.25 0 002.25-2.25v-9a2.25 2.25 0 00-2.25-2.25H15M9 12l3 3m0 0l3-3m-3 3V2.25'
const OUTPUT_ICON = 'M9 8.25H7.5a2.25 2.25 0 00-2.25 2.25v9a2.25 2.25 0 002.25 2.25h9a2.25 2.25 0 002.25-2.25v-9a2.25 2.25 0 00-2.25-2.25H15M12 2.25l3 3m0 0l-3 3m3-3h-9'
const LOOP_ICON = 'M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99'
const REPLACE_ICON = 'M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99'
const CHECK_ICON = 'M4.5 12.75l6 6 9-13.5'
const SPARK_ICON = 'M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z'
const INFO_ICON_BUTTON = 'M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z'

const iconPath = computed<string>(() => {
  if (props.superNode && props.focusedIterIdx == null) return LOOP_ICON
  const eq = focusEquation.value
  switch (eq?.equation_type) {
    case 'tool_call': return getTaskTypeIconPath(eq.task_type || '')
    case 'llm_call':
    case 'llm_batch':
    case 'llm_slot':  return LLM_ICON
    case 'code':      return CODE_ICON
    case 'hitl':      return HITL_ICON
    case 'info':      return INFO_ICON
    case 'flow_input': return INPUT_ICON
    case 'flow_output': return OUTPUT_ICON
    case 'control':   return LOOP_ICON
    default:          return DEFAULT_TASK_TYPE_ICON_PATH
  }
})

function formatDurationMs(ms: number | null | undefined): string | null {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return null
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`
  const mins = Math.floor(ms / 60_000)
  const secs = Math.round((ms % 60_000) / 1000)
  return secs ? `${mins}m ${secs}s` : `${mins}m`
}

const durationLabel = computed<string | null>(() => {
  const eq = focusEquation.value
  if (!eq || eq.status !== 'completed') return null
  if (!shouldShowEquationDuration(eq.equation_type)) return null
  const compute = eq.compute_duration_ms
  if (eq.equation_type === 'tool_call' && typeof compute === 'number' && Number.isFinite(compute) && compute >= 0) {
    return formatDurationMs(compute)
  }
  if (typeof eq.execution_duration_ms === 'number') return formatDurationMs(eq.execution_duration_ms)
  if (eq.created_at && eq.completed_at) {
    const t0 = Date.parse(eq.created_at)
    const t1 = Date.parse(eq.completed_at)
    if (Number.isFinite(t0) && Number.isFinite(t1) && t1 >= t0) return formatDurationMs(t1 - t0)
  }
  return null
})

// ---- Action buttons (right sidebar) ----
//
// Buttons are ordered from most-likely-to-act-now down. Slot approvals
// headline the column when an approve is awaiting; failures bring up the
// agent-fix CTA before the retry; completed steps surface re-run alone.
interface ActionButton {
  key: string
  label: string
  iconPath?: string
  class: string
  onClick: () => void
}

const PRIMARY_BTN  = 'w-full text-[12px] font-medium px-3 py-1.5 rounded-md bg-accent text-white hover:bg-accent/90 transition-colors'
const SECONDARY_BTN = 'w-full text-[12px] font-medium px-3 py-1.5 rounded-md bg-overlay-subtle text-content hover:bg-overlay-hover transition-colors'
const APPROVED_BTN = 'w-full text-[12px] font-medium px-3 py-1.5 rounded bg-blue-500/15 border border-blue-500/50 text-blue-400 hover:bg-blue-500/25 transition-colors'

const showGenerationDetailsModal = ref(false)
const detailsTrace = ref<any | null>(null)
const detailsLoading = ref(false)

async function showGenerationDetails() {
  showGenerationDetailsModal.value = true
  const eq = focusEquation.value
  if (!eq || props.flowId == null) return
  detailsTrace.value = null
  detailsLoading.value = true
  try {
    const url = `${getApiBase()}/flows/${props.flowId}/equations/${encodeURIComponent(eq.equation_key)}/trace`
    const res = await axios.get(url)
    detailsTrace.value = res.data
  } catch {
    detailsTrace.value = null
  } finally {
    detailsLoading.value = false
  }
}

const actionButtons = computed<ActionButton[]>(() => {
  const out: ActionButton[] = []

  // ----- Slot iteration: approve / replace / approved / failed -----
  if (focusedSlotIteration.value) {
    if (slotState.value === 'awaiting' && slotPendingApproveTask.value) {
      out.push({
        key: 'approve',
        label: 'Approve',
        iconPath: CHECK_ICON,
        class: PRIMARY_BTN,
        onClick: () => emit('resolve-task', slotPendingApproveTask.value!, true),
      })
      out.push({
        key: 'replace',
        label: 'Replace',
        iconPath: REPLACE_ICON,
        class: SECONDARY_BTN,
        onClick: () => emit('resolve-task', slotPendingApproveTask.value!, false),
      })
    } else if (slotState.value === 'approved') {
      out.push({
        key: 'unapprove',
        label: 'Approved (click to undo)',
        class: APPROVED_BTN,
        onClick: () => slotApproveEquation.value && emit('invalidate-equation', slotApproveEquation.value.equation_key),
      })
      const cand = slotCandidate.value
      if (cand) {
        out.push({
          key: 'regen',
          label: 'Regenerate candidate',
          iconPath: SPARK_ICON,
          class: SECONDARY_BTN,
          onClick: () => emit('invalidate-equation', focusedSlotIteration.value?.wrapperKey ?? cand.equation_key),
        })
      }
    } else if (slotState.value === 'failed') {
      out.push({
        key: 'fix-with-agent',
        label: 'Ask the agent for help',
        class: PRIMARY_BTN,
        onClick: () => {
          const failed = focusedSlotIteration.value!.equations.find((e) => e.status === 'failed')
          if (failed) emit('fix-step-with-agent', { equation_key: failed.equation_key, display_name: title.value })
        },
      })
      out.push({
        key: 'retry',
        label: 'Retry',
        iconPath: REPLACE_ICON,
        class: SECONDARY_BTN,
        onClick: () => {
          const failed = focusedSlotIteration.value!.equations.find((e) => e.status === 'failed')
          if (failed) emit('invalidate-equation', failed.equation_key)
        },
      })
    } else if (slotState.value === 'computing' || slotState.value === 'pending') {
      const cand = slotCandidate.value
      if (cand) {
        out.push({
          key: 'regen',
          label: 'Regenerate',
          iconPath: SPARK_ICON,
          class: SECONDARY_BTN,
          onClick: () => emit('invalidate-equation', focusedSlotIteration.value?.wrapperKey ?? cand.equation_key),
        })
      }
    }
    return out
  }

  // ----- Standalone HITL approve -----
  if (standaloneHitlApprove.value && hitlTask.value) {
    if (standaloneHitlApprove.value.state === 'awaiting') {
      out.push({
        key: 'approve',
        label: 'Approve',
        iconPath: CHECK_ICON,
        class: PRIMARY_BTN,
        onClick: () => emit('resolve-task', hitlTask.value!, true),
      })
      out.push({
        key: 'replace',
        label: 'Replace',
        iconPath: REPLACE_ICON,
        class: SECONDARY_BTN,
        onClick: () => emit('resolve-task', hitlTask.value!, false),
      })
    }
    return out
  }

  // ----- Failed step (non-slot) -----
  if (focusEquation.value?.status === 'failed') {
    out.push({
      key: 'fix-with-agent',
      label: 'Ask the agent for help',
      class: PRIMARY_BTN,
      onClick: () => emit('fix-step-with-agent', { equation_key: focusEquation.value!.equation_key, display_name: title.value }),
    })
    out.push({
      key: 'retry',
      label: 'Retry',
      iconPath: REPLACE_ICON,
      class: SECONDARY_BTN,
      onClick: () => emit('invalidate-equation', focusEquation.value!.equation_key),
    })
    return out
  }

  // ----- Completed / invalidated single equation -----
  if (focusEquation.value && (focusEquation.value.status === 'completed' || focusEquation.value.status === 'invalidated')) {
    out.push({
      key: 'rerun',
      label: 'Re-run this step',
      iconPath: REPLACE_ICON,
      class: SECONDARY_BTN,
      onClick: () => emit('invalidate-equation', focusEquation.value!.equation_key),
    })
    if (previewMediaIds.value.length > 0) {
      out.push({
        key: 'show-generation-info',
        label: 'Show Generation Details',
        iconPath: INFO_ICON_BUTTON,
        class: SECONDARY_BTN,
        onClick: showGenerationDetails,
      })
    }
  }

  // ----- Super-node summary -----
  if (props.superNode && props.focusedIterIdx == null) {
    out.push({
      key: 'rerun-loop',
      label: 'Re-run all iterations',
      iconPath: REPLACE_ICON,
      class: SECONDARY_BTN,
      onClick: () => emit('invalidate-equation', props.superNode!.foreachKey),
    })
  }

  return out
})

const previewMediaIds = computed<number[]>(() => {
  if (focusedSlotIteration.value) return []  // candidate handled separately
  const eq = focusEquation.value
  if (!eq) return []
  return Array.isArray(eq.result_media_ids) ? eq.result_media_ids : []
})

const previewGridClass = computed<string>(() => {
  const n = previewMediaIds.value.length
  if (n <= 1) return 'grid-cols-1'
  if (n <= 4) return 'grid-cols-2'
  return 'grid-cols-3'
})
const fitMediaPreview = computed<boolean>(() =>
  focusEquation.value?.equation_type === 'tool_call' && previewMediaIds.value.length > 0,
)
const mediaFitGridStyle = computed<Record<string, string>>(() => {
  const n = Math.max(1, previewMediaIds.value.length)
  const cols = n <= 1 ? 1 : (n <= 4 ? 2 : 3)
  const rows = Math.ceil(n / cols)
  return {
    width: '100%',
    height: '100%',
    gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
    gridTemplateRows: `repeat(${rows}, minmax(0, 1fr))`,
    justifyContent: 'center',
    alignContent: 'center',
  }
})

const detailsToolTitle = computed<string | null>(() => {
  const eq = focusEquation.value
  return eq ? toolTitle(eq) : null
})
const detailsProviderLabel = computed<string | null>(() => {
  const eq = focusEquation.value
  return eq?.tool_id ? resolveProviderName(eq.tool_id) : null
})
const detailsProviderIsStimmaCloud = computed<boolean>(() => {
  const eq = focusEquation.value
  return eq?.tool_id ? isStimmaCloudToolId(eq.tool_id) : false
})
const detailsStatusText = computed<string | null>(() => statusTextFor(focusEquation.value?.status))
const detailsStatusTextClass = computed<string | null>(() => statusClassFor(focusEquation.value?.status))
const detailsStatusDotClass = computed<string | null>(() => dotClassFor(focusEquation.value?.status))
const detailsPreviewPlaceholder = computed(() => ({
  title: placeholderTitle(focusEquation.value?.status),
  body: placeholderBody(focusEquation.value?.status),
  iconPath: placeholderIconPath(focusEquation.value?.status),
  class: placeholderClass(focusEquation.value?.status),
}))

const DETAILS_PROMINENT_KEYS = new Set(['prompt', 'negative_prompt', 'system', 'instructions', 'source', 'static_content'])
const DETAILS_LONG_KEYS = new Set(['prompt', 'negative_prompt', 'system', 'instructions', 'source', 'static_content', 'checkpoint'])
const detailsInputEntries = computed<InputEntry[]>(() => {
  const t = detailsTrace.value
  const entries: InputEntry[] = []

  function addEntry(key: string, raw: unknown) {
    if (raw === null || raw === undefined || raw === '') return
    if (Array.isArray(raw) && raw.length === 0) return
    if (typeof raw === 'object' && !Array.isArray(raw) && Object.keys(raw as Record<string, unknown>).length === 0) return
    const value = formatDetailsValue(raw)
    entries.push({
      key,
      label: formatDetailsLabel(key),
      value,
      fullWidth: DETAILS_LONG_KEYS.has(key) || value.length > 60 || value.includes('\n'),
    })
  }

  function addObjectEntries(obj: Record<string, unknown> | null | undefined) {
    if (!obj || typeof obj !== 'object') return
    for (const [key, raw] of Object.entries(obj)) addEntry(key, raw)
  }

  if (t?.equation_type === 'tool_call') {
    const def = t.definition
    if (def?.params && typeof def.params === 'object') {
      addObjectEntries(def.params)
      if (def.n !== undefined && def.n !== 1) addEntry('n', def.n)
    } else if (def && typeof def === 'object') {
      addObjectEntries(def)
    }
  } else if (t?.equation_type === 'llm_call') {
    addEntry('system', t.system || t.system_template)
    addEntry('prompt', t.prompt || t.prompt_template)
  } else {
    addObjectEntries(t?.inputs || t?.definition?.params || t?.definition || null)
  }

  const deduped = new Map<string, InputEntry>()
  for (const entry of entries) {
    if (!deduped.has(entry.key)) deduped.set(entry.key, entry)
  }
  return Array.from(deduped.values())
})
const detailsProminentInputs = computed(() =>
  detailsInputEntries.value.filter((entry) => DETAILS_PROMINENT_KEYS.has(entry.key)),
)
const detailsCompactInputs = computed(() =>
  detailsInputEntries.value.filter((entry) => !DETAILS_PROMINENT_KEYS.has(entry.key)),
)
const detailsRawJson = computed<string | null>(() => {
  const payload = detailsTrace.value || focusEquation.value
  if (!payload) return null
  try {
    return JSON.stringify(payload, null, 2)
  } catch {
    return null
  }
})

function formatDetailsLabel(key: string): string {
  const overrides: Record<string, string> = {
    cfg: 'CFG',
    n: 'Count',
    negative_prompt: 'Negative prompt',
  }
  if (overrides[key]) return overrides[key]
  return key
    .split('_')
    .map((part) => part ? part[0].toUpperCase() + part.slice(1) : part)
    .join(' ')
}

function formatDetailsValue(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2)
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function statusTextFor(status?: string | null): string {
  switch (status) {
    case 'completed': return 'Done'
    case 'failed': return 'Failed'
    case 'computing': return 'Running'
    case 'awaiting_input': return 'Awaiting input'
    case 'skipped': return 'Skipped'
    case 'invalidated': return 'Stale'
    default: return 'Pending'
  }
}

function statusClassFor(status?: string | null): string {
  switch (status) {
    case 'completed': return 'text-green-500'
    case 'failed': return 'text-red-400'
    case 'computing': return 'text-blue-400'
    case 'awaiting_input': return 'text-purple-400'
    case 'invalidated': return 'text-yellow-400'
    default: return 'text-content-muted'
  }
}

function dotClassFor(status?: string | null): string {
  switch (status) {
    case 'completed': return 'bg-green-500'
    case 'failed': return 'bg-red-400'
    case 'computing': return 'bg-blue-400'
    case 'awaiting_input': return 'bg-purple-400'
    case 'invalidated': return 'bg-yellow-400'
    default: return 'bg-content-muted'
  }
}

function placeholderTitle(status?: string | null): string {
  switch (status) {
    case 'failed': return 'No image was produced'
    case 'computing': return 'Generation is running'
    case 'awaiting_input': return 'Waiting for input'
    default: return 'No preview available'
  }
}

function placeholderBody(status?: string | null): string {
  if (status === 'failed') return focusEquation.value?.error || 'See the error details below.'
  return ''
}

function placeholderClass(status?: string | null): string {
  switch (status) {
    case 'failed': return 'bg-red-500/5 text-red-400'
    case 'computing': return 'bg-blue-500/5 text-blue-400'
    default: return 'bg-overlay-faint text-content-muted'
  }
}

function placeholderIconPath(status?: string | null): string {
  if (status === 'failed') return 'M12 9v3.75m0 3.75h.007v.008H12v-.008ZM10.34 3.94 1.82 18a1.875 1.875 0 0 0 1.603 2.813h17.154A1.875 1.875 0 0 0 22.18 18L13.66 3.94a1.875 1.875 0 0 0-3.32 0Z'
  if (status === 'computing') return 'M16.5 6.75V3.75m0 0h-3m3 0-3 3m-3 10.5v3m0 0h3m-3 0 3-3m-7.5-6h-3m0 0v-3m0 3 3-3m15 3h-3m0 0v3m0-3-3 3'
  return 'M3.375 3.375h17.25v17.25H3.375V3.375Zm3.375 11.25 3-3 2.25 2.25 4.5-4.5 2.25 2.25'
}

const infoMarkdown = computed<string>(() => {
  const eq = focusEquation.value
  if (!eq || eq.equation_type !== 'info' || typeof eq.result !== 'string' || !eq.result) return ''
  try {
    return renderSafeMarkdown(eq.result)
  } catch {
    return eq.result
  }
})

// Failed-state error block — fed by the equation's own error string.
// Trace-level error detail (richer Python traceback) is rendered by
// EquationTraceBody via its devMode amber box; this block is the
// user-facing summary that's always available.
const errorMessage = computed<{ title: string; body: string } | null>(() => {
  const eq = focusEquation.value
  if (!eq || eq.status !== 'failed') return null
  if (errorTask.value) return null
  const parsed = parseFlowError(eq.error)
  if (!parsed) return null
  return { title: parsed.title || 'This step failed', body: parsed.message || '' }
})

const rawErrorText = computed<string | null>(() => {
  if (!props.devMode) return null
  return focusEquation.value?.error || null
})

// Flow input/output value: use the equation's `result` directly.
const inputValue = computed<unknown>(() => focusEquation.value?.result ?? null)

// Editable single-field input form: when the user selects a flow_input
// node and the flow carries a matching schema field, the panel renders
// the same FlowInputForm the steps-view input card uses, scoped to that
// one field. Falls back to the read-only preview when the schema is
// unavailable (no input_name on the equation, schema not loaded yet, or
// literal_list inputs which don't appear in input_schema).
const editableInputName = computed<string | null>(() => {
  const eq = focusEquation.value
  if (!eq || eq.equation_type !== 'flow_input') return null
  const name = eq.input_name
  if (!name) return null
  const schema = props.inputSchema
  if (!schema || !(name in schema)) return null
  return name
})
const singleFieldSchema = computed<Record<string, any> | null>(() => {
  const name = editableInputName.value
  if (!name) return null
  const schema = props.inputSchema
  if (!schema) return null
  return { [name]: schema[name] }
})
function onPanelInputSubmit(values: Record<string, any>) {
  // FlowInputForm emits the full schema slice — for our one-field schema
  // that's already the partial we want to merge upstream.
  emit('update-inputs', values)
}
const panelInputFormRef = ref<InstanceType<typeof FlowInputForm> | null>(null)
const panelInputDirty = ref(false)
const panelInputValid = ref(true)
// Reset dirty/valid when the selected input field changes — FlowInputForm
// remounts on schema change because we render a new key, but the local
// dirty/valid mirrors persist across instances and would otherwise show a
// stale Apply button briefly while the new form initializes.
watch(editableInputName, () => {
  panelInputDirty.value = false
  panelInputValid.value = true
})

// Which equation types render their content via EquationTraceBody. Anything
// else has a panel-specific treatment above (flow input/output, info,
// hitl, super-node summary, slot iteration) or falls through to the
// generic "Nothing to show" line.
const BODY_RENDERABLE_TYPES = new Set([
  'tool_call', 'llm_call', 'code',
  'create_set', 'create_grid', 'create_image', 'create_document',
])
const bodyRenderableType = computed<boolean>(() => {
  const t = focusEquation.value?.equation_type
  return t != null && BODY_RENDERABLE_TYPES.has(t)
})

// ---- Super-node summary derivations ----
const statusBuckets = computed(() => {
  if (!props.superNode) return []
  const counts = { completed: 0, computing: 0, failed: 0, awaiting: 0, pending: 0, skipped: 0 }
  for (let i = 0; i < props.superNode.iterCount; i++) {
    let s = 'pending'
    let saw = false
    for (const pos of props.superNode.bodyPositions) {
      const ps = pos.iterStatuses[i]
      if (ps == null) continue
      saw = true
      if (ps === 'failed') { s = 'failed'; break }
      if (ps === 'computing') s = 'computing'
      else if (ps === 'awaiting_input' && s !== 'computing') s = 'awaiting'
      else if (ps === 'completed' && s === 'pending') s = 'completed'
      else if (ps === 'skipped' && s === 'pending') s = 'skipped'
    }
    if (!saw) s = 'pending'
    if (s === 'completed') counts.completed++
    else if (s === 'computing') counts.computing++
    else if (s === 'failed') counts.failed++
    else if (s === 'awaiting') counts.awaiting++
    else if (s === 'skipped') counts.skipped++
    else counts.pending++
  }
  return [
    { label: 'Done',      count: counts.completed, chipClass: 'border-green-500/40 bg-green-500/10 text-green-400',     dotClass: 'bg-green-500' },
    { label: 'Running',   count: counts.computing, chipClass: 'border-blue-500/40 bg-blue-500/10 text-blue-400',        dotClass: 'bg-blue-500 animate-pulse' },
    { label: 'Your turn', count: counts.awaiting,  chipClass: 'border-purple-500/40 bg-purple-500/10 text-purple-400',  dotClass: 'bg-purple-500' },
    { label: 'Failed',    count: counts.failed,    chipClass: 'border-red-500/40 bg-red-500/10 text-red-400',           dotClass: 'bg-red-500' },
    { label: 'Pending',   count: counts.pending,   chipClass: 'border-edge-subtle bg-overlay-subtle text-content-muted', dotClass: 'bg-zinc-500/60' },
    { label: 'Skipped',   count: counts.skipped,   chipClass: 'border-edge-subtle bg-overlay-subtle text-content-muted/80', dotClass: 'bg-zinc-600/50' },
  ].filter((b) => b.count > 0)
})

const failedIterIdxs = computed<number[]>(() => {
  if (!props.superNode) return []
  const out: number[] = []
  for (let i = 0; i < props.superNode.iterCount; i++) {
    if (props.superNode.bodyPositions.some((p) => p.iterStatuses[i] === 'failed')) out.push(i)
  }
  return out
})

const actionableIterIdxs = computed<number[]>(() => {
  if (!props.superNode) return []
  const out: number[] = []
  for (let i = 0; i < props.superNode.iterCount; i++) {
    const positions = props.superNode.bodyPositions
    if (positions.some((p) => p.iterStatuses[i] === 'failed')) continue
    if (positions.some((p) => p.iterStatuses[i] === 'awaiting_input')) out.push(i)
  }
  return out
})

const totalDurationLabel = computed<string | null>(() => {
  if (!props.superNode) return null
  let total = 0
  for (const pos of props.superNode.bodyPositions) {
    for (const d of pos.iterDurations) {
      if (typeof d === 'number' && d > 0) total += d
    }
  }
  return total > 0 ? formatDurationMs(total) : null
})

</script>

<style scoped>
.info-prose :deep(p) { margin: 0; }
.info-prose :deep(p + p) { margin-top: 0.5em; }
.info-prose :deep(strong) { font-weight: 600; color: rgb(var(--color-content) / 1); }
.info-prose :deep(em) { font-style: italic; }
.info-prose :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.9em;
  padding: 0.1em 0.3em;
  border-radius: 3px;
  background: var(--color-overlay-light);
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
