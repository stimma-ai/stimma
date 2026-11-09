import assert from 'node:assert/strict'
import test from 'node:test'

import { PRINT_SHEET_PER_PAGE, printSheetHtml, printSheetLabel } from './printSheet.ts'

const url = (hashOrId: string | number, size: number, options: { mode: string }) => `/thumb/${hashOrId}?size=${size}&mode=${options.mode}`

test('a contact sheet prints every item, a page at a time, uncropped', () => {
  const items = Array.from({ length: 105 }, (_, i) => ({ id: i + 1, file_path: `/lib/${i + 1}.png` }))
  const html = printSheetHtml(items, url)
  assert.equal(html.match(/<img /g)?.length, 105)
  assert.equal(html.match(/data-print-page/g)?.length, Math.ceil(105 / PRINT_SHEET_PER_PAGE))
  assert.equal(html.match(/break-after:page/g)?.length, Math.ceil(105 / PRINT_SHEET_PER_PAGE) - 1)
  assert.match(html, /mode=fit/)
  assert.match(html, /object-fit:contain/)
  assert.doesNotMatch(html, /object-fit:cover/)
})

test('contact sheet labels are escaped and prefer the title', () => {
  const html = printSheetHtml([{ id: 1, file_path: '/a/<img src=x onerror=alert(1)>.png' }, { id: 2, title: 'Hero "shot"', file_path: '/a/b.png' }], url)
  assert.doesNotMatch(html, /<img src=x/)
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;\.png/)
  assert.match(html, /Hero &quot;shot&quot;/)
  assert.doesNotMatch(html, />b\.png</)
  assert.equal(printSheetLabel({ file_path: 'C:\\x\\y.png' }), 'y.png')
  assert.equal(printSheetLabel({}), 'Untitled')
})
