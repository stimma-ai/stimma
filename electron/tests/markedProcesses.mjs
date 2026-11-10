import fs from 'node:fs'
import path from 'node:path'

/** Find only this test's children, including Chromium helpers hiding environ. */
export function markedProcesses(marker, scratch) {
  const found = []
  for (const entry of fs.readdirSync('/proc')) {
    if (!/^\d+$/.test(entry)) continue
    let marked = false
    try {
      marked = fs.readFileSync(`/proc/${entry}/environ`, 'utf8')
        .includes(`STIMMA_UPDATE_TEST_ID=${marker}\0`)
    } catch { /* Chromium can make environ unreadable even to its own user. */ }
    if (!marked) {
      try {
        // Sandboxed Chromium subprocesses still expose their unique user-data
        // directory in argv. Match an entire argument value under this exact
        // scratch tree, never a process name or a shared cache directory.
        marked = fs.readFileSync(`/proc/${entry}/cmdline`, 'utf8').split('\0')
          .some(arg => (arg.includes('=') ? arg.slice(arg.indexOf('=') + 1) : arg)
            .startsWith(scratch + path.sep))
      } catch { /* Process exited or belongs to another user. */ }
    }
    if (marked) found.push(Number(entry))
  }
  return found
}
