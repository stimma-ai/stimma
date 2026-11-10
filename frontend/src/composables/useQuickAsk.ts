/**
 * Quick asks: a prompt aimed at selected assets starts a real chat.
 *
 * The chat is created in the project you're working in (none at the top
 * level) and keeps it, docks as a row, and sends the prompt with the
 * selection attached once its view is up. It's an ordinary chat from then
 * on: listed in Chats, opened full size or small like any other.
 *
 * Recent prompts are remembered per profile with what they were aimed at
 * (clips or stills), so the ones used on this kind of thing come first. They
 * never show on their own: typing completes from them, and the prompt's clock
 * lists them.
 */
import { ref } from 'vue'
import { makeProfileKey } from '../utils/storageKeys'
import { syncedStorage } from '../utils/workspaceStore'
import { getCurrentProfileId } from './useProfile'
import { useChatDock } from './useChatDock'
import { addToast } from './useToasts'

export type AskKind = 'video' | 'image'

interface Recent { text: string; kind: AskKind }
const MAX_RECENTS = 12

const recentKey = () => makeProfileKey('quick_ask', 'recent')
const recents = ref<Recent[]>([])
let recentsLoadedFor: string | null = null

function loadRecents() {
  const key = recentKey()
  if (recentsLoadedFor === key) return
  recentsLoadedFor = key
  try {
    const raw = JSON.parse(syncedStorage.getItem(key) || '{}')
    recents.value = Array.isArray(raw.items)
      ? raw.items.filter((r: any) => typeof r?.text === 'string' && r.text.trim()).map((r: any) => ({ text: r.text, kind: r.kind === 'video' ? 'video' : 'image' }))
      : []
  } catch { recents.value = [] }
}

function remember(text: string, kind: AskKind) {
  loadRecents()
  const t = text.trim()
  if (!t) return
  recents.value = [{ text: t, kind }, ...recents.value.filter(r => r.text.toLowerCase() !== t.toLowerCase())].slice(0, MAX_RECENTS)
  syncedStorage.setItem(recentKey(), JSON.stringify({ items: recents.value }))
}

/** Recent prompts, the ones used on this kind of selection first. */
export function recentPrompts(kind: AskKind): string[] {
  loadRecents()
  const same = recents.value.filter(r => r.kind === kind)
  const other = recents.value.filter(r => r.kind !== kind)
  return [...same, ...other].map(r => r.text)
}

/** The rest of a recent prompt that starts with what's typed, for inline completion. */
export function completionFor(typed: string, kind: AskKind): string {
  const q = typed.toLowerCase()
  if (q.trim().length < 2) return ''
  const hit = recentPrompts(kind).find(r => r.toLowerCase().startsWith(q) && r.length > typed.length)
  return hit ? hit.slice(typed.length) : ''
}

/** A few things worth asking about this kind of selection. */
export function ideasFor(kind: AskKind, count: number): string[] {
  if (kind === 'video') {
    return ['Regenerate at a higher resolution', 'Upscale', 'Write captions', count > 1 ? 'Which one is strongest?' : null].filter(Boolean) as string[]
  }
  if (count === 1) return ['Upscale 2×', 'Make 4 more like this', 'Remove the background', 'Crop to 16:9', 'Describe it']
  return ['Upscale 2×', 'Make 2 more like each', 'Which one is strongest?', 'Write captions']
}

/** Type-ahead match: the label contains what's typed. */
export function matchesPrompt(label: string, query: string): boolean {
  const q = query.trim().toLowerCase()
  return !q || label.toLowerCase().includes(q)
}

/**
 * Start a chat about `mediaIds` with `prompt`. Resolves to the new chat's id,
 * or null if it couldn't be created (the person is told).
 */
export async function startQuickAsk(options: {
  prompt: string
  mediaIds: number[]
  projectId: number | null
  kind: AskKind
  open?: boolean
}): Promise<number | null> {
  const prompt = options.prompt.trim()
  if (!prompt || options.mediaIds.length === 0) return null
  remember(prompt, options.kind)
  try {
    const response = await fetch('/api/chats', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Profile-ID': getCurrentProfileId() },
      body: JSON.stringify({ name: null, project_id: options.projectId ?? null }),
    })
    if (!response.ok) throw new Error(`create chat ${response.status}`)
    const chat = await response.json()
    useChatDock().dock(chat.id, { open: !!options.open, initial: { text: prompt, mediaIds: options.mediaIds } })
    return chat.id
  } catch (error) {
    console.error('Failed to start chat:', error)
    addToast("Couldn't start a chat", 'error')
    return null
  }
}

/** Test hook. */
export function _resetQuickAskForTests() {
  recents.value = []
  recentsLoadedFor = null
}
