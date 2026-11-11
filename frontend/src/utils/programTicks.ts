/**
 * What a choice's card has ticked, and how that is stored. Pure, so it tests without a DOM.
 *
 * A tick means the option can be drawn. Everything starts ticked; unticking leaves a value
 * out. What is stored is the shorter description of the ticks, so a list of thousands of
 * values never stores or sends thousands of strings:
 *
 *   all ticked              nothing
 *   half or fewer ticked    `pins`: the ticked values (the draw is limited to them)
 *   more than half ticked   `out`: the unticked values (kept in the list, left out of the draw)
 *   none ticked             `none`: the detail is left out of the prompt
 *
 * Two exceptions, both described with `pins` only:
 * - A choice that stands for something the user named (`said`, "yellow ferrari") draws only
 *   their words until others are ticked, so it starts with their words as the single tick.
 *   Unticking back to their words alone (or to nothing) is the same as never having ticked.
 * - Standby values (a list's opt-in values) are drawn only when pinned, so they start
 *   unticked, and ticking one stores the ticks as `pins`.
 */

import type { ChoiceEdit, ProgramChoice } from '../composables/usePromptProgram'

type Said = Pick<ProgramChoice, 'said'>
type Stored = Pick<ChoiceEdit, 'out' | 'none'>

/** How a choice's ticks are stored: `pins` in the pins, `out` and `none` in its edit. */
export interface TickState { pins: string[]; out: string[]; none: boolean }

const NO_STANDBY: ReadonlySet<string> = new Set()

/** The user's own words a choice stands for, while they are still one of its options. */
export function saidOf(c: Said, options: string[]): string | null {
  return c.said && options.includes(c.said) ? c.said : null
}

/** What is ticked before the user touches anything: every option but the standby ones, or
    only the user's words for a choice that stands for them. */
export function defaultTicks(c: Said, options: string[], standby: ReadonlySet<string> = NO_STANDBY): Set<string> {
  const said = saidOf(c, options)
  if (said) return new Set([said])
  return new Set(standby.size ? options.filter(o => !standby.has(o)) : options)
}

/** The options ticked in the card. Stored values the options no longer hold are ignored. */
export function ticksOf(c: Said, pins: string[] | undefined, edit: Stored | undefined, options: string[],
                        standby: ReadonlySet<string> = NO_STANDBY): Set<string> {
  const said = saidOf(c, options)
  if (!said && edit?.none) return new Set()
  if (pins?.length) {
    const have = new Set(options)
    const kept = pins.filter(v => have.has(v))
    if (kept.length) return new Set(kept)
  }
  const ticks = defaultTicks(c, options, standby)
  if (!said) for (const v of edit?.out || []) ticks.delete(v)
  return ticks
}

/** How to store a set of ticks: the shorter of the ticked and the unticked values, in the
    options' order. */
export function stateFor(c: Said, ticks: Iterable<string>, options: string[],
                         standby: ReadonlySet<string> = NO_STANDBY): TickState {
  const want = new Set(ticks)
  const on = options.filter(o => want.has(o))
  const clean: TickState = { pins: [], out: [], none: false }
  const said = saidOf(c, options)
  if (said) return !on.length || (on.length === 1 && on[0] === said) ? clean : { ...clean, pins: on }
  const base = defaultTicks(c, options, standby)
  const extra = on.some(o => !base.has(o))  // a standby value is ticked: only a pin draws it
  if (!extra && on.length === base.size) return clean
  if (!on.length) return { ...clean, none: true }
  if (extra || on.length * 2 <= base.size) return { ...clean, pins: on }
  return { ...clean, out: options.filter(o => base.has(o) && !want.has(o)) }
}

/** Whether the user changed what the choice draws from how it starts. */
export function isLimited(c: Said, pins: string[] | undefined, edit: Stored | undefined, options: string[],
                          standby: ReadonlySet<string> = NO_STANDBY): boolean {
  const ticks = ticksOf(c, pins, edit, options, standby)
  const base = defaultTicks(c, options, standby)
  if (ticks.size !== base.size) return true
  for (const v of ticks) if (!base.has(v)) return true
  return false
}

/** Edits as the server reads them: values left out are removed from the draw, and a choice
    with nothing ticked is off. */
export function wireEdits(edits: Record<string, ChoiceEdit>): Record<string, { add?: string[]; remove?: string[]; off?: boolean }> {
  const result: Record<string, { add?: string[]; remove?: string[]; off?: boolean }> = {}
  for (const [id, e] of Object.entries(edits || {})) {
    const remove = e.out?.length ? [...new Set([...(e.remove || []), ...e.out])] : e.remove
    const wire: { add?: string[]; remove?: string[]; off?: boolean } = {}
    if (e.add?.length) wire.add = e.add
    if (remove?.length) wire.remove = remove
    if (e.off || e.none) wire.off = true
    if (Object.keys(wire).length) result[id] = wire
  }
  return result
}
