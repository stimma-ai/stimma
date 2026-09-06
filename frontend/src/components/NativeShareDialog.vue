<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import axios from 'axios'
import Modal from './ui/Modal.vue'
import Button from './ui/Button.vue'
import { useMediaApi } from '../composables/useMediaApi'
import { desktop } from '../desktop'
import { shareFile } from '../utils/nativeShare'

const props = defineProps<{ mediaId: number }>()
const emit = defineEmits<{ close: [] }>()
const { getMediaItem, getMediaFileUrl } = useMediaApi()
const file = shallowRef<File | null>(null)
const error = ref('')
const loading = ref(true)
const sharing = ref(false)
const controller = new AbortController()
onBeforeUnmount(() => controller.abort())

onMounted(async () => {
  try {
    const item = await getMediaItem(props.mediaId)
    if (controller.signal.aborted) return
    const response = await axios.get(getMediaFileUrl(props.mediaId), {
      responseType: 'blob', signal: controller.signal,
    })
    const extension = String(item.file_format || '').replace(/^\./, '')
    const name = String(item.file_path || '').split(/[\\/]/).pop() || `stimma-${props.mediaId}${extension ? `.${extension}` : ''}`
    file.value = new File([response.data], name, { type: response.data.type })
  } catch {
    if (!controller.signal.aborted) error.value = 'Could not prepare this file for sharing. Close this sheet and try again.'
  } finally {
    loading.value = false
  }
})

async function share() {
  if (!file.value || sharing.value) return
  sharing.value = true
  error.value = ''
  try {
    await shareFile(file.value, desktop)
    emit('close')
  } catch (err) {
    if ((err as Error)?.name !== 'AbortError') {
      error.value = (err as Error)?.message || 'Could not share this file. Please try again.'
    }
  } finally {
    sharing.value = false
  }
}
</script>

<template>
  <Modal :show="true" size="sm" :close-on-backdrop="!sharing" :close-on-esc="!sharing" @close="emit('close')">
    <div class="px-6 py-5 space-y-3">
      <h2 class="text-lg font-semibold text-content">Share file</h2>
      <p v-if="loading" role="status" class="text-sm text-content-secondary">Preparing file…</p>
      <p v-else-if="file" class="text-sm text-content-secondary break-all">{{ file.name }}</p>
      <p v-if="error" role="alert" class="text-sm text-red-400">{{ error }}</p>
    </div>
    <template #footer>
      <Button variant="secondary" :disabled="sharing" @click="emit('close')">Cancel</Button>
      <Button :disabled="!file" :loading="loading || sharing" @click="share">Share…</Button>
    </template>
  </Modal>
</template>
