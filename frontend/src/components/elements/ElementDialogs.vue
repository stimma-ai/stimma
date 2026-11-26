<template>
  <!-- Rename: a sheet on a phone (RenameSheet, as every compact rename), a
       small dialog on desktop when it comes from a menu with no title on
       screen to edit in place. -->
  <RenameSheet
    v-if="isCompact"
    :show="!!renameTarget"
    :name="renameTarget?.name || ''"
    label="Rename element"
    @close="elementUi.renaming = null"
    @save="saveName"
  />
  <Modal v-else :show="!!renameTarget" size="sm" @close="elementUi.renaming = null">
    <form class="flex flex-col gap-4 p-5" @submit.prevent="saveName(draftName)">
      <h2 class="m-0 text-sm font-semibold text-content">Rename element</h2>
      <input
        ref="nameInput"
        v-model="draftName"
        v-no-autocorrect
        class="h-control-main w-full rounded-md border border-edge bg-base px-3 text-sm text-content outline-none focus:border-accent"
        aria-label="Element name"
      >
      <div class="flex justify-end gap-2">
        <Button variant="ghost" size="sm" @click="elementUi.renaming = null">Cancel</Button>
        <Button variant="primary" size="sm" type="submit" :disabled="!draftName.trim()">Save</Button>
      </div>
    </form>
  </Modal>

  <!-- Set cover: pick one of the element's own media. -->
  <component
    :is="isCompact ? Sheet : Modal"
    :show="!!coverTarget"
    v-bind="isCompact ? { title: 'Set cover' } : { size: 'md' }"
    @close="elementUi.coverPicking = null"
  >
    <div :class="isCompact ? 'px-4 pb-4' : 'p-5'">
      <h2 v-if="!isCompact" class="m-0 mb-1 text-sm font-semibold text-content">Set cover</h2>
      <p class="m-0 mb-3 text-xs text-content-tertiary">Pick one of {{ coverTarget?.name }}'s media.</p>
      <div class="grid gap-2" :class="isCompact ? 'grid-cols-3' : 'grid-cols-4'">
        <button
          v-for="m in coverMedia"
          :key="m.key"
          type="button"
          class="relative aspect-square overflow-hidden rounded-media border-none bg-matte p-0"
          :class="m.is_cover ? 'ring-2 ring-inset ring-selection' : 'hover:opacity-90'"
          @click="saveCover(m.key)"
        >
          <MediaImage :media-id="m.media_id" :file-hash="m.file_hash" :thumbnail-size="256" :draggable="false" :enable-context-menu="false" container-class="h-full w-full" img-class="h-full w-full object-cover" />
          <TileChip v-if="m.is_cover" class="absolute bottom-1.5 left-1.5">Cover</TileChip>
        </button>
      </div>
    </div>
  </component>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import RenameSheet from '../compact/RenameSheet.vue'
import Modal from '../ui/Modal.vue'
import Sheet from '../ui/Sheet.vue'
import Button from '../ui/Button.vue'
import MediaImage from '../media/MediaImage.vue'
import TileChip from '../media/TileChip.vue'
import { useViewport } from '../../composables/useViewport'
import { elementUi, cachedElement, saveElement } from './useElements'

const { isCompact } = useViewport()

// A desktop rename aimed at the element the open viewer shows is the viewer's
// to handle in place; only the others get the dialog.
const renameId = computed(() => (elementUi.renaming != null && (isCompact.value || elementUi.renaming !== elementUi.inlineRenameHost)) ? elementUi.renaming : null)
const renameTarget = computed(() => cachedElement(renameId.value))
const coverTarget = computed(() => cachedElement(elementUi.coverPicking))
const coverMedia = computed(() => (coverTarget.value?.media || []).filter(m => !m.missing && m.media_id != null))

const draftName = ref('')
const nameInput = ref<HTMLInputElement | null>(null)
watch(renameTarget, async t => {
  if (!t || isCompact.value) return
  draftName.value = t.name
  await nextTick()
  nameInput.value?.select()
})

async function saveName(name: string) {
  const id = renameId.value
  elementUi.renaming = null
  if (id != null && name?.trim() && name.trim() !== cachedElement(id)?.name) await saveElement(id, { name: name.trim() })
}
async function saveCover(key: string) {
  const id = elementUi.coverPicking
  elementUi.coverPicking = null
  if (id != null) await saveElement(id, { cover_member_key: key })
}
</script>
