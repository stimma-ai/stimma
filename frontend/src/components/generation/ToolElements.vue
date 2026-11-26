<template>
  <!-- Elements on this tool: one more form section in ToolSectionHeader's grammar,
       above the slots it fills. Rows follow the LoRA rows (LoraChip). -->
  <div v-if="elements" :class="attached.length ? 'mb-5 coarse:mb-3' : 'mb-3 coarse:mb-1'" data-tool-elements>
    <ToolSectionHeader
      ref="header"
      label="Elements"
      :state="attached.length ? undefined : 'None'"
      addable
      add-title="Add element"
      :class="attached.length ? 'mb-1' : ''"
      @add="openPicker"
    />
    <div v-if="attached.length">
      <div
        v-for="a in attached"
        :key="a.asset_id"
        class="group flex items-center gap-2.5 py-1.5 border-b border-edge-subtle last:border-b-0 coarse:min-h-11"
        :title="a.name"
        data-element-row
      >
        <div class="relative w-8 h-8 flex-none rounded-md overflow-hidden bg-matte">
          <MediaImage
            v-if="a.media_id"
            :media-id="a.media_id"
            :thumbnail="true"
            :thumbnail-size="128"
            :draggable="false"
            :enable-context-menu="false"
            container-class="w-full h-full"
            class="w-full h-full object-cover"
          />
        </div>
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-1 min-w-0">
            <PuzzlePieceIcon class="w-3.5 h-3.5 flex-none text-content-tertiary" />
            <span class="truncate text-[13px] font-medium text-content">{{ a.name }}</span>
          </div>
          <div class="text-[11px] leading-snug text-content-tertiary truncate">{{ kindLabel(a.kind) }}</div>
        </div>
        <!-- Background work on this screen reads as the kit's small spinner, as on
             the Fluent chip while it prepares a prompt. -->
        <Spinner v-if="working" size="sm" class="flex-none" />
        <button
          type="button"
          class="flex-none w-6 h-6 coarse:w-11 coarse:h-11 flex items-center justify-center rounded-md text-content-tertiary opacity-0 group-hover:opacity-100 focus-visible:opacity-100 [[data-pointer=coarse]_&]:opacity-100 hover:text-content hover:bg-overlay-subtle transition-opacity"
          :title="`Remove ${a.name}`"
          :aria-label="`Remove ${a.name}`"
          @click="elements.detach(a.asset_id)"
        >
          <XMarkIcon class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>

    <ElementPickerPopover
      v-if="pickerOpen"
      :anchor-el="anchor"
      :attached-ids="attached.map(a => a.asset_id)"
      :project-id="projectId"
      @pick="onPick"
      @new="onNew"
      @close="pickerOpen = false"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { PuzzlePieceIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import ToolSectionHeader from './ToolSectionHeader.vue'
import MediaImage from '../media/MediaImage.vue'
import Spinner from '../ui/Spinner.vue'
import ElementPickerPopover, { type PickedElement } from './ElementPickerPopover.vue'
import { injectToolElements } from '../../composables/useToolElements'
import { kindLabel } from '../elements/useElements'

defineProps<{ projectId?: number | null }>()
const emit = defineEmits<{ new: [] }>()

const elements = injectToolElements()
const attached = computed(() => elements?.attached.value ?? [])
const working = computed(() => !!elements?.working.value)

const header = ref<InstanceType<typeof ToolSectionHeader> | null>(null)
const pickerOpen = ref(false)
const anchor = ref<HTMLElement | null>(null)
function openPicker(e?: MouseEvent) {
  anchor.value = (e?.currentTarget as HTMLElement | null) || (header.value as any)?.addEl || null
  pickerOpen.value = true
}
function onPick(el: PickedElement) {
  pickerOpen.value = false
  elements?.attach({ asset_id: el.asset_id, revision_id: el.revision_id, name: el.name, kind: el.kind, media_id: el.cover_media_id || el.media_id })
}
function onNew() {
  pickerOpen.value = false
  emit('new')
}

defineExpose({ openPicker })
</script>
