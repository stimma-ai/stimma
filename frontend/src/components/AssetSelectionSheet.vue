<script setup lang="ts">
import { ref, watch } from 'vue'
import Sheet from './ui/Sheet.vue'
import AppImage from './media/AppImage.vue'
import { useAssetApi, type AssetBrowserItem } from '../composables/useAssetApi'
import { useMediaApi } from '../composables/useMediaApi'
const props = defineProps<{ show: boolean; saving?: boolean }>()
const emit = defineEmits<{ close: []; select: [ids: number[]] }>()
const { fetchAssets } = useAssetApi()
const { getThumbnailUrl } = useMediaApi()
const items = ref<AssetBrowserItem[]>([])
const selected = ref<number[]>([])
const query = ref('')
const loading = ref(false)
const error = ref('')
const page = ref(0)
const total = ref(0)
let request = 0
async function load(reset = false) {
  const token = ++request
  if (reset) { items.value = []; page.value = 0 }
  loading.value = true
  error.value = ''
  try {
    const result = await fetchAssets({ page: page.value + 1, page_size: 60, caption_query: query.value || undefined })
    if (token !== request || !props.show) return
    items.value.push(...result.items)
    total.value = result.total
    page.value++
  } catch { if (token === request) error.value = 'Could not load assets. Try again.' }
  finally { if (token === request) loading.value = false }
}
function toggle(id: number) {
  selected.value = selected.value.includes(id) ? selected.value.filter(value => value !== id) : [...selected.value, id]
}
watch(() => props.show, show => {
  if (!show) { request++; return }
  selected.value = []; query.value = ''; void load(true)
})
</script>
<template>
  <Sheet :show="show" title="Add assets" expandable content-class="flex flex-col overflow-hidden" :close-on-backdrop="!saving" @close="!saving && emit('close')">
    <form class="flex flex-none gap-2 p-3" @submit.prevent="load(true)">
      <input v-model="query" aria-label="Search asset captions" placeholder="Search captions" class="h-11 min-w-0 flex-1 px-3 bg-base border border-edge rounded-md text-content" />
      <button class="min-h-11 px-3 text-accent-hi" :disabled="loading">Search</button>
    </form>
    <div class="flex-1 min-h-0 overflow-y-auto overscroll-contain p-3">
      <p v-if="error" role="alert" class="text-content-secondary">{{ error }} <button class="min-h-11 text-accent-hi" @click="load()">Retry</button></p>
      <div class="grid grid-cols-3 gap-2">
        <button v-for="item in items" :key="item.asset_id" type="button" class="relative aspect-square overflow-hidden rounded-media border-2" :class="selected.includes(item.asset_id) ? 'border-selection' : 'border-transparent'" :aria-label="`Select asset ${item.asset_id}`" :aria-pressed="selected.includes(item.asset_id)" @click="toggle(item.asset_id)">
          <AppImage :src="getThumbnailUrl(item.file_hash, 256)" container-class="w-full h-full" />
          <span v-if="selected.includes(item.asset_id)" class="absolute top-1 right-1 rounded-full bg-selection text-white px-1" aria-hidden="true">✓</span>
        </button>
      </div>
      <p v-if="loading" role="status" class="py-4 text-content-secondary">Loading assets…</p>
      <p v-else-if="!items.length && !error" class="py-4 text-content-secondary">No assets found.</p>
      <button v-else-if="items.length < total" class="min-h-11 w-full text-accent-hi" @click="load()">Load more</button>
    </div>
    <div class="flex flex-none gap-2 justify-end p-3">
      <button class="min-h-11 px-4 text-content-secondary" :disabled="saving" @click="emit('close')">Cancel</button>
      <button class="min-h-11 px-4 rounded-md bg-accent text-white disabled:opacity-40" :disabled="!selected.length || saving" @click="emit('select', selected)">{{ saving ? 'Adding…' : selected.length ? `Add ${selected.length} ${selected.length === 1 ? 'asset' : 'assets'}` : 'Add assets' }}</button>
    </div>
  </Sheet>
</template>
