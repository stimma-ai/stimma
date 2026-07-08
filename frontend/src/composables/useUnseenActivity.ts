import { ref } from 'vue'
import { useWebSocket } from './useWebSocket'
import { useAgentActivity } from './useAgentActivity'
import { useWorkspaceTabs, toolRouteTabId } from './useWorkspaceTabs'
import { instanceMatchesTool } from './useGenerationStatus'
import router from '../router'

// Singleton: "finished while you weren't looking" markers per workspace tab.
// When a sidebar spinner stops (tool jobs drained, agent turn ended) and the
// tab isn't the focused foreground screen, the tab gets a dot — blue for a
// normal finish, red when something failed — cleared the next time the user
// actually views the tab. In-memory only: dots do not survive an app restart.
// Flows are excluded; FlowStatusPill's own status dot already covers them.

export type UnseenKind = 'done' | 'error'

const unseen = ref<Map<string, UnseenKind>>(new Map())

// Per-tool-tab in-flight job tracking (keyed by tab.id). Counted here
// independently of useGenerationStatus so the falling edge and the
// saw-failure flag don't depend on WS handler registration order.
const toolRuns = new Map<string, { count: number, sawFailure: boolean }>()

const windowFocused = ref(typeof document !== 'undefined' ? document.hasFocus() : true)

let initialized = false

function activeTabKey(): string | null {
  const route = router.currentRoute.value
  // Dots are keyed by workspace tab id (tool:{id}[:project:{p}]:i:{K}), so the
  // "am I looking at this tab" key must include the instance suffix too —
  // toolRouteTabId is the same builder the sidebar uses for tab.id.
  if (route.name === 'tool') return toolRouteTabId(route)
  if (route.name === 'chat' && route.params.id) return `chat:${route.params.id}`
  return null
}

function setUnseen(tabId: string, kind: UnseenKind) {
  // The tab the user is actively looking at never gets a dot; a tab that is
  // active but in an unfocused window does (matches how you juggle windows).
  if (windowFocused.value && activeTabKey() === tabId) return
  // Error sticks until seen — a later clean finish doesn't downgrade it.
  if (unseen.value.get(tabId) === 'error') return
  unseen.value.set(tabId, kind)
  unseen.value = new Map(unseen.value)
}

function clearUnseen(tabId: string | null) {
  if (!tabId || !unseen.value.has(tabId)) return
  unseen.value.delete(tabId)
  unseen.value = new Map(unseen.value)
}

function clearActiveIfSeen() {
  if (windowFocused.value) clearUnseen(activeTabKey())
}

function matchingToolTabIds(instanceId: string): string[] {
  const { tabs } = useWorkspaceTabs()
  return tabs.value
    .filter(t => t.type === 'tool' && instanceMatchesTool(instanceId, t.entityId, t.projectId ?? null))
    .map(t => t.id)
}

function init() {
  if (initialized) return
  initialized = true

  const { on } = useWebSocket()

  const instanceIdOf = (data: any): string | null => {
    const id = data?.job?.generator_instance_id || data?.generator_instance_id
    return id && id.startsWith('tool-') ? id : null
  }

  on('generation_job_queued', (data: any) => {
    const instanceId = instanceIdOf(data)
    if (!instanceId) return
    for (const tabId of matchingToolTabIds(instanceId)) {
      const run = toolRuns.get(tabId)
      if (!run || run.count <= 0) {
        // Fresh batch: previous dot is superseded by the live spinner.
        toolRuns.set(tabId, { count: 1, sawFailure: false })
        clearUnseen(tabId)
      } else {
        run.count++
      }
    }
  })

  const onJobDone = (failed: boolean) => (data: any) => {
    const instanceId = instanceIdOf(data)
    if (!instanceId) return
    for (const tabId of matchingToolTabIds(instanceId)) {
      const run = toolRuns.get(tabId)
      if (!run || run.count <= 0) continue
      run.count--
      if (failed) run.sawFailure = true
      if (run.count === 0) {
        toolRuns.delete(tabId)
        setUnseen(tabId, run.sawFailure ? 'error' : 'done')
      }
    }
  }

  on('generation_job_completed', onJobDone(false))
  on('generation_job_failed', onJobDone(true))
  // User-initiated cancel still ends the run, but isn't a failure.
  on('generation_job_cancelled', onJobDone(false))

  on('agent_started', (data: any) => {
    if (data?.chat_id != null) clearUnseen(`chat:${data.chat_id}`)
  })

  // Covers live agent_stopped events AND runs discovered to have ended
  // while the socket was down (reported by the reconnect re-prime).
  useAgentActivity().onAgentRunEnd((chatId, reason) => {
    setUnseen(`chat:${chatId}`, reason === 'error' ? 'error' : 'done')
  })

  // Counts are meaningless across a disconnect — jobs may have died or
  // finished unobserved. Reset without marking so reconnects don't spray
  // false dots across every tool that had been spinning.
  on('websocket_disconnected', () => {
    toolRuns.clear()
  })

  if (typeof window !== 'undefined') {
    window.addEventListener('focus', () => {
      windowFocused.value = true
      clearActiveIfSeen()
    })
    window.addEventListener('blur', () => { windowFocused.value = false })
  }

  // Visiting a tab clears its dot. Registered as a router hook, NOT a
  // watch(): init() usually runs first from NavigationSidebar's setup, and a
  // watch would bind to that component's effect scope — unmounting the
  // sidebar (lock screen, no-chrome routes) would silently kill it, leaving
  // dots that never clear. afterEach is scope-independent.
  router.afterEach(() => clearActiveIfSeen())
}

export function useUnseenActivity() {
  init()

  function unseenKindFor(tabId: string): UnseenKind | null {
    return unseen.value.get(tabId) ?? null
  }

  return { unseenKindFor, clearUnseen }
}
