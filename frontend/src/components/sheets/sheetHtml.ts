/**
 * A contact sheet's HTML, made safe and native.
 *
 * 1. <style> blocks come out and are nested under this sheet's own scope, so
 *    the agent's CSS can style the sheet and nothing else in the app.
 * 2. The rest is sanitized: no scripts, handlers, frames or external loads.
 * 3. The DOM becomes VNodes. Kit elements (stimma-*) become live components;
 *    every other element renders as itself.
 */
import DOMPurify from 'dompurify'
import { h, type Component, type VNode } from 'vue'

export const KIT_TAGS = [
  'stimma-section', 'stimma-media-group', 'stimma-media', 'stimma-columns', 'stimma-column',
  'stimma-compare', 'stimma-check', 'stimma-choice', 'stimma-option', 'stimma-rating', 'stimma-field',
]

const KIT_ATTRS = [
  'ref', 'caption', 'label', 'note', 'collapsible', 'collapsed', 'layout', 'size', 'aspect',
  'for', 'value', 'a', 'b', 'placeholder', 'multiple',
]

export interface SheetMember {
  media_id: number
  asset_id: number | null
  file_hash: string
  file_path?: string
  file_format: string
  width: number | null
  height: number | null
  duration?: number | null
  has_alpha?: boolean | null
}

export interface SheetContent {
  type: 'contact_sheet'
  title: string | null
  asset_id: number | null
  revision_id: number | null
  revision_number: number | null
  html: string
  members: Record<string, SheetMember | null>
}

export interface SheetMediaEntry {
  /** Component id of the first tile showing this media. */
  id: string
  ref: string
  mediaId: number
  caption: string
  section: string
}

export function mediaIdOfRef(ref: string | null | undefined): number | null {
  const match = /^(?:media:)?(\d+)$/.exec((ref || '').trim())
  return match ? Number(match[1]) : null
}

/** Nest the agent's CSS under the sheet's scope; drop it if it could escape. */
export function scopeCss(css: string, scope: string): string {
  const cleaned = css
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/@import[^;]*;?/gi, '')
    .replace(/url\(\s*(['"]?)\s*(?:https?:)?\/\/[^)]*\)/gi, 'none')
  let depth = 0
  let quote: string | null = null
  for (const char of cleaned) {
    if (quote) {
      if (char === quote) quote = null
      continue
    }
    if (char === '"' || char === "'") quote = char
    else if (char === '{') depth += 1
    else if (char === '}') {
      depth -= 1
      if (depth < 0) return ''
    }
  }
  if (depth !== 0 || quote) return ''
  return cleaned.trim() ? `${scope} {\n${cleaned}\n}` : ''
}

export interface ParsedSheet {
  root: HTMLElement
  css: string
}

export function parseSheet(html: string, scope: string): ParsedSheet {
  const styles: string[] = []
  const body = (html || '').replace(/<style[^>]*>([\s\S]*?)<\/style>/gi, (_match, css) => {
    styles.push(css)
    return ''
  })
  const clean = DOMPurify.sanitize(body, {
    ADD_TAGS: KIT_TAGS,
    ADD_ATTR: KIT_ATTRS,
    // Refs look like URLs with an unknown scheme (media:12); keep them.
    ADD_URI_SAFE_ATTR: ['ref', 'a', 'b'],
    FORBID_TAGS: ['script', 'iframe', 'object', 'embed', 'link', 'meta', 'base', 'form', 'style'],
    FORBID_ATTR: ['srcdoc'],
    CUSTOM_ELEMENT_HANDLING: {
      tagNameCheck: /^stimma-/,
      attributeNameCheck: /^[a-z][a-z0-9-]*$/,
      allowCustomizedBuiltInElements: false,
    },
  }) as string
  const doc = new DOMParser().parseFromString(`<body>${clean}</body>`, 'text/html')
  // External pictures and links never load in a sheet.
  doc.body.querySelectorAll('[src], [srcset]').forEach(el => {
    const src = el.getAttribute('src') || ''
    if (/^(?:https?:)?\/\//i.test(src)) el.removeAttribute('src')
    el.removeAttribute('srcset')
  })
  doc.body.querySelectorAll('[style]').forEach(el => {
    const style = el.getAttribute('style') || ''
    if (/url\(/i.test(style)) el.setAttribute('style', style.replace(/url\(\s*(['"]?)\s*(?:https?:)?\/\/[^)]*\)/gi, 'none'))
  })
  doc.body.querySelectorAll('a[href]').forEach(el => {
    el.setAttribute('target', '_blank')
    el.setAttribute('rel', 'noopener noreferrer')
  })
  return { root: doc.body, css: styles.map(css => scopeCss(css, scope)).filter(Boolean).join('\n') }
}

/** Every distinct media in reading order: what the sheet's slideshow walks. */
export function sheetMediaList(root: HTMLElement): SheetMediaEntry[] {
  const seen = new Set<number>()
  const out: SheetMediaEntry[] = []
  root.querySelectorAll('stimma-media').forEach(el => {
    const ref = el.getAttribute('ref') || ''
    const mediaId = mediaIdOfRef(ref)
    if (mediaId == null || seen.has(mediaId)) return
    seen.add(mediaId)
    out.push({
      id: el.id,
      ref,
      mediaId,
      caption: el.getAttribute('caption') || '',
      section: el.closest('stimma-section')?.getAttribute('label') || '',
    })
  })
  return out
}

function attrsOf(el: Element): Record<string, string | boolean> {
  const out: Record<string, string | boolean> = {}
  for (const attr of Array.from(el.attributes)) out[attr.name] = attr.value === '' ? true : attr.value
  return out
}

export function sheetToVNodes(nodes: Node[], components: Record<string, Component>): Array<VNode | string> {
  const out: Array<VNode | string> = []
  nodes.forEach((node, index) => {
    if (node.nodeType === Node.TEXT_NODE) {
      out.push(node.textContent || '')
      return
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return
    const el = node as Element
    const tag = el.tagName.toLowerCase()
    const attrs = attrsOf(el)
    const component = components[tag]
    if (component) {
      const { id, class: cls, style, ...rest } = attrs
      out.push(h(component, { key: (id as string) || `${tag}-${index}`, kid: id || undefined, class: cls, style, at: rest, node: el },
        { default: () => sheetToVNodes(Array.from(el.childNodes), components) }))
    } else if (tag.startsWith('stimma-')) {
      // Unknown kit names render their children, never an unknown element.
      out.push(...sheetToVNodes(Array.from(el.childNodes), components))
    } else {
      out.push(h(tag, attrs, sheetToVNodes(Array.from(el.childNodes), components)))
    }
  })
  return out
}
