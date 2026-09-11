import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'

const source = readFileSync(new URL('../src/apiConfig.js', import.meta.url), 'utf8')
  .replace(/^import .* from .*\n/gm, '')
  .replace(/^export /gm, '')

for (const [kind, origin, expected] of [
  ['ios', 'http://192.168.1.20:9407', 'http://192.168.1.20:9407'],
  ['ios', 'https://[fd00::20]:9407', 'https://[fd00::20]:9407'],
  ['ios', 'http://127.0.0.1:54321', 'http://127.0.0.1:54321'],
  ['android', 'http://127.0.0.1:54321', 'http://127.0.0.1:54321'],
  ['electron', 'http://localhost:9192', 'http://127.0.0.1:54321'],
]) {
  test(`${kind} at ${origin} routes health, API, media and WebSocket requests correctly`, async () => {
    const healthOrigins = []
    const axios = { defaults: {}, interceptors: { request: { use() {} } } }
    const context = vm.createContext({
      axios,
      window: { location: { origin } },
      console: { log() {} },
      desktop: {
        kind, getBackendPort: async () => 54321,
        mdGetState: async () => ({ connectionState: 'ready', activeDeviceId: 'dev:fixture' }),
        mdOnConnectionState() {},
      },
      isDesktop: () => true,
      waitForBackendHealth: async origin => { healthOrigins.push(origin); return { status: 200 } },
      getStartupWaitMessage: () => null,
    })
    vm.runInContext(source, context)
    await context.initApiConfig()
    assert.deepEqual(healthOrigins, [expected])
    assert.equal(context.getApiBase(), `${expected}/api`)
    assert.equal(context.getWsBase(), `${expected.replace(/^http/, 'ws')}/ws`)
    assert.equal(context.rewriteUrl('/api/media/example'), `${expected}/api/media/example`)
    assert.equal(axios.defaults.baseURL, expected)
  })
}
