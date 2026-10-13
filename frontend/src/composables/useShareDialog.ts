/**
 * The one share-link dialog (mounted once in App.vue), opened from anywhere:
 * `useShareDialog().open(media)`. Accepts a media id or a media object; the
 * dialog always reloads the full item itself.
 */
import { readonly, ref } from 'vue'

export interface ShareDialogTarget {
  id: number
  [key: string]: unknown
}

interface ShareDialogState {
  visible: boolean
  mediaId: number | null
  /** The caller's copy of the item, if it had one: lets the dialog paint before the reload lands. */
  media: ShareDialogTarget | null
  /** Bumps on every open, so reopening the same item restarts the session. */
  openCount: number
}

const state = ref<ShareDialogState>({ visible: false, mediaId: null, media: null, openCount: 0 })

export function useShareDialog() {
  function open(target: number | ShareDialogTarget | null | undefined) {
    const media = target != null && typeof target === 'object' ? target : null
    const id = media ? Number(media.id) : Number(target)
    if (!Number.isFinite(id) || id <= 0) return false
    state.value = { visible: true, mediaId: id, media, openCount: state.value.openCount + 1 }
    return true
  }

  function close() {
    state.value = { ...state.value, visible: false }
  }

  return { state: readonly(state), open, close }
}
