/**
 * The shapes of Fluent's Suggest answer, and the pure checks on them (the composable that
 * asks is composables/usePromptSuggestions.ts).
 */

export interface SuggestedPhrase { from: number; to: number; text: string }
export interface SuggestedAdd {
  name: string
  label: string
  /** A photo's photography add (its light, or one part of its camera: angle, lens, film look,
      framing): the kind its slot is read as (`light`, or `list` for a camera part)… */
  kind?: string
  /** …and the vocabulary lists it draws from (a camera part: its one list, e.g. `camera.lens`). */
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

/** Whether a slot of the prompt already is this photography add: read as its kind (a light),
    or drawing from one of its lists, or from a list under one of them. A camera part is a
    `list`, so it is covered per part: a slot on the angle list, or a whole camera whose details
    include the angle, covers "+ angle" and leaves "+ lens" offered. Unknown until the slots are
    read: false. Structure only: list ids, never the slot's words. */
export function slotCovers(add: SuggestedAdd, read: ReadSlots | null | undefined): boolean {
  if (!read || !add.kind) return false
  if (add.kind !== 'list' && read.kinds.includes(add.kind)) return true
  return !!add.lists?.some(l => read.lists.some(r => r === l || r.startsWith(`${l}.`)))
}
