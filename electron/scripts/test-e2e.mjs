import { spawnSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const electronRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const tests = [
  'smoke.test.mjs',
  'windows.e2e.mjs',
  'helper.e2e.mjs',
  'legacy-storage.e2e.mjs',
]

function run(command, args, env = process.env) {
  const result = spawnSync(command, args, {
    cwd: electronRoot,
    env,
    stdio: 'inherit',
  })
  if (result.error) throw result.error
  return result.status ?? 1
}

function runTests() {
  for (const test of tests) {
    const status = run(process.execPath, [path.join('tests', test)])
    if (status !== 0) process.exit(status)
  }
}

if (process.platform !== 'linux' || process.argv.includes('--isolated-display')) {
  runTests()
} else {
  // Never let Electron E2E windows connect to the developer's live Wayland
  // compositor. xvfb-run supplies a private DISPLAY and tears it down when the
  // nested runner exits; the explicit X11 hint prevents Chromium's Ozone auto
  // detection from following other inherited desktop-session variables.
  const env = { ...process.env }
  delete env.WAYLAND_DISPLAY
  delete env.DISPLAY
  env.ELECTRON_OZONE_PLATFORM_HINT = 'x11'
  env.OZONE_PLATFORM = 'x11'
  env.XDG_SESSION_TYPE = 'x11'
  env.XDG_BACKEND = 'x11'
  env.GDK_BACKEND = 'x11'
  env.QT_QPA_PLATFORM = 'xcb'
  delete env.MOZ_ENABLE_WAYLAND

  const status = run(
    'xvfb-run',
    [
      '-a',
      '-s',
      '-screen 0 1920x1080x24',
      process.execPath,
      fileURLToPath(import.meta.url),
      '--isolated-display',
    ],
    env,
  )
  process.exit(status)
}
