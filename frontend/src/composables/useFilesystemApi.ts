/**
 * Folder browsing on the machine running the backend.
 *
 * Whatever server the window is driving answers here, so a remote server
 * lists its own disks rather than the laptop's.
 */
import axios from 'axios'
import { getApiBase } from '../apiConfig'
import type { DirectoryListing } from '../utils/directoryPicker'

export type { DirectoryEntry, DirectoryListing, PathSegment } from '../utils/directoryPicker'

export function useFilesystemApi() {
  /** Omit `path` for the roots (home, standard folders, volumes). */
  async function browseDirectory(path?: string): Promise<DirectoryListing> {
    const response = await axios.get(`${getApiBase()}/fs/browse`, {
      params: path ? { path } : {},
    })
    return response.data
  }

  return { browseDirectory }
}

/** The server's reason when it has one, otherwise something readable. */
export function browseErrorMessage(err: unknown): string {
  const detail = (err as any)?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  const message = (err as any)?.message
  return typeof message === 'string' && message ? message : 'Could not read that folder'
}
