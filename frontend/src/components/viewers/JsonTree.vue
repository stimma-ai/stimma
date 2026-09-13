<template>
  <details v-if="isObject && depth < 30" :open="expanded" class="ml-3" @toggle="expanded = ($event.target as HTMLDetailsElement).open">
    <summary class="cursor-pointer py-1 text-content-secondary">{{ label }} {{ Array.isArray(value) ? '[' + count + ']' : '{' + count + '}' }}</summary>
    <template v-if="expanded">
      <JsonTree v-for="[key, child] in children" :key="key" :value="child" :label="key + ':'" :depth="depth + 1" />
      <Button v-if="count > limit" variant="ghost" size="sm" @click="limit += 200">Show more</Button>
    </template>
  </details>
  <div v-else class="ml-3 py-0.5 whitespace-pre-wrap break-all">{{ label }} {{ JSON.stringify(value) }}</div>
</template>
<script setup lang="ts">
import { ref, computed } from 'vue'
import Button from '../ui/Button.vue'
const props = withDefaults(defineProps<{ value: any; label?: string; depth?: number }>(), { label: '', depth: 0 })
const expanded = ref(props.depth < 1), limit = ref(200)
const isObject = computed(() => props.value !== null && typeof props.value === 'object')
const count = computed(() => isObject.value ? Object.keys(props.value).length : 0)
const children = computed(() => Object.entries(props.value).slice(0, limit.value))
</script>
