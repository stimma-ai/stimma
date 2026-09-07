// Package a local fix with the REAL Canary identity and install location.
// Reuse the staged backend/frontend from the CLI's generated builder config.
// This does not publish a release or exercise update-feed delivery.
import { build, Platform } from 'electron-builder'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const config = JSON.parse(readFileSync(path.join(root, '.generated-builder.json'), 'utf8'))
if (config.appId !== 'ai.stimma.stimma.canary' || config.productName !== 'Stimma Canary') {
  throw new Error('Generate a Canary builder config first; this helper must not target another channel')
}
const version = process.argv[2]
if (!version || !/^\d+\.\d+\.\d+-canary\.\d+-test\.\d+$/.test(version)) {
  throw new Error('Usage: node scripts/build-real-canary-test.mjs X.Y.Z-canary.N-test.N [output-directory]')
}
config.extraMetadata.version = version
const archives = config.extraResources.filter(r => /^stimma-python-runtime-[a-f0-9]{64}\.tar\.xz$/.test(r.to))
if (archives.length !== 1) throw new Error('Expected exactly one staged Python runtime archive')
config.extraMetadata.stimmaPythonRuntimeArchive = archives[0].to
config.directories.output = process.argv[3] || 'out-real-canary-test'
config.extraResources = config.extraResources.map((resource) => resource.to === 'stimma-watchdog.exe'
  ? { ...resource, from: '../src-tauri/watchdog/target/release/stimma-watchdog.exe' }
  : resource)
await build({ projectDir: root, targets: Platform.WINDOWS.createTarget('nsis'), config })
