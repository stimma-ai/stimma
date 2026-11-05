<template>
  <div class="h-full flex flex-col bg-base">
    <!-- Header row. Wide: title, task and provider filters, tool filter field.
         Compact (the "Tools" title is the compact header's): one 44px row with
         the task and provider filters and the tool filter field side by side.
         This field is the page's one search entry; the compact header drops its
         own search icon here, and global search stays reachable from the other hubs. -->
    <PageHeader class="compact:h-auto compact:min-h-12 compact:gap-1 compact:bg-surface compact:px-3 compact:py-0 compact:[&>:first-child]:hidden compact:[&>:nth-child(2)]:min-w-0 compact:[&>:nth-child(2)]:flex-1">
      <template #title>All tools</template>
      <template #actions>
        <!-- Task filter. Multi-select, like providers; compact / coarse opens
             it as a sheet, as the provider filter does. -->
        <div v-if="availableTaskTypes.length > 0" class="relative compact:min-w-0" ref="taskDropdownRef">
          <Select
            :label="taskFilterLabel"
            :open="taskDropdownOpen"
            :active="activeTaskFilters.size > 0"
            :caret="!isCompact"
            class="compact:max-w-full compact:gap-1.5 compact:px-2"
            @click="taskDropdownOpen = !taskDropdownOpen"
          >
            <template #icon><Squares2X2Icon class="h-icon-nav w-icon-nav flex-shrink-0 hidden compact:block" /></template>
          </Select>

          <div
            v-if="taskDropdownOpen && !providerSheet"
            class="absolute right-0 top-full mt-1 bg-surface border border-edge-subtle rounded-lg shadow-lg z-menu min-w-[220px] max-h-[min(26rem,70vh)] overflow-y-auto py-1"
            role="listbox"
            aria-multiselectable="true"
          >
            <button
              type="button"
              @click="activeTaskFilters = new Set()"
              class="w-full px-3 py-2 text-left text-sm flex items-center gap-2 hover:bg-overlay-subtle transition-colors"
              :class="activeTaskFilters.size === 0 ? 'text-accent-hi' : 'text-content-secondary'"
              role="option"
              :aria-selected="activeTaskFilters.size === 0"
            >
              <svg v-if="activeTaskFilters.size === 0" class="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
              </svg>
              <span v-else class="w-4 flex-shrink-0"></span>
              <span class="flex-1">All tasks</span>
            </button>
            <div class="border-t border-edge-subtle my-1"></div>
            <button
              v-for="taskType in availableTaskTypes"
              :key="taskType"
              type="button"
              @click="toggleTaskFilter(taskType)"
              class="w-full px-3 py-2 text-left text-sm flex items-center gap-2 hover:bg-overlay-subtle transition-colors"
              :class="activeTaskFilters.has(taskType) ? 'text-accent-hi' : 'text-content-secondary'"
              role="option"
              :aria-selected="activeTaskFilters.has(taskType)"
            >
              <svg v-if="activeTaskFilters.has(taskType)" class="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
              </svg>
              <span v-else class="w-4 flex-shrink-0"></span>
              <span class="flex-1 truncate">{{ formatTaskType(taskType) }}</span>
              <span class="text-[11px] font-mono tabular-nums text-content-muted">{{ taskTypeCounts[taskType] }}</span>
            </button>
          </div>
        </div>

        <!-- Provider filter. Wide: an inline dropdown. Compact / coarse: the
             kit Sheet — an inline dropdown converted to a sheet would sit
             inside the app column's stacking context, under the shared sheet
             backdrop, and no tap would ever reach it. -->
        <div v-if="availableProviders.length > 1 || hasUnavailableTools" class="relative compact:min-w-0" ref="providerDropdownRef">
          <Select
            :label="providerFilterLabel"
            :open="providerDropdownOpen"
            :active="activeProviderFilters.size > 0"
            :caret="!isCompact"
            :class="providerFilterIsStimma ? 'stimma-cloud-text font-medium' : ''"
            class="compact:max-w-full compact:gap-1.5 compact:px-2"
            @click="providerDropdownOpen = !providerDropdownOpen"
          >
            <template #icon><FunnelIcon class="h-icon-nav w-icon-nav flex-shrink-0 hidden compact:block" /></template>
          </Select>

          <!-- Dropdown menu (wide) -->
          <div
            v-if="providerDropdownOpen && !providerSheet"
            class="absolute right-0 top-full mt-1 bg-surface border border-edge-subtle rounded-lg shadow-lg z-menu min-w-[180px] py-1"
          >
            <button
              v-for="provider in availableProviders"
              :key="provider.provider_id"
              @click="toggleProviderFilter(provider.provider_id)"
              class="w-full px-3 py-2 text-left text-sm flex items-center gap-2 hover:bg-overlay-subtle transition-colors"
              :class="activeProviderFilters.has(provider.provider_id) ? 'text-accent-hi' : 'text-content-secondary'"
            >
              <svg
                v-if="activeProviderFilters.has(provider.provider_id)"
                class="w-4 h-4 flex-shrink-0"
                fill="none"
                viewBox="0 0 24 24"
                stroke-width="2"
                stroke="currentColor"
              >
                <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
              </svg>
              <span v-else class="w-4 flex-shrink-0"></span>
              <span :class="isStimmaCloudTool(provider) ? 'stimma-cloud-text font-medium' : ''">{{ toolProviderDisplayName(provider) }}</span>
            </button>
            <div class="border-t border-edge-subtle my-1"></div>
            <button
              @click="showUnavailable = !showUnavailable"
              class="w-full px-3 py-2 text-left text-sm flex items-center gap-2 hover:bg-overlay-subtle transition-colors"
              :class="showUnavailable ? 'text-accent-hi' : 'text-content-secondary'"
            >
              <svg
                v-if="showUnavailable"
                class="w-4 h-4 flex-shrink-0"
                fill="none"
                viewBox="0 0 24 24"
                stroke-width="2"
                stroke="currentColor"
              >
                <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
              </svg>
              <span v-else class="w-4 flex-shrink-0"></span>
              <span>Show unavailable</span>
            </button>
          </div>
        </div>

        <!-- Tool filter: the one explicit field for narrowing the tools on this
             page, beside the provider filter. -->
        <SearchField
          ref="searchInputRef"
          v-model="searchQuery"
          placeholder="Filter tools..."
          aria-label="Filter tools"
          class="w-48 compact:w-full compact:flex-1 compact:min-w-0"
          @escape="closeSearch"
        />
      </template>
    </PageHeader>

    <!-- Task filter as a bottom sheet (compact / coarse), same rows as the
         wide dropdown. -->
    <Sheet :show="taskDropdownOpen && providerSheet" title="Tasks" @close="taskDropdownOpen = false">
      <div class="pb-2">
        <button
          type="button"
          class="sheet-row"
          :class="activeTaskFilters.size === 0 ? '!text-accent-hi' : ''"
          @click="activeTaskFilters = new Set()"
        >
          <svg v-if="activeTaskFilters.size === 0" class="sheet-row-icon" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
          </svg>
          <span v-else class="sheet-row-icon"></span>
          <span class="flex-1">All tasks</span>
        </button>
        <div class="mx-4 my-1 border-t border-edge-subtle"></div>
        <button
          v-for="taskType in availableTaskTypes"
          :key="taskType"
          type="button"
          class="sheet-row"
          :class="activeTaskFilters.has(taskType) ? '!text-accent-hi' : ''"
          @click="toggleTaskFilter(taskType)"
        >
          <svg v-if="activeTaskFilters.has(taskType)" class="sheet-row-icon" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
          </svg>
          <span v-else class="sheet-row-icon"></span>
          <span class="flex-1 truncate">{{ formatTaskType(taskType) }}</span>
          <span class="sheet-row-detail">{{ taskTypeCounts[taskType] }}</span>
        </button>
      </div>
    </Sheet>

    <!-- Provider filter as a bottom sheet (compact / coarse). Multi-select:
         rows toggle and the sheet stays; tap outside or the handle to close. -->
    <Sheet :show="providerDropdownOpen && providerSheet" title="Providers" @close="providerDropdownOpen = false">
      <div class="pb-2">
        <button
          v-for="provider in availableProviders"
          :key="provider.provider_id"
          type="button"
          class="sheet-row"
          :class="activeProviderFilters.has(provider.provider_id) ? '!text-accent-hi' : ''"
          @click="toggleProviderFilter(provider.provider_id)"
        >
          <svg v-if="activeProviderFilters.has(provider.provider_id)" class="sheet-row-icon" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
          </svg>
          <span v-else class="sheet-row-icon"></span>
          <span class="truncate" :class="isStimmaCloudTool(provider) ? 'stimma-cloud-text font-medium' : ''">{{ toolProviderDisplayName(provider) }}</span>
        </button>
        <div class="mx-4 my-1 border-t border-edge-subtle"></div>
        <button
          type="button"
          class="sheet-row"
          :class="showUnavailable ? '!text-accent-hi' : ''"
          @click="showUnavailable = !showUnavailable"
        >
          <svg v-if="showUnavailable" class="sheet-row-icon" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
          </svg>
          <span v-else class="sheet-row-icon"></span>
          <span>Show unavailable</span>
        </button>
      </div>
    </Sheet>

    <!-- Tools Grid -->
    <div class="flex-1 overflow-y-auto py-page">
      <!-- Connection Error -->
      <ConnectionError
        v-if="loadError"
        @retry="loadProviders"
      />

      <!-- Loading state -->
      <div v-else-if="loading" class="flex items-center justify-center h-64">
        <div class="text-content-muted">Loading tools...</div>
      </div>

      <!-- Empty state: No tools at all -->
      <div v-else-if="tools.length === 0" class="flex flex-col items-center justify-center h-64 text-center">
        <svg class="w-16 h-16 text-content-muted mb-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M11.42 15.17L17.25 21A2.652 2.652 0 0021 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 11-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 004.486-6.336l-3.276 3.277a3.004 3.004 0 01-2.25-2.25l3.276-3.276a4.5 4.5 0 00-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437l1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008z" />
        </svg>
        <p class="text-content-muted mb-2">No tools available</p>
        <p class="text-content-muted text-sm">Check that providers are connected and configured properly.</p>
      </div>

      <!-- Empty state: No tools match filters -->
      <div v-else-if="filteredTools.length === 0" class="flex flex-col items-center justify-center h-64 text-center">
        <svg class="w-16 h-16 text-content-muted mb-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
        </svg>
        <p class="text-content-muted mb-2">No tools match your filters</p>
        <p class="text-content-muted text-sm">Try adjusting your search, task type, or provider filters.</p>
      </div>

      <!-- Tools by task. Plain rows in the chats and flows grammar: name (the
           variant beside it, lighter), then only the facts that tell a tool
           from its neighbours in one fixed right-aligned column. Facts every
           tool in a section shares (provider, "open weights") sit once on the
           section label; related variants of one tool sit together, the
           repeats of the title dimmed. The full list stays in the tooltip. -->
      <div v-else class="space-y-section">
        <section v-for="group in toolSections" :key="group.taskType">
          <div class="mb-1 flex max-w-[56rem] items-baseline gap-3 px-page">
            <h2 class="text-xs font-semibold text-content-secondary">
              {{ formatTaskType(group.taskType) }}
            </h2>
            <span v-if="group.sharedFacts.length" class="min-w-0 truncate text-[11px] text-content-muted">
              <template v-for="(fact, i) in group.sharedFacts" :key="fact.text">
                <span v-if="i > 0" aria-hidden="true"> · </span>
                <span :class="fact.cloud ? 'stimma-cloud-text font-medium' : ''">{{ fact.text }}</span>
              </template>
            </span>
          </div>

          <div
            v-for="row in group.rows"
            :key="row.tool.full_tool_id"
            class="group relative cursor-pointer px-page py-1.5 transition-colors hover:bg-overlay-subtle"
            :class="[
              row.tool.availability !== 'available' ? 'opacity-40 pointer-events-none' : '',
              row.clusterStart && !row.first ? 'mt-2' : '',
            ]"
            @click="openTool(row.tool)"
            @contextmenu.prevent="isUserTool(row.tool) ? openToolMenu($event, row.tool) : null"
          >
            <div
              class="grid max-w-[56rem] gap-x-4 narrow:grid-cols-[minmax(0,1fr)_auto] narrow:gap-x-3"
              :class="[
                group.hasPrice ? 'grid-cols-[minmax(0,1fr)_15rem_3.5rem]' : 'grid-cols-[minmax(0,1fr)_15rem]',
                isUserTool(row.tool) ? 'pr-8' : '',
              ]"
            >
              <!-- Identity: name, with the variant beside it in a lighter
                   weight. A repeated title is dimmed so the variants read as
                   one tool. Wraps before it truncates. -->
              <h3 class="col-start-1 row-start-1 min-w-0 break-words text-sm leading-5 line-clamp-2" :title="row.tool.name">
                <span class="font-medium" :class="row.repeat ? 'text-content-tertiary' : 'text-content'">{{ row.title }}</span><span v-if="row.variant" class="ml-1.5 text-content-secondary">{{ row.variant }}</span>
              </h3>

              <!-- Distinguishing facts, fixed right-aligned column. -->
              <div
                v-if="row.facts.length || row.hidden > 0"
                class="col-start-2 row-start-1 flex min-w-0 items-center justify-end gap-1.5 text-[11px] leading-5 text-content-muted narrow:col-start-1 narrow:row-start-3 narrow:col-span-2 narrow:justify-start"
                :title="row.allFacts.join(' · ')"
              >
                <template v-for="(fact, i) in row.facts" :key="fact.text">
                  <span v-if="i > 0" class="flex-shrink-0" aria-hidden="true">·</span>
                  <span
                    class="min-w-0 truncate whitespace-nowrap"
                    :class="fact.cloud ? 'stimma-cloud-text font-medium' : fact.fast ? 'text-accent-hi' : ''"
                  >{{ fact.text }}</span>
                </template>
                <span v-if="row.hidden > 0" class="flex-shrink-0 font-mono tabular-nums">+{{ row.hidden }}</span>
              </div>

              <span
                v-if="group.hasPrice"
                class="col-start-3 row-start-1 text-right font-mono text-[11px] leading-5 tabular-nums text-content-tertiary narrow:col-start-2"
              >{{ row.price }}</span>

              <p
                v-if="row.description"
                class="col-start-1 row-start-2 min-w-0 truncate text-xs leading-5 text-content-secondary narrow:col-span-2"
              >{{ row.description }}</p>
            </div>

            <!-- Per-tool menu (user tools only) -->
            <button
              v-if="isUserTool(row.tool)"
              class="absolute right-page top-1/2 -mr-2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-content-muted opacity-0 transition-opacity hover:bg-overlay-light hover:text-content group-hover:opacity-100 compact:opacity-100 [[data-pointer=coarse]_&]:opacity-100"
              title="Tool options"
              @click.stop="openToolMenu($event, row.tool)"
            >
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.75a.75.75 0 1 1 0-1.5.75.75 0 0 1 0 1.5ZM12 12.75a.75.75 0 1 1 0-1.5.75.75 0 0 1 0 1.5ZM12 18.75a.75.75 0 1 1 0-1.5.75.75 0 0 1 0 1.5Z" />
              </svg>
            </button>
          </div>
        </section>
      </div>
    </div>

    <!-- Per-tool context menu (user tools only) -->
    <Teleport to="body">
      <div
        v-if="toolMenu.visible"
        ref="toolMenuRef" data-escape-layer
        class="fixed bg-surface border border-edge-subtle rounded-lg shadow-xl z-menu py-1 min-w-[160px]"
        :style="{ left: toolMenu.x + 'px', top: toolMenu.y + 'px' }"
      >
        <button
          @click="editToolFromMenu"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        >
          <svg class="w-4 h-4 flex-shrink-0 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Zm0 0L19.5 7.125" />
          </svg>
          <span>Edit</span>
        </button>
        <div class="border-t border-edge-subtle my-1"></div>
        <button
          @click="deleteToolFromMenu"
          class="w-full px-3 py-2 text-left text-xs text-red-500 hover:bg-overlay-light flex items-center gap-2"
        >
          <svg class="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
          </svg>
          <span>Delete</span>
        </button>
      </div>
    </Teleport>

    <!-- Edit tool (re-freeze) dialog -->
    <FreezeToolDialog
      :show="editDialogOpen"
      :tool="editingTool"
      :flow-name="editingFlowName"
      :flow-output-names="editingFlowOutputNames"
      @cancel="editDialogOpen = false"
      @saved="onToolEdited"
      @deleted="onToolDeleted"
      @open-flow="onOpenBackingFlow"
    />

    <!-- Delete confirmation -->
    <ConfirmModal
      :show="confirmDeleteOpen"
      title="Delete tool"
      :message="`Delete '${pendingDeleteTool?.name || 'this tool'}'? The flow it was made from is not affected.`"
      confirm-text="Delete"
      cancel-text="Cancel"
      @confirm="confirmDeleteTool"
      @cancel="confirmDeleteOpen = false"
    />
  </div>
</template>

<script setup>
import { consumeEscape, hasEscapeLayer, isTopmostEscapeLayer } from '../utils/escapeLayers'
import { ref, computed, nextTick, onMounted, onUnmounted, onActivated, onDeactivated, watch } from 'vue'
import { useGlobalKeyboardShortcuts } from '../composables/useGlobalKeyboardShortcuts'
import { useRoute, useRouter } from 'vue-router'
import { FunnelIcon, Squares2X2Icon } from '@heroicons/vue/24/outline'
import { useViewport } from '../composables/useViewport'
import Sheet from '../components/ui/Sheet.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import Select from '../components/ui/Select.vue'
import SearchField from '../components/ui/SearchField.vue'
import { useProvidersApi } from '../composables/useProvidersApi'
import { makeProfileKey } from '../utils/storageKeys'
import {
  STIMMA_CLOUD_PROVIDER_ID,
  STIMMA_TOOL_PROVIDER_DISPLAY_NAME,
  isStimmaCloudTool,
  toolProviderDisplayName,
} from '../utils/stimmaCloud'
import { formatTaskTypeLabel, TASK_TYPE_LABELS } from '../utils/taskTypeIcons'
import ConnectionError from '../components/ConnectionError.vue'
import ConfirmModal from '../components/ConfirmModal.vue'
import FreezeToolDialog from '../components/flow/FreezeToolDialog.vue'
import { getApiBase } from '../apiConfig'
import { hidePricesRef } from '../appConfig'
import { useFlowsApi } from '../composables/useFlowsApi'
import { useToasts } from '../composables/useToasts'
import axios from 'axios'

const props = defineProps({
  projectId: {
    type: Number,
    default: null
  }
})

defineOptions({
  name: 'AllToolsView'
})

const router = useRouter()
const route = useRoute()
const { fetchProvidersAndTools, subscribeToProviderChanges, clearCache } = useProvidersApi()

// WebSocket subscription for reactive updates
let unsubscribeFromProviderChanges = null

// Search input ref
const searchInputRef = ref(null)

// Provider dropdown. On compact or coarse pointers it renders as the kit Sheet.
const providerDropdownRef = ref(null)
const providerDropdownOpen = ref(false)
const { isCompact, isCoarsePointer, allowsAutofocus } = useViewport()
const providerSheet = computed(() => isCompact.value || isCoarsePointer.value)

// Escape in the filter field clears it and drops focus.
function closeSearch() {
  searchQuery.value = ''
  searchInputRef.value?.blur()
}

// Task filter dropdown (wide). On coarse pointers it renders as a sheet too.
const taskDropdownRef = ref(null)
const taskDropdownOpen = ref(false)

function getSearchKey() {
  return makeProfileKey('allTools', 'searchQuery')
}

function getFiltersKey() {
  return makeProfileKey('allTools', 'taskFilters')
}

function getProviderFiltersKey() {
  return makeProfileKey('allTools', 'providerFilters')
}

function getShowUnavailableKey() {
  return makeProfileKey('allTools', 'showUnavailable')
}

// State
const providers = ref([])
const tools = ref([])
const loading = ref(true)
const loadError = ref(false)
const searchQuery = ref(localStorage.getItem(getSearchKey()) || '')

// Global search "View all" handoff: seed the local filter from ?q= so the
// omnibox's per-type result caps never hide matches for good.
watch(() => route.query.q, (q) => {
  if (typeof q === 'string' && q) searchQuery.value = q
}, { immediate: true })

const activeTaskFilters = ref(new Set())
const activeProviderFilters = ref(new Set())
const showUnavailable = ref(localStorage.getItem(getShowUnavailableKey()) === '1')
const filtersInitialized = ref(false)

// Persist state on changes. Wrapped in try/catch so a full localStorage quota
// can't throw out of a watcher and break navigation from this view.
function safeSetItem(key, value) {
  try {
    localStorage.setItem(key, value)
  } catch (e) {
    console.warn('[AllToolsView] failed to write', key, e)
  }
}

watch(searchQuery, (val) => {
  safeSetItem(getSearchKey(), val)
})

watch(activeTaskFilters, (val) => {
  if (!filtersInitialized.value) return
  safeSetItem(getFiltersKey(), JSON.stringify([...val]))
}, { deep: true })

watch(activeProviderFilters, (val) => {
  if (!filtersInitialized.value) return
  safeSetItem(getProviderFiltersKey(), JSON.stringify([...val]))
}, { deep: true })

watch(showUnavailable, (val) => {
  safeSetItem(getShowUnavailableKey(), val ? '1' : '0')
})

// Reload state when profile changes
function handleProfileChanged() {
  searchQuery.value = localStorage.getItem(getSearchKey()) || ''
  const savedFilters = localStorage.getItem(getFiltersKey())
  if (savedFilters) {
    try {
      activeTaskFilters.value = new Set(JSON.parse(savedFilters))
    } catch {
      activeTaskFilters.value = new Set()
    }
  } else {
    activeTaskFilters.value = new Set()
  }
  const savedProviderFilters = localStorage.getItem(getProviderFiltersKey())
  if (savedProviderFilters) {
    try {
      activeProviderFilters.value = new Set(JSON.parse(savedProviderFilters))
    } catch {
      activeProviderFilters.value = new Set()
    }
  } else {
    activeProviderFilters.value = new Set()
  }
  showUnavailable.value = localStorage.getItem(getShowUnavailableKey()) === '1'
}

if (typeof window !== 'undefined') {
  window.addEventListener('profile-changed', handleProfileChanged)
}

// Alias for template compatibility
function formatTaskType(taskType) {
  return formatTaskTypeLabel(taskType)
}

// Computed

// Unavailable tools (e.g. cached cloud tools while signed out) are hidden
// unless the user opts in via the providers menu.
const visibleTools = computed(() => (
  showUnavailable.value ? tools.value : tools.value.filter(t => t.availability === 'available')
))

const availableTaskTypes = computed(() => {
  // Count tools per task type (using all task_types, not just primary)
  const counts = {}
  for (const tool of visibleTools.value) {
    const taskTypes = tool.task_types?.length ? tool.task_types : (tool.task_type ? [tool.task_type] : [])
    if (taskTypes.length === 0) {
      // Tools without task types count as "utility"
      counts['utility'] = (counts['utility'] || 0) + 1
    } else {
      for (const tt of taskTypes) {
        counts[tt] = (counts[tt] || 0) + 1
      }
    }
  }
  // Sort by count descending, with "filter" and "utility" pinned to the end
  // (filters are secondary post-processing tools, not what you come here for)
  const endRank = (t) => (t === 'utility' ? 2 : t === 'filter' ? 1 : 0)
  return Object.keys(counts).sort((a, b) => {
    if (endRank(a) !== endRank(b)) return endRank(a) - endRank(b)
    return counts[b] - counts[a]
  })
})

const taskTypeCounts = computed(() => {
  const counts = {}
  for (const tool of visibleTools.value) {
    const taskTypes = tool.task_types?.length ? tool.task_types : (tool.task_type ? [tool.task_type] : [])
    for (const tt of (taskTypes.length ? taskTypes : ['utility'])) counts[tt] = (counts[tt] || 0) + 1
  }
  return counts
})

const taskFilterLabel = computed(() => {
  const selected = [...activeTaskFilters.value].filter(t => availableTaskTypes.value.includes(t))
  if (selected.length === 0) return 'All tasks'
  const first = formatTaskType(selected[0])
  return selected.length === 1 ? first : `${first} +${selected.length - 1}`
})

const hasUnavailableTools = computed(() => (
  tools.value.some(t => t.availability !== 'available')
))

const availableProviders = computed(() => {
  // Get unique providers from tools, with counts
  const providerCounts = {}
  const providerInfo = {}
  for (const tool of visibleTools.value) {
    providerCounts[tool.provider_id] = (providerCounts[tool.provider_id] || 0) + 1
    if (!providerInfo[tool.provider_id]) {
      providerInfo[tool.provider_id] = {
        provider_id: tool.provider_id,
        provider_name: tool.provider_name
      }
    }
  }
  // Sort by count descending, then by name
  return Object.keys(providerCounts)
    .map(id => providerInfo[id])
    .sort((a, b) => {
      const countDiff = providerCounts[b.provider_id] - providerCounts[a.provider_id]
      if (countDiff !== 0) return countDiff
      return (a.provider_name || a.provider_id).localeCompare(b.provider_name || b.provider_id)
    })
})

const providerFilterLabel = computed(() => {
  if (activeProviderFilters.value.size === 0) {
    return isCompact.value ? 'All providers' : 'All Providers'
  }
  // Get names of selected providers
  const selectedNames = [...activeProviderFilters.value]
    .map(id => {
      const provider = availableProviders.value.find(p => p.provider_id === id)
      return provider?.provider_name || provider?.provider_id || 'Provider'
    })
    .sort()
  return selectedNames.join(', ')
})

const providerFilterIsStimma = computed(() => (
  activeProviderFilters.value.size === 1
  && activeProviderFilters.value.has(STIMMA_CLOUD_PROVIDER_ID)
))

const filteredTools = computed(() => {
  let result = [...visibleTools.value]

  // Filter by task types (only if any are selected - empty means show all)
  // A tool matches if ANY of its task_types match the filter
  // "utility" matches tools with no task types
  if (activeTaskFilters.value.size > 0) {
    result = result.filter(t => {
      const toolTaskTypes = t.task_types?.length ? t.task_types : (t.task_type ? [t.task_type] : [])
      if (toolTaskTypes.length === 0) {
        // Tools with no task types match "utility" filter
        return activeTaskFilters.value.has('utility')
      }
      return toolTaskTypes.some(tt => activeTaskFilters.value.has(tt))
    })
  }

  // Filter by providers (only if any are selected - empty means show all)
  if (activeProviderFilters.value.size > 0) {
    result = result.filter(t => activeProviderFilters.value.has(t.provider_id))
  }

  // Filter by search query — name, provider, and description are all fair
  // game (all three are visible on the card, and e.g. "darkroom" should find
  // the Darkroom tools by either name or description).
  if (searchQuery.value.trim()) {
    const query = searchQuery.value.toLowerCase().trim()
    result = result.filter(t =>
      t.name.toLowerCase().includes(query)
      || (t.provider_name || '').toLowerCase().includes(query)
      || String(t.metadata?.description || t.subtitle || '').toLowerCase().includes(query)
    )
  }

  // Sort by name
  result.sort((a, b) => a.name.localeCompare(b.name))

  return result
})

const providerMap = computed(() => {
  const map = new Map()
  for (const provider of providers.value) {
    map.set(provider.provider_id, provider)
  }
  return map
})

const groupedByTask = computed(() => {
  const groups = {}

  // Group tools by ALL their task_types (tool may appear in multiple groups)
  for (const tool of filteredTools.value) {
    const taskTypes = tool.task_types?.length ? tool.task_types : (tool.task_type ? [tool.task_type] : [])
    if (taskTypes.length === 0) {
      // Tools without task types go in "Utility" group
      if (!groups['utility']) {
        groups['utility'] = []
      }
      groups['utility'].push(tool)
    } else {
      for (const taskType of taskTypes) {
        if (!groups[taskType]) {
          groups[taskType] = []
        }
        groups[taskType].push(tool)
      }
    }
  }

  const taskTypeOrder = new Map(
    availableTaskTypes.value.map((taskType, index) => [taskType, index])
  )

  // Convert to array and sort to match the filter pill order at the top
  return Object.entries(groups)
    .map(([taskType, tools]) => ({ taskType, tools }))
    .sort((a, b) => {
      const aIndex = taskTypeOrder.get(a.taskType) ?? Number.MAX_SAFE_INTEGER
      const bIndex = taskTypeOrder.get(b.taskType) ?? Number.MAX_SAFE_INTEGER

      if (aIndex !== bIndex) {
        return aIndex - bIndex
      }

      return formatTaskType(a.taskType).localeCompare(formatTaskType(b.taskType))
    })
})

// Methods
function toggleTaskFilter(taskType) {
  const newSet = new Set(activeTaskFilters.value)
  if (newSet.has(taskType)) {
    newSet.delete(taskType)
  } else {
    newSet.add(taskType)
  }
  activeTaskFilters.value = newSet
}

function toggleProviderFilter(providerId) {
  const newSet = new Set(activeProviderFilters.value)
  if (newSet.has(providerId)) {
    newSet.delete(providerId)
  } else {
    newSet.add(providerId)
  }
  activeProviderFilters.value = newSet
}

function getProviderForTool(tool) {
  return providerMap.value.get(tool.provider_id)
}

function initializeFilters() {
  const taskKey = getFiltersKey()
  const providerKey = getProviderFiltersKey()

  console.log('[AllToolsView] initializeFilters - taskKey:', taskKey)
  console.log('[AllToolsView] initializeFilters - providerKey:', providerKey)

  // Load task type filters from localStorage (default is empty = show all)
  const savedFilters = localStorage.getItem(taskKey)
  console.log('[AllToolsView] savedFilters from localStorage:', savedFilters)

  // Collect all task types (using task_types array with fallback to task_type)
  const allTaskTypes = new Set(tools.value.flatMap(t =>
    t.task_types?.length ? t.task_types : (t.task_type ? [t.task_type] : [])
  ))
  console.log('[AllToolsView] allTaskTypes:', [...allTaskTypes])

  if (savedFilters) {
    const saved = new Set(JSON.parse(savedFilters))
    console.log('[AllToolsView] parsed saved filters:', [...saved])
    // Only keep saved filters that still exist
    const filtered = new Set([...saved].filter(t => allTaskTypes.has(t)))
    console.log('[AllToolsView] after filtering against available:', [...filtered])
    activeTaskFilters.value = filtered
  }
  // else: leave empty (show all tools)

  // Load provider filters from localStorage
  const savedProviderFilters = localStorage.getItem(providerKey)
  console.log('[AllToolsView] savedProviderFilters from localStorage:', savedProviderFilters)

  const allProviderIds = new Set(tools.value.map(t => t.provider_id))
  console.log('[AllToolsView] allProviderIds:', [...allProviderIds])

  if (savedProviderFilters) {
    const saved = new Set(JSON.parse(savedProviderFilters))
    console.log('[AllToolsView] parsed saved provider filters:', [...saved])
    // Only keep saved filters that still exist
    const filtered = new Set([...saved].filter(id => allProviderIds.has(id)))
    console.log('[AllToolsView] after filtering against available:', [...filtered])
    activeProviderFilters.value = filtered
  }
  // else: leave empty (show all tools)

  filtersInitialized.value = true
}

async function loadProviders() {
  loading.value = true
  loadError.value = false
  try {
    // The shared catalog: fresh entries, or the read already in flight. Tool
    // and provider changes clear it before this reloads, so no force needed.
    const result = await fetchProvidersAndTools()
    providers.value = result.providers
    // Filter out agent-only tools (not for direct user interaction)
    tools.value = result.tools.filter(t => !t.metadata?.agent_only)
    initializeFilters()
  } catch (error) {
    console.error('Failed to load providers:', error)
    loadError.value = true
  } finally {
    loading.value = false
  }
}

function openTool(tool) {
  // Always allow navigation - ToolView will show unavailable overlay if needed
  const query = {}
  const pid = props.projectId || route.query.project_id
  if (pid) {
    query.project_id = String(pid)
  }
  router.push({
    name: 'tool',
    params: { fullToolId: tool.full_tool_id },
    query
  })
}

function getPrimaryTaskType(tool) {
  if (tool.task_types?.length) return tool.task_types[0]
  return tool.task_type || 'utility'
}

function getToolDescription(tool) {
  return tool.metadata?.description || tool.subtitle || ''
}

// Splits a tool's name into identity and variant. The variant is the trailing
// parenthetical already in the name; the group's task label is dropped from the
// title when something else remains. Falls back to the plain name.
function toolTitleParts(tool, taskType) {
  const name = (tool.name || '').trim()
  let base = name
  let variant = ''
  const m = name.match(/^(.*?)\s*\(([^()]+)\)\s*$/)
  if (m && m[1].trim()) {
    base = m[1].trim()
    variant = m[2].trim()
  }
  const task = formatTaskType(taskType)
  if (task) {
    const stripped = base.replace(new RegExp(`\\s+${task.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(\\s*⚡)?$`, 'i'), '$1').trim()
    if (stripped && stripped !== base) base = stripped
  }
  // A lightning mark on the title is a fact about the tool, so it moves to the facts line.
  let fast = false
  if (/\s*⚡\s*$/.test(base)) {
    fast = true
    base = base.replace(/\s*⚡\s*$/, '').trim()
  }
  return { title: base, variant, fast }
}

function getToolPrice(tool) {
  if (hidePricesRef.value) return ''
  return tool.metadata?.display_price || ''
}

function getToolBadges(tool) {
  return tool.metadata?.badges || []
}

// Rows show only what tells a tool from its neighbours: at most two facts, the
// rest fold into a quiet +N (the full list is the row's tooltip). Facts every
// tool in a section shares are lifted onto the section label.
const VISIBLE_FACTS = 2

function toolProviderFact(tool) {
  if (isUserTool(tool)) return { text: 'Custom tool' }
  if (isStimmaCloudTool(tool)) return { text: STIMMA_TOOL_PROVIDER_DISPLAY_NAME, cloud: true }
  return { text: tool.provider_name || tool.provider_id || '' }
}

// Capability facts for display: the lightning mark (on the title or in a
// badge) is the word "fast", leading.
function toolCapabilityFacts(tool, parts) {
  const out = []
  const seen = new Set()
  const add = (text, extra = {}) => {
    const t = String(text).replace(/⚡/g, '').trim().toLowerCase()
    const key = t
    if (!t || seen.has(key)) return
    seen.add(key)
    out.push({ text: t, ...extra })
  }
  const badges = getToolBadges(tool)
  if (parts.fast || badges.some((b) => String(b).toLowerCase().replace(/⚡/g, '').trim() === 'fast' || String(b).includes('⚡'))) {
    add('fast', { fast: true })
  }
  for (const b of badges) add(b)
  return out
}

const toolSections = computed(() => {
  return groupedByTask.value.map((group) => {
    const items = group.tools.map((tool) => {
      const parts = toolTitleParts(tool, group.taskType)
      const provider = toolProviderFact(tool)
      const caps = toolCapabilityFacts(tool, parts)
      return { tool, parts, provider, caps }
    })

    // Facts shared by every tool in the section (only meaningful with 2+).
    const shared = []
    if (items.length > 1) {
      if (items.every((i) => i.provider.text === items[0].provider.text) && items[0].provider.text) {
        shared.push(items[0].provider)
      }
      for (const cap of items[0].caps) {
        if (items.every((i) => i.caps.some((c) => c.text.toLowerCase() === cap.text.toLowerCase()))) shared.push(cap)
      }
    }
    const sharedKeys = new Set(shared.map((f) => f.text.toLowerCase()))

    // Related variants of one tool sit together, in order of first appearance.
    const clusters = new Map()
    for (const item of items) {
      const key = item.parts.title.toLowerCase()
      if (!clusters.has(key)) clusters.set(key, [])
      clusters.get(key).push(item)
    }

    const rows = []
    for (const cluster of clusters.values()) {
      cluster.forEach((item, ci) => {
        const own = [item.provider, ...item.caps].filter((f) => f.text && !sharedKeys.has(f.text.toLowerCase()))
        // Provider only distinguishes when it is not the section's.
        const all = [item.provider.text, ...item.caps.map((c) => c.text)].filter(Boolean)
        rows.push({
          tool: item.tool,
          title: item.parts.title,
          variant: item.parts.variant,
          repeat: ci > 0,
          clusterStart: ci === 0,
          first: rows.length === 0,
          facts: own.slice(0, VISIBLE_FACTS),
          hidden: Math.max(0, own.length - VISIBLE_FACTS),
          allFacts: all,
          price: getToolPrice(item.tool),
          description: getToolDescription(item.tool),
        })
      })
    }
    return {
      taskType: group.taskType,
      sharedFacts: shared,
      hasPrice: rows.some((r) => r.price),
      rows,
    }
  })
})

// ==========================================================================
// User Tools — "Yours" badge + per-tool Edit/Delete
// ==========================================================================

const USER_TOOLS_PROVIDER_ID = 'user-tools'

function isUserTool(tool) {
  return tool?.provider_id === USER_TOOLS_PROVIDER_ID
}

const { getFlow } = useFlowsApi()
const { addToast } = useToasts()

// Lightweight context menu (matches EntityContextMenu visual style; user tools
// carry string ids + Edit/Delete-only actions, so we keep this self-contained
// rather than overloading the chat/board singleton menu).
const toolMenu = ref({ visible: false, x: 0, y: 0, tool: null })
const toolMenuRef = ref(null)

function openToolMenu(event, tool) {
  if (!isUserTool(tool)) return
  toolMenu.value = { visible: true, x: event.clientX, y: event.clientY, tool }
}

function closeToolMenu() {
  toolMenu.value = { ...toolMenu.value, visible: false, tool: null }
}

// Edit dialog state
const editDialogOpen = ref(false)
const editingTool = ref(null)            // full UserTool dict
const editingFlowOutputNames = ref([])   // source flow's declared output names
const editingFlowName = ref(null)        // source flow's name (for the dialog banner)

// Delete confirmation state
const confirmDeleteOpen = ref(false)
const pendingDeleteTool = ref(null)      // the ProviderTool from the grid

// Resolve a grid ProviderTool to its canonical UserTool row (with output_map,
// hitl_policies, flow_id, etc.) via GET /api/user-tools.
async function fetchUserToolRow(providerTool) {
  const userToolId = providerTool?.metadata?.user_tool_id
  const base = getApiBase()
  const resp = await axios.get(`${base}/user-tools`)
  const rows = resp.data || []
  if (userToolId != null) {
    const match = rows.find((r) => String(r.id) === String(userToolId))
    if (match) return match
  }
  // Fallback: match by name when metadata is missing.
  return rows.find((r) => r.name === providerTool.name) || null
}

async function editToolFromMenu() {
  const providerTool = toolMenu.value.tool
  closeToolMenu()
  if (!providerTool) return
  try {
    const row = await fetchUserToolRow(providerTool)
    if (!row) {
      addToast('Could not load tool for editing', 'error', 5000)
      return
    }
    // Derive the source flow's name + output names for the dialog.
    let outputNames = []
    editingFlowName.value = null
    if (row.flow_id != null) {
      try {
        const flow = await getFlow(row.flow_id)
        editingFlowName.value = flow?.name || null
        const schema = flow?.output_schema
        if (schema && typeof schema === 'object') {
          const props = schema.properties && typeof schema.properties === 'object' ? schema.properties : schema
          outputNames = Object.keys(props).filter((k) => !['type', 'properties', 'required'].includes(k))
        }
      } catch (e) {
        console.warn('[AllToolsView] failed to load backing flow outputs', e)
      }
    }
    // Always include any flow outputs already referenced by the saved map.
    for (const v of Object.values(row.output_map || {})) {
      if (v && !outputNames.includes(v)) outputNames.push(v)
    }
    editingFlowOutputNames.value = outputNames
    editingTool.value = row
    editDialogOpen.value = true
  } catch (err) {
    console.error('[AllToolsView] edit tool failed', err)
    addToast('Could not load tool for editing', 'error', 5000)
  }
}

function deleteToolFromMenu() {
  pendingDeleteTool.value = toolMenu.value.tool
  closeToolMenu()
  confirmDeleteOpen.value = true
}

async function confirmDeleteTool() {
  const providerTool = pendingDeleteTool.value
  confirmDeleteOpen.value = false
  pendingDeleteTool.value = null
  if (!providerTool) return
  const userToolId = providerTool?.metadata?.user_tool_id
  if (userToolId == null) {
    addToast('Could not resolve tool id', 'error', 5000)
    return
  }
  try {
    const base = getApiBase()
    await axios.delete(`${base}/user-tools/${userToolId}`)
    addToast(`Tool "${providerTool.name}" deleted`, 'success', 4000)
    clearCacheAndReload()
  } catch (err) {
    const detail = err?.response?.data?.detail || err?.message || 'Failed to delete tool'
    addToast(typeof detail === 'string' ? detail : 'Failed to delete tool', 'error', 6000)
  }
}

function clearCacheAndReload() {
  try { clearCache() } catch (_) {}
  loadProviders()
}

// FreezeToolDialog (edit mode) callbacks
function onToolEdited() {
  editDialogOpen.value = false
  editingTool.value = null
  clearCacheAndReload()
}

function onToolDeleted() {
  editDialogOpen.value = false
  editingTool.value = null
  clearCacheAndReload()
}

function onOpenBackingFlow(flowId) {
  editDialogOpen.value = false
  router.push({ name: 'flow', params: { id: String(flowId) } })
}

function handleKeydown(e) {
  if (e.defaultPrevented) return
  if (e.key === 'Escape' && toolMenu.value.visible && isTopmostEscapeLayer(toolMenuRef.value)) {
    consumeEscape(e)
    closeToolMenu()
    return
  }
  if (hasEscapeLayer()) return
  // Focus search on '/' key, unless already in an input
  if (e.key === '/' && !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
    e.preventDefault()
    searchInputRef.value?.focus()
  }
}

useGlobalKeyboardShortcuts({ onKeydown: handleKeydown })
onDeactivated(() => {
  closeToolMenu()
  providerSheet.value = false
  providerDropdownOpen.value = false
  taskDropdownOpen.value = false
})

function handleClickOutside(e) {
  // The Sheet teleports to body (outside providerDropdownRef) and dismisses
  // itself; treating its taps as outside clicks would close it on every pick.
  if (!providerSheet.value && providerDropdownRef.value && !providerDropdownRef.value.contains(e.target)) {
    providerDropdownOpen.value = false
  }
  if (!providerSheet.value && taskDropdownRef.value && !taskDropdownRef.value.contains(e.target)) {
    taskDropdownOpen.value = false
  }
  // Close the per-tool menu when clicking outside it.
  if (toolMenu.value.visible && toolMenuRef.value && !toolMenuRef.value.contains(e.target)) {
    closeToolMenu()
  }
}

onMounted(() => {
  loadProviders()

  // Subscribe to provider status changes for reactive updates
  unsubscribeFromProviderChanges = subscribeToProviderChanges(() => {
    // Reload tools when provider status changes
    loadProviders()
  })

  // Focus search input on mount (wide only: on a phone that pops the keyboard)
  if (allowsAutofocus.value) searchInputRef.value?.focusQuietly()

  // Listen for click outside to close dropdown
  document.addEventListener('click', handleClickOutside)
})

onActivated(() => {
  // Focus search input when returning to the page (KeepAlive reactivation)
  if (allowsAutofocus.value) searchInputRef.value?.focusQuietly()
})

onUnmounted(() => {
  // Clean up WebSocket subscription
  if (unsubscribeFromProviderChanges) {
    unsubscribeFromProviderChanges()
    unsubscribeFromProviderChanges = null
  }

  // Clean up click outside listener
  document.removeEventListener('click', handleClickOutside)

  // Clean up profile-changed listener
  window.removeEventListener('profile-changed', handleProfileChanged)
})

// No reload on reactivation - KeepAlive preserves state including scroll position
// If user wants fresh data, they can refresh the page
</script>
