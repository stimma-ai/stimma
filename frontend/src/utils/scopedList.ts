/**
 * Chats, boards, flows and saved views are strictly scoped: a project lists
 * its own, and the top level lists only items with no project
 * (`project_id=none`). An older server that rejects `none` gets the
 * unfiltered request and the result is filtered here instead.
 */
export function scopeParam(projectId: number | null | undefined): string {
  return projectId != null ? String(projectId) : 'none'
}

function unscopedOnly(data: any) {
  const keep = (item: any) => (item?.project_id ?? null) === null
  if (Array.isArray(data)) return data.filter(keep)
  if (data && Array.isArray(data.items)) return { ...data, items: data.items.filter(keep) }
  return data
}

export async function fetchScopedJson(path: string, params: URLSearchParams, projectId: number | null | undefined) {
  const scoped = new URLSearchParams(params)
  scoped.set('project_id', scopeParam(projectId))
  let response = await fetch(`${path}?${scoped}`)
  if (response.status === 422 && projectId == null) {
    const loose = new URLSearchParams(params)
    loose.delete('project_id')
    response = await fetch(`${path}?${loose}`)
    if (!response.ok) throw new Error(`Request failed: ${response.status}`)
    return unscopedOnly(await response.json())
  }
  if (!response.ok) throw new Error(`Request failed: ${response.status}`)
  return response.json()
}

/** True when an item belongs in a list scoped to `projectId` (null = top level). */
export function inScope(item: { project_id?: number | null } | null | undefined, projectId: number | null | undefined) {
  return (item?.project_id ?? null) === (projectId ?? null)
}
