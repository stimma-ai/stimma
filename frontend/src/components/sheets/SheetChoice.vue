<template>
  <fieldset class="m-0 min-w-0 border-0 p-0">
    <legend class="mb-2 p-0 text-[13px] font-semibold text-content">{{ at.label }}</legend>
    <div class="grid gap-2" :style="{ gridTemplateColumns: `repeat(auto-fill, minmax(${options.some(o => o.mediaId != null) ? 132 : 96}px, 1fr))` }">
      <button
        v-for="option in options"
        :key="option.value"
        type="button"
        class="group relative overflow-hidden rounded-lg border text-left transition-colors disabled:cursor-default"
        :class="picked.includes(option.value) ? 'border-accent bg-accent/10' : 'border-edge bg-surface hover:border-edge-strong'"
        :aria-pressed="picked.includes(option.value)"
        :disabled="sheet.readonly.value || !kid"
        @click="pick(option.value)"
      >
        <span v-if="option.mediaId != null" class="block aspect-[4/3] w-full bg-matte">
          <MediaImage :media-id="option.mediaId" :thumbnail="true" :thumbnail-size="256" container-class="h-full w-full" :draggable="false" :enable-context-menu="false" />
        </span>
        <span class="flex items-center gap-2 px-2.5 py-2 text-[12.5px] text-content">
          <span
            class="flex h-4 w-4 flex-none items-center justify-center border"
            :class="[multiple ? 'rounded' : 'rounded-full', picked.includes(option.value) ? 'border-accent bg-accent text-white' : 'border-edge-strong']"
          >
            <CheckIcon v-if="picked.includes(option.value)" class="h-2.5 w-2.5" stroke-width="3.5" />
          </span>
          <span class="min-w-0 truncate">{{ option.label }}</span>
        </span>
      </button>
    </div>
  </fieldset>
</template>

<script setup lang="ts">
// <stimma-choice id label multiple><stimma-option value ref>Label</stimma-option>...
import { computed } from 'vue'
import { CheckIcon } from '@heroicons/vue/24/outline'
import { MediaImage } from '../media'
import { mediaIdOfRef } from './sheetHtml'
import { useSheetContext } from './useContactSheet'

const props = defineProps<{ kid?: string; at: Record<string, any>; node: Element }>()
const sheet = useSheetContext()
const multiple = computed(() => !!props.at.multiple)
const options = computed(() => Array.from(props.node?.querySelectorAll('stimma-option') || []).map(el => ({
  value: el.getAttribute('value') || (el.textContent || '').trim(),
  label: (el.textContent || '').trim() || el.getAttribute('value') || '',
  mediaId: mediaIdOfRef(el.getAttribute('ref')),
})))
const picked = computed<string[]>(() => {
  const value = props.kid ? sheet.answers.value[props.kid]?.value : null
  return Array.isArray(value) ? value.map(String) : value ? [String(value)] : []
})
function pick(value: string) {
  if (!props.kid) return
  if (multiple.value) {
    const next = new Set(picked.value)
    next.has(value) ? next.delete(value) : next.add(value)
    sheet.setAnswer(props.kid, [...next])
  } else {
    sheet.setAnswer(props.kid, picked.value[0] === value ? null : value)
  }
}
</script>
