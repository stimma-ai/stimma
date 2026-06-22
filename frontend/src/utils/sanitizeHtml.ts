import DOMPurify from 'dompurify'
import { marked } from 'marked'

const HTML_SANITIZE_CONFIG = {
  ADD_ATTR: ['target'],
  FORBID_TAGS: [
    'base',
    'embed',
    'form',
    'iframe',
    'input',
    'link',
    'meta',
    'object',
    'script',
    'select',
    'style',
    'textarea',
  ],
  FORBID_ATTR: ['srcdoc'],
}

const SVG_SANITIZE_CONFIG = {
  USE_PROFILES: { svg: true, svgFilters: true },
  FORBID_TAGS: [
    'a',
    'embed',
    'foreignObject',
    'iframe',
    'image',
    'link',
    'object',
    'script',
    'style',
    'use',
  ],
  FORBID_ATTR: ['href', 'xlink:href', 'src', 'srcset', 'srcdoc'],
}

export function sanitizeHtml(html: string | null | undefined): string {
  return DOMPurify.sanitize(html || '', HTML_SANITIZE_CONFIG)
}

export function sanitizeSvg(svg: string | null | undefined): string {
  return DOMPurify.sanitize(svg || '', SVG_SANITIZE_CONFIG)
}

export function renderSafeMarkdown(
  text: string | null | undefined,
  options: Record<string, unknown> = {},
): string {
  if (!text) return ''
  const html = marked.parse(text, {
    breaks: true,
    async: false,
    ...options,
  }) as string
  return sanitizeHtml(html)
}

export function escapeHtmlAttribute(value: string | null | undefined): string {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}
