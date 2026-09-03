/**
 * DOM-free helpers for the in-app folder picker.
 *
 * Paths come from whichever machine runs the backend, so every helper here
 * is separator-agnostic: a Windows server can be driven from a Mac and the
 * crumbs, names, and root matching still have to come out right.
 */

export type RootKind = 'home' | 'place' | 'volume'

export interface DirectoryEntry {
  name: string
  path: string
  is_dir: boolean
  kind?: RootKind | null
  item_count?: number | null
}

export interface PathSegment {
  name: string
  path: string
}

export interface DirectoryListing {
  /** "" for the root-of-roots listing. */
  path: string
  parent: string | null
  segments: PathSegment[]
  entries: DirectoryEntry[]
}

export interface RecentEntry {
  name: string
  path: string
}

export interface RootGroup {
  label: string
  roots: DirectoryEntry[]
}

export const MAX_RECENTS = 4

function separatorOf(path: string): '/' | '\\' {
  return path.includes('\\') && !path.includes('/') ? '\\' : '/'
}

/** Last path component, or the whole thing for a bare root like "/" or "C:\". */
export function basename(path: string): string {
  const trimmed = path.replace(/[/\\]+$/, '')
  if (!trimmed) return path
  const idx = Math.max(trimmed.lastIndexOf('/'), trimmed.lastIndexOf('\\'))
  return idx >= 0 ? trimmed.slice(idx + 1) || trimmed : trimmed
}

export function isSameOrDescendant(path: string, root: string): boolean {
  if (path === root) return true
  const rootWithSep = /[/\\]$/.test(root) ? root : root + separatorOf(root)
  return path.startsWith(rootWithSep)
}

/**
 * The sidebar root that contains `path`, longest match first so a path under
 * ~/Pictures highlights Pictures rather than Home.
 */
export function activeRootFor(path: string | null | undefined, roots: DirectoryEntry[]): string | null {
  if (!path) return null
  let best: string | null = null
  for (const root of roots) {
    if (!isSameOrDescendant(path, root.path)) continue
    if (best === null || root.path.length > best.length) best = root.path
  }
  return best
}

/** Fallback crumbs from a raw path, for listings without server segments. */
export function crumbsFromPath(path: string): PathSegment[] {
  if (!path) return []
  const sep = separatorOf(path)
  const parts = path.split(sep).filter(Boolean)
  // A Windows path starts at its drive letter, which keeps its slash.
  const drive = sep === '\\' ? parts.shift() ?? '' : ''
  const crumbs: PathSegment[] = drive ? [{ name: drive, path: drive + sep }] : [{ name: sep, path: sep }]
  let acc = drive
  for (const part of parts) {
    acc = acc + sep + part
    crumbs.push({ name: part, path: acc })
  }
  return crumbs
}

export function crumbsFor(listing: DirectoryListing | null): PathSegment[] {
  if (!listing || !listing.path) return []
  if (listing.segments?.length) return listing.segments
  return crumbsFromPath(listing.path)
}

/** Sidebar groups; empty groups are dropped, kind-less roots go last. */
export function groupRoots(roots: DirectoryEntry[]): RootGroup[] {
  const groups: RootGroup[] = [
    { label: 'Places', roots: roots.filter((r) => r.kind === 'home' || r.kind === 'place') },
    { label: 'Volumes', roots: roots.filter((r) => r.kind === 'volume') },
    { label: 'Locations', roots: roots.filter((r) => !r.kind) },
  ]
  return groups.filter((g) => g.roots.length > 0)
}

/** Most recent first, de-duplicated, capped. */
export function pushRecent(recents: RecentEntry[], path: string, max = MAX_RECENTS): RecentEntry[] {
  const next = [{ name: basename(path), path }, ...recents.filter((r) => r.path !== path)]
  return next.slice(0, max)
}

export function parseRecents(raw: string | null | undefined): RecentEntry[] {
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((r) => r && typeof r.path === 'string' && r.path)
      .map((r) => ({ name: typeof r.name === 'string' && r.name ? r.name : basename(r.path), path: r.path }))
      .slice(0, MAX_RECENTS)
  } catch {
    return []
  }
}

/** Storage key for recents, scoped to the server whose filesystem they name. */
export function recentsStorageKey(deviceId: string | null | undefined): string {
  return `stimma_folder_picker_recents:${deviceId || 'local'}`
}
