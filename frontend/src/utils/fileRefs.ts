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
  subtitle?: string
  modified_ns?: number
  caption?: string
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
