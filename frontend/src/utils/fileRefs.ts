import { getApiBase } from '../apiConfig'
import { getCurrentProfileId } from '../composables/useProfile'
import { getCachedPin } from '../composables/usePinLock'

export interface WorkspaceFile {
  root: 'chat' | 'project'
  path: string
  name: string
  size: number
  mime: string
  kind?: string
  width?: number
  height?: number
  duration?: number
  lines?: number
  rows?: number
  subtitle?: string
  modified_ns?: number
  media_id?: number
  entry?: string
}
export function fileUrl(chatId: number | string, file: WorkspaceFile, action = 'content', download = false) {
  const profile = getCurrentProfileId()
  const params = new URLSearchParams({ path: file.path, profile })
  const pin = getCachedPin(profile)
  if (file.media_id) params.set('media_id', String(file.media_id))
  if (pin) params.set('pin', pin)
  if (file.entry && action === 'content') params.set('entry', file.entry)
  if (file.modified_ns && action === 'content') params.set('v', String(file.modified_ns))
  if (download) params.set('download', 'true')
  return `${getApiBase()}/chats/${chatId}/files/${file.root}/${action}?${params}`
}
export function fileKind(name: string, mime = '') {
  const ext = name.toLowerCase().split('.').pop() || ''
  if (['md', 'markdown'].includes(ext)) return 'markdown'
  if (['csv', 'tsv'].includes(ext)) return 'table'
  if (ext === 'json' || mime === 'application/json') return 'json'
  if (ext === 'zip' || mime === 'application/zip') return 'zip'
  if (mime.startsWith('image/') || ['png', 'jpg', 'jpeg', 'webp', 'gif', 'avif', 'svg', 'bmp'].includes(ext)) return 'image'
  if (mime.startsWith('video/') || ['mp4', 'webm', 'mov', 'mkv'].includes(ext)) return 'video'
  if (mime.startsWith('audio/') || ['mp3', 'wav', 'ogg', 'flac', 'm4a'].includes(ext)) return 'audio'
  if (mime.startsWith('text/') || ['py', 'js', 'ts', 'jsx', 'tsx', 'html', 'css', 'sql', 'sh', 'yaml', 'yml', 'toml', 'xml', 'rs', 'go', 'c', 'cpp', 'h', 'java', 'rb', 'txt', 'log'].includes(ext)) return 'text'
  return 'unknown'
}
export function fileSize(size?: number) {
  if (size == null) return ''
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}
export function parseDelimited(text: string, delimiter = ','): string[][] {
  const rows: string[][] = []
  let row: string[] = [], cell = '', quoted = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (c === '"') {
      if (quoted && text[i + 1] === '"') { cell += '"'; i++ }
      else if (quoted || cell === '') quoted = !quoted
      else cell += c
    } else if (c === delimiter && !quoted) { row.push(cell); cell = '' }
    else if ((c === '\n' || c === '\r') && !quoted) {
      if (c === '\r' && text[i + 1] === '\n') i++
      row.push(cell); rows.push(row); row = []; cell = ''
    } else cell += c
  }
  if (cell || row.length) { row.push(cell); rows.push(row) }
  return rows
}

export const workspaceFileDragType = 'application/x-stimma-workspace-file'
export function dragWorkspaceFile(event: DragEvent, chatId: number | string, file: WorkspaceFile) {
  if (!event.dataTransfer) return
  event.dataTransfer.effectAllowed = 'copy'
  event.dataTransfer.setData(workspaceFileDragType, JSON.stringify({ chatId, profile: getCurrentProfileId(), file }))
}

// Library-supported media only; workspace documents remain downloadable/attachable.
export function canSaveFileToLibrary(file: Pick<WorkspaceFile, 'name'>) {
  const name = file.name.toLowerCase()
  return /\.(?:jpg|jpeg|png|gif|webp|bmp|svg|mp4|webm|mov|avi|mkv|mp3|wav|flac|aac|m4a|ogg|md)$/.test(name)
    || /\.stimma(?:set|grid|sprite)\.json$/.test(name)
}

export function fileStats(file: WorkspaceFile) {
  const kind = fileKind(file.name, file.mime)
  const dimensions = file.width && file.height ? `${file.width} × ${file.height}` : ''
  const seconds = file.duration && Number.isFinite(file.duration) ? Math.round(file.duration) : 0
  const duration = seconds ? `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}` : ''
  if (kind === 'image') return dimensions
  if (kind === 'video') return [dimensions, duration].filter(Boolean).join(' · ')
  if (kind === 'audio') return duration
  if (kind === 'table') return file.rows != null ? `${file.rows} ${file.rows === 1 ? 'row' : 'rows'}` : (/^\d+ rows?$/.test(file.subtitle || '') ? file.subtitle : '')
  if (kind === 'text') return file.lines != null ? `${file.lines} ${file.lines === 1 ? 'line' : 'lines'}` : ''
  return fileSize(file.size)
}
