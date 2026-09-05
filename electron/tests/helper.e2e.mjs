// stimma-native integration through the real shell: embedMetadata round-trip
// and voice surface behavior without a downloaded model.
//
// Run: node electron/tests/helper.e2e.mjs (repo root; needs electron, frontend,
// and native/stimma-native builds)

import fs from 'node:fs'
import path from 'node:path'
import zlib from 'node:zlib'
import {
  assertPrereqs,
  launchShell,
  makeSandbox,
  repoRoot,
  startFrontendServer,
  waitForFrontendWindow,
} from './harness.mjs'

assertPrereqs()
const helperBin = path.join(repoRoot, 'native', 'stimma-native', 'target', 'debug', 'stimma-native')
if (!fs.existsSync(helperBin)) {
  console.error('stimma-native not built — run `cargo build` in native/stimma-native')
  process.exit(1)
}

let failed = false
const check = (label, condition) => {
  if (condition) console.log(`ok - ${label}`)
  else {
    failed = true
    console.error(`FAIL - ${label}`)
  }
}

// Minimal valid PNG via zlib CRC utilities.
function tinyPng() {
  const chunks = []
  const chunk = (type, data) => {
    const len = Buffer.alloc(4)
    len.writeUInt32BE(data.length)
    const body = Buffer.concat([Buffer.from(type), data])
    const crc = Buffer.alloc(4)
    crc.writeUInt32BE(zlib.crc32(body) >>> 0)
    chunks.push(Buffer.concat([len, body, crc]))
  }
  chunk('IHDR', Buffer.from([0, 0, 0, 1, 0, 0, 0, 1, 8, 0, 0, 0, 0]))
  chunk('IDAT', Buffer.from([0x78, 0x9c, 0x63, 0x00, 0x00, 0x00, 0x02, 0x00, 0x01]))
  chunk('IEND', Buffer.alloc(0))
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    ...chunks,
  ])
}

const { server, port } = await startFrontendServer()
const sandbox = makeSandbox()
fs.mkdirSync(sandbox.dataDir, { recursive: true })
fs.mkdirSync(sandbox.cacheDir, { recursive: true })

const srcPng = path.join(sandbox.dir, 'source.png')
fs.writeFileSync(srcPng, tinyPng())

const snapshotDir = path.join(sandbox.cacheDir, 'drag_snapshots', 'reservation')
fs.mkdirSync(snapshotDir, { recursive: true })
const destination = path.join(snapshotDir, 'snapshot.png')

const app = await launchShell({ sandbox, frontendPort: port })

try {
  const page = await app.firstWindow()
  await waitForFrontendWindow(page, port)

  const embedded = await page.evaluate(
    ({ source, destination }) =>
      window.stimmaDesktop.embedMetadata({
        source_path: source,
        destination_path: destination,
        format: 'png',
        a1111: 'e2e prompt',
        stimma_json: '{"via":"electron"}',
        jpeg_exif_hex: null,
      }),
    { source: srcPng, destination },
  )
  check(`embedMetadata returns a snapshot path (${embedded})`, typeof embedded === 'string')
  check('snapshot lives under drag_snapshots', String(embedded).includes('drag_snapshots'))
  const bytes = fs.readFileSync(embedded)
  check(
    'snapshot contains the embedded parameters chunk',
    bytes.includes(Buffer.from('parameters\0e2e prompt', 'latin1')),
  )
  check(
    'snapshot contains the stimma chunk',
    bytes.includes(Buffer.from('stimma\0{"via":"electron"}', 'latin1')),
  )

  const passthrough = await page.evaluate(
    ({ source, destination }) =>
      window.stimmaDesktop.embedMetadata({
        source_path: source,
        destination_path: destination,
        format: 'passthrough',
        a1111: null,
        stimma_json: null,
        jpeg_exif_hex: null,
      }),
    { source: srcPng, destination },
  )
  check('passthrough returns the original path', passthrough === srcPng)

  const status = await page.evaluate(() => window.stimmaDesktop.voiceModelStatus())
  check('voiceModelStatus is false with an empty cache', status === false)

  const startRejected = await page
    .evaluate(() => window.stimmaDesktop.voiceStart(() => {}))
    .then(() => false, () => true)
  check('voiceStart rejects without a model', startRejected)

  const stopText = await page.evaluate(() => window.stimmaDesktop.voiceStop())
  check('voiceStop with no session yields empty transcript', stopText === '')
} finally {
  await app.close()
}

server.close()
sandbox.cleanup()

if (failed) process.exit(1)
console.log('electron helper e2e: all checks passed')
