import { ref, readonly } from 'vue'

interface LineageModalState {
  visible: boolean
  mediaId: number | null
}

const state = ref<LineageModalState>({
  visible: false,
  mediaId: null
})

export function useLineageModal() {
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
