import type { MediaType } from './mediaTypes'

/**
 * Media-input extraction from a flow's input_schema, for surfaces that offer
 * drop targets outside FlowInputForm (the sidebar's flow-tab drop flyout).
 * Detection mirrors FlowInputForm's field-kind chain for media / media_list —
 * keep the two in sync.
 */

export interface FlowMediaInputField {
  name: string
  label: string
  multi: boolean
  accept: 'image' | 'video' | 'audio'
}

function normalizeSpec(def: any): any {
  return def && typeof def === 'object' ? def : { type: String(def || 'str') }
}

function humanizeName(name: string): string {
  const spaced = name.replace(/_+/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2').trim()
  if (!spaced) return name
  return spaced.charAt(0).toUpperCase() + spaced.slice(1).toLowerCase()
}

function listElementType(type: string): string {
  const match = type.match(/^list\[(.+)\]$/)
  return match ? match[1] : 'str'
}

function acceptFor(t: string): 'image' | 'video' | 'audio' {
  if (t === 'video') return 'video'
  if (t === 'audio') return 'audio'
  return 'image'
}

export function flowMediaInputFields(schema: Record<string, any> | null | undefined): FlowMediaInputField[] {
  const out: FlowMediaInputField[] = []
  for (const [name, rawDef] of Object.entries(schema || {})) {
    const d = normalizeSpec(rawDef)
    if (Array.isArray(d.enum) || Array.isArray(d.options)) continue
    const type = String(d.type || d.kind || 'string')
    const control = String(d['x-control'] || d.ui?.control || d.control || '')
    if (control === 'prompt' || type === 'prompt') continue
    const format = String(d.format || '')
    const itemFormat = String(d.items?.format || '')
    const isArray = type === 'array' || type.startsWith('list')
    const label = d['x-label'] || d.display_name || d.label || humanizeName(name)
    if (isArray && (itemFormat === 'file-path' || control === 'image_picker' || type === 'list[media]' || type === 'media_list' || type === 'list[image]')) {
      const itemType = String(d.items?.type || d.item?.type || listElementType(type))
      out.push({ name, label, multi: true, accept: acceptFor(itemType) })
    } else if (format === 'file-path' || control === 'image_picker' || type === 'media' || type === 'image' || type === 'video') {
      out.push({ name, label, multi: false, accept: acceptFor(type) })
    }
  }
  return out
}

/** Image inputs accept video drags too, matching the tile drop handlers. */
export function fieldAcceptsDraggedType(accept: FlowMediaInputField['accept'], dragged: MediaType | null): boolean {
  if (!dragged) return false
  if (accept === 'image') return dragged === 'image' || dragged === 'video'
  return dragged === accept
}
