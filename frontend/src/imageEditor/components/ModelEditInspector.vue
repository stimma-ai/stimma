<script setup lang="ts">
/**
 * Properties for one model-backed Remove or Repaint patch.
 *
 * Prompt is the normal Repaint surface. Provider controls and patch blending
 * are shown directly: Properties is already the disclosure boundary, so a
 * second Advanced disclosure only makes the controls harder to reach.
 */
import { computed, watch } from 'vue'
import Button from '../../components/ui/Button.vue'
import ScrubValue from '../../components/ui/ScrubValue.vue'
import ToolProviderLabel from '../../components/tools/ToolProviderLabel.vue'
import { isStimmaCloudTool } from '../../utils/stimmaCloud'
import ReferenceImageStrip from './ReferenceImageStrip.vue'
import ToolAdvancedParams from './ToolAdvancedParams.vue'
import { useLoraPool } from '../../composables/useLoraPool'
import type { LoraPoolItem } from '../../composables/useLoraPool'
import type { GenerativeOp, ModelReferenceImage, OpBlend } from '../stack/types'
import {
  modelReferenceLimits,
  sanitizeModelToolParams,
} from '../stack/modelToolParams'
import { MAX_FEATHER_PX } from '../stack/featherScale'

const props = defineProps<{
  op: GenerativeOp
  tool: any | null
  running?: boolean
  isRefreshingLoras?: boolean
  isUploadingLora?: boolean
  loraUploadProgress?: number | null
  loraUploadFileName?: string | null
}>()

const emit = defineEmits<{
  params: [Record<string, any>]
  references: [ModelReferenceImage[]]
  blend: [Partial<OpBlend>]
  blendCommit: []
  run: []
  refreshLoras: [string]
  uploadLoras: [string, string, File[]]
}>()

const isRepaint = computed(() =>
  props.op.operation === 'repaint'
  || (!props.op.operation && props.op.label === 'Repaint')
)
const blend = computed(() => ({
  feather_px: props.op.blend?.feather_px ?? 6,
  opacity: props.op.blend?.opacity ?? 1,
}))
const toolParams = computed(() =>
  sanitizeModelToolParams(props.tool, props.op.params)
)
// Only Regenerate: outpaint-image tools take the original and the four
// percents, nothing else — the old inpaint-backed Expand's references are gone
// with it.
const supportsReferences = computed(() => props.op.operation === 'repaint')
const referenceLimits = computed(() => modelReferenceLimits(props.tool))
const referencesValid = computed(() => {
  const count = props.op.reference_images?.length ?? 0
  return count >= referenceLimits.value.min && count <= referenceLimits.value.max
})

// Each edit owns its enabled/weight selection, while the picker still shares
// the normal tool's pool membership, groups, and display names.
const loraPool = useLoraPool()
const loraToolId = computed(() => props.tool?.full_tool_id
  ? `${props.tool.full_tool_id}__i_image-stack-op-${props.op.id}`
  : null)

function opLoraItems(): LoraPoolItem[] {
  const value = props.op.params?.loras
  return Array.isArray(value)
    ? value.map((item: any) => ({
        lora: String(item?.lora || item?.path || ''),
        weight: Number(item?.weight ?? 1),
        enabled: true,
      })).filter(item => item.lora)
    : []
}

watch(loraToolId, id => {
  if (id) loraPool.syncItemsToPool(id, opLoraItems())
}, { immediate: true })

watch(
  () => loraPool.getEnabledLoras(loraToolId.value),
  selected => {
    if (JSON.stringify(selected) !== JSON.stringify(props.op.params?.loras ?? [])) {
      emit('params', { loras: selected })
    }
  },
  { deep: true, immediate: true },
)

</script>

<template>
  <div class="p-3 space-y-5">
    <section v-if="isRepaint" class="space-y-2">
      <h3 class="text-xs font-semibold text-content-secondary">Prompt</h3>
      <textarea
        :value="op.params.prompt ?? ''"
        rows="3"
        placeholder="Describe the changes for the selected area"
        class="w-full resize-y rounded-md border border-transparent bg-overlay-subtle
               px-3 py-2 text-sm text-content outline-none placeholder:text-content-muted
               focus:border-accent focus-visible:ring-2 ring-accent/40"
        @input="emit('params', {
          prompt: ($event.target as HTMLTextAreaElement).value,
        })"
      />
    </section>

    <section
      v-if="supportsReferences && (referenceLimits.max > 0 || op.reference_images?.length)"
    >
      <ReferenceImageStrip
        :model-value="op.reference_images || []"
        :min-items="referenceLimits.min"
        :max-items="referenceLimits.max"
        :disabled="running"
        @update:model-value="emit('references', $event)"
      />
    </section>

    <section class="space-y-2">
      <div class="flex items-center justify-between gap-3">
        <div class="min-w-0">
          <h3 class="flex min-w-0 items-baseline gap-2 text-xs font-semibold text-content-secondary">
            <span class="min-w-0 truncate">{{ tool?.name || 'Tool unavailable' }}</span>
            <ToolProviderLabel v-if="tool" :cloud="isStimmaCloudTool(tool)" :provider-name="tool.provider_name" />
          </h3>
          <p class="text-xs text-content-tertiary">
            Parameter changes apply the next time this edit runs.
          </p>
        </div>
        <Button
          class="shrink-0 whitespace-nowrap"
          size="sm"
          :loading="running"
          :disabled="!tool || !referencesValid"
          @click="emit('run')"
        >
          Run again
        </Button>
      </div>
    </section>

    <ToolAdvancedParams
      v-if="tool"
      :tool="tool"
      :values="toolParams"
      :lora-tool-id="loraToolId"
      :is-refreshing-loras="isRefreshingLoras"
      :is-uploading-lora="isUploadingLora"
      :lora-upload-progress="loraUploadProgress"
      :lora-upload-file-name="loraUploadFileName"
      @update="(name, value) => emit('params', { [name]: value })"
      @refresh-loras="emit('refreshLoras', $event)"
      @upload-loras="(toolId, scopedId, files) => emit('uploadLoras', toolId, scopedId, files)"
    />

    <section class="space-y-3">
      <h3 class="text-xs font-semibold text-content-secondary">Blend</h3>
      <label class="flex items-center justify-between gap-3 text-xs">
        <span class="text-content-tertiary">Opacity</span>
        <span class="min-w-12 text-right">
          <ScrubValue
            :model-value="Math.round(blend.opacity * 100)"
            :min="0"
            :max="100"
            :step="1"
            :non-default="blend.opacity !== 1"
            :format="value => `${value}%`"
            title="Drag to adjust opacity · click for slider"
            @update:model-value="emit('blend', { opacity: $event / 100 })"
            @commit="emit('blendCommit')"
          />
        </span>
      </label>
      <label class="flex items-center justify-between gap-3 text-xs">
        <span class="text-content-tertiary">Feather</span>
        <span class="min-w-12 text-right">
          <ScrubValue
            :model-value="Math.round(blend.feather_px)"
            :min="0"
            :max="MAX_FEATHER_PX"
            :step="1"
            :non-default="blend.feather_px !== 6"
            :format="value => `${value}px`"
            title="Drag to adjust feather · click for slider"
            @update:model-value="emit('blend', { feather_px: $event })"
            @commit="emit('blendCommit')"
          />
        </span>
      </label>
    </section>
  </div>
</template>
