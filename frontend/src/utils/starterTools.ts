import { isStimmaCloudTool } from './stimmaCloud'

/**
 * Starter tool recommendations for the home screen.
 *
 * When the user has no tool usage history yet, we pick a small set of
 * known-good model families from whatever tools are actually installed,
 * fuzzy-matched by name so local naming variants still hit (e.g.
 * "LTX-2.3 Image to Video" matches the LTX entry). Restricted to
 * text-to-image / image-to-image / image-to-video so recommendations stay
 * beginner-shaped, with coverage across those tasks — text-to-image first,
 * since it's the only one that needs no input media.
 *
 * At most one tool per family (and per name, for unmatched tools) so a
 * library full of variants — Klein 4B, Klein 9B, cloud + local — yields
 * variety instead of near-duplicates.
 */

export const STARTER_TASK_TYPES = ['text-to-image', 'image-to-image', 'image-to-video']

// Ranked: earlier entries win when several installed tools compete for the
// same task slot. `family` is the dedupe key — one pick per family, so a
// weaker pattern for the same family (e.g. Klein 4B via the bare /klein/
// entry) can never join its favorite sibling, only stand in when the
// favorite is absent. The top tier is the fan-favorites list; the tier
// below it exists so unusual libraries still get sane picks.
const STARTER_FAMILIES: { family: string; pattern: RegExp }[] = [
  // Fan favorites
  { family: 'klein', pattern: /klein[\s._-]*9b|9b[\s._-]*klein/i },
  { family: 'nano-banana', pattern: /nano[\s._-]?banana/i },
  { family: 'ltx', pattern: /\bltx/i },
  { family: 'kling', pattern: /\bkling/i },
  { family: 'krea', pattern: /\bkrea/i },
  { family: 'z-image', pattern: /z[\s._-]?image/i },
  // Respectable stand-ins when favorites aren't installed
  { family: 'seedream', pattern: /seedream/i },
  { family: 'qwen-image', pattern: /qwen[\s._-]?image/i },
  { family: 'wan', pattern: /\bwan\b/i },
  // Last-resort variants of favorite lines (Klein 4B, Flux Flex, ...)
  { family: 'klein', pattern: /klein/i },
  { family: 'flux', pattern: /\bflux\b/i },
  { family: 'sd', pattern: /stable[\s._-]?diffusion|sd[\s._-]?xl/i },
]

interface StarterToolLike {
  full_tool_id: string
  name?: string
  task_type?: string | null
  task_types?: string[] | null
}

export interface StarterPick<T extends StarterToolLike = StarterToolLike> {
  tool: T
  /** The starter task this pick covers (drives the card's task badge). */
  taskType: string
}

export function toolTaskTypes(tool: StarterToolLike): string[] {
  if (tool.task_types?.length) return tool.task_types
  return tool.task_type ? [tool.task_type] : []
}

export function pickStarterTools<T extends StarterToolLike>(tools: T[], count = 4): StarterPick<T>[] {
  const ranked = tools
    .filter(t => toolTaskTypes(t).some(tt => STARTER_TASK_TYPES.includes(tt)))
    .map(tool => {
      const idx = STARTER_FAMILIES.findIndex(f => f.pattern.test(tool.name || ''))
      return { tool, rank: idx === -1 ? Number.MAX_SAFE_INTEGER : idx, family: idx === -1 ? null : STARTER_FAMILIES[idx].family }
    })

  // Unmatched tools still rank (cloud/featured first, then name) so a library
  // of exotic tools yields a weird starting point rather than none.
  const cmp = (a: (typeof ranked)[number], b: (typeof ranked)[number]) =>
    a.rank - b.rank
    || Number(isStimmaCloudTool(b.tool)) - Number(isStimmaCloudTool(a.tool))
    || (a.tool.name || '').localeCompare(b.tool.name || '')

  // One pick per family — Klein 4B and Klein 9B are near-duplicates, not
  // variety. Unmatched tools dedupe by normalized name instead (cloud and
  // local copies of the same model).
  const dedupeKey = (entry: (typeof ranked)[number]) =>
    entry.family ? `family:${entry.family}` : `name:${(entry.tool.name || '').toLowerCase().trim()}`

  const picked: StarterPick<T>[] = []
  const seenKeys = new Set<string>()
  const take = (entry: (typeof ranked)[number], taskType: string) => {
    seenKeys.add(dedupeKey(entry))
    picked.push({ tool: entry.tool, taskType })
  }

  // Coverage first: one tool per starter task, in order.
  for (const task of STARTER_TASK_TYPES) {
    if (picked.length >= count) break
    const pool = ranked
      .filter(r => !seenKeys.has(dedupeKey(r)) && toolTaskTypes(r.tool).includes(task))
      .sort(cmp)
    if (pool.length) take(pool[0], task)
  }

  // Fill remaining slots with the next best unused candidates.
  for (const r of ranked.filter(r => !seenKeys.has(dedupeKey(r))).sort(cmp)) {
    if (picked.length >= count) break
    take(r, toolTaskTypes(r.tool).find(tt => STARTER_TASK_TYPES.includes(tt)) || 'text-to-image')
  }

  return picked
}
