import test from 'node:test'
import assert from 'node:assert/strict'
import { ANYWHERE, placeFromLocale, placeOptions } from './peopleFrom.ts'

const CODES = ['US', 'GB', 'JP', 'BR']

test('the default place comes from the locale region, else anywhere', () => {
  assert.equal(placeFromLocale('en-GB', CODES), 'GB')
  assert.equal(placeFromLocale('ja-JP', CODES), 'JP')
  assert.equal(placeFromLocale('pt-br', CODES), 'BR')
  assert.equal(placeFromLocale('en', CODES), ANYWHERE)          // no region: no place
  assert.equal(placeFromLocale('es-419', CODES), ANYWHERE)      // a region that is no country
  assert.equal(placeFromLocale('fr-FR', CODES), ANYWHERE)       // a country the table lacks
  assert.equal(placeFromLocale('', CODES), ANYWHERE)
  assert.equal(placeFromLocale(undefined, CODES), ANYWHERE)
  assert.equal(placeFromLocale('not a locale!', CODES), ANYWHERE)
})

test('Anywhere is the first option, then places by name', () => {
  assert.deepEqual(placeOptions([{ code: 'JP', name: 'Japan' }]), [{ value: 'anywhere', label: 'Anywhere' }, { value: 'JP', label: 'Japan' }])
})
