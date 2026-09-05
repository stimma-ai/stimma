<script setup lang="ts">
/**
 * The switcher: the desktop sidebar's zone 2 (Pinned · Editing · Open) as a
 * sheet from the tab bar. Same store, same row grammar as the sidebar: a
 * 32px leading tile (tool mark, entity icon, thumbnail), 13px title over an
 * 11px subtitle, a mono project chip, and the close control — always shown
 * here, since there is no hover. Editing uses the sidebar's EditorShelf.
 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { XMarkIcon } from '@heroicons/vue/24/outline'
import Sheet from '../ui/Sheet.vue'
import EditorShelf from '../EditorShelf.vue'
import EntityIcon from '../EntityIcon.vue'
import ToolIcon from '../tools/ToolIcon.vue'
import { MediaImage } from '../media'
import { useProvidersApi } from '../../composables/useProvidersApi'
import { useWorkspaceTabs, toolTabRoute, editorTabRoute, type WorkspaceTab } from '../../composables/useWorkspaceTabs'
import { isStimmaCloudTool } from '../../utils/stimmaCloud'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ close: [] }>()

const router = useRouter()
const { pinnedTabs, openTabs, editorTabs, removeTab, markTabActivated } = useWorkspaceTabs()
const { fetchProvidersAndTools } = useProvidersApi()

const toolsById = ref<Map<string, any>>(new Map())
watch(() => props.show, async (open) => {
  if (!open || toolsById.value.size) return
  try {
    const { tools } = await fetchProvidersAndTools()
    toolsById.value = new Map(tools.map((t: any) => [t.full_tool_id, t]))
  } catch { /* task-type glyphs still work */ }
})

function toolFor(fullToolId: string) {
  return toolsById.value.get(fullToolId) ?? { id: fullToolId, full_tool_id: fullToolId, task_types: [] as string[] }
}
function toolSubtitle(fullToolId: string): string {
  const tool = toolsById.value.get(fullToolId)
  const provider = tool?.provider_name || tool?.provider_id || ''
  const availability = tool?.availability
  if (availability === 'disconnected') return `${provider} · disconnected`
  if (availability === 'needs_setup') return `${provider} · not ready`
  if (availability && availability !== 'available') return `${provider} · not configured`
  return provider
}
function toolSubtitleClass(fullToolId: string): string {
  const tool = toolsById.value.get(fullToolId)
  if (tool?.availability && tool.availability !== 'available') return 'text-content-muted italic'
  return tool && isStimmaCloudTool(tool) ? 'stimma-cloud-text font-medium' : 'text-content-muted'
}

const recentOpen = computed(() => [...openTabs.value].sort((a, b) => (b.lastActivatedAt ?? 0) - (a.lastActivatedAt ?? 0)))
const isEmpty = computed(() => pinnedTabs.value.length + openTabs.value.length + editorTabs.value.length === 0)

function open(tab: WorkspaceTab) {
  emit('close')
  markTabActivated?.(tab.id)
  if (tab.type === 'tool') router.push(toolTabRoute(tab))
  else if (tab.type === 'chat') router.push({ name: 'chat', params: { id: tab.entityId } })
  else if (tab.type === 'board') router.push({ name: 'board-detail', params: { id: tab.entityId } })
  else if (tab.type === 'project') router.push({ name: 'project-overview', params: { id: tab.entityId } })
  else if (tab.type === 'editor') router.push(editorTabRoute(tab))
  else if (tab.type === 'lineage') router.push({ name: 'lineage', params: { mediaId: tab.entityId } })
  else if (tab.type === 'flow') router.push({ name: 'flow', params: { id: tab.entityId } })
}
function openEditor(tabId: string) {
  const tab = editorTabs.value.find((t) => t.id === tabId)
  if (tab) open(tab)
}
</script>

<template>
  <Sheet :show="show" @close="emit('close')">
    <div class="pb-2">
      <p v-if="isEmpty" class="px-3 py-6 text-center text-[13px] text-content-tertiary">Nothing open. Tools, chats, boards and edits you open stay here.</p>

      <template v-if="pinnedTabs.length">
        <div class="px-3 pt-1 pb-1 text-xs font-semibold text-content-secondary">Pinned</div>
        <div v-for="tab in pinnedTabs" :key="tab.id" class="flex items-center">
          <button type="button" class="ws-row" @click="open(tab)">
            <div class="w-8 h-8 flex items-center justify-center flex-shrink-0 text-content-secondary">
              <div class="w-7 h-7"><ToolIcon :tool="toolFor(tab.entityId)" bare :ring="false" /></div>
            </div>
            <div class="flex-1 min-w-0 flex items-center gap-1.5">
              <div class="flex-1 min-w-0 flex flex-col">
                <span class="truncate text-[13px] text-content">{{ tab.customName || tab.displayName }}</span>
                <span class="truncate text-[11px]" :class="toolSubtitleClass(tab.entityId)">{{ toolSubtitle(tab.entityId) }}</span>
              </div>
              <span v-if="tab.projectName" class="ws-chip">{{ tab.projectName }}</span>
            </div>
          </button>
        </div>
      </template>

      <template v-if="editorTabs.length">
        <div class="px-3 pt-2 pb-1 text-xs font-semibold text-content-secondary">Editing</div>
        <div class="px-1">
          <EditorShelf :tabs="editorTabs" @open="openEditor" @remove="(id: string) => removeTab(id)" />
        </div>
      </template>

      <template v-if="recentOpen.length">
        <div class="px-3 pt-2 pb-1 text-xs font-semibold text-content-secondary">Open</div>
        <div v-for="tab in recentOpen" :key="tab.id" class="flex items-center">
          <button type="button" class="ws-row !pr-0" @click="open(tab)">
            <MediaImage v-if="tab.type === 'lineage'" :media-id="Number(tab.editorMediaId || tab.entityId)" thumbnail :thumbnail-size="64" :draggable="false" :enable-context-menu="false" container-class="w-8 h-8 rounded-media flex-shrink-0" img-class="w-full h-full object-cover" />
            <div v-else-if="tab.type === 'tool'" class="w-8 h-8 flex items-center justify-center flex-shrink-0 text-content-secondary">
              <div class="w-7 h-7"><ToolIcon :tool="toolFor(tab.entityId)" bare :ring="false" /></div>
            </div>
            <EntityIcon v-else-if="tab.type === 'chat' || tab.type === 'board' || tab.type === 'project' || tab.type === 'flow'" :type="tab.type" />
            <span v-else class="w-8 h-8 rounded-media bg-overlay-subtle flex-shrink-0"></span>

            <div v-if="tab.type === 'tool'" class="flex-1 min-w-0 flex items-center gap-1.5">
              <div class="flex-1 min-w-0 flex flex-col">
                <span class="truncate text-[13px] text-content">{{ tab.customName || tab.displayName }}</span>
                <span v-if="tab.customName" class="truncate text-[11px] text-content-muted">{{ tab.displayName }} · <span :class="toolSubtitleClass(tab.entityId)">{{ toolSubtitle(tab.entityId) }}</span></span>
                <span v-else class="truncate text-[11px]" :class="toolSubtitleClass(tab.entityId)">{{ toolSubtitle(tab.entityId) }}</span>
              </div>
              <span v-if="tab.projectName" class="ws-chip">{{ tab.projectName }}</span>
            </div>
            <div v-else class="flex-1 min-w-0 flex items-center gap-1.5">
              <span class="flex-1 truncate text-[13px]" :class="tab.displayName ? 'text-content' : 'text-content-muted italic'">{{ tab.customName || tab.displayName || 'Untitled' }}</span>
              <span v-if="tab.projectName" class="ws-chip">{{ tab.projectName }}</span>
            </div>
          </button>
          <button type="button" class="w-11 h-11 mr-1 flex items-center justify-center rounded text-content-muted border-none bg-transparent flex-shrink-0" :aria-label="`Close ${tab.displayName}`" @click.stop="removeTab(tab.id)">
            <XMarkIcon class="w-4 h-4" />
          </button>
        </div>
      </template>
    </div>
  </Sheet>
</template>

<style scoped>
/* The sidebar's tab row, verbatim: 44px, px-3 py-2, gap-2.5, 13/11 text. */
.ws-row {
  @apply flex items-center gap-2.5 px-3 py-2 rounded text-content-secondary text-sm font-normal whitespace-nowrap border-none bg-transparent text-left w-full min-w-0 flex-1;
  min-height: 44px;
}
.ws-chip {
  @apply flex-shrink-0 text-[10px] font-mono text-content-tertiary bg-overlay-subtle rounded px-1.5 py-0.5 truncate max-w-[80px];
}
</style>
