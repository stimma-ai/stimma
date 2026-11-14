/**
 * What the user chose for a prompt's slots, and what follows from it: how a slot shows in the
 * text, what its line under the prompt says, which variants its picker lists. Pure, so it
 * tests without a DOM.
 *
 * A slot is one choice (its id is the slot's). Nothing starts chosen: the slot draws from its
 * whole pool of variants. The user can pin variants (`values`), or, for a person, pick seeds
 * from the comprehensive lists (age, gender, descent), which steer the draw and the next
 * writes. A `{a|b}` list of the user's own is a choice too, with its options as values.
 */

import type {
  AgePicker, ChoicePool, ChoiceSeeds, ChoiceState, DescentPicker, PreparedProgram, ProgramChoice, ProgramChoices, ProgramSlot, Variant,
} from './programWire.ts'

type Person = ChoicePool['person']

const uniq = (xs: unknown[] | undefined) => [...new Set((xs || []).filter((x): x is string => typeof x === 'string' && !!x.trim()))]

/** The seeds as stored: empty parts dropped. Null when nothing is picked. */
export function cleanSeeds(seeds: ChoiceSeeds | null | undefined): ChoiceSeeds | null {
  if (!seeds) return null
  const values = uniq(seeds.descent?.values)
  const region = uniq(seeds.descent?.groups?.region)
  const gender = uniq(seeds.gender?.values)
  const stages = uniq(seeds.age?.values)
  const years = [...new Set((seeds.age?.years || []).filter(y => Number.isInteger(y) && y >= 0))].sort((a, b) => a - b)
  const out: ChoiceSeeds = {}
  if (values.length || region.length) out.descent = { ...(values.length ? { values } : {}), ...(region.length ? { groups: { region } } : {}) }
  if (gender.length) out.gender = { values: gender }
  if (stages.length || years.length) out.age = { ...(stages.length ? { values: stages } : {}), ...(years.length ? { years } : {}) }
  return Object.keys(out).length ? out : null
}

/** A state as stored: empty parts dropped; `off` alone with the user's own variants; `from`
    only on a single pin. Null when nothing is left. A choice of the slot's own words saved
    before (`as_written`) is no choice: it is dropped, so the slot varies again. */
export function cleanState(raw: ChoiceState | null | undefined): ChoiceState | null {
  if (!raw) return null
  const { as_written: _old, ...s } = raw as ChoiceState & { as_written?: unknown }
  const add = uniq(s.add)
  const own = add.length ? { add } : {}
  if (s.off) return { off: true, ...own }
  const values = uniq(s.values)
  const seeds = cleanSeeds(s.seeds)
  const from = values.length === 1 && typeof s.from === 'number' && !seeds ? { from: s.from } : {}
  const out: ChoiceState = {
    ...(values.length ? { values } : {}),
    ...(seeds ? { seeds } : {}),
    ...own,
    ...from,
  }
  return Object.keys(out).length ? out : null
}

/** Choices as saved (or carried from an earlier prompt), as they are read: a choice saved as
    the slot's own words (`as_written`, before that choice went) becomes no choice. The same
    object back when there is none. */
export function readChoices(saved: ProgramChoices | null | undefined): ProgramChoices {
  if (!saved) return {}
  const old = Object.entries(saved).filter(([, s]) => s && 'as_written' in (s as object))
  if (!old.length) return saved
  const out: ProgramChoices = { ...saved }
  for (const [id, s] of old) {
    const clean = cleanState(s)
    if (clean) out[id] = clean
    else delete out[id]
  }
  return out
}

/** What is sent for a state: as stored, without what only the editor uses (`from`). */
export function wireState(s: ChoiceState): ChoiceState {
  const { from: _from, ...rest } = s
  return rest
}

export function hasSeeds(s: ChoiceState | null | undefined): boolean {
  return !!cleanSeeds(s?.seeds)
}

/** The user changed what the choice draws (their own variants alone change nothing). */
export function isChanged(s: ChoiceState | null | undefined): boolean {
  return !!s && (!!s.off || !!s.values?.length || hasSeeds(s))
}

/** Back to how the choice starts; the user's own variants stay. */
export function resetState(s: ChoiceState | null | undefined): ChoiceState | null {
  return s?.add?.length ? { add: s.add } : null
}

const own = (s: ChoiceState | null | undefined) => (s?.add?.length ? { add: s.add } : {})
const seedsOf = (s: ChoiceState | null | undefined) => (s?.seeds && !s.off ? { seeds: s.seeds } : {})

/** Pin a variant, or un-pin it. Choosing brings a slot left out back. */
export function toggleValue(s: ChoiceState | null | undefined, text: string): ChoiceState | null {
  const values = s?.off ? [] : [...(s?.values || [])]
  const i = values.indexOf(text)
  if (i >= 0) values.splice(i, 1)
  else values.push(text)
  return cleanState({ values, ...seedsOf(s), ...own(s) })
}

/** "Any of these": no variant pinned; picked seeds stay. */
export function chooseAny(s: ChoiceState | null | undefined): ChoiceState | null {
  return cleanState({ ...seedsOf(s), ...own(s) })
}

/** Set these variants picked or not, together (a shift-click range, Select all): the rest of
    the picks, the seeds and the user's own stay. */
export function setPicked(s: ChoiceState | null | undefined, texts: string[], on: boolean): ChoiceState | null {
  const values = (s?.off ? [] : s?.values || []).filter(v => !texts.includes(v))
  return cleanState({ ...seedsOf(s), ...own(s), values: on ? [...values, ...texts] : values })
}

/** Add this variant to the picks (Use from an image); already picked, nothing changes. */
export function addValue(s: ChoiceState | null | undefined, text: string): ChoiceState | null {
  if (!s?.off && s?.values?.includes(text)) return cleanState(s)
  return setPicked(s, [text], true)
}

/** Add the user's own variant and pin it. */
export function addOwn(s: ChoiceState | null | undefined, text: string): ChoiceState | null {
  const v = text.trim()
  if (!v) return cleanState(s)
  const base = s?.off ? {} : s || {}
  return cleanState({ ...base, add: [v, ...(s?.add || []).filter(x => x !== v)], values: [...(base.values || []).filter(x => x !== v), v] })
}

// Seeds (a person's age, gender and descent) ------------------------------------------------

/** Every heritage the picked seeds allow ([] when no descent is picked). */
export function pickedHeritages(seeds: ChoiceSeeds | null | undefined, descent: DescentPicker | null | undefined): string[] {
  const out = new Set(seeds?.descent?.values || [])
  for (const r of seeds?.descent?.groups?.region || []) for (const h of descent?.parts.find(p => p.id === r)?.values || []) out.add(h)
  return [...out]
}

/** The year of an age list value as recorded in a variant's seeds ("24-year-old": 24, a
    newborn 0); null when it has none. */
export function yearOfAge(age: string | number | null | undefined): number | null {
  if (typeof age === 'number') return age
  if (!age) return null
  const m = /^(\d+)-year-old$/.exec(age.trim())
  if (m) return Number(m[1])
  return age.trim() === 'newborn' ? 0 : null
}

/** Every year the picked ages cover: the years of each picked stage, and the single years. */
export function pickedYears(seeds: ChoiceSeeds | null | undefined, age: AgePicker | null | undefined): number[] {
  const out = new Set(seeds?.age?.years || [])
  for (const id of seeds?.age?.values || []) for (const y of age?.stages.find(st => st.id === id)?.years || []) out.add(y)
  return [...out].sort((a, b) => a - b)
}

/** Whether a variant is what the picked seeds ask for (as the server draws). A seed facet with
    nothing picked allows anything. */
export function variantMatches(v: Variant, seeds: ChoiceSeeds | null | undefined, person: Person | null | undefined): boolean {
  const heritages = pickedHeritages(seeds, person?.descent)
  if (heritages.length && !heritages.includes(v.seeds?.descent || '')) return false
  const genders = seeds?.gender?.values || []
  if (genders.length && !genders.includes(v.seeds?.gender || '')) return false
  if (seeds?.age?.values?.length || seeds?.age?.years?.length) {
    const y = yearOfAge(v.seeds?.age)
    if (y === null || !pickedYears(seeds, person?.age).includes(y)) return false
  }
  return true
}

/** After a seed pick: pinned variants written for something the picks now rule out go, so a
    pin never contradicts the descent or gender the user just chose. A pin whose seeds aren't
    known (the user's own, kept from an image) stays. */
function dropConflicting(s: ChoiceState, pool: ChoicePool | null | undefined): ChoiceState {
  if (!s.values?.length) return s
  const byText = new Map((pool?.variants || []).map(v => [v.text, v]))
  const values = s.values.filter((t) => {
    const v = byText.get(t)
    return !v || v.own || variantMatches(v, s.seeds, pool?.person)
  })
  return { ...s, values }
}

function withSeeds(s: ChoiceState | null | undefined, seeds: ChoiceSeeds, pool: ChoicePool | null | undefined): ChoiceState | null {
  const base: ChoiceState = s?.off ? { ...own(s) } : { ...(s || {}) }
  delete base.from
  return cleanState(dropConflicting({ ...base, seeds }, pool))
}

const flip = (xs: string[] | undefined, x: string) => (xs || []).includes(x) ? (xs || []).filter(v => v !== x) : [...(xs || []), x]

/** Pick a heritage, or un-pick it. In a region picked whole, un-picking one leaves the rest. */
export function toggleHeritage(s: ChoiceState | null | undefined, heritage: string, pool: ChoicePool | null | undefined): ChoiceState | null {
  const descent = pool?.person?.descent
  let values = [...(s?.seeds?.descent?.values || [])]
  let regions = [...(s?.seeds?.descent?.groups?.region || [])]
  const whole = descent?.parts.find(p => regions.includes(p.id) && p.values.includes(heritage))
  if (whole) {
    regions = regions.filter(r => r !== whole.id)
    values = uniq([...values, ...whole.values.filter(h => h !== heritage)])
  } else values = flip(values, heritage)
  return withSeeds(s, { ...(s?.seeds || {}), descent: { values, groups: { region: regions } } }, pool)
}

/** Pick a region whole, or un-pick it. Picked whole, its heritages picked one by one go. */
export function toggleRegion(s: ChoiceState | null | undefined, region: string, pool: ChoicePool | null | undefined): ChoiceState | null {
  const members = new Set(pool?.person?.descent?.parts.find(p => p.id === region)?.values || [])
  const regions = s?.seeds?.descent?.groups?.region || []
  const on = !regions.includes(region)
  const values = (s?.seeds?.descent?.values || []).filter(h => !on || !members.has(h))
  return withSeeds(s, { ...(s?.seeds || {}), descent: { values, groups: { region: flip(regions, region) } } }, pool)
}

export function toggleGender(s: ChoiceState | null | undefined, gender: string, pool: ChoicePool | null | undefined): ChoiceState | null {
  return withSeeds(s, { ...(s?.seeds || {}), gender: { values: flip(s?.seeds?.gender?.values, gender) } }, pool)
}

export function clearSeed(s: ChoiceState | null | undefined, which: 'descent' | 'gender' | 'age', pool: ChoicePool | null | undefined): ChoiceState | null {
  const seeds = { ...(s?.seeds || {}) }
  delete seeds[which]
  return withSeeds(s, seeds, pool)
}

/** Pick a life stage whole, or un-pick it. Picked whole, its single years picked one by one go. */
export function toggleStage(s: ChoiceState | null | undefined, stage: string, pool: ChoicePool | null | undefined): ChoiceState | null {
  const stages = s?.seeds?.age?.values || []
  const on = !stages.includes(stage)
  const inStage = new Set(pool?.person?.age?.stages.find(st => st.id === stage)?.years || [])
  const years = (s?.seeds?.age?.years || []).filter(y => !on || !inStage.has(y))
  return withSeeds(s, { ...(s?.seeds || {}), age: { values: flip(stages, stage), years } }, pool)
}

/** Pick a single year, or un-pick it. A year inside a stage picked whole narrows that stage
    to the year. */
export function toggleYear(s: ChoiceState | null | undefined, year: number, pool: ChoicePool | null | undefined): ChoiceState | null {
  const age = pool?.person?.age
  let stages = [...(s?.seeds?.age?.values || [])]
  let years = [...(s?.seeds?.age?.years || [])]
  const whole = stages.filter(id => age?.stages.find(st => st.id === id)?.years.includes(year))
  if (whole.length) {
    stages = stages.filter(id => !whole.includes(id))
    if (!years.includes(year)) years.push(year)
  } else years = years.includes(year) ? years.filter(y => y !== year) : [...years, year]
  return withSeeds(s, { ...(s?.seeds || {}), age: { values: stages, years } }, pool)
}

// What the picker lists ------------------------------------------------------------------------

/** A slot's variants as its picker lists them: pinned texts the pool doesn't hold (kept from an
    image) first, then the pool; with seeds picked, only the variants that match them (the
    user's own always). */
export function shownVariants(pool: ChoicePool | null | undefined, s: ChoiceState | null | undefined): Variant[] {
  const all: Variant[] = pool?.variants || (pool?.options || []).map(text => ({ text }))
  const have = new Set(all.map(v => v.text))
  const extra = (s?.values || []).filter(t => !have.has(t)).map(text => ({ text, own: true }))
  const seeds = hasSeeds(s) ? s!.seeds : null
  const listed = seeds ? all.filter(v => v.own || (s?.values || []).includes(v.text) || variantMatches(v, seeds, pool?.person)) : all
  return [...extra, ...listed]
}

/** A choice's options: a slot's variant texts, a list's options, with the user's own first. */
export function optionsOf(c: ProgramChoice, pool: ChoicePool | null | undefined, s?: ChoiceState | null): string[] {
  const base = pool?.variants ? pool.variants.map(v => v.text) : pool?.options || c.options || []
  return uniq([...(s?.add || []), ...base, ...(s?.values || [])])
}

/** A variant in pieces, the runs of the slot's own words marked `kept`, so the picker can show
    them quieter than what the writer added. The server's `keep` names those runs (`[]`: none,
    the slot is only its category word); without it, the longest run of the slot's words the
    variant holds (display only: it decides nothing). */
export function keptPieces(text: string, words: string, keep?: string[] | null, also: string[] = []): Array<{ t: string; kept?: boolean }> {
  const find = (chunk: string): [number, number] | null => {
    const parts = chunk.trim().split(/[\s-]+/).filter(Boolean).map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    if (!parts.length) return null
    const m = new RegExp(`(?<![\\w])${parts.join('[\\s-]+')}(?![\\w])`, 'i').exec(text)
    return m ? [m.index, m.index + m[0].length] : null
  }
  let spans: Array<[number, number]> = []
  if (Array.isArray(keep)) spans = keep.map(find).filter((x): x is [number, number] => !!x)
  else {
    const ws = words.trim().split(/\s+/).filter(Boolean)
    for (let len = ws.length; len > 0 && !spans.length; len--) {
      for (let i = 0; i + len <= ws.length; i++) {
        const run = ws.slice(i, i + len).join(' ')
        if (len === 1 && run.length < 4) continue
        const at = find(run)
        if (at) { spans = [at]; break }
      }
    }
  }
  for (const a of also) { const at = find(a); if (at) spans.push(at) }
  spans.sort((a, b) => a[0] - b[0])
  const out: Array<{ t: string; kept?: boolean }> = []
  let at = 0
  for (const [a, b] of spans) {
    if (a < at) continue
    if (a > at) out.push({ t: text.slice(at, a) })
    out.push({ t: text.slice(a, b), kept: true })
    at = b
  }
  if (at < text.length) out.push({ t: text.slice(at) })
  return out
}

// How a slot shows -----------------------------------------------------------------------------

/** One word for how a slot stands, for its mark in the text and its row: `varying` (drawn from
    its whole pool), `restricted` (limited to some variants or seeds), `words` (it goes in as its
    words: the server couldn't vary it), `writing` (its first variants are being written). */
export type SlotLookKind = 'varying' | 'writing' | 'restricted' | 'words'

export function lookOf(slot: Pick<ProgramSlot, 'state'> | null | undefined, s: ChoiceState | null | undefined,
                       pool?: ChoicePool | null): SlotLookKind {
  if (s?.off) return 'words'
  if (s?.values?.length || hasSeeds(s)) return 'restricted'
  const state = pool?.state || slot?.state
  if (!slot || slot.state === 'reading' || state === 'writing' || state === 'reading') return 'writing'
  if (slot.state === 'as_written') return 'words'
  return 'varying'
}

/** "trans woman" as a row says it. */
export const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

/** A person's picks as items for a row: Age (its stages, then single years), Gender, Descent
    (regions, then heritages). */
export function ageItems(s: ChoiceState | null | undefined, age: AgePicker | null | undefined): string[] {
  const stages = (s?.seeds?.age?.values || []).map(id => age?.stages.find(st => st.id === id)?.label || cap(id))
  return [...stages, ...[...(s?.seeds?.age?.years || [])].sort((a, b) => a - b).map(String)]
}
export const genderItems = (s: ChoiceState | null | undefined) => (s?.seeds?.gender?.values || []).map(cap)
export const descentItems = (s: ChoiceState | null | undefined) => [...(s?.seeds?.descent?.groups?.region || []), ...(s?.seeds?.descent?.values || [])]

/** Items read as one line: the first one or two in full, then "+27"; "years old" after single
    years alone. */
export function lineOf(items: string[], room = 34): { shown: string; more: number } {
  let f: { shown: string; more: number }
  if (items.length <= 2 && items.join(', ').length <= room * 1.6) f = { shown: items.join(', '), more: 0 }
  else {
    const k = items.length > 1 && items[0].length + items[1].length <= room ? 2 : 1
    f = { shown: items.slice(0, k).join(', '), more: items.length - k }
  }
  return items.length && items.every(i => /^\d+$/.test(i)) ? { ...f, shown: `${f.shown} years old` } : f
}
export const lineString = (items: string[]) => { const f = lineOf(items); return f.shown + (f.more ? ` +${f.more}` : '') }

export type RowValue =
  | { kind: 'writing' }
  | { kind: 'varying'; text: string }
  | { kind: 'words'; text: string }
  | { kind: 'restricted'; lines: Array<{ shown: string; more: number }> }

/** What a slot's row says: how many options its pool holds while it varies freely (the row
    reads "Varied" until it opens), what it's limited to (a person: a line each for age, gender,
    descent, then variants), its words in quotes when it can't vary, or a shimmer while its
    first variants are written. A list of the user's own counts its options. */
export function rowValue(slot: Pick<ProgramSlot, 'state' | 'words'> | null, s: ChoiceState | null | undefined,
                         pool: ChoicePool | null | undefined, options: string[] = []): RowValue {
  const kind = slot ? lookOf(slot, s, pool) : (s?.values?.length ? 'restricted' : 'varying')
  if (kind === 'words') return { kind, text: `\u201c${slot?.words || ''}\u201d` }
  if (kind === 'writing') return { kind }
  if (kind === 'restricted') {
    const person = pool?.person
    const lines = person
      ? [ageItems(s, person.age), genderItems(s), descentItems(s), s?.values || []]
      : [s?.values || []]
    return { kind, lines: lines.filter(l => l.length).map(l => lineOf(l)) }
  }
  const n = pool?.variants?.length ?? (pool?.options?.length || options.length)
  return { kind: 'varying', text: `${n} option${n === 1 ? '' : 's'}` }
}

/** How many of a choice's options are in play: `of` the pool's `total` when it's limited to
    some (the picks, or the variants a person's seeds match), null while it draws from all. */
export function inPlayCount(pool: ChoicePool | null | undefined, s: ChoiceState | null | undefined,
                            total: number): { of: number; total: number } | null {
  if (s?.values?.length) return { of: s.values.length, total }
  if (!hasSeeds(s)) return null
  const of = (pool?.variants || []).filter(v => !v.own && variantMatches(v, s?.seeds, pool?.person)).length
  return { of, total }
}

/** The choice of the `n`-th list of the user's own in the text (1-based, as `findLists` counts
    them), given the options found there: the list choice in the same place with the same
    options, else the one list with those options. Null while the program doesn't have it
    (just typed, or edited since it was prepared). */
export function listChoiceAt(found: Array<{ items: string[] }>, choices: ProgramChoice[], n: number): ProgramChoice | null {
  const at = found[n - 1]
  if (!at) return null
  const lists = choices.filter(c => c.source === 'list' && !c.slot)
  const key = JSON.stringify(at.items.map(x => x.trim()))
  const same = (c: ProgramChoice) => JSON.stringify((c.options || []).map(x => x.trim())) === key
  if (lists[n - 1] && same(lists[n - 1])) return lists[n - 1]
  const match = lists.filter(same)
  return match.length === 1 ? match[0] : null
}

// Programs across edits ------------------------------------------------------------------------

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
    `mug_2`). Null when the answer doesn't say (it wasn't matched against `prev`). */
export function carriedIds(prev: Shown | null | undefined, next: Landed): Record<string, string> | null {
  if (!prev?.key || !next.from || next.from !== prev.key) return null
  const before = new Set((prev.slots || []).map(s => s.id))
  const have = new Set((next.choices || []).map(c => c.id))
  const out: Record<string, string> = {}
  for (const s of next.slots || []) if (s.was && before.has(s.was) && have.has(s.id)) out[s.was] = s.id
  for (const c of next.choices || []) if (c.source === 'list' && c.was) out[c.was] = c.id
  return out
}

/** Where an answer for slot `id` of the program `start` belongs now: the same id while the
    program is still `start`, else the id that slot has in the program prepared after the edit
    (carriedIds), or null when that slot is gone or the program moved on further (the answer is
    dropped, never shown on another slot: two `<mug>`s with the first removed leave `mug`, which
    must not get the removed one's variants). */
export function followId(id: string, start: Shown | null | undefined,
                         now: (Landed & Pick<PreparedProgram, 'key'>) | null | undefined): string | null {
  if (!start?.key || !now?.key) return null
  if (now.key === start.key) return id
  const ids = carriedIds(start, now)
  return ids && id in ids ? ids[id] : null
}

/** Values kept per choice id (what was chosen, the variants shown), moved to the ids a newly
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
