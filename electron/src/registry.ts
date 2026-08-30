/**
 * Window ↔ profile registry, ported from src-tauri/src/windows.rs.
 *
 * Persists to <dataDir>/windows.json — the SAME file the Tauri shell used,
 * so a fielded Tauri install restores its open windows on first Electron
 * launch. The file always reflects currently open windows: entries are added
 * on create, updated when the frontend reports its resolved profile, removed
 * when a window is closed while others remain. Quitting leaves the file
 * as-is, which is exactly the set to restore next launch.
 */

import fs from 'node:fs'
import path from 'node:path'

export interface WindowEntry {
  label: string
  profile_id: string | null
}

export class WindowRegistry {
  private filePath: string
  private entries: WindowEntry[] = []

  constructor(dataDir: string) {
    this.filePath = path.join(dataDir, 'windows.json')
    try {
      const parsed = JSON.parse(fs.readFileSync(this.filePath, 'utf8'))
      const seen = new Set<string>()
      this.entries = (Array.isArray(parsed?.windows) ? parsed.windows : [])
        .filter(
          (entry: any): entry is WindowEntry =>
            entry && typeof entry.label === 'string' && entry.label.length > 0,
        )
        .filter((entry: WindowEntry) => !seen.has(entry.label) && seen.add(entry.label))
        .map((entry: any) => ({
          label: entry.label,
          profile_id: typeof entry.profile_id === 'string' ? entry.profile_id : null,
        }))
    } catch {
      this.entries = []
    }
  }

  private persist(): void {
    const json = JSON.stringify({ windows: this.entries }, null, 2)
    const tmp = this.filePath + '.tmp'
    try {
      fs.writeFileSync(tmp, json)
      fs.renameSync(tmp, this.filePath)
    } catch {
      // Registry persistence is best-effort, like the Rust side.
    }
  }

  snapshot(): WindowEntry[] {
    return this.entries.map((entry) => ({ ...entry }))
  }

  replace(entries: WindowEntry[]): void {
    this.entries = entries.map((entry) => ({ ...entry }))
    this.persist()
  }

  profileFor(label: string): string | null {
    return this.entries.find((entry) => entry.label === label)?.profile_id ?? null
  }

  labelForProfile(profileId: string): string | null {
    return this.entries.find((entry) => entry.profile_id === profileId)?.label ?? null
  }

  setProfile(label: string, profileId: string): void {
    const existing = this.entries.find((entry) => entry.label === label)
    if (existing) existing.profile_id = profileId
    else this.entries.push({ label, profile_id: profileId })
    this.persist()
  }

  remove(label: string): void {
    this.entries = this.entries.filter((entry) => entry.label !== label)
    this.persist()
  }
}

/** Window labels stay within a conservative charset (mirrors the Rust side). */
export function profileWindowLabel(profileId: string): string {
  const safe = profileId.replace(/[^A-Za-z0-9\-_]/g, '-')
  return `profile-${safe}`
}
