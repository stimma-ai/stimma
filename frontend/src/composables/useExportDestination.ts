/**
 * Where exports land.
 *
 * Desktop shells write through native pickers: a Save panel for one file, a
 * folder picker for several files or a multi-file format. The panel opens in
 * the folder the profile last exported to. "Save to Downloads" skips the
 * picker. Phones and browsers hand the file to the share sheet or download.
 */

import { unzipSync } from 'fflate'
import { desktop } from '../desktop'
import type { KnownFolder } from '../desktop/types'
import { getCurrentProfileId } from './useProfile'
import { addToast } from './useToasts'
import { useDesktopDownload } from './useDesktopDownload'

export type ExportMediaCategory =
  'image' | 'video' | 'audio' | 'layout' | 'vector' | 'sprite' | 'package' | 'mixed' | 'other'

export interface ExportFile {
  blob: Blob
  filename: string
}

/** Desktop shells can open native pickers and write anywhere the user picks. */
export function canChooseExportLocation(): boolean {
  return desktop.kind === 'electron'
}

export function isZipExport(file: ExportFile): boolean {
  return file.filename.toLowerCase().endsWith('.zip')
}

const FIRST_FOLDER: Record<ExportMediaCategory, KnownFolder> = {
  image: 'pictures',
  vector: 'pictures',
  sprite: 'pictures',
  layout: 'documents',
  video: 'videos',
  audio: 'music',
  package: 'documents',
  mixed: 'documents',
  other: 'documents',
}

function lastFolderKey(): string {
  return `stimma:export-last-folder:${getCurrentProfileId() ?? 'default'}`
}

async function startFolder(category: ExportMediaCategory): Promise<string | undefined> {
  const remembered = localStorage.getItem(lastFolderKey())
  if (remembered) return remembered
  return (await desktop.knownFolder(FIRST_FOLDER[category])) ?? undefined
}

function rememberFolder(folder: string): void {
  localStorage.setItem(lastFolderKey(), folder)
}

function folderLabel(folderPath: string): string {
  const parts = folderPath.split(/[\\/]+/).filter(Boolean)
  return parts[parts.length - 1] || folderPath
}

export function revealLabel(): string {
  const platform = typeof navigator === 'undefined' ? '' : navigator.userAgent
  if (/Mac/i.test(platform)) return 'Show in Finder'
  if (/Windows/i.test(platform)) return 'Show in Explorer'
  return 'Show in folder'
}

function announce(message: string, revealPath: string | null): void {
  const action = revealPath
    ? { label: revealLabel(), onClick: () => { void desktop.revealItemInDir(revealPath) } }
    : undefined
  addToast(message, 'success', 6000, action)
}

async function bytesOf(blob: Blob): Promise<Uint8Array> {
  return new Uint8Array(await blob.arrayBuffer())
}

/** Files inside an export archive, skipping folder entries. */
function archiveEntries(zip: Uint8Array): Array<[string, Uint8Array]> {
  return Object.entries(unzipSync(zip)).filter(([name]) => !name.endsWith('/'))
}

/**
 * Save one file through the native Save panel. Resolves false when the user
 * cancels.
 */
export async function exportToChosenFile(file: ExportFile, category: ExportMediaCategory): Promise<boolean> {
  const picked = await desktop.pickSaveFile({
    directory: await startFolder(category),
    filename: file.filename,
  })
  if (!picked) return false
  await desktop.writeExportFile(picked.path, await bytesOf(file.blob))
  rememberFolder(picked.folder)
  const name = folderLabel(picked.path)
  announce(`Exported ${name} to ${folderLabel(picked.folder)}`, picked.path)
  return true
}

/**
 * Unpack an export archive into a folder the user picks. With `ownFolder`, the
 * files go into a new folder named after the archive (a multi-file format such
 * as a sprite sheet with its atlas); otherwise they land loose (several
 * exported items). Resolves false when the user cancels.
 */
export async function exportToChosenFolder(
  file: ExportFile,
  category: ExportMediaCategory,
  { ownFolder }: { ownFolder: boolean },
): Promise<boolean> {
  const entries = archiveEntries(await bytesOf(file.blob))
  if (entries.length === 0) throw new Error('The export was empty')

  const picked = await desktop.pickExportFolder({ defaultPath: await startFolder(category) })
  if (!picked) return false

  const target = ownFolder
    ? await desktop.makeExportFolder(picked, file.filename.replace(/\.zip$/i, ''))
    : picked
  let firstWritten: string | null = null
  for (const [name, data] of entries) {
    const written = await desktop.writeExportFileIn(target, name, data)
    firstWritten ??= written
  }
  rememberFolder(picked)

  if (ownFolder) {
    announce(`Exported ${folderLabel(target)} to ${folderLabel(picked)}`, target)
  } else {
    const what = entries.length === 1 ? folderLabel(firstWritten ?? '') : `${entries.length} files`
    announce(`Exported ${what} to ${folderLabel(picked)}`, firstWritten)
  }
  return true
}

/** Write straight to Downloads (desktop), or hand off to the share sheet / browser. */
export async function exportToDownloads(file: ExportFile): Promise<void> {
  if (!canChooseExportLocation()) {
    await useDesktopDownload().downloadFromResponse(file.blob, file.filename)
    return
  }
  const saved = await desktop.saveToDownloads(file.filename, await bytesOf(file.blob))
  if (!saved) throw new Error('The file was not saved. Please try exporting again.')
  const savedPath = typeof saved === 'string' ? saved : null
  announce(`Saved ${savedPath ? folderLabel(savedPath) : file.filename} to Downloads`, savedPath)
}
