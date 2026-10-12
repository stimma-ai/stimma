/**
 * Export writes outside Downloads. The renderer may only write where the user
 * pointed a native picker during this session: the exact file chosen in a
 * Save panel, or anything inside a folder chosen in a folder picker.
 */

import fs from 'node:fs'
import path from 'node:path'

const grantedFiles = new Set<string>()
const grantedFolders = new Set<string>()

export function grantFile(filePath: string): void {
  grantedFiles.add(path.resolve(filePath))
}

export function grantFolder(folderPath: string): void {
  grantedFolders.add(path.resolve(folderPath))
}

function isInside(folder: string, target: string): boolean {
  const relative = path.relative(folder, target)
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative))
}

export function requireGrantedFile(target: string): string {
  const resolved = path.resolve(target)
  if (grantedFiles.has(resolved)) return resolved
  for (const folder of grantedFolders) {
    if (isInside(folder, resolved)) return resolved
  }
  throw new Error('That location was not chosen for export')
}

export function requireGrantedFolder(target: string): string {
  const resolved = path.resolve(target)
  for (const folder of grantedFolders) {
    if (isInside(folder, resolved)) return resolved
  }
  throw new Error('That folder was not chosen for export')
}

/** Split an archive entry name into safe segments, or throw. */
export function exportPathSegments(relativePath: string): string[] {
  const segments = relativePath.split(/[\\/]+/).filter(segment => segment.length > 0)
  if (segments.length === 0) throw new Error('Empty export file name')
  if (/^[\\/]/.test(relativePath) || /^[A-Za-z]:/.test(relativePath)) {
    throw new Error('Export file name must be relative')
  }
  if (segments.some(segment => segment === '.' || segment === '..')) {
    throw new Error('Export file name leaves its folder')
  }
  return segments
}

const exists = (p: string) => fs.promises.access(p).then(() => true, () => false)

/** First path in `folder` named `name`, or "name (N)", that nothing exists at. */
export async function firstFreePath(folder: string, name: string, isFolder: boolean): Promise<string> {
  const lastDot = isFolder ? -1 : name.lastIndexOf('.')
  const stem = lastDot > 0 ? name.slice(0, lastDot) : name
  const ext = lastDot > 0 ? name.slice(lastDot) : ''
  if (!(await exists(path.join(folder, name)))) return path.join(folder, name)
  for (let n = 1; n < 1000; n++) {
    const candidate = path.join(folder, `${stem} (${n})${ext}`)
    if (!(await exists(candidate))) return candidate
  }
  return path.join(folder, `${stem}-${Date.now()}${ext}`)
}
