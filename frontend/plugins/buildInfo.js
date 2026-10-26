import { execSync } from 'node:child_process'

const COMMIT = /^[0-9a-f]{7,40}$/

/** Short source commit: STIMMA_BUILD_COMMIT when set (CI, tests), else git, else ''. */
export function resolveBuildCommit(cwd) {
  const override = process.env.STIMMA_BUILD_COMMIT
  if (override !== undefined) return COMMIT.test(override) ? override : ''
  try {
    const commit = execSync('git rev-parse --short HEAD', { cwd, stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim()
    return COMMIT.test(commit) ? commit : ''
  } catch {
    // Not a git checkout (e.g. source tarball): omit the commit.
    return ''
  }
}

/**
 * Publish build metadata as `/build-info.json` beside the bundle instead of
 * compiling it into the JavaScript. The server's phone UI package is
 * content-addressed, so a commit string in the entry chunk changed the package
 * hash on every build and forced phones to download the whole interface again
 * even when no UI byte had changed. The package builder moves this file into
 * the package manifest and leaves it out of the hashed archive.
 */
export function buildInfo(cwd) {
  let body = ''
  const contents = () => {
    body ||= JSON.stringify({ commit: resolveBuildCommit(cwd) })
    return body
  }
  return {
    name: 'stimma-build-info',
    configureServer(server) {
      server.middlewares.use('/build-info.json', (_request, response) => {
        response.setHeader('Content-Type', 'application/json')
        response.setHeader('Cache-Control', 'no-store')
        response.end(contents())
      })
    },
    generateBundle() {
      this.emitFile({ type: 'asset', fileName: 'build-info.json', source: contents() })
    },
  }
}
