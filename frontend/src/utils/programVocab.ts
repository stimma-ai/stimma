/**
 * Fluent vocabulary lists, frontend side: what the option picker groups by and the
 * dev vocabulary browser shows. Pure functions only, so they test without a DOM.
 */

/** `opt_in`: a value drawn only when asked for (an age under 18 the prompt didn't ask for):
 *  the picker offers it in its own group, and picking it draws it. */
export type VocabTier = 'typical' | 'plausible' | 'unusual' | 'generated' | 'opt_in'

/** A bound pick's list, as the pools endpoint describes it (keyed by choice id). */
export interface ChoiceVocab {
  cls: string
  label: string
  closed: boolean
  tiers: Record<string, VocabTier>
}

/** Picks with more options than this get the search-and-scroll picker. */
export const MANY_OPTIONS = 12

export const TIER_ORDER: VocabTier[] = ['typical', 'plausible', 'unusual', 'generated', 'opt_in']

/** What a person reads for each tier's group in the picker. */
export const TIER_LABEL: Record<VocabTier, string> = {
  typical: 'Usual',
  plausible: 'Less usual',
  unusual: 'Rare',
  generated: 'More ideas',
  opt_in: 'Only when picked',
}

/** Case-insensitive; every word in the query must appear somewhere in the option. */
/** A list value as the picker shows it: a template's color slots ({main}, {accent},
 *  {neutral}) read as "…", since its colors come from the Colors choice. */
export function shownOption(text: string): string {
  return text.replace(/\{(?:main|accent|neutral)\}/g, '…').replace(/\s{2,}/g, ' ').trim()
}

export function matchesQuery(text: string, query: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  if (!words.length) return true
  const t = text.toLowerCase()
  return words.every(w => t.includes(w))
}

export interface OptionGroup {
  tier: VocabTier
  label: string
  /** Options in this group that pass the query (all of them when there is none). */
  items: string[]
  /** All options in the group, filter or not. */
  total: number
}

export interface OptionLayout {
  /** Pinned options, always first and never filtered out. */
  pinned: string[]
  /** Tiered groups (bound picks); empty for a flat list. */
  groups: OptionGroup[]
  /** The flat list (unbound picks), filtered, pinned left out. */
  flat: string[]
  /** How many unpinned options pass the query. */
  hits: number
}

/**
 * Lay out a pick's options for the picker. Pinned values come first whatever the
 * query; the rest are filtered, and grouped by tier when the pick has a list.
 * An option the list doesn't know (one the person added) sits with the usual ones.
 */
export function layoutOptions(options: string[], pinned: Iterable<string>, query: string, tiers?: Record<string, VocabTier> | null): OptionLayout {
  const pinSet = new Set(pinned)
  const pinnedOut = options.filter(o => pinSet.has(o))
  const rest = options.filter(o => !pinSet.has(o))
  if (!tiers) {
    const flat = rest.filter(o => matchesQuery(o, query))
    return { pinned: pinnedOut, groups: [], flat, hits: flat.length }
  }
  const byTier = new Map<VocabTier, string[]>(TIER_ORDER.map(t => [t, []]))
  for (const o of rest) {
    const t = tiers[o]
    byTier.get(t && byTier.has(t) ? t : 'typical')!.push(o)
  }
  let hits = 0
  const groups: OptionGroup[] = []
  for (const tier of TIER_ORDER) {
    const all = byTier.get(tier)!
    if (!all.length) continue
    const items = all.filter(o => matchesQuery(o, query))
    hits += items.length
    groups.push({ tier, label: TIER_LABEL[tier], items, total: all.length })
  }
  return { pinned: pinnedOut, groups, flat: [], hits }
}

/** Whether a tier group shows its options: while searching, exactly the groups with hits. */
export function groupOpen(group: OptionGroup, query: string, opened: Record<string, boolean>): boolean {
  if (query.trim()) return group.items.length > 0
  return opened[group.tier] ?? group.tier === 'typical'
}

// The whole vocabulary (GET /prompt-programs/vocabulary), for the dev browser -------------

export interface VocabFacet { values: string[]; default: string | null; about: string }
export interface VocabNode { id: string; label: string; description: string }
export interface VocabValue {
  text: string
  tier: VocabTier
  tags?: Record<string, string[] | 'any'>
  /** Drawn only when the prompt or the person asks for it (ages under 18). */
  opt_in?: boolean
  /** An adult-coded look: never in the pools of a person under 18. */
  adult_only?: boolean
}
export interface VocabLeaf {
  id: string
  label: string
  description: string
  pos: string
  frame: string
  notes: string
  facets: string[]
  closed: boolean
  untagged: Record<string, string[]>
  values: VocabValue[]
}
export interface Vocabulary {
  version: string
  facets: Record<string, VocabFacet>
  defaults: Record<string, string>
  nodes: VocabNode[]
  leaves: VocabLeaf[]
}

/** The context a value is checked against: defaults first, then what the context sets. */
export function effectiveContext(defaults: Record<string, string | null | undefined>, context: Record<string, string | null | undefined>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries({ ...defaults, ...context })) if (v) out[k] = v
  return out
}

/** A value fits when, for each facet the context sets, its tag (else the leaf's
    `untagged`, else everything) includes the context's value. */
export function valueFits(leaf: Pick<VocabLeaf, 'untagged'>, value: Pick<VocabValue, 'tags'>, context: Record<string, string>): boolean {
  for (const [facet, want] of Object.entries(context)) {
    const fits = value.tags?.[facet] ?? leaf.untagged?.[facet] ?? 'any'
    if (fits !== 'any' && !fits.includes(want)) return false
  }
  return true
}

export interface VocabTreeNode {
  id: string
  label: string
  description: string
  children: VocabTreeNode[]
  leaves: VocabLeaf[]
  /** Values in every leaf under this node. */
  count: number
}

/** Nodes and leaves as a tree: each hangs from the longest node id that prefixes it
    (`person.outfit.casual` under `person.outfit`, under `person`). Leaves with no node
    collect under a root-level node named after their first segment. */
export function buildVocabTree(nodes: VocabNode[], leaves: VocabLeaf[]): VocabTreeNode[] {
  const all = new Map<string, VocabTreeNode>()
  for (const n of nodes) all.set(n.id, { id: n.id, label: n.label || n.id, description: n.description || '', children: [], leaves: [], count: 0 })
  const parentOf = (id: string): VocabTreeNode | null => {
    const parts = id.split('.')
    for (let i = parts.length - 1; i > 0; i--) {
      const p = all.get(parts.slice(0, i).join('.'))
      if (p) return p
    }
    return null
  }
  const roots: VocabTreeNode[] = []
  for (const n of [...all.values()].sort((a, b) => a.id.split('.').length - b.id.split('.').length)) {
    const p = parentOf(n.id)
    ;(p ? p.children : roots).push(n)
  }
  for (const leaf of leaves) {
    let p = parentOf(leaf.id)
    if (!p) {
      const top = leaf.id.split('.')[0]
      p = { id: top, label: top, description: '', children: [], leaves: [], count: 0 }
      all.set(top, p)
      roots.push(p)
    }
    p.leaves.push(leaf)
  }
  const total = (n: VocabTreeNode): number => {
    n.children.sort((a, b) => a.label.localeCompare(b.label))
    n.leaves.sort((a, b) => a.label.localeCompare(b.label))
    n.count = n.leaves.reduce((s, l) => s + l.values.length, 0) + n.children.reduce((s, c) => s + total(c), 0)
    return n.count
  }
  roots.sort((a, b) => a.label.localeCompare(b.label))
  roots.forEach(total)
  return roots
}
