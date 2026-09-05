/**
 * What the compact header shows for the current route.
 *
 * Hub routes have fixed titles. Detail routes (a board, a chat, a tool) call
 * `setCompactTitle()` once they know their entity's name; the header reads it
 * and App.vue clears it on every navigation so a stale title never survives a
 * route change. Views never render their own navigation chrome (DESIGN.md
 * §1.11) — this is the one channel they have into it.
 */
import { computed, ref } from 'vue'
import type { RouteLocationNormalizedLoaded } from 'vue-router'

const HUB_TITLES: Record<string, string> = {
  home: 'Home',
  browse: 'All assets',
  search: 'Search',
  trash: 'Trash',
  'saved-view': 'Saved view',
  upload: 'Upload',
  boards: 'Boards',
  chats: 'Chats',
  workspace: 'Workspace',
  'all-tools': 'Workspace',
  flows: 'Workspace',
  stimpacks: 'Workspace',
  projects: 'Projects',
}

const DETAIL_FALLBACKS: Record<string, string> = {
  'board-detail': 'Board',
  chat: 'Chat',
  flow: 'Flow',
  tool: 'Tool',
  lineage: 'Lineage',
  'edit-image': 'Edit',
}

export type HubId = 'home' | 'library' | 'workspace' | 'boards' | 'chats'

/** Which hub a route belongs to. Detail routes light their parent hub. */
export function hubForRoute(name: unknown): HubId | null {
  switch (name) {
    case 'home': return 'home'
    case 'browse': case 'trash': case 'saved-view': case 'upload': return 'library'
    // Search belongs to no hub: it rides on whichever hub opened it.
    case 'workspace': case 'all-tools': case 'flows': case 'stimpacks': case 'tool': case 'flow':
    case 'edit-image': case 'lineage': case 'projects': return 'workspace'
    case 'boards': case 'board-detail': return 'boards'
    case 'chats': case 'chat': return 'chats'
    default:
      if (typeof name === 'string' && name.startsWith('project-')) return 'workspace'
      return null
  }
}

export const HUB_ROOTS: Record<HubId, string> = {
  home: '/home', library: '/browse', workspace: '/workspace', boards: '/boards', chats: '/chats',
}

const routeTitle = ref<string>('')
const routeSubtitle = ref<string>('')

export function setCompactTitle(title: string, subtitle = '') {
  routeTitle.value = title
  routeSubtitle.value = subtitle
}

export interface CompactAction { label: string; run: () => void }
const primaryAction = ref<CompactAction | null>(null)

/** A hub's one create action, rendered as the header's plus button. */
export function setCompactPrimaryAction(action: CompactAction | null) {
  primaryAction.value = action
}

export function clearCompactTitle() {
  routeTitle.value = ''
  routeSubtitle.value = ''
  primaryAction.value = null
}

export function useCompactChrome(route: RouteLocationNormalizedLoaded) {
  const surface = computed<'hub' | 'detail' | 'overlay'>(() => {
    const s = route.meta?.surface
    return s === 'detail' || s === 'overlay' ? s : 'hub'
  })
  const isHub = computed(() => surface.value === 'hub')
  const title = computed(() => {
    if (routeTitle.value) return routeTitle.value
    const name = typeof route.name === 'string' ? route.name : ''
    if (HUB_TITLES[name]) return HUB_TITLES[name]
    if (DETAIL_FALLBACKS[name]) return DETAIL_FALLBACKS[name]
    if (name.startsWith('project-')) return 'Project'
    return 'Stimma'
  })
  const subtitle = computed(() => routeSubtitle.value)
  // The Workspace hub owns four landings as segments.
  const workspaceSegments = computed(() => {
    const name = typeof route.name === 'string' ? route.name : ''
    return ['workspace', 'all-tools', 'flows', 'stimpacks'].includes(name)
  })
  return { surface, isHub, title, subtitle, workspaceSegments, primaryAction }
}
