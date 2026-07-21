<template>
  <div class="h-full flex flex-col bg-slideshow-matt">
    <div class="shrink-0 flex items-center gap-2 px-6 py-3">
      <svg class="w-4 h-4 text-rose-400" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 0 1-1.125-1.125M3.375 19.5h1.5C5.496 19.5 6 18.996 6 18.375m14.625 1.125c.621 0 1.125-.504 1.125-1.125M6 18.375v-12.75m12 12.75v-12.75M6 5.625C6 5.004 6.504 4.5 7.125 4.5h9.75c.621 0 1.125.504 1.125 1.125M3.375 4.5h1.5C5.496 4.5 6 5.004 6 5.625m-3.75 0c0-.621.504-1.125 1.125-1.125m18 1.125c0-.621-.504-1.125-1.125-1.125h-1.5c-.621 0-1.125.504-1.125 1.125" />
      </svg>
      <h1 class="text-sm font-medium text-content truncate">{{ title || 'Untitled' }}</h1>
    </div>
    <div class="flex-1 min-h-0 relative">
      <TimelineViewer
        v-if="assetIdNumber"
        :key="assetIdNumber"
        :initial-asset-id="assetIdNumber"
        class="absolute inset-0"
        @loaded="onLoaded"
      />
    </div>

    <!-- Agent dock -->
    <div class="shrink-0 px-6 pb-4 pt-2">
      <div class="flex items-end gap-2">
        <textarea
          v-model="agentDraft"
          rows="1"
          placeholder="Ask the agent to plan, fill, or rearrange this cut…"
          class="flex-1 resize-none bg-overlay-subtle rounded-md px-3 py-2 text-sm text-content placeholder:text-content-muted border border-transparent focus:border-accent outline-none"
          disabled
        />
        <button
          class="bg-accent text-white rounded-md px-3 py-2 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
          disabled
          title="Agent not connected yet"
        >
          Send
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import TimelineViewer from '../components/viewers/TimelineViewer.vue'

const route = useRoute()
const title = ref('')
const agentDraft = ref('')

const assetIdNumber = computed(() => {
  const id = parseInt(route.params.id, 10)
  return isNaN(id) ? null : id
})

function onLoaded(payload) {
  title.value = payload?.title || ''
}
</script>
