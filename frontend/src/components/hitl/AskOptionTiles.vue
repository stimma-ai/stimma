<template>
  <div class="flex flex-wrap items-start gap-2">
    <button
      v-for="(opt, index) in options"
      :key="index"
      type="button"
      class="group relative w-[168px] max-w-full text-left rounded-lg p-1.5 transition-colors"
      :class="selectedLabel === opt.label
        ? 'bg-accent-selection/15 border border-accent-selection/40'
        : 'hover:bg-overlay-light border border-transparent'"
      @click="$emit('select', opt.label)"
    >
      <div
        class="relative w-full aspect-square bg-matte rounded-media overflow-hidden"
        :class="selectedLabel === opt.label ? 'ring-2 ring-accent-selection ring-inset' : ''"
      >
        <MediaImage
          v-if="opt.media_id"
          :media-id="opt.media_id"
          :thumbnail="true"
          :thumbnail-size="256"
          :contain="true"
          :enable-context-menu="false"
          container-class="w-full h-full"
          class="w-full h-full"
        />
        <button
          v-if="opt.media_id"
          type="button"
          class="absolute bottom-1 right-1 w-6 h-6 rounded-md bg-black/40 hover:bg-black/60 text-white/50 hover:text-white opacity-0 group-hover:opacity-100 flex items-center justify-center transition-opacity"
          title="View larger"
          @click.stop="$emit('view-image', opt.media_id)"
        >
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15" />
          </svg>
        </button>
      </div>
      <div class="mt-1.5 px-0.5 min-w-0">
        <div class="flex items-baseline gap-1.5">
          <span class="text-xs text-content-muted font-mono flex-shrink-0">{{ index + 1 }}.</span>
          <span class="text-sm font-medium text-content truncate">{{ opt.label }}</span>
        </div>
        <div v-if="opt.description" class="text-xs text-content-muted leading-snug mt-0.5 line-clamp-2">{{ opt.description }}</div>
      </div>
    </button>
  </div>
</template>

<script setup lang="ts">
import { MediaImage } from '../media'

defineProps<{
  options: { label: string; description?: string; media_id?: number }[]
  selectedLabel?: string | null
}>()

defineEmits<{
  (e: 'select', label: string): void
  (e: 'view-image', mediaId: number): void
}>()
</script>
