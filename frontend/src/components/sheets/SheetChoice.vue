<template>
  <fieldset class="m-0 my-4 min-w-0 max-w-[640px] border-0 p-0">
    <legend class="mb-2 p-0 text-[13px] font-semibold text-content">{{ at.label }}</legend>
    <div class="flex flex-col gap-1">
      <div
        v-for="option in options"
        :key="option.value"
        class="flex items-stretch gap-1 rounded-lg border transition-colors"
        :class="isPicked(option) ? 'border-accent bg-accent/10' : 'border-edge-subtle bg-surface hover:border-edge'"
      >
        <button
          type="button"
          class="flex min-w-0 flex-1 items-center gap-2.5 px-3 py-2 text-left text-[13px] leading-snug text-content disabled:cursor-default coarse:min-h-11"
          :aria-pressed="isPicked(option)"
          :disabled="sheet.readonly.value || !kid"
          @click="pick(option)"
        >
          <span
            class="flex h-[18px] w-[18px] flex-none items-center justify-center border"
            :class="[multiple ? 'rounded' : 'rounded-full', isPicked(option) ? 'border-accent bg-accent text-white' : 'border-edge-strong']"
          >
            <CheckIcon v-if="isPicked(option)" class="h-3 w-3" stroke-width="3" />
          </span>
          <span class="min-w-0 break-words">{{ option.label }}</span>
        </button>
        <!-- A picture that is only here, not up the sheet, shows whole and opens large. -->
        <button
          v-if="option.mediaId != null && !sheet.hasTile(option.mediaId)"
          type="button"
          class="m-1 flex h-16 w-24 flex-none items-center justify-center overflow-hidden rounded-media bg-matte"
          :aria-label="`Open ${option.label}`"
          @click="sheet.openMedia(option.mediaId, option.label)"
        >
          <MediaImage
            :media-id="option.mediaId"
            :thumbnail="true"
            :thumbnail-size="256"
            thumbnail-mode="fit"
            :contain="true"
            container-class="h-full w-full"
            img-class="h-full w-full"
            :draggable="false"
            :enable-context-menu="false"
          />
        </button>
      </div>
    </div>
  </fieldset>
</template>

<script setup lang="ts">
// <stimma-choice id label multiple><stimma-option value ref>Label</stimma-option>...
// One row per answer, worded in full. An option whose picture is already a
// tile on the sheet is picked on that tile too, so the sheet shows it once.
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
function isPicked(option: { value: string }) {
  return !!props.kid && sheet.isPicked(props.kid, option.value)
}
function pick(option: { value: string }) {
  if (props.kid) sheet.togglePick({ choiceId: props.kid, value: option.value, multiple: multiple.value })
}
</script>
