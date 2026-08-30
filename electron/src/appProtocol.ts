/**
 * app:// protocol serving the bundled frontend in packaged builds — the
 * Electron equivalent of tauri://localhost. A standard+secure scheme gives
 * the SPA a stable origin (app://stimma) so vue-router web history,
 * localStorage, and absolute asset paths all behave like a normal site.
 * Unknown paths fall back to index.html (SPA routing).
 */

import { protocol } from 'electron'
import { readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { log } from './log'

export const APP_ORIGIN = 'app://stimma'

/** Must run before app.ready. */
export function registerAppScheme(): void {
  protocol.registerSchemesAsPrivileged([
    {
      scheme: 'app',
      privileges: {
        standard: true,
        secure: true,
        supportFetchAPI: true,
        stream: true,
        codeCache: true,
      },
    },
  ])
}

const MIME: Record<string, string> = {
  '.html': 'text/html',
  '.js': 'text/javascript',
  '.mjs': 'text/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.wasm': 'application/wasm',
  '.mp4': 'video/mp4',
  '.webm': 'video/webm',
  '.mp3': 'audio/mpeg',
  '.txt': 'text/plain',
  '.map': 'application/json',
}

/** Must run after app.ready. */
export function installAppProtocolHandler(frontendDist: string): void {
  const root = path.resolve(frontendDist)
  protocol.handle('app', (request) => {
    const url = new URL(request.url)
    const requestPath = decodeURIComponent(url.pathname)
    let file = path.normalize(path.join(root, requestPath))
    const isFile = (p: string) => {
      try {
        return statSync(p).isFile()
      } catch {
        return false
      }
    }
    if (!file.startsWith(root) || !isFile(file)) {
      file = path.join(root, 'index.html') // SPA fallback
    }
    try {
      const body = readFileSync(file)
      log.debug('app-protocol', `${request.url} -> ${path.relative(root, file)} (${body.length}b)`)
      return new Response(body as unknown as BodyInit, {
        headers: {
          'Content-Type': MIME[path.extname(file).toLowerCase()] || 'application/octet-stream',
        },
      })
    } catch (e) {
      log.error('app-protocol', `Failed serving ${request.url}: ${e}`)
      return new Response('Not found', { status: 404 })
    }
  })
  log.info('app-protocol', `Serving app:// from ${root}`)
}
