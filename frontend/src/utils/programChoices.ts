/**
 * What the user chose for a prompt's slots, and what follows from it: the options a card
 * lists, which of them an image can draw, the pills' words. Pure, so it tests without a DOM.
 *
 * Nothing starts chosen. With nothing chosen a choice draws from its default zone (its first:
 * kinds of what the words name), or from all its options when it has no zones. Choosing adds:
 * options, whole groups ("any sporty"), whole zones ("Other ages"). "Any X" and the default
 * zone alone are stored as no choice. Leaving a choice out (`off`) replaces what is chosen.
 */

import type { ChoicePool, ChoiceState, PreparedProgram, ProgramChoice, ProgramChoices, ProgramSlot } from './programWire.ts'
import { shownOption } from './programVocab.ts'

export type Token =
  | { kind: 'value'; value: string }
  | { kind: 'group'; facet: string; part: string }
  | { kind: 'zone'; zone: string }

export interface Zone { id: string; title: string; options: string[] }

const uniq = (xs: string[]) => [...new Set(xs.filter(x => typeof x === 'string' && x.trim()))]

/** The zone a choice draws from when nothing is chosen. */
export function defaultZone(c: Pick<ProgramChoice, 'zones'>): string {
  return c.zones?.[0]?.id ?? 'all'
}

type ChoiceShape = Pick<ProgramChoice, 'zones'> & { starts_off?: boolean }

/** A state as stored: empty parts dropped, the default zone alone dropped, `off` alone with
    the user's own options. A choice that starts left out keeps `on` and stores no `off` (that
    is how it starts). Null when nothing is left. */
export function cleanState(c: ChoiceShape, s: ChoiceState | null | undefined): ChoiceState | null {
  if (!s) return null
  const add = uniq(s.add || [])
  const own = add.length ? { add } : {}
  if (s.off) return c.starts_off ? (add.length ? { add } : null) : { off: true, ...own }
  const values = uniq(s.values || [])
  const groups: Record<string, string[]> = {}
  for (const [facet, parts] of Object.entries(s.groups || {})) {
    const p = uniq(parts || [])
    if (p.length) groups[facet] = p
  }
  const grouped = Object.keys(groups).length > 0
  let zones = uniq(s.zones || [])
  if (!values.length && !grouped && zones.length === 1 && zones[0] === defaultZone(c)) zones = []
  const out: ChoiceState = {
    ...(c.starts_off && s.on ? { on: true } : {}),
    ...(values.length ? { values } : {}),
    ...(grouped ? { groups } : {}),
    ...(zones.length ? { zones } : {}),
    ...own,
  }
  return Object.keys(out).length ? out : null
}

/** The user changed what the choice draws (their own options alone change nothing). */
export function isChanged(s: ChoiceState | null | undefined): boolean {
  return !!s && (!!s.off || !!s.on || !!s.values?.length || !!s.zones?.length || Object.values(s.groups || {}).some(p => p.length))
}

/** Left out now: by the user, or a choice that starts left out and wasn't turned on. */
export function isOff(c: { starts_off?: boolean } | null | undefined, s: ChoiceState | null | undefined): boolean {
  return !!s?.off || (!!c?.starts_off && !isChanged(s))
}

/** A list longer than this (thousands of faces) comes whole with /prepare, and /pools sends
    only the options it adds (the server's PARTS_MAX). */
export const LONG_LIST = 400

function firstZone(c: ProgramChoice, pool: ChoicePool | null | undefined): string[] {
  if (!pool) return c.options
  return c.options.length > LONG_LIST ? uniq([...pool.options, ...c.options]) : pool.options
}

/** A choice's options by zone, as its card lists them, in the order given. The user's own
    options (added here, or kept for its list) lead the first zone. Before its pool arrives,
    the prepared options stand in for the first zone. */
export function zonesOf(c: ProgramChoice, pool: ChoicePool | null | undefined, s?: ChoiceState | null): Zone[] {
  const declared = c.zones?.length ? c.zones : [{ id: 'all', title: '' }]
  const zones: Zone[] = declared.map((z, i) => ({
    id: z.id,
    title: z.title || '',
    options: pool?.zones ? pool.zones[z.id] || [] : i === 0 ? firstZone(c, pool) : [],
  }))
  const listed = new Set(zones.flatMap(z => z.options))
  const own = uniq([...(s?.add || []), ...(pool?.mine || [])]).filter(o => !listed.has(o))
  if (own.length) zones[0] = { ...zones[0], options: [...own, ...zones[0].options] }
  return zones
}

export function optionsOf(c: ProgramChoice, pool: ChoicePool | null | undefined, s?: ChoiceState | null): string[] {
  return uniq(zonesOf(c, pool, s).flatMap(z => z.options))
}

/** The pools of the choices a newly prepared program still has (an edit kept their slots): they
    show until the program's own pools arrive. */
export function keptPools(pools: Record<string, ChoicePool>, have: Record<string, unknown>): Record<string, ChoicePool> {
  return Object.fromEntries(Object.entries(pools).filter(([id]) => id in have))
}

type Shown = Pick<PreparedProgram, 'key' | 'slots' | 'choices'>
type Landed = Pick<PreparedProgram, 'slots' | 'choices' | 'from'>

/** For a program prepared after an edit: each choice id of the program shown before it, mapped
    to the id the same choice has now, by the parts the server matched (`was`: where each part
    stands in the text, not its id; two `<mug>`s with the first removed leave `mug`, which was
    `mug_2`). Null when the answer doesn't say (it wasn't matched against `prev`). A choice of
    `prev` missing from the map went with the edit, or couldn't be told apart from another. */
export function carriedIds(prev: Shown | null | undefined, next: Landed): Record<string, string> | null {
  if (!prev?.key || !next.from || next.from !== prev.key) return null
  const before = new Map((prev.slots || []).map(s => [s.id, s]))
  const have = new Set((next.choices || []).map(c => c.id))
  const out: Record<string, string> = {}
  for (const s of next.slots || []) {
    const o = s.was ? before.get(s.was) : undefined
    if (!o) continue
    for (const d of o.details) {
      const id = d === o.id ? s.id : d.startsWith(`${o.id}.`) ? s.id + d.slice(o.id.length) : null
      if (id && have.has(id)) out[d] = id
    }
  }
  for (const c of next.choices || []) if (c.source === 'list' && c.was) out[c.was] = c.id
  return out
}

/** Values kept per choice id (what was chosen, the options shown), moved to the ids a newly
    prepared program gives the same choices. With no map, by id: those the program still has. */
export function carryChoices<T>(byId: Record<string, T>, ids: Record<string, string> | null,
  prev: Shown | null | undefined, next: Pick<PreparedProgram, 'choices'>): Record<string, T> {
  const have = new Set((next.choices || []).map(c => c.id))
  if (!ids) return Object.fromEntries(Object.entries(byId).filter(([id]) => have.has(id)))
  const shown = new Set((prev?.choices || []).map(c => c.id))
  const out: Record<string, T> = {}
  for (const [id, v] of Object.entries(byId)) if (id in ids) out[ids[id]] = v
  for (const [id, v] of Object.entries(byId)) {
    if (id in ids || shown.has(id) || !have.has(id) || id in out) continue
    out[id] = v   // not the shown program's (kept from before it): by id
  }
  return out
}

/** The options a group holds. */
export function groupMembers(pool: ChoicePool | null | undefined, facet: string, part: string): string[] {
  return pool?.groups?.[facet]?.[part] || []
}

/** What an image can draw now. Null when the choice is left out. */
export function drawable(c: ProgramChoice, pool: ChoicePool | null | undefined, s: ChoiceState | null | undefined): Set<string> | null {
  if (isOff(c, s)) return null
  const zones = zonesOf(c, pool, s)
  if (!tokensOf(s).length) return new Set(zones.find(z => z.id === defaultZone(c))?.options || zones[0]?.options || [])
  const out = new Set<string>(s!.values || [])
  for (const [facet, parts] of Object.entries(s!.groups || {})) for (const p of parts) for (const o of groupMembers(pool, facet, p)) out.add(o)
  for (const z of zones) if (s!.zones?.includes(z.id)) for (const o of z.options) out.add(o)
  return out
}

export function tokensOf(s: ChoiceState | null | undefined): Token[] {
  if (!s || s.off) return []
  return [
    ...(s.zones || []).map(zone => ({ kind: 'zone' as const, zone })),
    ...Object.entries(s.groups || {}).flatMap(([facet, parts]) => parts.map(part => ({ kind: 'group' as const, facet, part }))),
    ...(s.values || []).map(value => ({ kind: 'value' as const, value })),
  ]
}

export function hasToken(s: ChoiceState | null | undefined, t: Token): boolean {
  if (!s || s.off) return false
  if (t.kind === 'value') return !!s.values?.includes(t.value)
  if (t.kind === 'zone') return !!s.zones?.includes(t.zone)
  return !!s.groups?.[t.facet]?.includes(t.part)
}

const flip = (xs: string[] | undefined, x: string) => (xs || []).includes(x) ? (xs || []).filter(v => v !== x) : [...(xs || []), x]

/** Choose a token, or un-choose it when it is chosen. Choosing brings a left-out choice back. */
export function toggleToken(c: ChoiceShape, s: ChoiceState | null | undefined, t: Token): ChoiceState | null {
  const base: ChoiceState = s?.off ? { add: s.add } : { ...(s || {}) }
  if (t.kind === 'value') base.values = flip(base.values, t.value)
  else if (t.kind === 'zone') base.zones = flip(base.zones, t.zone)
  else base.groups = { ...(base.groups || {}), [t.facet]: flip(base.groups?.[t.facet], t.part) }
  return cleanState(c, base)
}

/** Back to how the choice starts; the user's own options stay in its list. */
export function resetState(s: ChoiceState | null | undefined): ChoiceState | null {
  return s?.add?.length ? { add: s.add } : null
}

export function leaveOut(s: ChoiceState | null | undefined, c?: { starts_off?: boolean } | null): ChoiceState | null {
  if (c?.starts_off) return resetState(s)   // how it starts
  return s?.add?.length ? { off: true, add: s.add } : { off: true }
}

/** "Any", for a choice that starts left out: drawn from all its options. */
export function turnOn(s: ChoiceState | null | undefined): ChoiceState {
  return { on: true, ...(s?.add?.length ? { add: s.add } : {}) }
}

// Words ----------------------------------------------------------------------------------

/** An option as a pill, chip or row says it: its short form when it has one. */
export function valueText(pool: ChoicePool | null | undefined, value: string): string {
  return pool?.short?.[value] || shownOption(value)
}

/** A group's name as its chip reads. */
export function partLabel(part: string): string {
  return part.replace(/_/g, ' ')
}

function zoneTitle(c: ProgramChoice, zone: string): string {
  return c.zones?.find(z => z.id === zone)?.title || `Any ${c.label.toLowerCase()}`
}

/** A chosen token in words: "sporty" as "any sporty", a zone by its title, an option short. */
export function tokenText(c: ProgramChoice, pool: ChoicePool | null | undefined, t: Token): string {
  if (t.kind === 'value') return valueText(pool, t.value)
  if (t.kind === 'group') return `any ${partLabel(t.part)}`
  return zoneTitle(c, t.zone)
}

/** A slot's own words, drawn as they are. Only for a slot with one choice. */
export function asWrittenState(slot: Pick<ProgramSlot, 'words'>, s?: ChoiceState | null): ChoiceState {
  return { values: [slot.words], ...(s?.add?.length ? { add: s.add } : {}) }
}
export function isAsWritten(slot: Pick<ProgramSlot, 'words'> | null | undefined, s: ChoiceState | null | undefined): boolean {
  return !!slot && !!s && !s.off && !s.zones?.length && !Object.keys(s.groups || {}).length
    && s.values?.length === 1 && s.values[0] === slot.words
}

/** What the pill says after its label; '' when the label says it all. */
export function pillValue(c: ProgramChoice, pool: ChoicePool | null | undefined, s: ChoiceState | null | undefined,
                          slot?: ProgramSlot | null): string {
  if (!s || isOff(c, s)) return ''
  if (isAsWritten(slot, s)) return 'as written'
  const tokens = tokensOf(s)
  if (!tokens.length) return ''
  if (tokens.every(t => t.kind === 'value')) {
    return valueText(pool, (tokens[0] as { value: string }).value) + (tokens.length > 1 ? ` +${tokens.length - 1}` : '')
  }
  if (tokens.length === 1) return tokens[0].kind === 'group' ? partLabel(tokens[0].part) : tokenText(c, pool, tokens[0])
  return `${tokens.length} chosen`
}

/** "No light": the label of something left out. */
export function offLabel(label: string): string {
  return `No ${label.charAt(0).toLowerCase()}${label.slice(1)}`
}

// Colors -----------------------------------------------------------------------------------

/** The outfit colors list: its values read as swatches. */
export const PALETTE_CLS = 'person.palette'

// The palette list's color names.
const HEX: Record<string, string> = {
  beige: '#d9c7a7', black: '#1b1b1d', 'blue-gray': '#6e8194', 'blush pink': '#eebfc3', 'brick red': '#a0432f', burgundy: '#6d1f2f',
  'butter yellow': '#f2dd8a', camel: '#b98b56', charcoal: '#3a3d42', chestnut: '#7b4631', 'chocolate brown': '#4b2e22', 'cobalt blue': '#1f4fc4',
  cocoa: '#6a4a3c', coral: '#f0745f', cream: '#f1e8d2', 'dark teal': '#12525a', 'deep teal': '#0f5f66', 'dusty blue': '#7f9bb5',
  'dusty rose': '#c48a91', ecru: '#d8ceb2', eggplant: '#43264a', 'electric blue': '#1a6bff', 'electric purple': '#9a2bff', espresso: '#33221b',
  'forest green': '#24523a', 'golden yellow': '#e5b22c', gray: '#8b8e93', 'heather gray': '#a9abb0', 'hot pink': '#f0308b', ivory: '#f4efe1',
  'jet black': '#0d0d0f', lavender: '#b3a2d8', mauve: '#a37d92', mustard: '#c99a26', navy: '#1c2c52', 'neon green': '#4cff3a',
  'neon orange': '#ff7a1a', 'neon pink': '#ff3fb4', 'neon red': '#ff2a3a', 'neon yellow': '#f3ff2e', oatmeal: '#d6cab4', 'off-white': '#eeeae0',
  olive: '#6c6f36', 'pale blue': '#bcd6ea', 'pale lavender': '#d9d0ee', 'pale mint': '#c9ecd9', 'pale peach': '#f6d6c0', 'pearl gray': '#cfd0d2',
  plum: '#5c2a52', 'powder blue': '#a9c8e4', rust: '#a8502a', sage: '#9aa88a', sand: '#d3bf98', scarlet: '#d3202c',
  seafoam: '#93d6bd', 'silver gray': '#b4b7bb', 'slate blue': '#566b8c', 'slate gray': '#5b6570', tan: '#c3a076', tangerine: '#f28a1c',
  taupe: '#8d7f73', terracotta: '#bf6b4a', turquoise: '#2bbfc0', violet: '#7a48c8', white: '#f7f7f5',
}

/** A palette value ("burgundy, cream and charcoal") as its colors, when every one is known. */
export function swatchesOf(value: string): string[] | null {
  const names = value.split(/, | and /).map(n => n.trim())
  const hex = names.map(n => HEX[n])
  return hex.length && hex.every(Boolean) ? hex : null
}

// Pills ------------------------------------------------------------------------------------

export interface Pill {
  id: string
  /** What clicking it opens: a slot (its builder or chooser), or one choice's chooser. */
  open: { slot: string } | { choice: string }
  label: string
  value: string
  swatches: string[] | null
  title: string
  changed: boolean
  /** The choices its × puts back. */
  resets: string[]
  /** A person (or camera) with several details chosen, as one pill. */
  folded: boolean
  /** Its slot is still being read, or went in as written because it couldn't be. */
  pending?: 'reading' | 'written'
}

export interface ChoiceWorld {
  slots: ProgramSlot[]
  choices: ProgramChoice[]
  states: ProgramChoices
  pools: Record<string, ChoicePool>
}

/** Slots whose labels repeat, numbered in order ("Friend 1", "Friend 2"); the rest as they are. */
export function numberRepeats(slots: ProgramSlot[]): ProgramSlot[] {
  const count = new Map<string, number>()
  for (const s of slots) count.set(s.label, (count.get(s.label) || 0) + 1)
  const seen = new Map<string, number>()
  return slots.map((s) => {
    if ((count.get(s.label) || 0) < 2) return s
    const k = (seen.get(s.label) || 0) + 1
    seen.set(s.label, k)
    return { ...s, label: `${s.label} ${k}` }
  })
}

/** A slot whose card lists details (a person, an animal, a camera) rather than options. */
export function isBuilder(slot: ProgramSlot): boolean {
  return slot.kind === 'person' || slot.kind === 'animal' || slot.kind === 'camera' || slot.details.length > 1
}

/** Three or more of one person's details chosen: one pill for the person. */
export const FOLD = 3

export function pillsOf(w: ChoiceWorld): Pill[] {
  const byId = new Map(w.choices.filter(c => !c.hidden).map(c => [c.id, c]))
  const st = (id: string) => w.states[id]
  const pool = (id: string) => w.pools[id]
  const builders = w.slots.filter(isBuilder).length
  const out: Pill[] = []
  const inSlot = new Set<string>()

  function choicePill(c: ProgramChoice, label: string, slot: ProgramSlot | null, open: Pill['open']): Pill {
    const s = st(c.id)
    const off = isOff(c, s)
    const value = pillValue(c, pool(c.id), s, slot)
    const tokens = tokensOf(s)
    const swatches = c.cls === PALETTE_CLS && tokens.length === 1 && tokens[0].kind === 'value' ? swatchesOf(tokens[0].value) : null
    const shown = off ? offLabel(label) : label
    return {
      id: c.id, open, label: shown, value, swatches, changed: isChanged(s), resets: [c.id], folded: false,
      title: [shown, ...tokens.map(t => tokenText(c, pool(c.id), t))].join('\n'),
    }
  }

  for (const slot of [...w.slots].sort((a, b) => a.n - b.n)) {
    const details = slot.details.map(id => byId.get(id)).filter((c): c is ProgramChoice => !!c)
    details.forEach(c => inSlot.add(c.id))
    // A slot still being read (or read as written) is a pill with its label and nothing chosen yet.
    if (!details.length) {
      const pending = slot.degraded || slot.state === 'ready' ? 'written' : 'reading'
      out.push({ id: slot.id, open: { slot: slot.id }, label: slot.label, value: pending === 'written' ? 'as written' : '',
        swatches: null, changed: false, resets: [], folded: false, title: slot.label, pending })
      continue
    }
    if (!isBuilder(slot)) {
      if (details[0]) out.push(choicePill(details[0], slot.label, slot, { slot: slot.id }))
      continue
    }
    const ids = details.map(c => c.id)
    const changed = details.filter(c => isChanged(st(c.id)))
    const base = { id: slot.id, open: { slot: slot.id }, swatches: null, resets: ids }
    if (details.length && details.every(c => isOff(c, st(c.id))) && details.some(c => st(c.id)?.off)) {
      out.push({ ...base, label: slot.label, value: 'as written', title: `${slot.label}\nas written`, changed: true, folded: false })
    } else if (changed.length >= FOLD) {
      const said = changed.map(c => isOff(c, st(c.id)) ? offLabel(c.label).toLowerCase() : pillValue(c, pool(c.id), st(c.id)) || 'any')
      const lines = changed.map((c, i) => `${c.label}: ${said[i]}`)
      out.push({ ...base, label: slot.label, value: said.join(', '), title: [slot.label, ...lines].join('\n'), changed: true, folded: true })
    } else {
      out.push({ ...base, label: slot.label, value: '', title: slot.label, changed: false, folded: false })
      for (const c of changed) {
        const label = builders > 1 ? `${slot.label}’s ${c.label.toLowerCase()}` : c.label
        out.push(choicePill(c, label, null, { choice: c.id }))
      }
    }
  }
  // The user's own {a|b} lists.
  for (const c of byId.values()) {
    if (inSlot.has(c.id) || c.slot || c.follows) continue
    out.push(choicePill(c, c.label, null, { choice: c.id }))
  }
  return out
}

/** How many choices are changed, of those the pills show. */
export function changedCount(w: ChoiceWorld): number {
  return new Set(pillsOf(w).flatMap(p => p.resets).filter(id => isChanged(w.states[id]))).size
}
