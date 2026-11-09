<template>
  <section class="group/section mb-10 scroll-mt-3" :id="kid" :data-kid="kid">
    <header v-if="at.label" class="mb-2 flex min-h-8 flex-wrap items-center gap-x-2 gap-y-1">
      <button
        v-if="collapsible"
        type="button"
        class="-ml-1 flex min-w-0 items-center gap-1.5 rounded-md px-1 py-1 text-left hover:bg-overlay-subtle"
        :aria-expanded="open"
        @click="open = !open"
      >
        <ChevronRightIcon class="h-3.5 w-3.5 flex-none text-content-muted transition-transform" :class="open ? 'rotate-90' : ''" />
        <span role="heading" aria-level="2" class="min-w-0 break-words font-brand text-[16px] font-semibold leading-snug text-content">{{ at.label }}</span>
      </button>
      <span v-else role="heading" aria-level="2" class="min-w-0 break-words font-brand text-[16px] font-semibold leading-snug text-content">{{ at.label }}</span>
      <span v-if="!open" ref="strip" class="ml-1 flex min-w-0 gap-0.5 overflow-hidden">
        <span v-for="id in mediaIds.slice(0, 8)" :key="id" class="relative h-6 w-6 flex-none overflow-hidden rounded-media bg-matte opacity-70">
          <MediaImage :media-id="id" :thumbnail="true" :thumbnail-size="128" container-class="h-full w-full" :draggable="false" :enable-context-menu="false" />
        </span>
        <Transition leave-active-class="transition-opacity duration-700" leave-to-class="opacity-0">
          <span v-if="folderNew.length" class="ml-1 h-1.5 w-1.5 flex-none self-center rounded-full bg-accent" title="New" />
        </Transition>
      </span>
      <span class="flex-1" />
      <button
        v-if="!sheet.readonly.value"
        type="button"
        class="flex h-7 flex-none items-center gap-1 rounded-md px-1.5 text-content-muted transition-opacity hover:bg-overlay-subtle hover:text-content-secondary"
        :class="commentCount ? 'opacity-100' : 'opacity-0 group-hover/section:opacity-100 coarse:opacity-100'"
        title="Comment on this section"
        @click="comment"
      >
        <ChatBubbleLeftIcon class="h-4 w-4" />
        <span v-if="commentCount" class="font-mono text-[11px] tabular-nums">{{ commentCount }}</span>
      </button>
    </header>
    <template v-if="open">
      <p v-if="at.note" class="!mb-3 max-w-[70ch] text-[13px] text-content-secondary">{{ at.note }}</p>
      <slot />
    </template>
  </section>
</template>

<script setup lang="ts">
// <stimma-section label note collapsible collapsed>. Collapsed sections keep a
// strip of their pictures in the header, so what is folded away stays visible.
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ChatBubbleLeftIcon, ChevronRightIcon } from '@heroicons/vue/24/outline'
import { MediaImage } from '../media'
import { mediaIdOfRef } from './sheetHtml'
import { useSheetContext } from './useContactSheet'

const props = defineProps<{ kid?: string; at: Record<string, any>; node: Element }>()
const sheet = useSheetContext()
const collapsible = computed(() => !!props.at.collapsible || !!props.at.collapsed)
const open = ref(!props.at.collapsed)

const tiles = computed(() => Array.from(props.node?.querySelectorAll('stimma-media') || []))
const mediaIds = computed(() => [...new Set(tiles.value.map(el => mediaIdOfRef(el.getAttribute('ref'))).filter((id): id is number => id != null))])
// Folded work shows as the strip; seeing the strip is seeing what's new in it.
const folderNew = computed(() => (open.value ? [] : tiles.value.filter(el => sheet.newIds.value.has(el.id))
  .map(el => mediaIdOfRef(el.getAttribute('ref'))).filter((id): id is number => id != null)))
const strip = ref<HTMLElement | null>(null)
let stopSeen: (() => void) | null = null
watch([() => folderNew.value.length > 0, strip], ([fresh, el]) => {
  stopSeen?.()
  stopSeen = fresh && el ? sheet.watchSeen(el, () => folderNew.value) : null
}, { immediate: true })
onBeforeUnmount(() => stopSeen?.())
const commentCount = computed(() => (props.kid ? sheet.commentsFor(props.kid).length : 0))
// Jumping to new work unfolds the section that holds it.
watch(() => sheet.flashIds.value, ids => {
  if (!open.value && tiles.value.some(el => ids.includes(el.id))) open.value = true
})

function comment(event: MouseEvent) {
  if (!props.kid) return
  const r = (event.currentTarget as HTMLElement).getBoundingClientRect()
  sheet.commentFor.value = { id: props.kid, label: String(props.at.label || 'this section'), x: r.right, y: r.bottom + 6 }
}
</script>
