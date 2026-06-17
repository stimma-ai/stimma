<template>
  <MediaImage
    :media-id="mediaId"
    :thumbnail="thumbnail"
    :thumbnail-size="thumbnailSize"
    :contain="contain"
    :draggable="draggable"
    :enable-context-menu="enableContextMenu"
    :container-class="containerClass"
    :img-class="imgClass"
    @click="handleClick"
  >
    <slot />
    <button
      v-if="showInfoButton"
      type="button"
      class="absolute bottom-1 right-1 z-10 w-6 h-6 flex items-center justify-center rounded bg-black/60 backdrop-blur-md text-white/75 hover:text-white hover:bg-blue-500/85 transition-colors"
      title="Show media info"
      @click.stop="handleInfoClick"
    >
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
        <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a.75.75 0 000 1.5h.253a.25.25 0 01.244.304l-.459 2.066A1.75 1.75 0 0010.747 15H11a.75.75 0 000-1.5h-.253a.25.25 0 01-.244-.304l.459-2.066A1.75 1.75 0 009.253 9H9z" clip-rule="evenodd" />
      </svg>
    </button>
  </MediaImage>
</template>

<script setup lang="ts">
import { inject } from 'vue'
import { MediaImage } from '../media'
import { flowMediaSlideshowKey } from './flowMediaSlideshow'

interface Props {
  mediaId: number
  mediaIds?: number[]
  index?: number
  thumbnail?: boolean
  thumbnailSize?: number
  contain?: boolean
  draggable?: boolean | 'true' | 'false'
  enableContextMenu?: boolean
  showInfoButton?: boolean
  containerClass?: string
  imgClass?: string
}

const props = withDefaults(defineProps<Props>(), {
  index: undefined,
  thumbnail: true,
  thumbnailSize: 256,
  contain: false,
  draggable: true,
  enableContextMenu: true,
  showInfoButton: false,
  containerClass: '',
  imgClass: '',
})

const slideshow = inject(flowMediaSlideshowKey, null)

function handleClick(event: MouseEvent) {
  event.stopPropagation()
  openMediaInfo()
}

function handleInfoClick(event: MouseEvent) {
  event.stopPropagation()
  openMediaInfo()
}

function openMediaInfo() {
  slideshow?.open(props.mediaId, {
    mediaIds: props.mediaIds,
    startIndex: props.index,
  })
}
</script>
