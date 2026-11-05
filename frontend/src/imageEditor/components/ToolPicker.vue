<script setup lang="ts">
/**
 * The tools that can run the active sub-tool, and nothing else.
 *
 * Deliberately NOT the full catalog menu: that one opens on the task type,
 * offers every task, and carries a search — all of which is wrong when the
 * question is only "which tool does this inpaint". What is reused is the ROW —
 * icon, name, provider label — so a tool reads the same here as everywhere.
 */
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import ToolIcon from '../../components/tools/ToolIcon.vue'
import ToolProviderLabel from '../../components/tools/ToolProviderLabel.vue'
import { isStimmaCloudTool } from '../../utils/stimmaCloud'
import { isRunnableTool } from '../../utils/toolHandoff'

const props = withDefaults(defineProps<{
  tools: any[]
  /** Only tools that can run this task are listed. */
  taskType: string
  /** Optional compatible tasks, ordered from best match to fallback. */
  compatibleTaskTypes?: string[]
  selectedId?: string | null
  /**
   * Width. A fixed 320px is right under a toolbar with the whole window to
   * spill into; in the right-hand sidebar it hangs off the edge of the screen,
   * so that host asks for the column's width instead.
   */
  widthClass?: string
}>(), { widthClass: 'w-[320px]' })

const emit = defineEmits<{ select: [any]; close: [] }>()

const root = ref<HTMLElement | null>(null)

const eligible = computed(() => {
  const accepted = props.compatibleTaskTypes?.length
    ? props.compatibleTaskTypes
    : [props.taskType]
  // Every row here is an offer, so a tool behind a disconnected or disabled
  // provider does not belong in it — the catalog carries those so screens that
  // explain a tool can name it, not so a menu can promise one that cannot run.
  const runnable = props.tools.filter(isRunnableTool)
  return accepted.flatMap(taskType =>
    runnable.filter(tool => {
      const taskTypes = tool.task_types?.length
        ? tool.task_types
        : tool.task_type
          ? [tool.task_type]
          : []
      return taskTypes.includes(taskType)
        && !accepted.slice(0, accepted.indexOf(taskType)).some(earlier =>
          taskTypes.includes(earlier)
        )
    })
  )
})

function isCloud(tool: any): boolean {
  return isStimmaCloudTool(tool)
}

function onDocumentPointerDown(event: PointerEvent) {
  if (!root.value?.contains(event.target as Node)) emit('close')
}
onMounted(() => document.addEventListener('pointerdown', onDocumentPointerDown, true))
onBeforeUnmount(() => document.removeEventListener('pointerdown', onDocumentPointerDown, true))
</script>

<template>
  <div
    ref="root"
    :class="[
      widthClass,
      'max-h-[min(420px,50vh)] overflow-y-auto custom-scrollbar',
      'rounded-lg border border-edge-subtle bg-surface-overlay shadow-xl py-1',
    ]"
  >
    <p v-if="!eligible.length" class="px-3.5 py-3 text-xs text-content-tertiary">
      No installed tool can do this yet.
    </p>
    <button
      v-for="tool in eligible"
      :key="tool.full_tool_id"
      type="button"
      class="w-full px-3.5 py-2 text-left text-[13px] flex items-center gap-2.5 transition-colors"
      :class="tool.full_tool_id === selectedId
        ? 'bg-selection/20 text-content'
        : 'text-content hover:bg-overlay-light'"
      @click="emit('select', tool)"
    >
      <div class="w-3.5 h-3.5 shrink-0" :class="isCloud(tool) ? '' : 'text-content-tertiary'">
        <ToolIcon :tool="tool" size="xs" :bare="true" :ring="false" />
      </div>
      <span class="flex-1 min-w-0 truncate">{{ tool.name }}</span>
      <ToolProviderLabel :cloud="isCloud(tool)" :provider-name="tool.provider_name" class="pl-3" />
    </button>
  </div>
</template>
