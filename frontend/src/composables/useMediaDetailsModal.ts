import { ref, readonly } from 'vue'

interface MediaDetailsModalState {
  visible: boolean
  mediaId: number | null
}

const state = ref<MediaDetailsModalState>({
  visible: false,
  mediaId: null
})

export function useMediaDetailsModal() {
  function open(mediaId: number) {
    state.value = { visible: true, mediaId }
  }

  function close() {
    state.value = { visible: false, mediaId: null }
  }

  return {
    state: readonly(state),
    open,
    close
  }
}
