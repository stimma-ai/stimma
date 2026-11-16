/**
 * The shapes of Fluent's Suggest answer, and the pure checks on them (the composable that
 * asks is composables/usePromptSuggestions.ts).
 *
 * phrases  words the user wrote worth changing from picture to picture: underlined in the
 *          text, and a chip. Detail keeps the words and wraps them in brackets ("Detail dog");
 *          Any writes their kind in their place, in brackets ("Any hairstyle").
 * adds     something good prompts state and this one leaves to the image model's habits,
 *          written in as a new slot ("+ Camera", "+ Face").
 */

/** Detail: every picture keeps the words, each a specific one of them. Any: the words become
    one of their kind and the others come in. */
export type PhraseWay = 'detail' | 'any'

/** A phrase worth changing. `kind` names what it is ("hairstyle" for "short bob"), "" when
    unknown; `mode` 'one' when it names one specific thing (the Eiffel Tower, seen new ways). */
export interface SuggestedPhrase { from: number; to: number; text: string; kind: string; way: PhraseWay; mode: 'one' | 'kind' }
/** A slot to write in: `text` (holding the slot) goes in at `at`, an offset into the prompt the
    answer is for. */
export interface SuggestedAdd { key: string; label: string; at: number; text: string }
/** `loading`: an answer is on its way for the text as it stands. */
export interface Suggestions { phrases: SuggestedPhrase[]; adds: SuggestedAdd[]; loading?: boolean }

export const NO_SUGGESTIONS: Suggestions = { phrases: [], adds: [] }

/** A /suggest answer, keeping only well-formed parts. */
export function cleanSuggestions(data: any): Suggestions {
  const phrases = Array.isArray(data?.phrases) ? data.phrases
    .filter((p: any) => Number.isInteger(p?.from) && Number.isInteger(p?.to) && typeof p?.text === 'string')
    .map((p: any): SuggestedPhrase => {
      const kind = typeof p.kind === 'string' ? p.kind.trim() : ''
      return { from: p.from, to: p.to, text: p.text, kind,
        way: p.way === 'any' && kind ? 'any' : 'detail', mode: p.mode === 'one' ? 'one' : 'kind' }
    }) : []
  const adds = Array.isArray(data?.adds) ? data.adds
    .filter((a: any) => typeof a?.key === 'string' && typeof a?.text === 'string' && a.text.includes('<') && Number.isInteger(a?.at))
    .map((a: any): SuggestedAdd => ({ key: a.key, label: typeof a.label === 'string' && a.label.trim() ? a.label : a.key, at: a.at, text: a.text })) : []
  return { phrases, adds }
}

/** A phrase chip's words: "Detail dog", "Any hairstyle". */
export function phraseLabel(p: Pick<SuggestedPhrase, 'text' | 'kind' | 'way'>, way: PhraseWay = p.way): string {
  return way === 'any' && p.kind ? `Any ${p.kind}` : `Detail ${p.text}`
}

/** The prompt with an add written in, and where its slot's `<` lands. */
export function insertAdd(prompt: string, add: SuggestedAdd): { text: string; slotAt: number } {
  const at = Math.max(0, Math.min(prompt.length, add.at))
  return { text: prompt.slice(0, at) + add.text + prompt.slice(at), slotAt: at + add.text.indexOf('<') }
}
