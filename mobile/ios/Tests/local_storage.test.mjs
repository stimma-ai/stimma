import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { createRequire } from 'node:module'
import test from 'node:test'

const require = createRequire(new URL('../../../frontend/package.json', import.meta.url))
const { chromium } = require('@playwright/test')
const source = readFileSync(new URL('../Sources/LocalStoragePersistence.swift', import.meta.url), 'utf8')
const bootstrap = source.match(/static let bootstrap = #"""\n([\s\S]*?)\n    """#/)[1]

test('preferences survive new WebViews and origins, with isolated server snapshots', async () => {
    const browser = await chromium.launch({ headless: true })
    const servers = []
    const contexts = []
    try {
        const snapshots = new Map()
        async function launch(scope, path = '/') {
            const server = createServer((_, response) => {
                response.setHeader('Content-Type', 'text/html')
                response.end('<script>window.startupProfile = localStorage.getItem("profileId")</script>')
            })
            await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
            servers.push(server)
            const origin = `http://127.0.0.1:${server.address().port}`
            const context = await browser.newContext()
            contexts.push(context)
            await context.exposeBinding('saveNative', (_, serialized) => {
                const message = JSON.parse(serialized)
                assert.equal(message.method, 'saveLocalStorage')
                snapshots.set(scope, message.args.values)
            })
            await context.addInitScript({ content: `
                window.webkit = { messageHandlers: { stimma: { postMessage(message) {
                    return window.pendingSave = window.saveNative(JSON.stringify(message));
                } } } };
                (${bootstrap})(JSON.parse(${JSON.stringify(JSON.stringify(snapshots.get(scope) ?? {}))}), ${JSON.stringify(origin)});
            ` })
            const page = await context.newPage()
            await page.goto(origin + path)
            return page
        }
        const first = await launch('account-a/server-a')
        await first.evaluate(async () => {
            localStorage.setItem('profileId', 'creative')
            localStorage.setItem('theme', 'light')
            localStorage.setItem('draft', 'hello 🌍\n"world"')
            localStorage.setItem('__proto__', 'value')
            localStorage.setItem('removed', 'gone')
            localStorage.removeItem('removed')
            sessionStorage.setItem('pin', 'session-only')
            await window.pendingSave
        })
        assert.equal(snapshots.get('account-a/server-a')['__proto__'], 'value')
        const second = await launch('account-a/server-a')
        assert.equal(await second.evaluate(() => localStorage.getItem('__proto__')), 'value')
        assert.notEqual(new URL(first.url()).port, new URL(second.url()).port)
        assert.equal(await second.evaluate(() => window.startupProfile), 'creative')
        assert.deepEqual(JSON.parse(await second.evaluate(() => JSON.stringify(Object.fromEntries(
            Array.from({ length: localStorage.length }, (_, i) => {
                const key = localStorage.key(i)
                return [key, localStorage.getItem(key)]
            })
        )))), {
            profileId: 'creative', theme: 'light', draft: 'hello 🌍\n"world"',
            ...JSON.parse('{"__proto__":"value"}'),
        })
        assert.equal(await second.evaluate(() => sessionStorage.getItem('pin')), null)
        for (const scope of ['account-a/server-b', 'account-b/server-a']) {
            const other = await launch(scope)
            assert.equal(await other.evaluate(() => localStorage.length), 0)
        }
        const generated = await launch('account-a/server-a', '/api/generated')
        assert.equal(await generated.evaluate(() => localStorage.length), 0)
        await second.evaluate(async () => { localStorage.clear(); await window.pendingSave })
        const cleared = await launch('account-a/server-a')
        assert.equal(await cleared.evaluate(() => localStorage.length), 0)
    } finally {
        await Promise.all(contexts.map(context => context.close()))
        await browser.close()
        await Promise.all(servers.map(server => new Promise(resolve => server.close(resolve))))
    }
})
