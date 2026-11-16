/**
 * The shapes of Fluent's Suggest answer, and the pure checks on them (the composable that
 * asks is composables/usePromptSuggestions.ts).
 *
 * phrases  words the user wrote worth changing from picture to picture: underlined in the
 *          text, and a chip named by Suggest's label. Add Detail keeps the words and wraps them
 *          in brackets ("Add Detail: dog"); Add Variety writes their kind in their place, in
 *          brackets ("Add Variety: hairstyle").
 * adds     something good prompts state and this one leaves to the image model's habits,
 *          written in as a new slot ("+ Camera", "+ Face").
 */

/** 'detail' (Add Detail): every picture keeps the words, each a specific one of them. 'any'
    (Add Variety): the words become one of their kind and the others come in. */
export type PhraseWay = 'detail' | 'any'

/** A phrase worth changing. `kind` names what it is ("hairstyle" for "short bob"), "" when
    unknown; `mode` 'one' when it names one specific thing (the Eiffel Tower, seen new ways);
    `label` one or two words naming the thing, for its chip ("dog" for "scruffy old dog"). */
export interface SuggestedPhrase { from: number; to: number; text: string; kind: string; way: PhraseWay; mode: 'one' | 'kind'; label: string }
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
      const label = typeof p.label === 'string' ? p.label.trim() : ''
      return { from: p.from, to: p.to, text: p.text, kind,
        way: p.way === 'any' && kind ? 'any' : 'detail', mode: p.mode === 'one' ? 'one' : 'kind',
        label: label || p.text.trim().split(/\s+/).slice(-2).join(' ') }
    }) : []
  const adds = Array.isArray(data?.adds) ? data.adds
    .filter((a: any) => typeof a?.key === 'string' && typeof a?.text === 'string' && a.text.includes('<') && Number.isInteger(a?.at))
    .map((a: any): SuggestedAdd => ({ key: a.key, label: typeof a.label === 'string' && a.label.trim() ? a.label : a.key, at: a.at, text: a.text })) : []
  return { phrases, adds }
}

/** A way's name, as every control says it. */
export const WAY_NAMES: Record<PhraseWay, string> = { detail: 'Add Detail', any: 'Add Variety' }

/** A phrase chip's words: "Add Detail: dog", "Add Variety: hairstyle". Its label is Suggest's
    (its words when there is none). */
export function phraseLabel(p: Pick<SuggestedPhrase, 'text' | 'kind' | 'way'> & { label?: string }, way: PhraseWay = p.way): string {
  return `${WAY_NAMES[way === 'any' && p.kind ? 'any' : 'detail']}: ${p.label?.trim() || p.text}`
}

/** The prompt with an add written in, and where its slot's `<` lands. */
export function insertAdd(prompt: string, add: SuggestedAdd): { text: string; slotAt: number } {
  const at = Math.max(0, Math.min(prompt.length, add.at))
  return { text: prompt.slice(0, at) + add.text + prompt.slice(at), slotAt: at + add.text.indexOf('<') }
}
