/**
 * The shapes of Fluent's Suggest answer, and the pure checks on them (the composable that
 * asks is composables/usePromptSuggestions.ts).
 */

export interface SuggestedPhrase { from: number; to: number; text: string }
export interface SuggestedAdd {
  name: string
  label: string
  /** A photo's photography add: the kind its slot is read as (`camera`, `light`, `list`)… */
  kind?: string
  /** …and the vocabulary lists it draws from. */
  lists?: string[]
  /** Where it goes: words of the prompt it was suggested for, written in right after them… */
  after?: string
  /** …as these words, which hold its slot. Sent with Add, which splices them in with no model call. */
  insert?: string
}
/** What the prompt's slots were read as: their kinds and the lists their choices draw from. */
export interface ReadSlots { kinds: string[]; lists: string[] }
export interface Suggestions { vary: SuggestedPhrase[]; adds: SuggestedAdd[] }

/** A /suggest answer, keeping only well-formed parts. */
export function cleanSuggestions(data: any): Suggestions {
  const vary = Array.isArray(data?.vary) ? data.vary.filter((p: any) =>
    Number.isInteger(p?.from) && Number.isInteger(p?.to) && typeof p?.text === 'string') : []
  const adds = Array.isArray(data?.adds) ? data.adds.filter((a: any) => typeof a?.name === 'string' && a.name.trim())
    .map((a: any): SuggestedAdd => ({
      name: a.name,
      label: typeof a.label === 'string' && a.label.trim() ? a.label : a.name,
      ...(typeof a.kind === 'string' && a.kind ? { kind: a.kind } : {}),
      ...(Array.isArray(a.lists) ? { lists: a.lists.filter((l: unknown) => typeof l === 'string') } : {}),
      ...(typeof a.after === 'string' && typeof a.insert === 'string' ? { after: a.after, insert: a.insert } : {}),
    })) : []
  return { vary, adds }
}

/** What Add is sent for the add named `name`: where Suggest said it goes, with the prompt it
    said so for, only when that is exactly `text`. After an edit the words it goes after may
    still be there, yet the join would land beside what the edit added: Add places it afresh. */
export function joinFor(answer: { text: string; suggestions: Suggestions } | null | undefined, name: string, text: string):
  { after: string; insert: string; suggested_for: string } | null {
  if (!answer || answer.text !== text) return null
  const add = answer.suggestions.adds.find(a => a.name === name)
  return add?.after != null && add.insert != null ? { after: add.after, insert: add.insert, suggested_for: answer.text } : null
}

/** Whether a slot of the prompt already is this photography add: read as its kind (a camera,
    a light), or drawing from one of its lists. Unknown until the slots are read: false. */
export function slotCovers(add: SuggestedAdd, read: ReadSlots | null | undefined): boolean {
  if (!read || !add.kind) return false
  if (add.kind !== 'list' && read.kinds.includes(add.kind)) return true
  return !!add.lists?.some(l => read.lists.includes(l))
}
