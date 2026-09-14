<template>
  <div class="flex items-center gap-0.5">
    <IconButton title="Attach to reply" aria-label="Attach to reply" @click="$emit('attach')"><PaperClipIcon class="w-4 h-4" /></IconButton>
    <IconButton v-if="canSaveFileToLibrary(file)" title="Save to library" aria-label="Save to library" @click="$emit('save')"><ArrowUpTrayIcon class="w-4 h-4" /></IconButton>
    <a :href="url" title="Download" aria-label="Download" class="inline-flex items-center justify-center w-7 h-7 rounded-md text-content-muted hover:text-content hover:bg-overlay-subtle focus-visible:ring-2 focus-visible:ring-accent"><ArrowDownTrayIcon class="w-4 h-4" /></a>
  </div>
</template>
<script setup lang="ts">
import { PaperClipIcon, ArrowUpTrayIcon, ArrowDownTrayIcon } from '@heroicons/vue/24/outline'
import IconButton from '../ui/IconButton.vue'
import { canSaveFileToLibrary, type WorkspaceFile } from '../../utils/fileRefs'
defineProps<{ url: string; file: WorkspaceFile }>()
defineEmits<{ attach: []; save: [] }>()
</script>
