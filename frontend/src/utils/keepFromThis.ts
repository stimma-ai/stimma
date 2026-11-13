/**
 * Keep from this: what one Fluent image drew, as a short checklist, and what ticking a line
 * does to the choices. Pure, so it tests without a DOM.
 *
 * A line stands for one slot (or one list of the user's own) of the current prompt. Ticking it
 * pins exactly what this image drew there, with the image it came from, and the same line then
 * shows under the prompt; unticking puts the slot back. A line is ticked whenever the slot
 * already holds exactly what this image drew, so the card keeps no state of its own.
 *
 * Only images made from a slot program offer it: their record says so (`version` "slots-…").
 * Images made by the old writer, or from the words as written, have nothing to keep. An image
 * drawn by an earlier Fluent keeps what it drew for a whole slot; its person, animal and camera
 * detail draws match no choice now and are passed by.
 */

import type { ChoicePool, ChoiceState, ProgramChoice, ProgramChoices, ProgramSlot } from './programWire.ts'
import { pinTo, resetState } from './programChoices.ts'

/** One draw in an image's record (`prompt_program.draws`). */
export interface RecordedDraw {
  id: string
  value: unknown
  hidden?: boolean
}

export interface KeepWorld {
  slots: ProgramSlot[]
  choices: ProgramChoice[]
  states: ProgramChoices
  pools: Record<string, ChoicePool>
}

export interface KeepRow {
  /** The choice it sets. */
  key: string
  label: string
  /** What this image drew there. */
  text: string
  on: boolean
}

/** The image was made from a slot program, with draws to keep. */
export function isSlotRun(run: any): boolean {
  return !!run && typeof run.version === 'string' && run.version.startsWith('slots')
    && Array.isArray(run.draws) && run.draws.length > 0 && run.fallback?.rung !== 'words'
}

/** The choice holds exactly this value, and nothing else is chosen for it. */
function holdsExactly(s: ChoiceState | undefined, value: string): boolean {
  return !!s && !s.off && !s.as_written && !s.seeds && s.values?.length === 1 && s.values[0] === value
}

/** The card's lines for one image, against the prompt as it is now: a line per slot in the
    prompt's order, then per list of the user's own. Empty when nothing it drew is still in the
    prompt. */
export function keepRows(run: any, w: KeepWorld): KeepRow[] {
  if (!isSlotRun(run)) return []
  const draws = new Map<string, RecordedDraw>((run.draws as RecordedDraw[]).filter(d => d && typeof d.id === 'string').map(d => [d.id, d]))
  const live = new Map(w.choices.filter(c => !c.hidden).map(c => [c.id, c]))
  const order = [
    ...[...w.slots].sort((a, b) => a.n - b.n).map(s => ({ id: s.id, label: s.label })),
    ...w.choices.filter(c => !c.hidden && !c.slot).map(c => ({ id: c.id, label: c.label })),
  ]
  const rows: KeepRow[] = []
  for (const { id, label } of order) {
    const d = draws.get(id)
    if (!live.has(id) || !d || d.hidden || d.value == null) continue
    const text = String(d.value)
    if (!text.trim()) continue
    rows.push({ key: id, label, text, on: holdsExactly(w.states[id], text) })
  }
  return rows
}

/** The choice to set when a line is ticked (this image's value, kept from `media`) or unticked
    (back to how it starts). The user's own variants stay either way. */
export function flipRow(r: KeepRow, states: ProgramChoices, media?: number | null): Record<string, ChoiceState | null> {
  const s = states[r.key]
  return { [r.key]: r.on ? resetState(s) : pinTo(s, r.text, media) }
}
