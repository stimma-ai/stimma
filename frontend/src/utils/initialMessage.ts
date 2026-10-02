/**
 * Home hands a chat its first message through the route query. ChatView reads
 * it from both onMounted (after the transcript loads) and onActivated (KeepAlive
 * wake-up), and on a first mount both run before the query is cleared. The
 * consumer hands out each initial message exactly once; it re-arms only after
 * the query has been cleared.
 */
export interface InitialMessage {
  text: string
  attachmentIds: number[]
}

function first(value: unknown): string | null {
  const raw = Array.isArray(value) ? value[0] : value
  return typeof raw === 'string' && raw !== '' ? raw : null
}

export function createInitialMessageConsumer() {
  let consumed: string | null = null
  return function consume(chatId: unknown, query: Record<string, unknown>): InitialMessage | null {
    const text = first(query.initialMessage)
    if (!text) { consumed = null; return null }
    const attachments = first(query.attachmentIds) ?? ''
    const key = `${String(chatId)}\u0000${text}\u0000${attachments}`
    if (key === consumed) return null
    consumed = key
    const attachmentIds = attachments.split(',').map(id => parseInt(id, 10)).filter(id => !Number.isNaN(id))
    return { text, attachmentIds }
  }
}
