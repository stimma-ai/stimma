/**
 * Suggest, the prompt editor's recommendations in Fluent.
 *
 * It asks, for the prompt as it stands, which written phrases could vary (`vary`), a few
 * complete ways the picture could be shot or made (`looks`) and things it could add (`adds`).
 * It runs a moment after typing stops and when the box loses focus, remembers each answer by
 * the exact prompt text, and drops answers that come back for text that has since changed.
 * The answer's shapes and checks are in utils/promptSuggestions.ts. A failure changes nothing.
 */
import { ref, watch, onUnmounted, type Ref } from 'vue'
import axios from 'axios'
import { getApiBase } from '../apiConfig'
import { cleanSuggestions, type Suggestions } from '../utils/promptSuggestions'

export type { SuggestedPhrase, SuggestedWords, Suggestions } from '../utils/promptSuggestions'
export { appendWords, shownWords } from '../utils/promptSuggestions'

/** How long after the last keystroke Suggest runs. */
const SUGGEST_DELAY_MS = 900

export interface PromptSuggestionsOptions {
  /** The prompt as typed. */
  prompt: Ref<string> | (() => string)
  /** Whether Suggest runs at all (Fluent, not Direct or Raw). */
  active: Ref<boolean> | (() => boolean)
  /** Extra request fields: `project_id`, whose chat model answers. */
  context?: () => Record<string, unknown> | undefined
}

const read = <T>(v: Ref<T> | (() => T)) => (typeof v === 'function' ? (v as () => T)() : v.value)

export function usePromptSuggestions(o: PromptSuggestionsOptions) {
  /** The latest answer, and the exact text it is for. */
  const answer = ref<{ text: string; suggestions: Suggestions } | null>(null)

  const cache = new Map<string, Suggestions>()
  const inFlight = new Map<string, Promise<Suggestions | null>>()
  let timer: ReturnType<typeof setTimeout> | null = null

  const body = (extra: Record<string, unknown>) => ({ ...(o.context?.() || {}), ...extra })

  function fetchFor(text: string): Promise<Suggestions | null> {
    const known = cache.get(text)
    if (known) return Promise.resolve(known)
    let p = inFlight.get(text)
    if (!p) {
      p = axios.post(`${getApiBase()}/prompt-programs/suggest`, body({ prompt: text }))
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
    if (!read(o.active) || !text.trim()) return
    const s = await fetchFor(text)
    // A late answer for text that has changed since is dropped (it stays cached).
    if (!s || text !== read(o.prompt) || !read(o.active)) return
    answer.value = { text, suggestions: s }
  }

  function schedule() {
    if (timer) clearTimeout(timer)
    timer = null
    const text = read(o.prompt)
    if (!read(o.active) || !text.trim()) return
    const known = cache.get(text)
    if (known) { answer.value = { text, suggestions: known }; return }
    timer = setTimeout(() => { void suggestNow() }, SUGGEST_DELAY_MS)
  }

  watch(() => [read(o.prompt), read(o.active)] as const, schedule, { immediate: true })

  onUnmounted(() => { if (timer) clearTimeout(timer) })

  return { answer, suggestNow }
}
