import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const test = fileURLToPath(new URL('../tests/appimage-update.e2e.mjs', import.meta.url))

if (process.platform !== 'linux') {
  console.error('The AppImage update test only runs on Linux.')
  process.exit(1)
}

const env = { ...process.env }
delete env.WAYLAND_DISPLAY
delete env.DISPLAY
delete env.MOZ_ENABLE_WAYLAND
env.ELECTRON_OZONE_PLATFORM_HINT = 'x11'
env.OZONE_PLATFORM = 'x11'
env.XDG_SESSION_TYPE = 'x11'
env.XDG_BACKEND = 'x11'
env.GDK_BACKEND = 'x11'
env.QT_QPA_PLATFORM = 'xcb'

const result = spawnSync(
  'xvfb-run',
  [
    '-a',
    '-s',
    '-screen 0 1920x1080x24',
    'prlimit',
    '--core=0:0',
    '--',
    process.execPath,
    test,
  ],
  { env, stdio: 'inherit' },
)

if (result.error) throw result.error
process.exit(result.status ?? 1)
