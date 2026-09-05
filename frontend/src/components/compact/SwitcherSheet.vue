<script setup lang="ts">
/**
 * The switcher: everything open right now, across kinds (pinned tools,
 * editors, open tools / chats / boards / projects / flows), as a sheet from
 * the header. The desktop sidebar's zone 2, reachable from any screen. Same
 * useWorkspaceTabs store. Tapping a row resumes it; the close control
 * removes the shortcut, never the work.
 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { XMarkIcon, MapPinIcon } from '@heroicons/vue/24/outline'
import Sheet from '../ui/Sheet.vue'
import EntityIcon from '../EntityIcon.vue'
import ToolIcon from '../tools/ToolIcon.vue'
import { MediaImage } from '../media'
import { useProvidersApi } from '../../composables/useProvidersApi'
import { useWorkspaceTabs, toolTabRoute, editorTabRoute, type WorkspaceTab } from '../../composables/useWorkspaceTabs'

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
function detailFor(tab: WorkspaceTab): string {
  if (tab.type === 'tool') {
    const tool = toolsById.value.get(tab.entityId)
    return [tool?.task_type?.replace(/_/g, ' ') || 'tool', tool?.provider_name || tool?.provider_id, tab.projectName].filter(Boolean).join(' · ')
  }
  return tab.projectName ? `${tab.type} · ${tab.projectName}` : tab.type
}

const recentOpen = computed(() => [...openTabs.value].sort((a, b) => (b.lastActivatedAt ?? 0) - (a.lastActivatedAt ?? 0)))
const recentEditors = computed(() => [...editorTabs.value].sort((a, b) => (b.lastActivatedAt ?? 0) - (a.lastActivatedAt ?? 0)))
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
function closeAll() {
  for (const t of [...openTabs.value, ...editorTabs.value]) removeTab(t.id)
}
</script>

<template>
  <Sheet :show="show" title="Open" @close="emit('close')">
    <div class="pb-2">
      <p v-if="isEmpty" class="px-4 py-6 text-center text-[13px] text-content-tertiary">Nothing open. Tools, chats, boards and edits you open show up here.</p>

      <template v-if="pinnedTabs.length">
        <div class="sheet-section">Pinned</div>
        <button v-for="tab in pinnedTabs" :key="tab.id" type="button" class="sheet-row" @click="open(tab)">
          <span class="sheet-row-icon text-accent-hi"><ToolIcon :tool="toolFor(tab.entityId)" bare :ring="false" /></span>
          <span class="flex-1 min-w-0">
            <span class="block truncate">{{ tab.customName || tab.displayName }}</span>
            <span class="block truncate sheet-row-detail !max-w-full">{{ detailFor(tab) }}</span>
          </span>
          <MapPinIcon class="w-4 h-4 text-content-muted flex-shrink-0" aria-hidden="true" />
        </button>
      </template>

      <template v-if="recentEditors.length">
        <div class="sheet-section">Editing</div>
        <div v-for="tab in recentEditors" :key="tab.id" class="sheet-row !pr-1">
          <button type="button" class="flex-1 min-w-0 flex items-center gap-3 min-h-[44px] text-left border-none bg-transparent p-0" @click="open(tab)">
            <MediaImage
              :media-id="Number(tab.editorMediaId || tab.entityId)"
              thumbnail :thumbnail-size="64" :draggable="false" :enable-context-menu="false"
              container-class="sheet-row-icon rounded-media bg-matte" img-class="w-full h-full object-cover"
            />
            <span class="flex-1 min-w-0">
              <span class="block truncate text-content">{{ tab.customName || tab.displayName || 'Edit' }}</span>
              <span class="block truncate sheet-row-detail !max-w-full">image editor</span>
            </span>
          </button>
          <button type="button" class="w-11 h-11 flex items-center justify-center rounded-md text-content-muted border-none bg-transparent flex-shrink-0" :aria-label="`Close ${tab.displayName}`" @click.stop="removeTab(tab.id)">
            <XMarkIcon class="w-5 h-5" />
          </button>
        </div>
      </template>

      <template v-if="recentOpen.length">
        <div class="sheet-section">Open</div>
        <div v-for="tab in recentOpen" :key="tab.id" class="sheet-row !pr-1">
          <button type="button" class="flex-1 min-w-0 flex items-center gap-3 min-h-[44px] text-left border-none bg-transparent p-0" @click="open(tab)">
            <span v-if="tab.type === 'tool'" class="sheet-row-icon text-accent-hi"><ToolIcon :tool="toolFor(tab.entityId)" bare :ring="false" /></span>
            <MediaImage
              v-else-if="tab.type === 'lineage'"
              :media-id="Number(tab.editorMediaId || tab.entityId)"
              thumbnail :thumbnail-size="64" :draggable="false" :enable-context-menu="false"
              container-class="sheet-row-icon rounded-media bg-matte" img-class="w-full h-full object-cover"
            />
            <span v-else-if="tab.type === 'chat' || tab.type === 'board' || tab.type === 'project' || tab.type === 'flow'" class="sheet-row-icon"><EntityIcon :type="tab.type" size="sm" /></span>
            <span v-else class="sheet-row-icon rounded-md bg-overlay-subtle"></span>
            <span class="flex-1 min-w-0">
              <span class="block truncate text-content">{{ tab.customName || tab.displayName || 'Untitled' }}</span>
              <span class="block truncate sheet-row-detail !max-w-full">{{ detailFor(tab) }}</span>
            </span>
          </button>
          <button type="button" class="w-11 h-11 flex items-center justify-center rounded-md text-content-muted border-none bg-transparent flex-shrink-0" :aria-label="`Close ${tab.displayName}`" @click.stop="removeTab(tab.id)">
            <XMarkIcon class="w-5 h-5" />
          </button>
        </div>
        <button type="button" class="sheet-row !text-content-tertiary" @click="closeAll">
          <span class="sheet-row-icon"></span><span>Close all</span>
        </button>
      </template>
    </div>
  </Sheet>
</template>
