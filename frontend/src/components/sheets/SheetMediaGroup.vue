<template>
  <div ref="root" class="relative my-1.5 w-full" :style="{ height: `${placement.height}px` }" :data-layout="layout">
    <slot />
  </div>
</template>

<script setup lang="ts">
// <stimma-media-group layout="rows|masonry|uniform" size="s|m|l" aspect>.
// Whole pictures, never cropped: the group measures itself and gives every
// tile its rectangle (see sheetLayout.ts).
import { computed, onBeforeUnmount, onMounted, provide, ref } from 'vue'
import { mediaIdOfRef } from './sheetHtml'
import { parseAspect, parseLayout, parseSize, placeTiles } from './sheetLayout'
import { useSheetContext } from './useContactSheet'

const props = defineProps<{ kid?: string; at: Record<string, any>; node: Element }>()
const sheet = useSheetContext()
const root = ref<HTMLElement | null>(null)
const width = ref(0)

const layout = computed(() => parseLayout(props.at.layout))
const size = computed(() => parseSize(props.at.size))
const items = computed(() => Array.from(props.node?.children || [])
  .filter(el => el.tagName === 'STIMMA-MEDIA' && el.id)
  .map(el => {
    const member = sheet.member(mediaIdOfRef(el.getAttribute('ref')))
    const ratio = member?.width && member?.height ? member.width / member.height : 4 / 3
    return { id: el.id, ratio, caption: size.value !== 's' && !!el.getAttribute('caption') }
  }))
const placement = computed(() => placeTiles(items.value, width.value, layout.value, size.value, parseAspect(props.at.aspect || '1')))
provide('sheetPlacement', placement)
provide('sheetGroupSize', size)

let observer: ResizeObserver | null = null
onMounted(() => {
  observer = new ResizeObserver(([entry]) => { width.value = Math.floor(entry.contentRect.width) })
  if (root.value) observer.observe(root.value)
})
onBeforeUnmount(() => observer?.disconnect())
</script>
