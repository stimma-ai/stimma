import { ref } from 'vue'
import { useWebSocket } from './useWebSocket'

// Singleton: which chats have an agent loop running right now. Single source
// for the sidebar/landing chat spinners. Unlike the raw agent_started /
// agent_stopped events, this primes from GET /api/chats/agent/running on
// startup (catching runs already in flight) and re-primes after a WebSocket
// reconnect; on disconnect the set clears so spinners don't stick for runs
// whose stop event we'll never see.

export type AgentRunEndListener = (chatId: number, reason: string) => void

const generatingChatIds = ref<Set<number>>(new Set())

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

function emitRunEnd(chatId: number, reason: string) {
  for (const cb of runEndListeners) {
    try { cb(chatId, reason) } catch {}
  }
}

async function prime() {
  const seq = ++primeSeq
  try {
    const res = await fetch('/api/chats/agent/running')
    if (!res.ok) return
    const data = await res.json()
    if (seq !== primeSeq) return
    const fresh = new Set<number>(
      (Array.isArray(data?.chat_ids) ? data.chat_ids : []).filter((id: any) => typeof id === 'number')
    )
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

  on('websocket_disconnected', () => {
    for (const id of generatingChatIds.value) lostWhileDisconnected.add(id)
    replaceSet(new Set())
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

  function onAgentRunEnd(cb: AgentRunEndListener) {
    runEndListeners.push(cb)
  }

  return { generatingChatIds, isChatGenerating, onAgentRunEnd }
}
