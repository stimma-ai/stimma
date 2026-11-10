/**
 * What a choice's card has ticked, and what a tick does. Pure, so it tests without a DOM.
 *
 * Ticks are the user's pins: each image draws from the ticked options, or from all of them
 * when none are. A choice that stands for something the user named (`said`, "yellow
 * ferrari") is the exception: with nothing ticked it draws only their words, so the card
 * shows their words ticked and the rest unticked. Ticking others widens it; unticking back
 * to their words alone (or to nothing) is the same as never having ticked.
 */

import type { ProgramChoice } from '../composables/usePromptProgram'

/** The user's own words a choice stands for, while they are still one of its options. */
export function saidOf(c: Pick<ProgramChoice, 'said'>, options: string[]): string | null {
  return c.said && options.includes(c.said) ? c.said : null
}

/** The options ticked in the card: the pins the options still hold, else the user's words. */
export function ticksOf(c: Pick<ProgramChoice, 'said'>, pins: string[] | undefined, options: string[]): Set<string> {
  const kept = (pins || []).filter(v => options.includes(v))
  if (kept.length) return new Set(kept)
  const said = saidOf(c, options)
  return new Set(said ? [said] : [])
}

/** The pins to store for a set of ticks, in the options' order: none when the ticks are what
    the choice draws anyway (nothing, or only the user's words). */
export function pinsFor(c: Pick<ProgramChoice, 'said'>, ticks: Iterable<string>, options: string[]): string[] {
  const on = new Set(ticks)
  const out = options.filter(o => on.has(o))
  const said = saidOf(c, options)
  return out.length === 1 && out[0] === said ? [] : out
}

/** The pins after ticking or unticking one option. */
export function toggleTick(c: Pick<ProgramChoice, 'said'>, pins: string[] | undefined, options: string[], value: string): string[] {
  const next = ticksOf(c, pins, options)
  next.has(value) ? next.delete(value) : next.add(value)
  return pinsFor(c, next, options)
}

/** Whether the user changed what the choice draws: some options ticked, other than only
    their own words. */
export function isLimited(c: Pick<ProgramChoice, 'said'>, pins: string[] | undefined, options: string[]): boolean {
  return pinsFor(c, ticksOf(c, pins, options), options).length > 0
}

/** An option the card may delete: never the user's own words (we never edit their prompt). */
export function deletable(c: Pick<ProgramChoice, 'said'>, value: string): boolean {
  return !c.said || value !== c.said
}
