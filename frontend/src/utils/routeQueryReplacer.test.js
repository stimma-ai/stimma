import test from 'node:test'
import assert from 'node:assert/strict'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createRouteQueryReplacer } from './routeQueryReplacer.js'

async function browseRouter(url) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/browse', name: 'browse', component: {} }],
  })
  await router.push(url)
  return router
}

function dropKeys(keys) {
  return (query) => {
    let changed = false
    for (const key of keys) {
      if (query[key] !== undefined) { delete query[key]; changed = true }
    }
    return changed
  }
}

test('back-to-back query replacements keep both changes', async () => {
  const router = await browseRouter('/browse?library=1&mw=11&include_projects=1&sim=2&s=sim')
  const replaceRouteQuery = createRouteQueryReplacer(router)

  // Clear all: the similarity cleanup runs first, then the Made with sync.
  const first = replaceRouteQuery(dropKeys(['sim', 's']), { reapply: true })
  const second = replaceRouteQuery(dropKeys(['mw', 'include_projects']))
  assert.ok(first && second)
  assert.equal(second.reapply, true)

  await new Promise(resolve => setTimeout(resolve, 0))
  assert.equal(router.currentRoute.value.fullPath, '/browse?library=1')
})

test('an unchanged update does not navigate', async () => {
  const router = await browseRouter('/browse?library=1')
  const replaceRouteQuery = createRouteQueryReplacer(router)
  assert.equal(replaceRouteQuery(dropKeys(['mw'])), null)
})

test('later updates start from the settled route again', async () => {
  const router = await browseRouter('/browse?library=1&mw=11')
  const replaceRouteQuery = createRouteQueryReplacer(router)
  replaceRouteQuery(dropKeys(['mw']), { reapply: true })
  await new Promise(resolve => setTimeout(resolve, 0))
  await router.replace({ query: { library: '1', mw: '12' } })
  const entry = replaceRouteQuery((query) => { query.sim = '3'; return true })
  assert.equal(entry.reapply, false)
  assert.deepEqual(entry.query, { library: '1', mw: '12', sim: '3' })
})
