import axios from 'axios'
import { computed, ref } from 'vue'
import { getVersion } from '@tauri-apps/api/app'
import { isTauri, getApiBase } from '../apiConfig'
import { useTelemetry } from './useTelemetry'

// What's New: after the app first launches on a new version, fetch that
// version's release notes from the update host and surface a one-time pill
// in the top bar. Notes live at <update host>/stimma/notes/vX.Y.Z.md and are
// published by CI from releasenotes/ on main (see release-notes.yml). A 404
// simply means no notes exist for this version (e.g. a beta without a draft)
// and shows nothing.

const SEEN_PREF_KEY = 'release_notes_last_seen'

const { track } = useTelemetry()

const notesMarkdown = ref<string | null>(null)
const notesVersion = ref<string | null>(null)
const hasUnseenNotes = ref(false)
const whatsNewOpen = ref(false)
let initStarted = false

const updateEndpoint = (import.meta.env.VITE_STIMMA_UPDATE_ENDPOINT || '') as string

// The updater endpoint looks like <base>/stimma/<channel>/<target>/latest.json;
// notes are served from the same host at <base>/stimma/notes/.
const notesBase = computed(() => {
  const idx = updateEndpoint.indexOf('/stimma/')
  if (idx === -1) return ''
  return `${updateEndpoint.slice(0, idx)}/stimma/notes`
})

// Notes files are keyed by the production core version; a beta build of the
// upcoming train (1.0.6-beta.2) reads the 1.0.6 draft if one exists.
function coreVersion(version: string): string {
  return version.split('-')[0]
}

async function getSeenVersion(): Promise<string | null> {
  try {
    const response = await axios.get(`${getApiBase()}/preferences/${SEEN_PREF_KEY}`)
    return response.data?.value?.version ?? null
  } catch {
    return null
  }
}

// privacyLockdownActive is passed in (rather than read here) so init shares
// the caller's already-resolved lockdown state — same contract as
// startUpdaterLoop() in App.vue.
async function initReleaseNotes(privacyLockdownActive: boolean): Promise<void> {
  if (initStarted) return
  initStarted = true

  if (!isTauri() || privacyLockdownActive || !notesBase.value) return

  try {
    const version = coreVersion(await getVersion())
    const seen = await getSeenVersion()
    if (seen === version) return

    const response = await axios.get(`${notesBase.value}/v${version}.md`, {
      responseType: 'text',
      // Axios sniffs JSON-ish text otherwise; the notes are always markdown.
      transformResponse: [(data) => data],
    })
    const body = typeof response.data === 'string' ? response.data.trim() : ''
    if (!body) return

    notesMarkdown.value = body
    notesVersion.value = version
    // First run on this install has no seen version: don't greet a fresh
    // install with What's New, just baseline it.
    if (seen === null) {
      await markNotesSeen()
      return
    }
    hasUnseenNotes.value = true
  } catch {
    // 404 (no notes for this version) or offline — nothing to show.
  }
}

async function markNotesSeen(): Promise<void> {
  hasUnseenNotes.value = false
  if (!notesVersion.value) return
  try {
    await axios.put(`${getApiBase()}/preferences/${SEEN_PREF_KEY}`, { version: notesVersion.value })
  } catch (error) {
    console.error('[release-notes] Failed to persist seen version:', error)
  }
}

function openWhatsNew(): void {
  if (!notesMarkdown.value) return
  whatsNewOpen.value = true
  track('whats_new_opened', { version: notesVersion.value })
  void markNotesSeen()
}

function closeWhatsNew(): void {
  whatsNewOpen.value = false
}

export function useReleaseNotes() {
  return {
    notesMarkdown,
    notesVersion,
    hasUnseenNotes,
    whatsNewOpen,
    initReleaseNotes,
    openWhatsNew,
    closeWhatsNew,
  }
}
