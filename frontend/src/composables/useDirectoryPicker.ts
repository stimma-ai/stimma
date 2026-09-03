/**
 * One way to ask for a folder, wherever the backend lives.
 *
 * Folder paths are interpreted by the backend, so the picker has to browse
 * the backend's machine. When that is this machine (desktop shell driving
 * its own server) the native OS dialog is the right tool. When the window
 * is driving a remote server, or runs in a plain browser, the native dialog
 * would show the wrong disks, so the in-app picker (DirectoryPickerModal,
 * mounted once in App.vue) browses over the API instead.
 */
import { readonly, ref } from 'vue'
import { desktop, isDesktop } from '../desktop'
import { useMultiDevice } from './useMultiDevice'

export interface DirectoryPickerOptions {
  title?: string
  /** Folder to open first; the picker falls back to Home if it cannot be read. */
  defaultPath?: string
}

// The in-app picker is a singleton: one host component, one pending request.
const request = ref<DirectoryPickerOptions | null>(null)
let resolver: ((path: string | null) => void) | null = null

function settle(path: string | null) {
  const resolve = resolver
  resolver = null
  request.value = null
  resolve?.(path)
}

function pickInApp(options: DirectoryPickerOptions): Promise<string | null> {
  // A second request while one is open supersedes it; the first caller
  // sees a cancel rather than hanging forever.
  if (resolver) settle(null)
  return new Promise((resolve) => {
    resolver = resolve
    request.value = { ...options }
  })
}

/** Resolves the chosen absolute path, or null when cancelled. */
export async function pickDirectory(options: DirectoryPickerOptions = {}): Promise<string | null> {
  const { isRemote } = useMultiDevice()
  if (isDesktop() && !isRemote.value) {
    try {
      return await desktop.pickDirectory(options)
    } catch (err) {
      console.warn('[DirectoryPicker] native dialog failed, using in-app picker:', err)
    }
  }
  return pickInApp(options)
}

/** For DirectoryPickerModal only. */
export function useDirectoryPickerHost() {
  return {
    request: readonly(request),
    resolve: settle,
  }
}
