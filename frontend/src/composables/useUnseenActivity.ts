import { ref, watch } from 'vue'
import { useWebSocket } from './useWebSocket'
import { useWorkspaceTabs, type WorkspaceTab } from './useWorkspaceTabs'
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
  if (route.name === 'tool' && route.params.fullToolId) {
    const raw = route.query.project_id
    const projectId = raw ? parseInt(String(Array.isArray(raw) ? raw[0] : raw), 10) : null
    const suffix = projectId && Number.isFinite(projectId) ? `:project:${projectId}` : ''
    return `tool:${route.params.fullToolId}${suffix}`
  }
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

function matchingToolTabs(instanceId: string): WorkspaceTab[] {
  const { tabs } = useWorkspaceTabs()
  return tabs.value.filter(t =>
    t.type === 'tool' && instanceMatchesTool(instanceId, t.entityId, t.projectId ?? null)
  )
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
    for (const tab of matchingToolTabs(instanceId)) {
      const run = toolRuns.get(tab.id)
      if (!run || run.count <= 0) {
        // Fresh batch: previous dot is superseded by the live spinner.
        toolRuns.set(tab.id, { count: 1, sawFailure: false })
        clearUnseen(tab.id)
      } else {
        run.count++
      }
    }
  })

  const onJobDone = (failed: boolean) => (data: any) => {
    const instanceId = instanceIdOf(data)
    if (!instanceId) return
    for (const tab of matchingToolTabs(instanceId)) {
      const run = toolRuns.get(tab.id)
      if (!run || run.count <= 0) continue
      run.count--
      if (failed) run.sawFailure = true
      if (run.count === 0) {
        toolRuns.delete(tab.id)
        setUnseen(tab.id, run.sawFailure ? 'error' : 'done')
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

  on('agent_stopped', (data: any) => {
    if (data?.chat_id == null) return
    // already_running is a no-op echo for a start that never happened.
    if (data.reason === 'already_running') return
    setUnseen(`chat:${data.chat_id}`, data.reason === 'error' ? 'error' : 'done')
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

  // Visiting a tab clears its dot.
  watch(router.currentRoute, clearActiveIfSeen)
}

export function useUnseenActivity() {
  init()

  function unseenKindFor(tabId: string): UnseenKind | null {
    return unseen.value.get(tabId) ?? null
  }

  return { unseenKindFor, clearUnseen }
}
