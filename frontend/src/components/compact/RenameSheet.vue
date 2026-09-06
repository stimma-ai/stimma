<script setup lang="ts">
/**
 * Rename on a phone: a sheet with one field. Desktop keeps tap-to-edit
 * titles; on compact every renamable entity renames from its ⋯ menu.
 */
import { nextTick, ref, watch } from 'vue'
import Sheet from '../ui/Sheet.vue'

const props = defineProps<{ show: boolean; name: string; label?: string }>()
const emit = defineEmits<{ close: []; save: [name: string] }>()

const value = ref('')
const inputEl = ref<HTMLInputElement | null>(null)

watch(() => props.show, async (open) => {
  if (!open) return
  value.value = props.name || ''
  await nextTick()
  inputEl.value?.focus()
  inputEl.value?.select?.()
})

function save() {
  const name = value.value.trim()
  emit('close')
  if (name && name !== (props.name || '')) emit('save', name)
}
</script>

<template>
  <Sheet :show="show" :title="label || 'Rename'" @close="emit('close')">
    <form class="px-4 pb-4 flex flex-col gap-3" @submit.prevent="save">
      <input
        ref="inputEl"
        v-model="value"
        type="text"
        class="w-full h-11 px-3 rounded-md bg-base border border-edge text-[16px] text-content outline-none focus:border-accent"
        autocomplete="off"
        autocapitalize="sentences"
      />
      <div class="flex gap-2 justify-end">
        <button type="button" class="h-11 px-4 rounded-md text-[15px] text-content-secondary border-none bg-transparent" @click="emit('close')">Cancel</button>
        <button type="submit" class="h-11 px-5 rounded-md text-[15px] font-medium text-white bg-accent border-none disabled:opacity-40" :disabled="!value.trim()">Save</button>
      </div>
    </form>
  </Sheet>
</template>
