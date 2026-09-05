<script setup lang="ts">
/**
 * Workspace › Open — the compact-viewport hub for the working set.
 *
 * The desktop sidebar's zone 2, in its order: Pinned tools, the Editing shelf
 * (open editors as thumbnails, same EditorShelf and rules as the sidebar),
 * then everything else open by recency. Same useWorkspaceTabs store, so the
 * set is the one the desktop shows when both sit on one server. Tapping a
 * row resumes it; the close control removes the shortcut, never the work.
 *
 * Wide viewports have the sidebar for this; the view still renders (deep
 * links, tests) but the tab bar that leads here does not exist there.
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { XMarkIcon, MapPinIcon, PlusIcon } from '@heroicons/vue/24/outline'
import EditorShelf from '../components/EditorShelf.vue'
import EntityIcon from '../components/EntityIcon.vue'
import ToolIcon from '../components/tools/ToolIcon.vue'
import { MediaImage } from '../components/media'
import { useProvidersApi } from '../composables/useProvidersApi'
import { useWorkspaceTabs, toolTabRoute, editorTabRoute, type WorkspaceTab } from '../composables/useWorkspaceTabs'

const router = useRouter()
const { pinnedTabs, openTabs, editorTabs, removeTab, markTabActivated } = useWorkspaceTabs()
const { fetchProvidersAndTools } = useProvidersApi()

const toolsById = ref<Map<string, any>>(new Map())
onMounted(async () => {
  try {
    const { tools } = await fetchProvidersAndTools()
    toolsById.value = new Map(tools.map((t: any) => [t.full_tool_id, t]))
  } catch {
    // Icons fall back to the task-type glyph; the list still works.
  }
})

function toolFor(fullToolId: string) {
  return toolsById.value.get(fullToolId) ?? { id: fullToolId, full_tool_id: fullToolId, task_types: [] as string[] }
}

function detailFor(tab: WorkspaceTab): string {
  if (tab.type === 'tool') {
    const tool = toolsById.value.get(tab.entityId)
    const parts = [tool?.task_type?.replace(/_/g, ' ') || 'tool', tool?.provider_name || tool?.provider_id].filter(Boolean)
    if (tab.projectName) parts.push(tab.projectName)
    return parts.join(' · ')
  }
  return tab.type
}

const recentOpen = computed(() =>
  [...openTabs.value].sort((a, b) => (b.lastActivatedAt ?? 0) - (a.lastActivatedAt ?? 0)),
)

function open(tab: WorkspaceTab) {
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

function close(tab: WorkspaceTab) {
  removeTab(tab.id)
}

const isEmpty = computed(() => pinnedTabs.value.length + openTabs.value.length + editorTabs.value.length === 0)
</script>

<template>
  <div class="h-full overflow-y-auto custom-scrollbar bg-base">
    <template v-if="isEmpty">
      <div class="px-8 pt-16 pb-10 text-center">
        <h2 class="font-brand text-xl font-semibold text-content">Nothing open yet</h2>
        <p class="mt-2 text-sm text-content-tertiary">Tools, chats, boards and flows you open stay here until you close them. Pin the tools you reach for most.</p>
        <router-link
          to="/tools"
          class="inline-flex items-center gap-1.5 mt-5 px-4 min-h-11 rounded-md bg-accent text-white text-sm font-medium"
        >Browse tools</router-link>
      </div>
    </template>

    <template v-else>
      <section v-if="pinnedTabs.length" class="pt-2">
        <h2 class="px-4 pt-3 pb-1 text-xs font-semibold text-content-secondary">Pinned</h2>
        <ul class="divide-y divide-edge-subtle">
          <li v-for="tab in pinnedTabs" :key="tab.id" class="flex items-center">
            <button type="button" class="flex-1 min-w-0 flex items-center gap-3 px-4 min-h-[56px] text-left border-none bg-transparent" @click="open(tab)">
              <span class="w-9 h-9 rounded-md bg-accent/15 text-accent-hi flex items-center justify-center flex-shrink-0">
                <span class="w-6 h-6"><ToolIcon :tool="toolFor(tab.entityId)" bare :ring="false" /></span>
              </span>
              <span class="flex-1 min-w-0">
                <span class="block truncate text-[15px] text-content">{{ tab.customName || tab.displayName }}</span>
                <span class="block truncate text-[11.5px] font-mono text-content-tertiary">{{ detailFor(tab) }}</span>
              </span>
              <MapPinIcon class="w-4 h-4 text-content-muted flex-shrink-0" aria-hidden="true" />
            </button>
          </li>
        </ul>
      </section>

      <section v-if="editorTabs.length">
        <h2 class="px-4 pt-4 pb-1 text-xs font-semibold text-content-secondary">Editing</h2>
        <div class="px-1">
          <EditorShelf :tabs="editorTabs" @open="openEditor" @remove="(id) => removeTab(id)" />
        </div>
      </section>

      <section v-if="recentOpen.length">
        <h2 class="px-4 pt-4 pb-1 text-xs font-semibold text-content-secondary">Open</h2>
        <ul class="divide-y divide-edge-subtle">
          <li v-for="tab in recentOpen" :key="tab.id" class="flex items-center">
            <button type="button" class="flex-1 min-w-0 flex items-center gap-3 pl-4 pr-1 min-h-[56px] text-left border-none bg-transparent" @click="open(tab)">
              <span v-if="tab.type === 'tool'" class="w-9 h-9 rounded-md bg-accent/15 text-accent-hi flex items-center justify-center flex-shrink-0">
                <span class="w-6 h-6"><ToolIcon :tool="toolFor(tab.entityId)" bare :ring="false" /></span>
              </span>
              <MediaImage
                v-else-if="tab.type === 'lineage'"
                :media-id="Number(tab.editorMediaId || tab.entityId)"
                thumbnail :thumbnail-size="64" :draggable="false" :enable-context-menu="false"
                container-class="w-9 h-9 rounded-media flex-shrink-0 bg-matte" img-class="w-full h-full object-cover"
              />
              <EntityIcon v-else-if="tab.type === 'chat' || tab.type === 'board' || tab.type === 'project' || tab.type === 'flow'" :type="tab.type" size="md" />
              <span v-else class="w-9 h-9 rounded-md bg-overlay-subtle flex-shrink-0"></span>
              <span class="flex-1 min-w-0">
                <span class="block truncate text-[15px] text-content">
                  {{ tab.customName || tab.displayName || 'Untitled' }}
                  <span v-if="tab.projectName" class="ml-1 align-middle text-[10.5px] font-mono px-1.5 py-px rounded bg-overlay-subtle text-content-secondary">{{ tab.projectName }}</span>
                </span>
                <span class="block truncate text-[11.5px] font-mono text-content-tertiary">{{ detailFor(tab) }}</span>
              </span>
            </button>
            <button
              type="button"
              class="w-11 h-11 mr-1 flex items-center justify-center rounded-md text-content-muted border-none bg-transparent flex-shrink-0"
              :aria-label="`Close ${tab.displayName}`"
              @click.stop="close(tab)"
            >
              <XMarkIcon class="w-5 h-5" />
            </button>
          </li>
        </ul>
      </section>

      <div class="px-4 py-4">
        <router-link to="/tools" class="inline-flex items-center gap-1.5 min-h-11 text-[15px] text-accent-hi">
          <PlusIcon class="w-5 h-5" /> All tools
        </router-link>
      </div>
    </template>
  </div>
</template>
