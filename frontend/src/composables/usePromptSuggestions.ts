/**
 * Suggest and Add, the prompt editor's helpers for making slots in Fluent.
 *
 * Suggest asks, for the prompt as it stands, which written phrases could vary (`vary`) and
 * which things the prompt doesn't mention would be worth adding as a slot (`adds`). It runs
 * a moment after typing stops and when the box loses focus, remembers each answer by the
 * exact prompt text, and drops answers that come back for text that has since changed.
 *
 * For a photo, `adds` also holds the photography the prompt lacks (camera, light). Each of
 * those carries the slot kind it is read as and the lists it draws from, so the editor can
 * leave it out once a slot of the prompt is read as that (`slotCovers`, in
 * utils/promptSuggestions.ts with the answer's shapes).
 *
 * Add has a model write one of those things into the prompt as a slot. Both fail quietly:
 * nothing changes.
 */
import { ref, watch, onUnmounted, type Ref } from 'vue'
import axios from 'axios'
import { getApiBase } from '../apiConfig'
import { cleanSuggestions, type Suggestions } from '../utils/promptSuggestions'

export type { ReadSlots, SuggestedAdd, SuggestedPhrase, Suggestions } from '../utils/promptSuggestions'
export { slotCovers } from '../utils/promptSuggestions'

export interface AddResult { prompt: string; slot: { from: number; to: number } }

/** How long after the last keystroke Suggest runs. */
export const SUGGEST_DELAY_MS = 900

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
  /** The add being written (its name), while it runs. */
  const adding = ref<string | null>(null)

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

  /** Write `name` into the prompt as a slot. Null when it failed or the prompt moved on. */
  async function add(name: string): Promise<AddResult | null> {
    if (adding.value) return null
    const text = read(o.prompt)
    adding.value = name
    try {
      const { data } = await axios.post(`${getApiBase()}/prompt-programs/add`, body({ prompt: text, name }))
      if (typeof data?.prompt !== 'string' || !Number.isInteger(data?.slot?.from) || !Number.isInteger(data?.slot?.to)) return null
      if (read(o.prompt) !== text || !read(o.active)) return null
      return { prompt: data.prompt, slot: { from: data.slot.from, to: data.slot.to } }
    } catch {
      return null
    } finally {
      adding.value = null
    }
  }

  onUnmounted(() => { if (timer) clearTimeout(timer) })

  return { answer, adding, suggestNow, add }
}
