<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="visible" class="fixed inset-0 z-[10000] flex items-center justify-center bg-black/75 p-5" @click.self="close">
        <div class="flex max-h-[80vh] w-full max-w-[520px] flex-col rounded-xl border border-edge-subtle bg-surface shadow-2xl">
          <div class="flex items-center justify-between border-b border-edge-subtle px-5 py-4">
            <h2 class="text-lg font-semibold text-content">Add to Board</h2>
            <button
              class="rounded p-1 text-content-tertiary transition-colors hover:bg-overlay-light hover:text-content"
              @click="close"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="h-5 w-5">
                <path d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <div class="flex gap-2 border-b border-edge-subtle px-5 py-4">
            <input
              v-no-autocorrect
              v-model="newBoardName"
              type="text"
              placeholder="Create new board..."
              class="flex-1 rounded-md border border-edge-subtle bg-surface-raised px-3 py-2 text-sm text-content outline-none ring-0 placeholder:text-content-muted focus:border-edge-strong"
              @keydown.enter="createNewBoard"
            />
            <button
              class="rounded-md bg-surface-hover px-4 py-2 text-sm font-medium text-content transition-colors hover:bg-surface-active disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="!newBoardName.trim() || creating"
              @click="createNewBoard"
            >
              {{ creating ? 'Creating...' : 'Create' }}
            </button>
          </div>

          <div class="flex-1 overflow-y-auto px-5 py-3">
            <div v-if="loading" class="py-10 text-center text-sm text-content-tertiary">
              Loading boards...
            </div>

            <div v-else-if="boards.length === 0" class="py-10 text-center text-sm text-content-tertiary">
              No boards yet. Create one above.
            </div>

            <button
              v-for="board in boards"
              :key="board.id"
              class="mb-2 flex w-full items-center justify-between gap-3 rounded-lg px-3 py-3 text-left transition-colors"
              :class="selectedBoardId === board.id ? 'bg-blue-500/15 ring-1 ring-blue-500/40' : 'hover:bg-overlay-subtle'"
              @click="selectedBoardId = board.id"
            >
              <div class="min-w-0 flex-1">
                <h3
                  class="truncate text-sm font-medium"
                  :class="board.name ? 'text-content' : 'italic text-content-muted'"
                >
                  {{ board.name || 'Name this board...' }}
                </h3>
                <span class="text-xs text-content-muted">{{ board.asset_count || 0 }} items</span>
              </div>
              <svg
                v-if="selectedBoardId === board.id"
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="currentColor"
                class="h-6 w-6 flex-shrink-0 text-blue-400"
              >
                <path fill-rule="evenodd" d="M2.25 12c0-5.385 4.365-9.75 9.75-9.75s9.75 4.365 9.75 9.75-4.365 9.75-9.75 9.75S2.25 17.385 2.25 12zm13.36-1.814a.75.75 0 10-1.22-.872l-3.236 4.53L9.53 12.22a.75.75 0 00-1.06 1.06l2.25 2.25a.75.75 0 001.14-.094l3.75-5.25z" clip-rule="evenodd" />
              </svg>
            </button>
          </div>

          <div class="flex justify-end gap-2 border-t border-edge-subtle px-5 py-4">
            <button
              class="rounded-md px-4 py-2 text-sm font-medium text-content-tertiary transition-colors hover:bg-overlay-light hover:text-content"
              @click="close"
            >
              Cancel
            </button>
            <button
              class="rounded-md bg-blue-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-400 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="!selectedBoardId || saving"
              @click="saveChanges"
            >
              {{ saving ? 'Saving...' : 'Add to Board' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useMediaApi } from '../composables/useMediaApi'

const props = defineProps({
  visible: { type: Boolean, default: false },
  mediaIds: { type: Array, default: () => [] }
})

const emit = defineEmits(['close', 'saved'])
const { addMediaToBoard, createBoard, getBoards } = useMediaApi()

const boards = ref([])
const loading = ref(false)
const saving = ref(false)
const creating = ref(false)
const selectedBoardId = ref(null)
const newBoardName = ref('')

async function loadBoards() {
  loading.value = true
  try {
    boards.value = await getBoards()
  } finally {
    loading.value = false
  }
}

async function createNewBoard() {
  const name = newBoardName.value.trim()
  if (!name) return
  creating.value = true
  try {
    const board = await createBoard(name)
    boards.value.unshift({ ...board, asset_count: board.asset_count || 0 })
    selectedBoardId.value = board.id
    newBoardName.value = ''
  } finally {
    creating.value = false
  }
}

async function saveChanges() {
  if (!selectedBoardId.value) return
  saving.value = true
  try {
    await addMediaToBoard(selectedBoardId.value, props.mediaIds)
    emit('saved', selectedBoardId.value)
    close()
  } finally {
    saving.value = false
  }
}

function close() {
  emit('close')
  selectedBoardId.value = null
  newBoardName.value = ''
}

watch(() => props.visible, (visible) => {
  if (visible) loadBoards()
})
</script>

<style scoped>
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active > div,
.modal-leave-active > div {
  transition: transform 0.2s ease;
}

.modal-enter-from > div,
.modal-leave-to > div {
  transform: scale(0.95);
}
</style>
