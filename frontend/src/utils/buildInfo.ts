/**
 * Build metadata (the source commit) is published beside the UI bundle, never
 * compiled into it, so identical UI source builds to identical bytes and a
 * phone's cached UI package survives server updates that leave the UI alone.
 *
 * Desktop and the dev server read `/build-info.json` from the page's origin.
 * Phones run a content-addressed package without that file; the server
 * describes the package it serves in the package manifest instead.
 */
export interface BuildInfo {
  commit: string
}

const COMMIT = /^[0-9a-f]{7,40}$/
const UNKNOWN: BuildInfo = { commit: '' }

export function parseBuildInfo(value: unknown): BuildInfo {
  const commit = value && typeof value === 'object' ? (value as { commit?: unknown }).commit : undefined
  return { commit: typeof commit === 'string' && COMMIT.test(commit) ? commit : '' }
}

type FetchLike = (url: string, init?: RequestInit) => Promise<Pick<Response, 'ok' | 'json'>>

export async function loadBuildInfo({ mobile, apiUrl = path => path, fetchImpl = fetch }: {
  mobile: boolean
  /** Resolves an `/api` path against the active backend. */
  apiUrl?: (path: string) => string
  fetchImpl?: FetchLike
}): Promise<BuildInfo> {
  const url = mobile ? apiUrl('/api/mobile-ui/manifest') : '/build-info.json'
  try {
    const response = await fetchImpl(url, { cache: 'no-cache' })
    if (!response.ok) return UNKNOWN
    const body: unknown = await response.json()
    return parseBuildInfo(mobile ? (body as { build?: unknown } | null)?.build : body)
  } catch {
    // Older servers, SPA fallbacks and offline phones simply omit the commit.
    return UNKNOWN
  }
}
