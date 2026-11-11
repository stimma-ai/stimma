/**
 * A choice's settings row ("Just Irish · Similar 3 · Any 105"): one click to narrow to what
 * the user said, vary within what fits their prompt, or reach beyond it. Pure, so it tests
 * without a DOM.
 *
 * The server decides which options each setting holds (backend prompt_programs/reach.py) and
 * sends them with the choice's list; nothing here judges what fits. Ticks stay the stored
 * truth: a setting is a one-click way to set them, and which setting is lit is read back from
 * the ticks, so ticks saved before (or set by hand) read as "yours" when they match none.
 *
 * The user's own options (added in the card, or kept for the list) are in no setting: they
 * stay ticked or unticked as the user left them, and never change which setting is lit.
 * Options the server didn't place (a writer's seed that isn't on the list, so never drawn)
 * are left as they are too.
 */

import { shownOption } from './programVocab.ts'

/** What the server sends per list-bound choice (`vocab[id].reach`). */
export interface ChoiceReach {
  /** The value the user stated, when the choice stands for one. */
  said?: string[]
  /** What fits their prompt: the stated value and those like it, the subset their words
      narrowed the list to, or what the image's context leaves at full weight. */
  fits?: string[]
  /** Everything a run may draw from the list, short of values drawn only when ticked one by one. */
  any: string[]
  /** The user's own words the list was narrowed by ("young"), to name the "fits" setting. */
  words?: string
}

export type ReachKey = 'said' | 'fits' | 'any'
export interface ReachSetting { key: ReachKey; label: string; values: string[] }
/** Which setting the ticks match; `yours` when they match none, `none` when nothing is ticked. */
export type ReachLit = ReachKey | 'yours' | 'none'

const sameSet = (a: Set<string>, b: Set<string>) => a.size === b.size && [...a].every(x => b.has(x))

function label(key: ReachKey, reach: ChoiceReach): string {
  if (key === 'said') return `Just ${shownOption(reach.said?.[0] || '')}`
  if (key === 'any') return 'Any'
  if (reach.said?.length) return 'Similar'
  const w = (reach.words || '').trim()
  return w ? w[0].toUpperCase() + w.slice(1) : 'What fits'
}

/** The settings a choice offers, narrowest first, each holding only options the card lists
    (and none of the user's own). Settings that would draw the same values merge into one,
    under the wider one's name. Fewer than two: the card keeps its plain All row. */
export function reachSettings(reach: ChoiceReach | null | undefined, options: string[], own: ReadonlySet<string>): ReachSetting[] {
  if (!reach?.any?.length) return []
  const listed = new Set(options)
  const keep = (vs: string[] | undefined) => (vs || []).filter(v => listed.has(v) && !own.has(v))
  const out: ReachSetting[] = []
  for (const key of ['said', 'fits', 'any'] as ReachKey[]) {
    const values = keep(reach[key])
    if (!values.length) continue
    const prev = out[out.length - 1]
    if (prev && sameSet(new Set(prev.values), new Set(values))) {
      prev.key = key
      prev.label = label(key, reach)
      continue
    }
    out.push({ key, label: label(key, reach), values })
  }
  return out.length > 1 ? out : []
}

/** Options a setting speaks to: those in any of them. */
function placed(settings: ReachSetting[]): Set<string> {
  return new Set(settings.flatMap(s => s.values))
}

/** Which setting the ticks match, among the options the settings speak to. */
export function litSetting(settings: ReachSetting[], ticks: ReadonlySet<string>, standby: ReadonlySet<string> = new Set()): ReachLit {
  const known = placed(settings)
  const on = new Set([...ticks].filter(t => known.has(t)))
  // A value drawn only when ticked one by one, ticked: no setting holds it, so it's theirs.
  if ([...ticks].some(t => standby.has(t) && !known.has(t))) return 'yours'
  if (!on.size) return 'none'
  return settings.find(s => sameSet(new Set(s.values), on))?.key || 'yours'
}

/** The ticks a setting asks for: its values, with the user's own options and options no
    setting speaks to left as they are. */
export function ticksForSetting(settings: ReachSetting[], key: ReachKey, ticks: ReadonlySet<string>, standby: ReadonlySet<string> = new Set()): Set<string> {
  const known = placed(settings)
  const s = settings.find(x => x.key === key)
  return new Set([...[...ticks].filter(t => !known.has(t) && !standby.has(t)), ...(s?.values || [])])
}

/** The card's order: the user's own options, what they said, what fits, then (after the
    "Beyond your prompt" line) the rest, each part in the list's order. `beyond` is empty when
    nothing sets what fits. */
export function reachOrder(options: string[], reach: ChoiceReach | null | undefined, own: ReadonlySet<string>): { inside: string[]; beyond: string[] } {
  const inner = new Set([...(reach?.said || []), ...(reach?.fits || [])])
  if (!inner.size || !options.some(o => !own.has(o) && !inner.has(o))) return { inside: options, beyond: [] }
  const said = new Set(reach?.said || [])
  return {
    inside: [
      ...options.filter(o => own.has(o)),
      ...options.filter(o => !own.has(o) && said.has(o)),
      ...options.filter(o => !own.has(o) && !said.has(o) && inner.has(o)),
    ],
    beyond: options.filter(o => !own.has(o) && !inner.has(o)),
  }
}
