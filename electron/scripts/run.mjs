// One build, one shell process; `stimma run app` leaves renderer/backend servers
// under the caller's control and does not watch or restart the shell.
import { spawn } from 'node:child_process'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const require = createRequire(import.meta.url)
const env = { ...process.env }
delete env.ELECTRON_RUN_AS_NODE

const child = spawn(require('electron'), [root], { stdio: 'inherit', env })
child.on('error', error => {
  console.error(error)
  process.exit(1)
})
child.on('exit', (code, signal) => process.exit(code ?? (signal === 'SIGINT' ? 130 : 143)))
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.once(signal, () => child.kill(signal))
}
