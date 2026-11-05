import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { crc32, inflateRawSync } from 'node:zlib'
import { exportLogs, promptLogExport, scrubLogExport } from '../src/logExport.ts'
import { applicationMenuTemplate } from '../src/menuTemplate.ts'

// Inspect both ZIP directory and local records; inflate and verify every CRC.
function readZip(zip: Buffer): Map<string, string> {
  const end = zip.length - 22
  assert.equal(zip.readUInt32LE(end), 0x06054b50)
  const count = zip.readUInt16LE(end + 10)
  const directoryStart = zip.readUInt32LE(end + 16)
  assert.equal(directoryStart + zip.readUInt32LE(end + 12), end)
  let offset = directoryStart
  const entries = new Map<string, string>()
  for (let i = 0; i < count; i++) {
    assert.equal(zip.readUInt32LE(offset), 0x02014b50)
    const local = zip.readUInt32LE(offset + 42)
    assert.equal(zip.readUInt32LE(local), 0x04034b50)
    assert.equal(zip.readUInt16LE(local + 8), 8)
    const nameLength = zip.readUInt16LE(offset + 28)
    const name = zip.subarray(offset + 46, offset + 46 + nameLength).toString()
    assert.equal(zip.subarray(local + 30, local + 30 + zip.readUInt16LE(local + 26)).toString(), name)
    const start = local + 30 + zip.readUInt16LE(local + 26) + zip.readUInt16LE(local + 28)
    const data = inflateRawSync(zip.subarray(start, start + zip.readUInt32LE(offset + 20)))
    assert.equal(data.length, zip.readUInt32LE(offset + 24))
    assert.equal(crc32(data), zip.readUInt32LE(offset + 16))
    assert.equal(crc32(data), zip.readUInt32LE(local + 14))
    entries.set(name, data.toString())
    offset += 46 + nameLength + zip.readUInt16LE(offset + 30) + zip.readUInt16LE(offset + 32)
  }
  assert.equal(offset, end)
  return entries
}

async function scratch(t: test.TestContext): Promise<string> {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'log-export-'))
  t.after(() => fs.rm(dir, { recursive: true, force: true }))
  return dir
}

test('export ZIP includes all shell and backend rotations plus scrubbed version metadata', async (t) => {
  const dir = await scratch(t)
  const logs = path.join(dir, 'Logs')
  await fs.mkdir(logs)
  const names = ['Stimma-shell.log', ...Array.from({ length: 4 }, (_, i) => `Stimma-shell.log.${i + 1}`),
    ...Array.from({ length: 20 }, (_, i) => `Stimma_log.${String(i).padStart(2, '0')}.txt`)]
  for (const name of names) await fs.writeFile(path.join(logs, name), `${name.startsWith('Stimma-shell') ? '\n' : ''}failure in ${os.homedir()}/private/file token=private-token\n`)
  await fs.writeFile(path.join(logs, 'unrelated.txt'), 'must not export')
  const destination = path.join(dir, 'logs.zip')
  await exportLogs(destination, dir, '1.2.3')
  const entries = readZip(await fs.readFile(destination))
  assert.equal(entries.size, 26)
  for (const name of names) {
    assert.equal(entries.get(name), 'failure in ~/private/file token=[redacted]\n')
    assert.equal(path.basename(name), name)
  }
  assert.match(entries.get('version.txt')!, /Version: 1.2.3\nPlatform: /)
  assert.ok(!entries.has('unrelated.txt'))
})

test('export scrubs home paths, JSON secrets, bearer values, provider keys and JWTs', () => {
  const windowsHome = ['C:', 'Users', 'account'].join('\\')
  const posixHome = ['', 'Users', 'account'].join('/')
  const otherHome = ['', 'home', 'other account'].join('/')
  const jwt = 'eyJhbGciOiJSUzI1NiIsImtpZCI.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4'
  const key = 'sk-' + 'x'.repeat(40)
  const text = [windowsHome, windowsHome.replaceAll('\\', '\\\\'), windowsHome.replaceAll('\\', '/'), posixHome, otherHome,
    '"api_key": "private-key"', "'refresh_token': 'private-refresh'", 'Authorization: Basic private-basic',
    'Bearer ' + 'a'.repeat(24), jwt, key, 'ghp_' + 'b'.repeat(36), 'token=private-token', 'pin=123456',
    'password=private-password', 'client_secret=private-secret'].join('\n')
  const scrubbed = scrubLogExport(text, windowsHome)
  for (const value of ['account', 'private-', jwt, key, 'a'.repeat(24), 'b'.repeat(36), '123456']) {
    assert.ok(!scrubbed.includes(value), value)
  }
  assert.equal(scrubLogExport('completion used 1523 tokens (prompt_tokens 800)'), 'completion used 1523 tokens (prompt_tokens 800)')
})

test('export archives redact standalone local and known device identities', async (t) => {
  t.mock.method(os, 'userInfo', () => ({ username: 'test-account' }))
  t.mock.method(os, 'hostname', () => 'sample-workstation')
  const dir = await scratch(t)
  await fs.mkdir(path.join(dir, 'Logs'))
  const messages = [
    'user=test-account host=SAMPLE-WORKSTATION',
    'Connected to Studio Computer via tailscale studio-node.example:9191',
    'Bootstrap refused by Studio Computer: 403',
    'Cached session rejected by Studio Computer; re-bootstrapping',
    'Target set to 192.0.2.14:9191',
    'getaddrinfo ENOTFOUND studio-node.example',
  ].join('\n')
  await fs.writeFile(path.join(dir, 'Logs', 'Stimma-shell.log'), '\n' + messages)
  const destination = path.join(dir, 'logs.zip')
  await promptLogExport(dir, 'dev', {
    showSaveDialog: async () => ({ canceled: false, filePath: destination }),
    showErrorBox: (_title, message) => assert.fail(message),
  }, ['Studio Computer', 'studio-node.example', '192.0.2.14'])
  const text = readZip(await fs.readFile(destination)).get('Stimma-shell.log')!
  assert.match(text, /Connected to \[redacted\] via tailscale \[redacted\]:9191/)
  for (const value of ['test-account', 'sample-workstation', 'Studio Computer', 'studio-node.example', '192.0.2.14']) {
    assert.ok(!text.toLowerCase().includes(value.toLowerCase()), value)
  }
})

test('export drops leading fragments from every shell rotation including the current file', async (t) => {
  const dir = await scratch(t)
  const logs = path.join(dir, 'Logs')
  await fs.mkdir(logs)
  await fs.writeFile(path.join(logs, 'Stimma-shell.log.2'), 'older record\ntoken=')
  await fs.writeFile(path.join(logs, 'Stimma-shell.log.1'), 'private-rotated-value\nuseful diagnostic\ntoken=')
  await fs.writeFile(path.join(logs, 'Stimma-shell.log'), 'private-current-value')
  const destination = path.join(dir, 'logs.zip')
  await exportLogs(destination, dir, 'dev')
  const entries = readZip(await fs.readFile(destination))
  assert.equal(entries.get('Stimma-shell.log'), '')
  assert.equal(entries.get('Stimma-shell.log.1'), 'useful diagnostic\ntoken=')
  assert.ok(![...entries.values()].join('').includes('private-'))
})

test('export bounds legacy logs, tolerates missing rotations and never changes source logs', async (t) => {
  const dir = await scratch(t)
  const logs = path.join(dir, 'Logs')
  await fs.mkdir(logs)
  const filename = path.join(logs, 'Stimma-shell.log')
  const input = await fs.open(filename, 'w')
  await input.write('do not read this old content')
  await input.write('\nrecent renderer failure\n', 1024 * 1024 * 1024)
  await input.close()
  const before = (await fs.stat(filename)).size
  const destination = path.join(dir, 'logs.zip')
  await exportLogs(destination, dir, 'dev')
  const entries = readZip(await fs.readFile(destination))
  assert.equal(entries.size, 2)
  assert.equal(entries.get('Stimma-shell.log'), 'recent renderer failure\n')
  assert.equal((await fs.stat(filename)).size, before)
  await assert.rejects(exportLogs(filename, dir, 'dev'), /overwrite/)
  assert.equal((await fs.stat(filename)).size, before)
})

test('Help export item works in packaged and dev menus on every desktop platform', () => {
  for (const platform of ['darwin', 'linux', 'win32'] as const) {
    for (const dev of [true, false]) {
      let clicks = 0
      const template = applicationMenuTemplate(dev, platform, () => { clicks++ })
      const help = template.find((item) => item.role === 'help')!
      assert.ok(Array.isArray(help.submenu))
      const item = help.submenu.find((item) => item.label === 'Export Logs…')!
      ;(item.click as () => void)()
      assert.equal(clicks, 1)
    }
  }
})

test('native export dialog cancels quietly and reports failures with only the requested message', async (t) => {
  const dir = await scratch(t)
  const errors: string[][] = []
  const destination = path.join(dir, 'logs.zip')
  let canceled = true
  const dialogs = {
    showSaveDialog: async (options: { defaultPath: string }) => {
      assert.equal(options.defaultPath, 'Stimma-logs.zip')
      return { canceled, filePath: destination }
    },
    showErrorBox: (title: string, text: string) => { errors.push([title, text]) },
  }
  await promptLogExport(dir, 'dev', dialogs)
  assert.deepEqual(await fs.readdir(dir), [])
  canceled = false
  await promptLogExport(dir, 'dev', dialogs)
  assert.ok(readZip(await fs.readFile(destination)).has('version.txt'))
  assert.deepEqual(errors, [])
  // A bad log must fail the export, retain an existing destination, and remove
  // the temporary archive rather than reporting success with missing content.
  const prior = await fs.readFile(destination)
  await fs.mkdir(path.join(dir, 'Logs', 'Stimma-shell.log'), { recursive: true })
  await promptLogExport(dir, 'dev', dialogs)
  assert.deepEqual(errors, [['Stimma', "Couldn't export logs."]])
  assert.deepEqual(await fs.readFile(destination), prior)
  assert.ok(!(await fs.readdir(dir)).some((name) => name.endsWith('.tmp')))
  dialogs.showSaveDialog = async () => { throw new Error('dialog failed') }
  await promptLogExport(dir, 'dev', dialogs)
  assert.equal(errors.length, 2)
})
