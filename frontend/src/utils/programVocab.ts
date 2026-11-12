/**
 * Fluent vocabulary lists, frontend side: what the option picker filters by and the
 * dev vocabulary browser shows. Pure functions only, so they test without a DOM.
 */

/** `opt_in`: a value drawn only when asked for (an age under 18 the prompt didn't ask for). */
export type VocabTier = 'typical' | 'plausible' | 'unusual' | 'generated' | 'opt_in'

/** Choices with more options than this get a search field. */
export const MANY_OPTIONS = 12

/** The most rows a card renders at once; a longer list is narrowed by searching. */
export const MAX_ROWS = 150

export const TIER_ORDER: VocabTier[] = ['typical', 'plausible', 'unusual', 'generated', 'opt_in']

/** A list value as the picker shows it: a template's color slots ({main}, {accent},
 *  {neutral}) read as "…", since its colors come from the Colors choice. */
export function shownOption(text: string): string {
  return text.replace(/\{(?:main|accent|neutral)\}/g, '…').replace(/\s{2,}/g, ' ').trim()
}

/** Case-insensitive; every word in the query must appear somewhere in the option. */
export function matchesQuery(text: string, query: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  if (!words.length) return true
  const t = text.toLowerCase()
  return words.every(w => t.includes(w))
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
