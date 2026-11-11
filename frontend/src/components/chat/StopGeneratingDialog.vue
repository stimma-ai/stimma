<template>
  <!-- Stop pressed while the turn's code is mid-generation: the turn stops
       either way; this decides what happens to the generations. -->
  <Modal :show="show" size="sm" @close="emit('dismiss')">
    <div class="px-6 py-5 text-center">
      <h3 class="mb-2 text-lg font-semibold text-content">Keep generating?</h3>
      <p class="text-sm text-content-secondary">{{ message }}</p>
    </div>
    <template #footer>
      <Button variant="secondary" @click="emit('choose', false)">Stop them</Button>
      <Button variant="primary" @click="emit('choose', true)">Keep generating</Button>
    </template>
  </Modal>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Modal from '../ui/Modal.vue'
import Button from '../ui/Button.vue'

const props = defineProps<{ show: boolean; inProgress: number }>()
const emit = defineEmits<{ choose: [keep: boolean]; dismiss: [] }>()

const message = computed(() => {
  const n = props.inProgress
  const what = n === 1 ? '1 generation is' : `${n} generations are`
  return `${what} still in progress. They can finish in the background, and the results will appear here.`
})
</script>
