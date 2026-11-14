/**
 * Use from an image: what one Fluent image drew, part by part, and what using a part does to
 * the choices. Pure, so it tests without a DOM.
 *
 * A part is one slot (or one list of the user's own) the image drew. Using it adds what was
 * drawn there to that part's picks; a person's age, gender and descent (the seeds its variant
 * was written from) can each be used on their own, as seed picks. Using never replaces a pick,
 * and using the same thing again changes nothing. The image keeps no state of its own.
 *
 * A part is still in the prompt when the current program has a choice with its id and, for a
 * slot, the same words (the record's `about`); otherwise it is shown as not in the prompt now.
 * Only images made from a slot program offer it: their record says so (`version` "slots-…").
 * Images made by the old writer, or from the words as written, have nothing to use. An earlier
 * Fluent's person, animal and camera detail draws are not parts and are passed by.
 */

import type { ChoicePool, ChoiceState, ProgramChoice, ProgramChoices, ProgramSlot } from './programWire.ts'
import { addValue, cleanState, pickedHeritages, pickedYears, toggleGender, toggleHeritage, toggleYear, yearOfAge } from './programChoices.ts'

/** One draw in an image's record (`prompt_program.draws`). */
export interface RecordedDraw {
  id: string
  value: unknown
  label?: string
  /** A slot's own words when it was drawn. */
  about?: string
  /** `list` for a list of the user's own; `words` when the slot went in as its words. */
  source?: string
  hidden?: boolean
  /** The seeds a person's variant was written from. */
  seeds?: { descent?: string; gender?: string; age?: string | number }
}

export interface ImageWorld {
  slots: ProgramSlot[]
  choices: ProgramChoice[]
  states: ProgramChoices
  pools: Record<string, ChoicePool>
}

/** One of a person's broad strokes, usable on its own: "age 28", "woman", "Irish". */
export interface Facet { id: 'age' | 'gender' | 'descent'; says: string; value: string | number }

export interface ImagePart {
  /** The choice it sets. */
  key: string
  label: string
  /** What this image drew there. */
  text: string
  /** The slot's words when the image was made (for showing them quieter). */
  words: string
  /** The current prompt still has this part. */
  here: boolean
  /** A person's broad strokes, with "her", "him" or "them" by gender. */
  person?: { pronoun: 'her' | 'him' | 'them'; facets: Facet[] }
}

/** The image was made from a slot program, with draws to use. */
export function isSlotRun(run: any): boolean {
  return !!run && typeof run.version === 'string' && run.version.startsWith('slots')
    && Array.isArray(run.draws) && run.draws.length > 0 && run.fallback?.rung !== 'words'
}

const HER = new Set(['woman', 'trans woman', 'girl', 'trans girl'])
const HIM = new Set(['man', 'trans man', 'boy', 'trans boy'])
const pronounOf = (gender?: string) => (gender && HER.has(gender) ? 'her' : gender && HIM.has(gender) ? 'him' : 'them')

function facetsOf(seeds: RecordedDraw['seeds']): Facet[] {
  const out: Facet[] = []
  const year = yearOfAge(seeds?.age)
  if (year !== null) out.push({ id: 'age', says: `age ${year}`, value: year })
  if (seeds?.gender) out.push({ id: 'gender', says: seeds.gender, value: seeds.gender })
  if (seeds?.descent) out.push({ id: 'descent', says: seeds.descent, value: seeds.descent })
  return out
}

/** The image's parts, in the order it drew them: each slot and list of the user's own it drew,
    marked whether the prompt as it is now still has it. */
export function imageParts(run: any, w: ImageWorld): ImagePart[] {
  if (!isSlotRun(run)) return []
  const slots = new Map(w.slots.map(s => [s.id, s]))
  const live = new Map(w.choices.filter(c => !c.hidden).map(c => [c.id, c]))
  const parts: ImagePart[] = []
  for (const d of run.draws as RecordedDraw[]) {
    if (!d || typeof d.id !== 'string' || d.hidden || d.value == null || d.source === 'words') continue
    const isList = d.source === 'list'
    // Only a slot (it carries its words) or a list of the user's own is a part.
    if (!isList && typeof d.about !== 'string') continue
    const text = String(d.value)
    if (!text.trim()) continue
    const c = live.get(d.id)
    const slot = slots.get(d.id)
    const here = !!c && (isList ? !c.slot : !!slot && c.slot === slot.id && slot.words === d.about)
    const label = (here ? (slot?.label ?? c?.label) : null) || d.label || d.about || d.id
    const facets = here && slot?.kind === 'person' ? facetsOf(d.seeds) : []
    parts.push({
      key: d.id, label, text, words: d.about || '', here,
      ...(facets.length ? { person: { pronoun: pronounOf(d.seeds?.gender), facets } } : {}),
    })
  }
  return parts
}

/** The choice after using part `p` (what it drew), or `facet` of its person; undefined when
    that changes nothing (already picked, or covered by a pick). */
export function usedState(p: ImagePart, states: ProgramChoices, pool: ChoicePool | null | undefined, facet?: Facet): ChoiceState | null | undefined {
  const s = states[p.key]
  if (!p.here) return undefined
  if (!facet) return s?.values?.includes(p.text) ? undefined : addValue(s, p.text)
  if (facet.id === 'age') {
    const y = facet.value as number
    return pickedYears(s?.seeds, pool?.person?.age).includes(y) ? undefined : toggleYear(s, y, pool)
  }
  const v = String(facet.value)
  if (facet.id === 'gender') return s?.seeds?.gender?.values?.includes(v) ? undefined : toggleGender(s, v, pool)
  return pickedHeritages(s?.seeds, pool?.person?.descent).includes(v) ? undefined : toggleHeritage(s, v, pool)
}

/** Undo one use: take back only what it added (the value, or the year, gender or descent seed),
    if it is still there and wasn't picked before the use. Everything else stays, later edits
    and later uses included. */
export function undoUse(p: ImagePart, states: ProgramChoices, before: ChoiceState | null | undefined, facet?: Facet): ChoiceState | null {
  const s = states[p.key]
  if (!s) return null
  if (!facet) {
    if (before?.values?.includes(p.text) || !s.values?.includes(p.text)) return cleanState(s)
    return cleanState({ ...s, values: s.values.filter(v => v !== p.text) })
  }
  const seeds = { ...(s.seeds || {}) }
  if (facet.id === 'age') {
    const y = facet.value as number
    if (before?.seeds?.age?.years?.includes(y) || !seeds.age?.years?.includes(y)) return cleanState(s)
    seeds.age = { ...seeds.age, years: seeds.age.years.filter(x => x !== y) }
  } else if (facet.id === 'gender') {
    const g = String(facet.value)
    if (before?.seeds?.gender?.values?.includes(g) || !seeds.gender?.values?.includes(g)) return cleanState(s)
    seeds.gender = { values: seeds.gender.values.filter(x => x !== g) }
  } else {
    const h = String(facet.value)
    if (before?.seeds?.descent?.values?.includes(h) || !seeds.descent?.values?.includes(h)) return cleanState(s)
    seeds.descent = { ...seeds.descent, values: seeds.descent.values.filter(x => x !== h) }
  }
  return cleanState({ ...s, seeds })
}
