<script setup lang="ts">
/**
 * Assets scope, opened by tapping the Assets hub's title: All assets, saved
 * views, Upload, Trash. The desktop sidebar's zone 1 as a sheet.
 */
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Squares2X2Icon, TrashIcon, BookmarkIcon, ArrowUpTrayIcon, CheckIcon,
} from '@heroicons/vue/24/outline'
import Sheet from '../ui/Sheet.vue'
import { useMediaApi } from '../../composables/useMediaApi'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ close: [] }>()

const route = useRoute()
const router = useRouter()
const { getSavedViews } = useMediaApi()

const savedViews = ref<any[]>([])

watch(() => props.show, async (open) => {
  if (!open) return
  try { savedViews.value = await getSavedViews() } catch { savedViews.value = [] }
})

function go(to: string) {
  emit('close')
  router.push(to)
}
function isActive(name: string, id?: string | number) {
  if (route.name !== name) return false
  return id === undefined || String(route.params.id) === String(id)
}
</script>

<template>
  <Sheet :show="show" title="Assets" @close="emit('close')">
    <div class="pb-2">
      <button type="button" class="sheet-row" :class="isActive('browse') && 'text-accent-hi'" @click="go('/browse')">
        <Squares2X2Icon class="sheet-row-icon" />
        <span class="flex-1 truncate">All assets</span>
        <CheckIcon v-if="isActive('browse')" class="w-5 h-5 text-accent-hi" />
      </button>


      <template v-if="savedViews.length">
        <div class="sheet-section">Saved views</div>
        <button
          v-for="v in savedViews"
          :key="v.id"
          type="button"
          class="sheet-row"
          :class="isActive('saved-view', v.id) && 'text-accent-hi'"
          @click="go(`/saved-view/${v.id}`)"
        >
          <BookmarkIcon class="sheet-row-icon" />
          <span class="flex-1 truncate">{{ v.name }}</span>
          <CheckIcon v-if="isActive('saved-view', v.id)" class="w-5 h-5 text-accent-hi" />
        </button>
      </template>

      <div class="mt-2 border-t border-edge-subtle">
        <button type="button" class="sheet-row" :class="isActive('upload') && 'text-accent-hi'" @click="go('/upload')">
          <ArrowUpTrayIcon class="sheet-row-icon" />
          <span class="flex-1 truncate">Upload</span>
        </button>
        <button type="button" class="sheet-row" :class="isActive('trash') && 'text-accent-hi'" @click="go('/trash')">
          <TrashIcon class="sheet-row-icon" />
          <span class="flex-1 truncate">Trash</span>
          <CheckIcon v-if="isActive('trash')" class="w-5 h-5 text-accent-hi" />
        </button>
      </div>
    </div>
  </Sheet>
</template>

