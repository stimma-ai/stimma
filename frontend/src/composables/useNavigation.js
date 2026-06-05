import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'

// Page types
export const PAGE_TYPES = {
  BROWSE: 'browse',
  GENERATE: 'generate',
  TRASH: 'trash',
  BOARD_DETAIL: 'board-detail'
}

// Preserved pages (stay mounted, preserve state)
const PRESERVED_PAGES = [PAGE_TYPES.BROWSE, PAGE_TYPES.GENERATE, PAGE_TYPES.TRASH]

// Navigation stack (derived from router history)
const navigationStack = ref([])

export function useNavigation() {
  const router = useRouter()
  const route = useRoute()

  // Initialize stack from current route on first call
  if (navigationStack.value.length === 0) {
    const pageType = route.name || PAGE_TYPES.BROWSE
    const params = route.name === 'board-detail'
      ? { boardId: route.params.id }
      : {}
    navigationStack.value.push({ page: pageType, params })
  }

  // Current page (top of stack)
  const currentPage = () => navigationStack.value[navigationStack.value.length - 1]

  // Check if a page type is preserved
  const isPreservedPage = (pageType) => PRESERVED_PAGES.includes(pageType)

  // Navigate to a page
  function navigateTo(pageType, params = {}) {
    // Use Vue Router for actual navigation
    // The router.afterEach hook will update the navigation stack
    switch (pageType) {
      case PAGE_TYPES.BROWSE:
        router.push({ name: 'browse' })
        break
      case PAGE_TYPES.GENERATE:
        router.push({ name: 'generate' })
        break
      case PAGE_TYPES.TRASH:
        router.push({ name: 'trash' })
        break
      case PAGE_TYPES.BOARD_DETAIL:
        router.push({ name: 'board-detail', params: { id: params.boardId } })
        break
      default:
        router.push({ name: 'browse' })
    }
  }

  // Go back in navigation
  function goBack() {
    if (navigationStack.value.length > 1) {
      navigationStack.value.pop()
      router.back()
    }
  }

  // Initialize browser history integration
  function initHistoryIntegration() {
    // Listen to router navigation to keep stack in sync
    router.afterEach((to, from) => {
      // Update stack based on route changes
      const pageType = to.name || PAGE_TYPES.BROWSE
      const params = to.name === 'board-detail'
        ? { boardId: to.params.id }
        : {}

      // If navigating back (detected by stack length), we already popped
      // Otherwise, this is a forward navigation or external change
      const currentStack = navigationStack.value[navigationStack.value.length - 1]
      if (!currentStack || currentStack.page !== pageType ||
          JSON.stringify(currentStack.params) !== JSON.stringify(params)) {
        // Check if we went back
        const previousIndex = navigationStack.value.findIndex(
          item => item.page === pageType &&
                  JSON.stringify(item.params) === JSON.stringify(params)
        )

        if (previousIndex >= 0 && previousIndex < navigationStack.value.length - 1) {
          // Going back - trim stack
          navigationStack.value = navigationStack.value.slice(0, previousIndex + 1)
        } else {
          // Forward navigation - add to stack
          navigationStack.value.push({ page: pageType, params })
        }
      }
    })
  }

  // Check if we can go back
  const canGoBack = () => navigationStack.value.length > 1

  return {
    navigationStack,
    currentPage,
    navigateTo,
    goBack,
    canGoBack,
    isPreservedPage,
    initHistoryIntegration,
    PAGE_TYPES
  }
}
