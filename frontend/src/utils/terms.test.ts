/**
 * The clickwrap must survive switching the window to another computer.
 *
 * That is the whole point of the key being install-scoped: every other
 * first-run flag is namespaced by bundle id and sandbox, which since
 * multi-device come from the backend being DRIVEN, not from this machine.
 */
import assert from 'node:assert/strict'
import test, { beforeEach } from 'node:test'

// node:test has no DOM; the module only needs get/set/remove.
const store = new Map<string, string>()
;(globalThis as unknown as { localStorage: Storage }).localStorage = {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => void store.set(k, v),
  removeItem: (k: string) => void store.delete(k),
  clear: () => store.clear(),
  key: (i: number) => [...store.keys()][i] ?? null,
  get length() {
    return store.size
  },
} as Storage

const { TERMS_VERSION, hasAcceptedTerms, recordTermsAcceptance, clearTermsAcceptance, adoptLegacyAcceptance } =
  await import('./terms.ts')
const { makeInstallKey } = await import('./installKey.ts')

beforeEach(() => store.clear())

test('a fresh install has not accepted anything', () => {
  assert.equal(hasAcceptedTerms(), false)
})

test('acceptance is remembered', () => {
  recordTermsAcceptance()
  assert.equal(hasAcceptedTerms(), true)
})

test('the key carries no bundle, sandbox, profile or database id', () => {
  recordTermsAcceptance()
  const key = [...store.keys()][0]
  assert.equal(key, makeInstallKey('terms_accepted'))
  // The four ids that would make this per-server rather than per-install.
  for (const id of ['ai.stimma.stimma', 'mdA', 'default', 'db_']) {
    assert.ok(!key.includes(id), `key must not contain ${id}: ${key}`)
  }
})

test('switching the window to another computer does not ask again', () => {
  recordTermsAcceptance()
  // A device switch reloads the renderer against the same origin and repoints
  // bundle id and sandbox at the other machine. Nothing about that touches
  // this key, so simulate the reload by re-reading it.
  assert.equal(hasAcceptedTerms(), true)
})

test('acceptance records which version was agreed to', () => {
  recordTermsAcceptance()
  const stored = JSON.parse([...store.values()][0])
  assert.equal(stored.version, TERMS_VERSION)
  assert.ok(!Number.isNaN(Date.parse(stored.at)))
})

test('an older acceptance asks again after the terms change', () => {
  store.set(makeInstallKey('terms_accepted'), JSON.stringify({ version: TERMS_VERSION - 1, at: 'x' }))
  assert.equal(hasAcceptedTerms(), false)
})

test('a corrupt value asks again rather than assuming consent', () => {
  for (const bad of ['not json', '{}', 'null', '{"version":"1"}', '']) {
    store.set(makeInstallKey('terms_accepted'), bad)
    assert.equal(hasAcceptedTerms(), false, `should not accept: ${bad}`)
  }
})

test('the developer reset really does replay the clickwrap', () => {
  recordTermsAcceptance()
  clearTermsAcceptance()
  assert.equal(hasAcceptedTerms(), false)
})

test('finishing onboarding before this key existed counts as acceptance', () => {
  adoptLegacyAcceptance(true)
  assert.equal(hasAcceptedTerms(), true)
})

test('never onboarded means nothing to adopt', () => {
  adoptLegacyAcceptance(false)
  assert.equal(hasAcceptedTerms(), false)
})

test('adoption never overwrites a real decision', () => {
  // A stale record is the case that matters: if the terms have since changed,
  // adopting must not agree to the new ones on the user's behalf.
  const stale = JSON.stringify({ version: TERMS_VERSION - 1, at: 'then' })
  store.set(makeInstallKey('terms_accepted'), stale)
  adoptLegacyAcceptance(true)
  assert.equal(store.get(makeInstallKey('terms_accepted')), stale)
  assert.equal(hasAcceptedTerms(), false)
})

test('adoption is idempotent', () => {
  adoptLegacyAcceptance(true)
  const first = store.get(makeInstallKey('terms_accepted'))
  adoptLegacyAcceptance(true)
  assert.equal(store.get(makeInstallKey('terms_accepted')), first)
})
