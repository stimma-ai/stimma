<template>
  <Modal
    :show="visible"
    size="custom"
    custom-class="flex max-h-[80vh] w-full max-w-[520px] flex-col"
    @close="close"
  >
    <template #header>
      <div class="flex items-center justify-between">
        <h2 class="text-lg font-semibold text-content">Add to Collection</h2>
        <IconButton @click="close">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="h-icon-nav w-icon-nav">
            <path d="M6 18L18 6M6 6l12 12" />
          </svg>
        </IconButton>
      </div>
    </template>

          <div class="flex gap-2 border-b border-edge-subtle px-5 py-4">
            <input
              v-no-autocorrect
              v-model="newCollectionName"
              type="text"
              placeholder="Create new collection..."
              class="flex-1 rounded-md border border-edge-subtle bg-surface-raised px-3 py-2 text-sm text-content outline-none ring-0 placeholder:text-content-muted focus:border-edge-strong"
              @keydown.enter="createNewCollection"
            />
            <button
              class="rounded-md bg-surface-hover px-4 py-2 text-sm font-medium text-content transition-colors hover:bg-surface-active disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="!newCollectionName.trim() || creating"
              @click="createNewCollection"
            >
              {{ creating ? 'Creating...' : 'Create' }}
            </button>
          </div>

          <div class="flex-1 overflow-y-auto px-5 py-3">
            <div v-if="loading" class="py-10 text-center text-sm text-content-tertiary">
              Loading collections...
            </div>

            <div v-else-if="collections.length === 0" class="py-10 text-center text-sm text-content-tertiary">
              No collections yet. Create one above.
            </div>

            <button
              v-for="collection in collections"
              :key="collection.id"
              class="mb-2 flex w-full items-center justify-between gap-3 rounded-lg px-3 py-3 text-left transition-colors"
              :class="selectedCollectionId === collection.id ? 'bg-selection/15 ring-1 ring-selection/40' : 'hover:bg-overlay-subtle'"
              @click="selectedCollectionId = collection.id"
            >
              <div class="min-w-0 flex-1">
                <h3
                  class="truncate text-sm font-medium"
                  :class="collection.name ? 'text-content' : 'italic text-content-muted'"
                >
                  {{ collection.name || 'Name this collection...' }}
                </h3>
                <span class="font-mono text-xs tabular-nums text-content-muted">{{ collection.asset_count || 0 }} {{ (collection.asset_count || 0) === 1 ? 'asset' : 'assets' }}</span>
              </div>
              <svg
                v-if="selectedCollectionId === collection.id"
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="currentColor"
                class="h-6 w-6 flex-shrink-0 text-selection"
              >
                <path fill-rule="evenodd" d="M2.25 12c0-5.385 4.365-9.75 9.75-9.75s9.75 4.365 9.75 9.75-4.365 9.75-9.75 9.75S2.25 17.385 2.25 12zm13.36-1.814a.75.75 0 10-1.22-.872l-3.236 4.53L9.53 12.22a.75.75 0 00-1.06 1.06l2.25 2.25a.75.75 0 001.14-.094l3.75-5.25z" clip-rule="evenodd" />
              </svg>
            </button>
          </div>

    <template #footer>
      <Button variant="ghost" @click="close">
        Cancel
      </Button>
      <Button variant="primary" :disabled="!selectedCollectionId || saving" @click="saveChanges">
        {{ saving ? 'Saving...' : 'Add to Collection' }}
      </Button>
    </template>
  </Modal>
</template>

<script setup>
import { ref, watch } from 'vue'
import Modal from './ui/Modal.vue'
import Button from './ui/Button.vue'
import IconButton from './ui/IconButton.vue'
import { useMediaApi } from '../composables/useMediaApi'
import { useAssetApi } from '../composables/useAssetApi'
import { useOwnerProject } from '../composables/useProjectScope'

const props = defineProps({
  visible: { type: Boolean, default: false },
  mediaIds: { type: Array, default: () => [] },
  assetIds: { type: Array, default: () => [] },
  // Collections listed and created here belong to this project. Defaults to the
  // active working project; null means top-level collections.
  projectId: { type: Number, default: undefined }
})

const emit = defineEmits(['close', 'saved'])
const { addMediaToCollection, createCollection, getCollections } = useMediaApi()
const { addToCollection: addAssetsToCollection } = useAssetApi()

const collectionProjectId = useOwnerProject(() => props.projectId)
const collections = ref([])
const loading = ref(false)
const saving = ref(false)
const creating = ref(false)
const selectedCollectionId = ref(null)
const newCollectionName = ref('')

async function loadCollections() {
  loading.value = true
  try {
    collections.value = await getCollections(collectionProjectId.value)
  } finally {
    loading.value = false
  }
}

async function createNewCollection() {
  const name = newCollectionName.value.trim()
  if (!name) return
  creating.value = true
  try {
    const collection = await createCollection(name, collectionProjectId.value)
    collections.value.unshift({ ...collection, asset_count: collection.asset_count || 0 })
    selectedCollectionId.value = collection.id
    newCollectionName.value = ''
  } finally {
    creating.value = false
  }
}

async function saveChanges() {
  if (!selectedCollectionId.value) return
  saving.value = true
  try {
    if (props.assetIds.length > 0) {
      await addAssetsToCollection(selectedCollectionId.value, props.assetIds)
    } else {
      await addMediaToCollection(selectedCollectionId.value, props.mediaIds)
    }
    emit('saved', selectedCollectionId.value)
    close()
  } finally {
    saving.value = false
  }
}

function close() {
  emit('close')
  selectedCollectionId.value = null
  newCollectionName.value = ''
}

watch(() => props.visible, (visible) => {
  if (visible) loadCollections()
})
</script>
