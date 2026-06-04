<template>
  <div class="navigation-renderer">
    <!-- Preserved pages (always mounted, shown/hidden with v-show) -->
    <BrowseGridView
      v-show="current.page === PAGE_TYPES.BROWSE"
      :sidebar-collapsed="sidebarCollapsed"
      :is-trash-mode="false"
    />

    <GenerateView
      v-show="current.page === PAGE_TYPES.GENERATE"
      :sidebar-collapsed="sidebarCollapsed"
    />

    <!-- Trash view uses BrowseGridView with trash mode enabled -->
    <BrowseGridView
      v-show="current.page === PAGE_TYPES.TRASH"
      :sidebar-collapsed="sidebarCollapsed"
      :is-trash-mode="true"
    />

    <!-- Non-preserved pages (mount when on top of stack) -->
    <!-- Use :key to force fresh instances for each navigation -->
    <BoardDetailView
      v-if="current.page === PAGE_TYPES.BOARD_DETAIL"
      :key="`board-${current.params.boardId}-${navigationStack.length}`"
      :sidebar-collapsed="sidebarCollapsed"
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useNavigation, PAGE_TYPES } from '../composables/useNavigation'
import BrowseGridView from '../views/BrowseGridView.vue'
import GenerateView from '../views/GenerateView.vue'
import BoardDetailView from '../views/BoardDetailView.vue'

defineProps({
  sidebarCollapsed: {
    type: Boolean,
    default: false
  }
})

const { navigationStack, currentPage } = useNavigation()

const current = computed(() => currentPage())
</script>

<style scoped>
.navigation-renderer {
  width: 100%;
  height: 100%;
  position: relative;
}
</style>
