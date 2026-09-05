/**
 * Two-layer navigation for the compact chrome.
 *
 * Layer 1: each hub (Home, Library, Workspace, Boards, Chats) owns a stack of
 * routes. Navigating inside a hub pushes; the header's back control pops.
 * Layer 2: the order hubs were visited. When a hub's stack bottoms out, back
 * returns to the hub you came from, at the screen you left it on. Switching
 * hubs through the tab bar restores that hub's stack top; tapping the active
 * hub pops it to its root.
 *
 * This is the model native tab bars use (Instagram's, notably), and it is the
 * only way "leave a chat for Boards, come back to the chat" and "back always
 * goes somewhere sensible" both hold. The browser's own history keeps working
 * for the OS back gesture; this store decides what the in-app control does.
 *
 * Routes that belong to no hub (search, settings deep links) ride on whichever
 * hub is current.
 */
import { reactive, readonly } from 'vue'
import type { Router } from 'vue-router'
import { hubForRoute, HUB_ROOTS, type HubId } from './useCompactChrome'

interface NavState {
  current: HubId
  stacks: Record<HubId, string[]>
  hubHistory: HubId[]
}

const state = reactive<NavState>({
  current: 'home',
  stacks: {
    home: [HUB_ROOTS.home],
    library: [HUB_ROOTS.library],
    workspace: [HUB_ROOTS.workspace],
    boards: [HUB_ROOTS.boards],
    chats: [HUB_ROOTS.chats],
  },
  hubHistory: [],
})

let router: Router | null = null
// Set while this store drives a navigation so the afterEach hook records
// the result as a pop / switch instead of a fresh push.
let driving: 'pop' | 'switch' | null = null

function top(hub: HubId): string {
  const s = state.stacks[hub]
  return s[s.length - 1] ?? HUB_ROOTS[hub]
}

function isRoot(hub: HubId, path: string): boolean {
  return path.split('?')[0] === HUB_ROOTS[hub]
}

function record(fullPath: string, name: unknown, replaced: boolean) {
  const hub = hubForRoute(name) ?? state.current
  if (driving) {
    driving = null
    return
  }
  if (hub !== state.current) {
    // Hub switch by a link or a tab: remember where we came from.
    if (state.hubHistory[state.hubHistory.length - 1] !== state.current) state.hubHistory.push(state.current)
    if (state.hubHistory.length > 20) state.hubHistory.shift()
    state.current = hub
  }
  const stack = state.stacks[hub]
  if (isRoot(hub, fullPath)) {
    stack.splice(0, stack.length, fullPath)
    return
  }
  if (stack[stack.length - 1] === fullPath) return
  if (replaced && stack.length > 1) stack[stack.length - 1] = fullPath
  else stack.push(fullPath)
  if (stack.length > 30) stack.splice(1, 1)
}

/** Header back control. */
export function compactBack() {
  if (!router) return
  const stack = state.stacks[state.current]
  if (stack.length > 1) {
    stack.pop()
    driving = 'pop'
    router.replace(top(state.current))
    return
  }
  const previous = state.hubHistory.pop()
  if (previous) {
    state.current = previous
    driving = 'switch'
    router.replace(top(previous))
    return
  }
  if (state.current !== 'home') {
    state.current = 'home'
    driving = 'switch'
    router.replace(top('home'))
  }
}

/** Tab bar tap. */
export function compactGoToHub(hub: HubId) {
  if (!router) return
  if (hub === state.current) {
    const stack = state.stacks[hub]
    if (stack.length > 1) {
      stack.splice(1, stack.length - 1)
      driving = 'pop'
      router.replace(top(hub))
    }
    return
  }
  if (state.hubHistory[state.hubHistory.length - 1] !== state.current) state.hubHistory.push(state.current)
  state.current = hub
  driving = 'switch'
  router.push(top(hub))
}

/** True when back has somewhere to go other than Home's root. */
export function compactCanGoBack(): boolean {
  return state.stacks[state.current].length > 1 || state.hubHistory.length > 0 || state.current !== 'home'
}

export function installCompactNav(r: Router) {
  if (router) return
  router = r
  r.afterEach((to) => {
    const replaced = !!(window.history.state as { replaced?: boolean } | null)?.replaced
    record(to.fullPath, to.name, replaced)
  })
  const current = r.currentRoute.value
  if (current?.name) record(current.fullPath, current.name, true)
}

export function useCompactNav() {
  return { state: readonly(state), back: compactBack, goToHub: compactGoToHub, canGoBack: compactCanGoBack }
}
