import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { LIBRARY_UPLOAD_EXTENSIONS, isLibraryUpload } from '../src/utils/libraryUploadFormats.ts'

test('the library picker accepts exactly the formats the upload service supports', () => {
  const service = readFileSync(new URL('../../backend/upload_service.py', import.meta.url), 'utf8')
  const groups = [...service.matchAll(/ALLOWED_(?:IMAGE|VIDEO|AUDIO|VECTOR)_EXTENSIONS = \{([^}]+)\}/g)]
  assert.equal(groups.length, 4)
  const backend = groups.flatMap(group => [...group[1].matchAll(/'([^']+)'/g)].map(match => match[1]))
  assert.deepEqual([...LIBRARY_UPLOAD_EXTENSIONS].sort(), [...new Set(backend)].sort())
  for (const extension of backend) assert.equal(isLibraryUpload({ name: `example${extension.toUpperCase()}` }), true)
  for (const name of ['archive.zip', 'photo.png.exe', 'README', 'document.pdf']) assert.equal(isLibraryUpload({ name }), false)
})
