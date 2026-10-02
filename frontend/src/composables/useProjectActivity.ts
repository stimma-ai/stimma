import { computed, ref } from 'vue'
import { useWebSocket } from './useWebSocket'
import { useGenerationStatus } from './useGenerationStatus'
import { busyContexts, busyElsewhere, parseActivity, type ActivityEntry, type ContextKey } from '../utils/projectActivity'

// Singleton: which working contexts have work running (tool jobs, chat/agent
// runs, flow runs). Primed from GET /api/projects/activity, kept current by
// the `project_activity` broadcast, re-primed after a reconnect, and merged
// with this window's own tool work so a just-submitted run shows at once.
const serverActivity = ref<ActivityEntry[]>([])
let initialized = false
let primeSeq = 0

async function prime() {
  const seq = ++primeSeq
  try {
    const res = await fetch('/api/projects/activity')
    if (!res.ok || seq !== primeSeq) return
    serverActivity.value = parseActivity(await res.json())
  } catch { /* Keep the last snapshot; the broadcast still updates it. */ }
}

function init() {
  if (initialized) return
  initialized = true
  const { on } = useWebSocket()
  on('project_activity', (data: unknown) => {
    primeSeq++
    serverActivity.value = parseActivity(data)
  })
  on('websocket_disconnected', () => { serverActivity.value = [] })
  on('websocket_reconnected', () => { void prime() })
  void prime()
}

export function useProjectActivity() {
  init()
  const { activeJobsByInstanceId, pendingWorkByInstanceId, foreverModeByInstanceId } = useGenerationStatus()
  const busy = computed(() => busyContexts(
    serverActivity.value,
    activeJobsByInstanceId.value,
    pendingWorkByInstanceId.value,
    foreverModeByInstanceId.value,
  ))
  return {
    /** Work is running in this context (`null` = top level). */
    isBusy: (context: ContextKey) => busy.value.has(context),
    /** Work is running anywhere other than `current`. */
    isBusyElsewhere: (current: ContextKey) => busyElsewhere(busy.value, current),
  }
}
