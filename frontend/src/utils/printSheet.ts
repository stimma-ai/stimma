// The printable pages of a contact sheet: every item, each whole (fit, never
// cropped), four across and four down per page. Five rows overflow a Letter
// page at the print margins, which spills every sheet onto a second page.

export const PRINT_SHEET_PER_PAGE = 16

export interface PrintSheetItem {
  id?: number | null
  file_hash?: string | null
  file_path?: string | null
  filename?: string | null
  title?: string | null
  name?: string | null
}

export function escapeHtml(value: unknown): string {
  return String(value ?? '').replace(/[&<>"']/g, ch => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]!
  ))
}

/** What the person calls the item: its title, then its file name. */
export function printSheetLabel(item: PrintSheetItem): string {
  const named = [item.title, item.name, item.filename].find(value => typeof value === 'string' && value.trim())
  if (named) return named.trim()
  return item.file_path?.split(/[\\/]/).pop() || 'Untitled'
}

export function printSheetHtml(
  items: PrintSheetItem[],
  thumbnailUrl: (hashOrId: string | number, size: number, options: { mode: 'fit' }) => string,
): string {
  const pages: PrintSheetItem[][] = []
  for (let start = 0; start < items.length; start += PRINT_SHEET_PER_PAGE) pages.push(items.slice(start, start + PRINT_SHEET_PER_PAGE))
  return pages.map((page, index) => {
    const cells = page.map(item => {
      const label = escapeHtml(printSheetLabel(item))
      const src = escapeHtml(thumbnailUrl((item.file_hash || item.id) as string | number, 512, { mode: 'fit' }))
      return `<div style="break-inside:avoid;text-align:center;">`
        + `<div style="width:100%;aspect-ratio:1;background:#f0f0f0;border-radius:4px;margin-bottom:4px;display:flex;align-items:center;justify-content:center;">`
        + `<img src="${src}" alt="" style="max-width:100%;max-height:100%;object-fit:contain;" />`
        + `</div>`
        + `<div title="${label}" style="font-size:10px;font-weight:500;color:#111;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${label}</div>`
        + `</div>`
    }).join('')
    const breakAfter = index < pages.length - 1 ? 'break-after:page;page-break-after:always;' : ''
    return `<div data-print-page style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;width:100%;${breakAfter}">${cells}</div>`
  }).join('')
}
