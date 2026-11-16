/**
 * Suggest, the prompt editor's recommendations in Fluent.
 *
 * It asks, for the prompt as it stands, which written phrases are worth changing (`phrases`:
 * Detail or Any, with their kind) and which slots it could add (`adds`: the camera, a face).
 * It runs a moment after typing stops and when the box loses focus, remembers each answer by
 * the exact prompt text, and drops answers that come back for text that has since changed.
 * The answer's shapes and checks are in utils/promptSuggestions.ts. A failure changes nothing.
 */
import { ref, watch, onUnmounted, type Ref } from 'vue'
import axios from 'axios'
import { getApiBase } from '../apiConfig'
import { cleanSuggestions, type Suggestions } from '../utils/promptSuggestions'

export type { PhraseWay, SuggestedAdd, SuggestedPhrase, Suggestions } from '../utils/promptSuggestions'
export { insertAdd, phraseLabel, NO_SUGGESTIONS } from '../utils/promptSuggestions'

/** How long after the last keystroke Suggest runs. */
const SUGGEST_DELAY_MS = 900

export interface PromptSuggestionsOptions {
  /** The prompt as typed. */
  prompt: Ref<string> | (() => string)
  /** Whether Suggest runs at all (Fluent, not Direct or Raw). */
  active: Ref<boolean> | (() => boolean)
  /** Extra request fields: `project_id`, whose chat model answers. */
  context?: () => Record<string, unknown> | undefined
  /** What is showing now: Suggest keeps those that still fit, so chips stay put. */
  previous?: () => Suggestions
}

const read = <T>(v: Ref<T> | (() => T)) => (typeof v === 'function' ? (v as () => T)() : v.value)

export function usePromptSuggestions(o: PromptSuggestionsOptions) {
  /** The latest answer, and the exact text it is for. */
  const answer = ref<{ text: string; suggestions: Suggestions } | null>(null)
  /** The text an answer is on its way for (waiting out the pause, or asked): chips show a
      placeholder meanwhile. */
  const pending = ref<string | null>(null)

  const cache = new Map<string, Suggestions>()
  const inFlight = new Map<string, Promise<Suggestions | null>>()
  let timer: ReturnType<typeof setTimeout> | null = null

  const body = (extra: Record<string, unknown>) => ({ ...(o.context?.() || {}), ...extra })

  function fetchFor(text: string): Promise<Suggestions | null> {
    const known = cache.get(text)
    if (known) return Promise.resolve(known)
    let p = inFlight.get(text)
    if (!p) {
      const prev = o.previous?.()
      const previous = prev ? { phrases: prev.phrases.map(p => ({ text: p.text, way: p.way, kind: p.kind, mode: p.mode })), adds: prev.adds.map(a => a.key) } : undefined
      p = axios.post(`${getApiBase()}/prompt-programs/suggest`, body({ prompt: text, previous }))
        .then(({ data }) => { const s = cleanSuggestions(data); cache.set(text, s); return s })
        .catch(() => null)
        .finally(() => { inFlight.delete(text) })
      inFlight.set(text, p)
    }
    return p
  }

  /** Ask now for the prompt as it stands. */
  async function suggestNow() {
    if (timer) { clearTimeout(timer); timer = null }
    const text = read(o.prompt)
    if (!read(o.active) || !text.trim()) { pending.value = null; return }
    pending.value = text
    const s = await fetchFor(text)
    if (pending.value === text) pending.value = null
    // A late answer for text that has changed since is dropped (it stays cached).
    if (!s || text !== read(o.prompt) || !read(o.active)) return
    answer.value = { text, suggestions: s }
  }

  function schedule() {
    if (timer) clearTimeout(timer)
    timer = null
    const text = read(o.prompt)
    if (!read(o.active) || !text.trim()) { pending.value = null; return }
    const known = cache.get(text)
    if (known) { pending.value = null; answer.value = { text, suggestions: known }; return }
    pending.value = text
    timer = setTimeout(() => { void suggestNow() }, SUGGEST_DELAY_MS)
  }

  /** The kind of the words at [start, end) of `text` ("hairstyle" for "short bob"), for Any on
      words Suggest didn't name; "" when it can't be said. */
  const kinds = new Map<string, Promise<string>>()
  function kindOf(text: string, start: number, end: number): Promise<string> {
    const key = `${start}:${end}:${text}`
    let p = kinds.get(key)
    if (!p) {
      p = axios.post(`${getApiBase()}/prompt-programs/suggest-kind`, body({ prompt: text, start, end }))
        .then(({ data }) => (typeof data?.kind === 'string' ? data.kind.trim() : ''))
        .catch(() => { kinds.delete(key); return '' })
      kinds.set(key, p)
    }
    return p
  }

  watch(() => [read(o.prompt), read(o.active)] as const, schedule, { immediate: true })

  onUnmounted(() => { if (timer) clearTimeout(timer) })

  return { answer, pending, suggestNow, kindOf }
}
