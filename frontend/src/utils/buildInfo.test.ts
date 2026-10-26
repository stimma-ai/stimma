import assert from 'node:assert/strict'
import test from 'node:test'
import { loadBuildInfo, parseBuildInfo } from './buildInfo.ts'

const reply = (body: unknown, ok = true) => async () => ({ ok, json: async () => body })

test('parseBuildInfo keeps only a plausible commit', () => {
  assert.deepEqual(parseBuildInfo({ commit: 'f183c870' }), { commit: 'f183c870' })
  for (const value of [null, 'f183c870', {}, { commit: 7 }, { commit: '<b>x</b>' }, { commit: 'abc' }]) {
    assert.deepEqual(parseBuildInfo(value), { commit: '' })
  }
})

test('desktop and dev read build-info.json from the page origin', async () => {
  const urls: string[] = []
  const info = await loadBuildInfo({
    mobile: false,
    fetchImpl: async (url) => { urls.push(url); return reply({ commit: 'abc1234' })() },
  })
  assert.deepEqual(info, { commit: 'abc1234' })
  assert.deepEqual(urls, ['/build-info.json'])
})

test('phones read the commit from the server package manifest', async () => {
  const urls: string[] = []
  const info = await loadBuildInfo({
    mobile: true,
    apiUrl: path => `http://127.0.0.1:4100${path}`,
    fetchImpl: async (url) => {
      urls.push(url)
      return reply({ hash: 'a'.repeat(64), build: { commit: 'abc1234' } })()
    },
  })
  assert.deepEqual(info, { commit: 'abc1234' })
  assert.deepEqual(urls, ['http://127.0.0.1:4100/api/mobile-ui/manifest'])
})

test('missing metadata, SPA fallbacks and failures show no commit', async () => {
  const failures = [
    reply({ hash: 'a'.repeat(64) }),
    reply(null),
    reply({ commit: 'abc1234' }, false),
    async () => ({ ok: true, json: async () => { throw new SyntaxError('index.html') } }),
    async () => { throw new TypeError('offline') },
  ]
  for (const fetchImpl of failures) {
    assert.deepEqual(await loadBuildInfo({ mobile: true, fetchImpl }), { commit: '' })
  }
  assert.deepEqual(await loadBuildInfo({ mobile: false, fetchImpl: failures[3] }), { commit: '' })
})
