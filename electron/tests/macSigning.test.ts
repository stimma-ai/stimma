import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, rmSync, writeFileSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
import test from 'node:test'

const { needsCodeSignature, createSigningFilter } = createRequire(import.meta.url)('../build/sign-macos.cjs')

test('signs native code by contents, preserving bundles and skipping binary resources', () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'stimma-signing-'))
  try {
    const ignore = createSigningFilter(undefined)
    for (const magic of ['feedface', 'cefaedfe', 'feedfacf', 'cffaedfe', 'cafebabe', 'bebafeca', 'cafebabf', 'bfbafeca']) {
      const file = path.join(dir, `native-${magic}`) // helpers need no extension
      writeFileSync(file, Buffer.from(magic, 'hex'))
      assert.equal(ignore(file), false)
    }
    for (const name of ['startup.pyc', 'font.ttf', 'model.dat', 'image.png', 'empty', 'fake.so']) {
      const file = path.join(dir, name)
      writeFileSync(file, name === 'empty' ? '' : Buffer.from([0, 1, 2, 3, 4]))
      assert.equal(ignore(file), true)
    }
    const bundle = path.join(dir, 'Nested.app')
    mkdirSync(bundle)
    assert.equal(ignore(bundle), false)
    assert.equal(ignore(dir), false) // includes the outer application
    const native = path.join(dir, 'native-cffaedfe')
    const link = path.join(dir, 'lib-linked.dylib')
    symlinkSync(native, link)
    assert.equal(needsCodeSignature(link), true)
    assert.equal(createSigningFilter(file => file === native)(native), true)
    assert.equal(createSigningFilter([/native-/])(native), true)
    assert.throws(() => ignore(path.join(dir, 'missing')), /ENOENT/)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})
