import { randomUUID } from 'node:crypto'

/** Vite normally reloads after any HMR socket loss, including phone sleep.
 * Reconnect an unchanged dev session; still reload if edits/restarts were missed.
 * This adapter is checked against the installed Vite client in regression tests.
 */
export function mobileDevReconnect() {
  let revision = randomUUID()
  return {
    name: 'stimma-mobile-dev-reconnect',
    apply: 'serve',
    configureServer(server) {
      server.watcher.on('all', () => { revision = randomUUID() })
      server.middlewares.use('/__stimma_dev_revision', (_request, response) => {
        response.setHeader('Cache-Control', 'no-store')
        response.end(revision)
      })
    },
    transform(source, id) {
      if (!/\/vite\/dist\/client\/client\.mjs(?:\?|$)/.test(id)) return
      const reconnect = /await waitForSuccessfulPing\(url.href\);\s*location.reload\(\);/
      if (!reconnect.test(source)) throw new Error('Vite reconnect adapter needs updating')
      const prefix = `
const stimmaPhone = typeof window !== 'undefined' && !!(window.webkit?.messageHandlers?.stimma || window.stimmaAndroid);
const stimmaRevision = () => fetch('/__stimma_dev_revision', {cache:'no-store'}).then(r => { if (!r.ok) throw new Error('Dev server unavailable'); return r.text() });
let stimmaLoadedRevision = stimmaPhone ? await stimmaRevision().catch(() => null) : null;
`
      // Refresh the baseline after edits actually delivered to this page.
      source = source.replace('case "update":', 'case "update":\n if (stimmaPhone) stimmaLoadedRevision = await stimmaRevision().catch(() => null);')
      source = source.replace(reconnect, `await waitForSuccessfulPing(url.href);
        if (stimmaPhone && stimmaLoadedRevision && await stimmaRevision().catch(() => null) === stimmaLoadedRevision) {
          await transport.connect(createHMRHandler(handleMessage));
        } else { location.reload(); }`)
      // Repeated reconnects must not accumulate the old transport's ping timers.
      source = source.replace('onDisconnection();', 'clearInterval(pingIntervalId); onDisconnection();')
      return { code: prefix + source, map: null }
    },
  }
}
