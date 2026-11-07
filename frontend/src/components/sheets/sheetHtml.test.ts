import assert from 'node:assert/strict'
import test from 'node:test'

import { mediaIdOfRef } from './sheetHtml.ts'

// CSS scoping needs a real CSS engine: tests/contactSheetHtml.browser.test.mjs.
test('refs resolve to media ids', () => {
  assert.equal(mediaIdOfRef('media:12'), 12)
  assert.equal(mediaIdOfRef('12'), 12)
  assert.equal(mediaIdOfRef('asset:3'), null)
  assert.equal(mediaIdOfRef(''), null)
})
