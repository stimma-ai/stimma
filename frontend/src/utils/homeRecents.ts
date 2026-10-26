import { scopeParam } from './scopedList'

/**
 * Home's "Jump back in" cards, chosen by the server: the newest boards,
 * flows, and chats in a scope, each with only the artwork its card draws.
 * The response size follows the number of cards, not the size of the boards
 * and flows behind them.
 */
export interface HomeMediaRef {
  media_id: number
  file_hash?: string | null
}

export interface HomeRecents {
  items: Array<
    | { type: 'board'; board: { id: number; preview_items: any[]; [key: string]: any } }
    | { type: 'flow'; flow: { id: number; preview_media: HomeMediaRef[]; [key: string]: any } }
    | { type: 'chat'; chat: { id: number; [key: string]: any } }
  >
  /** The scope has boards, flows, or chats, even if none is worth a card. */
  has_entities: boolean
}

/**
 * Read the cards for `projectId` (null = top level). Resolves null only when
 * the server predates this read (404/405), so the caller can use the general
 * lists; any other failure, including a malformed reply, throws.
 */
export async function fetchHomeRecents(
  projectId: number | null | undefined,
  { limit, signal }: { limit: number; signal?: AbortSignal },
): Promise<HomeRecents | null> {
  const params = new URLSearchParams({ project_id: scopeParam(projectId), limit: String(limit) })
  const response = await fetch(`/api/home/recents?${params}`, { signal })
  if (response.status === 404 || response.status === 405) return null
  if (!response.ok) throw new Error(`Request failed: ${response.status}`)
  const data = await response.json()
  // A server that has this read but answers oddly is failing, not old.
  if (!data || !Array.isArray(data.items)) throw new Error('Malformed recents response')
  return data
}
