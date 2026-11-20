import { mobileRecoveryEnabled } from './useMobileRecovery.js'
import { ref } from 'vue'
import { useWebSocket } from './useWebSocket'

// Singleton: which chats have an agent loop running right now. Single source
// for the sidebar/landing chat spinners. Unlike the raw agent_started /
// agent_stopped events, this primes from GET /api/chats/agent/running on
// startup (catching runs already in flight) and re-primes after a WebSocket
// reconnect; on disconnect the set clears so spinners don't stick for runs
// whose stop event we'll never see.
//
// A chat also counts as working while a background task its agent started is
// still running (backend agent/v2/background.py): the turn has ended, so
// agent_stopped has fired, but generations go on. isChatWorking covers both;
// isChatGenerating stays turn-only for logic that waits on the turn itself.

export type AgentRunEndListener = (chatId: number, reason: string) => void

const generatingChatIds = ref<Set<number>>(new Set())
// chat id -> ids of its background tasks still running.
const backgroundTasksByChat = ref<Map<number, Set<string>>>(new Map())
type BackgroundTaskState = { chat_id: number, task_id: string, state: string }
// Task events that arrive while a prime is in flight; replayed onto its
// snapshot, which may predate them.
let backgroundEventsDuringPrime: BackgroundTaskState[] | null = null

const runEndListeners: AgentRunEndListener[] = []
// Chats that were running when the socket dropped: if the re-prime says
// they're no longer running, the run ended (or died) while we weren't
// listening — report that end to listeners since agent_stopped was lost.
const lostWhileDisconnected = new Set<number>()
let initialized = false
let primeSeq = 0

function replaceSet(next: Set<number>) {
  generatingChatIds.value = next
}

function applyBackgroundTask(tasks: Map<number, Set<string>>, e: BackgroundTaskState) {
  const ids = new Set(tasks.get(e.chat_id) ?? [])
  if (e.state === 'running') ids.add(e.task_id)
  else ids.delete(e.task_id)
  if (ids.size) tasks.set(e.chat_id, ids)
  else tasks.delete(e.chat_id)
}

function emitRunEnd(chatId: number, reason: string) {
  for (const cb of runEndListeners) {
    try { cb(chatId, reason) } catch {}
  }
}

async function prime() {
  const seq = ++primeSeq
  backgroundEventsDuringPrime = []
  try {
    const res = await fetch('/api/chats/agent/running')
    if (!res.ok) return
    const data = await res.json()
    if (seq !== primeSeq) return
    const fresh = new Set<number>(
      (Array.isArray(data?.chat_ids) ? data.chat_ids : []).filter((id: any) => typeof id === 'number')
    )
    const freshBackground = new Map<number, Set<string>>()
    for (const entry of Array.isArray(data?.background) ? data.background : []) {
      const ids = (Array.isArray(entry?.task_ids) ? entry.task_ids : []).filter((t: any) => typeof t === 'string')
      if (typeof entry?.chat_id === 'number' && ids.length) freshBackground.set(entry.chat_id, new Set(ids))
    }
    for (const e of backgroundEventsDuringPrime ?? []) applyBackgroundTask(freshBackground, e)
    backgroundEventsDuringPrime = null
    backgroundTasksByChat.value = freshBackground
    for (const id of [...generatingChatIds.value, ...lostWhileDisconnected]) {
      if (!fresh.has(id)) emitRunEnd(id, 'completed')
    }
    lostWhileDisconnected.clear()
    replaceSet(fresh)
  } catch {}
}

function init() {
  if (initialized) return
  initialized = true

  const { on } = useWebSocket()

  on('agent_started', (data: any) => {
    if (data?.chat_id == null) return
    generatingChatIds.value.add(data.chat_id)
    replaceSet(new Set(generatingChatIds.value))
  })

  on('agent_stopped', (data: any) => {
    if (data?.chat_id == null) return
    generatingChatIds.value.delete(data.chat_id)
    replaceSet(new Set(generatingChatIds.value))
    // already_running is a no-op echo for a start that never happened.
    if (data.reason !== 'already_running') emitRunEnd(data.chat_id, data.reason ?? 'completed')
  })

  // Sent to every client on task start and end (the detailed
  // background_task_* events only reach views of that chat).
  on('background_task_state', (data: any) => {
    if (typeof data?.chat_id !== 'number' || typeof data?.task_id !== 'string') return
    const e: BackgroundTaskState = { chat_id: data.chat_id, task_id: data.task_id, state: String(data.state) }
    backgroundEventsDuringPrime?.push(e)
    const next = new Map(backgroundTasksByChat.value)
    applyBackgroundTask(next, e)
    backgroundTasksByChat.value = next
  })

  on('websocket_disconnected', () => {
    for (const id of generatingChatIds.value) lostWhileDisconnected.add(id)
    // A prime still in flight answers for a connection that is gone; the
    // reconnect primes again.
    primeSeq++
    backgroundEventsDuringPrime = null
    if (!mobileRecoveryEnabled) {
      replaceSet(new Set())
      backgroundTasksByChat.value = new Map()
    }
  })

  on('websocket_reconnected', () => {
    prime()
  })

  prime()
}

export function useAgentActivity() {
  init()

  function isChatGenerating(chatId: number | string): boolean {
    const id = typeof chatId === 'string' ? parseInt(chatId, 10) : chatId
    return generatingChatIds.value.has(id)
  }

  // The chat's turn is running, or work it started is still going.
  function isChatWorking(chatId: number | string): boolean {
    const id = typeof chatId === 'string' ? parseInt(chatId, 10) : chatId
    return generatingChatIds.value.has(id) || backgroundTasksByChat.value.has(id)
  }

  function onAgentRunEnd(cb: AgentRunEndListener) {
    runEndListeners.push(cb)
  }

  return { generatingChatIds, isChatGenerating, isChatWorking, onAgentRunEnd }
}
