import { ref } from 'vue'
import type { Router } from 'vue-router'
import { useProvidersApi, type ProviderTool } from './useProvidersApi'
import { frecencyFor } from './useRecentEntities'
import { useWorkspaceTabs, toolInstanceRoute, type WorkspaceTab } from './useWorkspaceTabs'

/**
 * Shared search logic for the global search omnibox and the /search page.
 *
 * Entity names (chats/flows/boards/projects/presets) are matched by the
 * backend at GET /api/search. Tools are matched client-side from the cached
 * catalog. Assets come in TWO flavors, reflecting the app's duality:
 * PROMPT matches (word-boundary text match on generation/extracted prompts)
 * and VISUAL matches (CLIP text-to-image similarity). Captions are dead —
 * search never touches the caption path.
 */

export interface SearchMediaRef {
  media_id: number
  file_hash: string | null
}

export interface EntitySearchHit {
  id: number
  name: string
  updated_at: string | null
  project_id: number | null
  tool_id: string | null // presets only
  thumbnail?: SearchMediaRef | null // chats: latest generated media
  preview_items?: SearchMediaRef[] | null // boards: mosaic preview
}

export interface EntitySearchResults {
  query: string
  chats: EntitySearchHit[]
  flows: EntitySearchHit[]
  boards: EntitySearchHit[]
  projects: EntitySearchHit[]
  presets: EntitySearchHit[]
}

export interface MediaSearchHit {
  id: number
  file_hash: string
  file_format: string
  [key: string]: any
}

const EMPTY_ENTITY_RESULTS: EntitySearchResults = {
  query: '',
  chats: [],
  flows: [],
  boards: [],
  projects: [],
  presets: [],
}

// --- Omnibox focus bus (Cmd+K in App.vue → the TopBar search field) ---

const focusRequests = ref(0)

export function requestGlobalSearchFocus() {
  focusRequests.value++
}

export function useGlobalSearchFocusSignal() {
  return focusRequests
}

// --- Matching helpers ---

/** Lowercase and strip separators so "flux2" matches "Flux.2". */
function normalizeForMatch(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '')
}

/**
 * Token match: every whitespace-separated query token must appear in the
 * normalized name, in any order ("flux2 pro" matches "Flux.2 Space Pro").
 * Mirrors the backend's /api/search semantics.
 */
function rankNameMatches<T>(
  items: T[],
  q: string,
  nameOf: (item: T) => string,
  tieBreak: (item: T) => number,
  limit: number,
): T[] {
  const tokens = q.split(/\s+/).map(normalizeForMatch).filter(Boolean)
  if (tokens.length === 0) return []
  const joined = tokens.join('')
  const scored: Array<{ item: T; prefix: number; contiguous: number; tie: number }> = []
  for (const item of items) {
    const name = normalizeForMatch(nameOf(item))
    if (!tokens.every(t => name.includes(t))) continue
    scored.push({
      item,
      prefix: name.startsWith(joined) ? 0 : 1,
      contiguous: name.includes(joined) ? 0 : 1,
      tie: tieBreak(item),
    })
  }
  return scored
    .sort((a, b) => a.prefix - b.prefix || a.contiguous - b.contiguous || b.tie - a.tie)
    .slice(0, limit)
    .map(m => m.item)
}

export function useGlobalSearch() {
  const { fetchProvidersAndTools } = useProvidersApi()

  async function searchEntities(q: string, limit = 8, projectId?: number | null): Promise<EntitySearchResults> {
    if (!q.trim()) return { ...EMPTY_ENTITY_RESULTS }
    const params = new URLSearchParams({ q, limit: String(limit) })
    if (projectId != null) params.set('project_id', String(projectId))
    const response = await fetch(`/api/search?${params}`)
    if (!response.ok) throw new Error(`Search failed: ${response.status}`)
    return await response.json()
  }

  /**
   * Match tools from the cached provider catalog, frecency-boosted. Tokens
   * match across name AND provider ("ltx comfy" → LTX tools on ComfyUI —
   * both are visible on the result row, so both are fair game).
   */
  async function searchTools(q: string, limit = 6): Promise<ProviderTool[]> {
    if (!q.trim()) return []
    const { tools } = await fetchProvidersAndTools()
    return rankNameMatches(
      tools,
      q,
      t => `${t.name || ''} ${t.provider_name || ''}`,
      t => frecencyFor('tool', t.full_tool_id),
      limit,
    )
  }

  /**
   * Open tool-instance tabs matching the query (custom name AND tool name are
   * both fair game — a renamed "Hands" instance is findable either way).
   * Ranked by recency of activation. These are "switch to" results: they rank
   * above catalog tools, which are the open-fresh gesture.
   */
  function searchOpenToolInstances(q: string, limit = 5, projectId?: number | null): WorkspaceTab[] {
    if (!q.trim()) return []
    const { tabs } = useWorkspaceTabs()
    const instances = (tabs.value as WorkspaceTab[]).filter(t =>
      t.type === 'tool' && !!t.instanceId &&
      (projectId == null || (t.projectId ?? null) === projectId)
    )
    return rankNameMatches(
      instances,
      q,
      t => `${t.customName || ''} ${t.displayName || ''}`,
      t => t.lastActivatedAt ?? 0,
      limit,
    )
  }

  /** Assets whose generation/extracted PROMPT matches the query (word-boundary). */
  async function searchMediaByPrompt(q: string, pageSize = 6, projectId?: number | null): Promise<MediaSearchHit[]> {
    if (!q.trim()) return []
    const params = new URLSearchParams({
      prompt_query: q,
      page: '1',
      page_size: String(pageSize),
      sort_by: 'created_desc',
    })
    if (projectId != null) params.set('project_id', String(projectId))
    const response = await fetch(`/api/media?${params}`)
    if (!response.ok) return []
    const data = await response.json()
    return data.items || []
  }

  /** Assets that VISUALLY match the query via CLIP text-to-image similarity. */
  async function searchMediaVisual(q: string, pageSize = 6, projectId?: number | null): Promise<MediaSearchHit[]> {
    if (!q.trim()) return []
    const params = new URLSearchParams({
      similar_to_text: q,
      similarity_cutoff: 'auto',
      page: '1',
      page_size: String(pageSize),
    })
    if (projectId != null) params.set('project_id', String(projectId))
    const response = await fetch(`/api/media?${params}`)
    if (!response.ok) return []
    const data = await response.json()
    return data.items || []
  }

  return { searchEntities, searchTools, searchOpenToolInstances, searchMediaByPrompt, searchMediaVisual }
}

// --- Navigation ---

export type SearchResultKind =
  | 'tool' | 'chat' | 'flow' | 'board' | 'project' | 'preset'

/**
 * Navigate to a search result. Workspace-tab creation and recents recording
 * happen automatically via the sidebar's route watcher.
 *
 * `projectId` (scope chip): tools and presets open the PROJECT-SCOPED flavor
 * of the tool — its own instance with project presets/settings — by carrying
 * project_id on the route, same as the sidebar's project tool tabs.
 */
export function openSearchResult(
  router: Router,
  kind: SearchResultKind,
  result: { id?: number | string; tool_id?: string | null; full_tool_id?: string },
  projectId?: number | null,
  opts?: { forceNewInstance?: boolean },
) {
  const projectQuery = projectId != null ? { project_id: String(projectId) } : {}
  switch (kind) {
    case 'tool': {
      const fullToolId = String(result.full_tool_id ?? result.id)
      if (opts?.forceNewInstance) {
        // Explicit open-fresh gesture (a catalog row in the omnibox results):
        // mint a new instance instead of letting the router guard focus the
        // most-recent open one.
        const { resolveToolInstance } = useWorkspaceTabs()
        const { instanceId } = resolveToolInstance(fullToolId, projectId ?? null, { forceNew: true })
        router.push(toolInstanceRoute(fullToolId, projectId ?? null, instanceId))
        break
      }
      router.push({
        name: 'tool',
        params: { fullToolId },
        query: { ...projectQuery },
      })
      break
    }
    case 'chat':
      router.push({ name: 'chat', params: { id: String(result.id) } })
      break
    case 'flow':
      router.push({ name: 'flow', params: { id: String(result.id) } })
      break
    case 'board':
      router.push({ name: 'board-detail', params: { id: String(result.id) } })
      break
    case 'project':
      router.push({ name: 'project-overview', params: { id: String(result.id) } })
      break
    case 'preset':
      // Opens the parent tool; ToolView applies the preset from the query.
      router.push({
        name: 'tool',
        params: { fullToolId: String(result.tool_id) },
        query: { preset_id: String(result.id), ...projectQuery },
      })
      break
  }
}

/**
 * Split a label into segments for match highlighting, honoring the loose
 * matcher: each query token's first occurrence in the NORMALIZED label is
 * highlighted, mapped back to original character positions ("flux2 pro"
 * highlights "Flux.2" and "Pro" in "Flux.2 Space Pro").
 */
export function matchSegments(label: string, q: string): Array<{ text: string; match: boolean }> {
  const tokens = q.split(/\s+/).map(normalizeForMatch).filter(Boolean)
  if (!label || tokens.length === 0) return [{ text: label, match: false }]

  // Normalized string with a map back to original indices.
  const normChars: string[] = []
  const origIndex: number[] = []
  for (let i = 0; i < label.length; i++) {
    const c = label[i].toLowerCase()
    if (/[a-z0-9]/.test(c)) {
      normChars.push(c)
      origIndex.push(i)
    }
  }
  const normalized = normChars.join('')

  const marked = new Array(label.length).fill(false)
  let any = false
  for (const token of tokens) {
    const at = normalized.indexOf(token)
    if (at === -1) continue
    any = true
    for (let j = at; j < at + token.length; j++) marked[origIndex[j]] = true
  }
  if (!any) return [{ text: label, match: false }]

  const segments: Array<{ text: string; match: boolean }> = []
  let start = 0
  for (let i = 1; i <= label.length; i++) {
    if (i === label.length || marked[i] !== marked[start]) {
      segments.push({ text: label.slice(start, i), match: marked[start] })
      start = i
    }
  }
  return segments
}
