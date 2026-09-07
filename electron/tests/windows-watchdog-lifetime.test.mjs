import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

test('Windows kills backend and grandchild when watchdog is forcibly terminated', {
  skip: process.platform !== 'win32', timeout: 15000,
}, async () => {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
  const binary = path.join(root, 'src-tauri/watchdog/target/release/stimma-watchdog.exe')
  const backend = `const {spawn}=require('node:child_process'); const c=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'ignore'}); console.log(JSON.stringify([process.pid,c.pid])); setInterval(()=>{},1000)`
  const watchdog = spawn(binary, ['--parent-pid', String(process.pid), process.execPath, '-e', backend], { windowsHide: true })
  let descendants = []
  try {
    descendants = await new Promise((resolve, reject) => {
      let out = ''
      watchdog.on('error', reject)
      watchdog.on('exit', code => reject(new Error(`Watchdog exited before backend ready: ${code}`)))
      watchdog.stdout.on('data', chunk => {
        out += chunk
        if (out.includes('\n')) resolve(JSON.parse(out.split('\n')[0]))
      })
    })
    assert.equal(descendants.length, 2)
    // Deliberately omit /T: process-tree cleanup must come from the job.
    const killed = spawnSync('taskkill', ['/PID', String(watchdog.pid), '/F'], { windowsHide: true })
    assert.equal(killed.status, 0)
    const alive = pid => { try { process.kill(pid, 0); return true } catch { return false } }
    for (let i = 0; i < 50 && descendants.some(alive); i++) await new Promise(r => setTimeout(r, 100))
    assert.deepEqual(descendants.filter(alive), [], 'No orphan backend or worker may survive watchdog termination')
  } finally {
    for (const pid of [watchdog.pid, ...descendants]) {
      try { process.kill(pid, 'SIGKILL') } catch { /* already exited */ }
    }
  }
})
