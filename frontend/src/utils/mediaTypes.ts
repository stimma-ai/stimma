/**
 * Media type detection and classification utilities.
 */

// Format lists matching backend definitions
export const VIDEO_FORMATS = ['mp4', 'webm', 'mov', 'avi', 'mkv']
export const IMAGE_FORMATS = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']
export const AUDIO_FORMATS = ['mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg']
export const TEXT_FORMATS = ['md']
export const SET_FORMATS = ['stimmaset.json']
export const GRID_FORMATS = ['stimmagrid.json']
export const LAYOUT_FORMATS = ['stimmalayout']
export const STRUCTURED_FORMATS = [...TEXT_FORMATS, ...SET_FORMATS, ...GRID_FORMATS, ...LAYOUT_FORMATS]

export type MediaType = 'image' | 'video' | 'audio' | 'text' | 'set' | 'grid' | 'layout'

export interface MediaItem {
  file_format: string
  [key: string]: unknown
}

/**
 * Get the media type category for an item.
 */
export function getMediaType(item: MediaItem): MediaType {
  const format = item.file_format?.toLowerCase()

  if (format === 'md') return 'text'
  if (format === 'stimmaset.json') return 'set'
  if (format === 'stimmagrid.json') return 'grid'
  if (format === 'stimmalayout') return 'layout'
  if (AUDIO_FORMATS.includes(format)) return 'audio'
  if (VIDEO_FORMATS.includes(format)) return 'video'
  return 'image'
}

/**
 * Check if an item is a video.
 */
export function isVideo(item: MediaItem): boolean {
  return VIDEO_FORMATS.includes(item.file_format?.toLowerCase())
}

/**
 * Check if an item is an image.
 */
export function isImage(item: MediaItem): boolean {
  return IMAGE_FORMATS.includes(item.file_format?.toLowerCase())
}

/**
 * Check if an item is audio.
 */
export function isAudio(item: MediaItem): boolean {
  return AUDIO_FORMATS.includes(item.file_format?.toLowerCase())
}

/**
 * Check if an item is a structured type (text, set, or grid).
 */
export function isLayout(item: MediaItem): boolean {
  return LAYOUT_FORMATS.includes(item.file_format?.toLowerCase())
}

export function isStructured(item: MediaItem): boolean {
  return STRUCTURED_FORMATS.includes(item.file_format?.toLowerCase())
}

/**
 * Check if an item has visual content (can be displayed as image/video).
 */
export function hasVisualContent(item: MediaItem): boolean {
  const type = getMediaType(item)
  return type === 'image' || type === 'video' || type === 'layout'
}

/**
 * Get badge configuration for a media type.
 */
export interface BadgeConfig {
  icon: string
  color: string
  bgColor: string
  borderColor: string
  label: string
}

export function getBadgeConfig(item: MediaItem): BadgeConfig | null {
  const type = getMediaType(item)

  switch (type) {
    case 'video':
      return {
        icon: 'video',
        color: 'text-green-400',
        bgColor: 'bg-green-500/15',
        borderColor: 'border-green-500/50',
        label: 'Video'
      }
    case 'audio':
      return {
        icon: 'music',
        color: 'text-purple-400',
        bgColor: 'bg-purple-500/15',
        borderColor: 'border-purple-500/50',
        label: 'Audio'
      }
    case 'text':
      return {
        icon: 'file-text',
        color: 'text-gray-400',
        bgColor: 'bg-gray-500/15',
        borderColor: 'border-gray-500/50',
        label: 'Text'
      }
    case 'set':
      return {
        icon: 'layers',
        color: 'text-amber-400',
        bgColor: 'bg-amber-500/15',
        borderColor: 'border-amber-500/50',
        label: 'Set'
      }
    case 'grid':
      return {
        icon: 'grid-3x3',
        color: 'text-cyan-400',
        bgColor: 'bg-cyan-500/15',
        borderColor: 'border-cyan-500/50',
        label: 'Grid'
      }
    case 'layout':
      return {
        icon: 'newspaper',
        color: 'text-emerald-400',
        bgColor: 'bg-emerald-500/15',
        borderColor: 'border-emerald-500/50',
        label: 'Layout'
      }
    default:
      return null // Images don't get a badge by default
  }
}

/**
 * Format duration for display (works for both video and audio).
 */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || seconds <= 0) return ''

  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}
