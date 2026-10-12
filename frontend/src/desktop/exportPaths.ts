/**
 * Path rules shared by the desktop bridges for export writes.
 *
 * Export archives come from the backend and are unpacked into a folder the
 * user picked, so every entry name is treated as untrusted: it must stay a
 * plain relative path inside that folder.
 */

/** Split an archive entry name into safe path segments, or throw. */
export function exportPathSegments(relativePath: string): string[] {
  const segments = relativePath.split(/[\\/]+/).filter(segment => segment.length > 0)
  if (segments.length === 0) throw new Error('Empty export file name')
  if (/^[\\/]/.test(relativePath) || /^[A-Za-z]:/.test(relativePath)) {
    throw new Error(`Export file name must be relative: ${relativePath}`)
  }
  for (const segment of segments) {
    if (segment === '.' || segment === '..') {
      throw new Error(`Export file name leaves its folder: ${relativePath}`)
    }
  }
  return segments
}

/**
 * Candidate names for a new file or folder: the name itself, then
 * "name (1).ext", "name (2).ext", ... Folders keep their whole name as the stem.
 */
export function* uniqueNameCandidates(name: string, isFolder = false): Generator<string> {
  yield name
  const lastDot = isFolder ? -1 : name.lastIndexOf('.')
  const stem = lastDot > 0 ? name.slice(0, lastDot) : name
  const ext = lastDot > 0 ? name.slice(lastDot) : ''
  for (let n = 1; n < 1000; n++) yield `${stem} (${n})${ext}`
  yield `${stem}-${Date.now()}${ext}`
}
