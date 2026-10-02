/**
 * Where work is running, by working context. `null` is the top level
 * (Everything). The server reports jobs, chat runs and flow runs per project;
 * this window also knows about tool work it started that the server may not
 * have reported yet (a submit in flight, forever mode between submissions).
 */
export interface ActivityEntry {
  project_id: number | null
  running_jobs?: number
  running_chats?: number
  running_flows?: number
}

export type ContextKey = number | null

/** Accepts `{activity: [...]}` (REST and websocket) or a bare list. */
export function parseActivity(payload: unknown): ActivityEntry[] {
  const list = Array.isArray(payload) ? payload : (payload as any)?.activity
  if (!Array.isArray(list)) return []
  return list.filter(e => e && typeof e === 'object' && (e.project_id === null || Number.isSafeInteger(e.project_id)))
}

/** Tool generator instances in a project carry a `__project_<id>` segment. */
export function projectIdFromInstanceId(instanceId: string): ContextKey {
  const match = /__project_(\d+)/.exec(instanceId)
  return match ? Number(match[1]) : null
}

function entryCount(e: ActivityEntry) {
  return (e.running_jobs || 0) + (e.running_chats || 0) + (e.running_flows || 0)
}

/**
 * Merges the server snapshot with this window's tool instances (any map of
 * instance id to a truthy count or flag) into the set of busy contexts.
 */
export function busyContexts(server: ActivityEntry[], ...localInstances: Array<Record<string, unknown>>): Set<ContextKey> {
  const busy = new Set<ContextKey>()
  for (const entry of server) if (entryCount(entry) > 0) busy.add(entry.project_id ?? null)
  for (const instances of localInstances) {
    for (const [instanceId, value] of Object.entries(instances)) {
      if (!value || !instanceId.startsWith('tool-')) continue
      busy.add(projectIdFromInstanceId(instanceId))
    }
  }
  return busy
}

/** True when anything runs in a context other than the current one. */
export function busyElsewhere(busy: Set<ContextKey>, current: ContextKey): boolean {
  for (const key of busy) if (key !== current) return true
  return false
}
