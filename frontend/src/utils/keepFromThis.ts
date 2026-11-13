/**
 * Keep from this: what one Fluent image drew, as a short checklist, and what ticking a line
 * does to the choices. Pure, so it tests without a DOM.
 *
 * A line stands for one or more of the current prompt's choices. Ticking it sets each of them
 * to exactly what this image drew, as if chosen in the chooser (an outfit as the list's
 * template it was filled from, its colors as their own choice); unticking puts them back. A
 * line is ticked whenever the choices already hold exactly what this image drew, so the card
 * keeps no state of its own. A person's look is one line, not one per detail.
 *
 * Only images made from a slot program offer it: their record says so (`version` "slots-…").
 * Images made by the old writer, or from the words as written, have nothing to keep.
 */

import type { ChoicePool, ChoiceState, ProgramChoice, ProgramChoices, ProgramSlot } from './programWire.ts'
import { PALETTE_CLS, isBuilder, resetState, swatchesOf } from './programChoices.ts'
import { shownOption } from './programVocab.ts'

/** One draw in an image's record (`prompt_program.draws`). */
export interface RecordedDraw {
  id: string
  value: unknown
  hidden?: boolean
  /** An outfit's template, before its colors were filled in. */
  template?: string
}

export interface KeepWorld {
  slots: ProgramSlot[]
  choices: ProgramChoice[]
  states: ProgramChoices
  pools: Record<string, ChoicePool>
}

export interface KeepDrawn {
  id: string
  /** What the choice is set to when the line is ticked. */
  value: string
}

export interface KeepRow {
  /** Unique within the card. */
  key: string
  label: string
  /** What this image drew, in a few words. */
  text: string
  /** A palette among them, as swatches. */
  swatches: string[] | null
  drawn: KeepDrawn[]
  on: boolean
}

export interface KeepGroup {
  /** A person's name for their lines; '' for the prompt's other slots. */
  label: string
  rows: KeepRow[]
}

/** The image was made from a slot program, with draws to keep. */
export function isSlotRun(run: any): boolean {
  return !!run && typeof run.version === 'string' && run.version.startsWith('slots')
    && Array.isArray(run.draws) && run.draws.length > 0 && run.fallback?.rung !== 'words'
}

/** What a choice is set to, to keep this draw: an outfit's template, else the value drawn. */
function keptValue(d: RecordedDraw): string | null {
  if (d.hidden || d.value == null) return null
  const v = typeof d.template === 'string' && d.template ? d.template : String(d.value)
  return v.trim() ? v : null
}

/** The choice holds exactly this value, and nothing else is chosen for it. */
function holdsExactly(s: ChoiceState | undefined, value: string): boolean {
  return !!s && !s.off && !s.zones?.length && !Object.keys(s.groups || {}).length
    && s.values?.length === 1 && s.values[0] === value
}

function row(key: string, label: string, ids: string[], draws: Map<string, RecordedDraw>, w: KeepWorld): KeepRow | null {
  const byId = new Map(w.choices.map(c => [c.id, c]))
  const drawn: KeepDrawn[] = []
  const words: string[] = []
  let swatches: string[] | null = null
  for (const id of ids) {
    const d = draws.get(id)
    const c = byId.get(id)
    const value = d && c ? keptValue(d) : null
    if (!d || !c || value == null) continue
    drawn.push({ id, value })
    const palette = c.cls === PALETTE_CLS ? swatchesOf(String(d.value)) : null
    if (palette) { swatches = palette; continue }
    words.push(w.pools[id]?.short?.[value] || shownOption(String(d.value)))
  }
  if (!drawn.length) return null
  return {
    key, label, text: words.join(', '), swatches, drawn,
    on: drawn.every(x => holdsExactly(w.states[x.id], x.value)),
  }
}

/** The card's lines for one image, against the prompt as it is now: a section per person
    (their look, then what they wear), then a line per other slot and per list of the
    user's own. Empty when nothing it drew is still in the prompt. */
export function keepGroups(run: any, w: KeepWorld): KeepGroup[] {
  if (!isSlotRun(run)) return []
  const draws = new Map<string, RecordedDraw>((run.draws as RecordedDraw[]).filter(d => d && typeof d.id === 'string').map(d => [d.id, d]))
  const live = new Set(w.choices.filter(c => !c.hidden).map(c => c.id))
  const followers = (id: string) => w.choices.filter(c => c.follows === id).map(c => c.id)
  const groups: KeepGroup[] = []
  const rest: KeepRow[] = []
  const inSlot = new Set<string>()
  const byId = new Map(w.choices.filter(c => !c.hidden).map(c => [c.id, c]))
  for (const slot of [...w.slots].sort((a, b) => a.n - b.n)) {
    const ids = slot.details.filter(id => live.has(id))
    ids.forEach(id => inSlot.add(id))
    if (slot.kind !== 'person' || !isBuilder(slot, id => byId.get(id))) {
      // An image drawn while this slot was a camera with one detail varying recorded it as that
      // detail ("angle.angle"); the slot is that detail's list now ("angle").
      const old = ids.length === 1 && ids[0] === slot.id && !draws.has(slot.id)
        ? [...draws.keys()].filter(k => k.startsWith(`${slot.id}.`)) : []
      if (old.length === 1) draws.set(slot.id, { ...draws.get(old[0])!, id: slot.id })
      const r = row(slot.id, slot.label, ids, draws, w)
      if (r) rest.push(r)
      continue
    }
    // A person: what they wear (an outfit with its colors) is a line of its own; every
    // other detail is their look.
    const worn = ids.filter(id => id === `${slot.id}.outfit` || followers(id).length > 0)
    const wornAll = new Set(worn.flatMap(id => [id, ...followers(id)]))
    const rows = [
      row(`${slot.id}#look`, 'Look', ids.filter(id => !wornAll.has(id)), draws, w),
      ...worn.map(id => row(id, w.choices.find(c => c.id === id)?.label || 'Outfit', [id, ...followers(id)], draws, w)),
    ].filter((r): r is KeepRow => !!r)
    if (rows.length) groups.push({ label: slot.label, rows })
  }
  // The user's own {a|b} lists.
  for (const c of w.choices) {
    if (c.hidden || inSlot.has(c.id) || c.slot || c.follows) continue
    const r = row(c.id, c.label, [c.id], draws, w)
    if (r) rest.push(r)
  }
  if (rest.length) groups.push({ label: '', rows: rest })
  return groups
}

/** The choices to set when a line is ticked (each to this image's value) or unticked (each
    back to how it starts). The user's own options stay in their lists either way. */
export function flipRow(r: KeepRow, states: ProgramChoices): Record<string, ChoiceState | null> {
  const out: Record<string, ChoiceState | null> = {}
  for (const d of r.drawn) {
    const s = states[d.id]
    const own = s?.add?.length ? { add: s.add } : {}
    out[d.id] = r.on ? resetState(s) : { values: [d.value], ...own }
  }
  return out
}
