<template>
  <div class="space-y-2">
    <div v-if="loading" class="flex items-center gap-2 py-2 text-[11px] text-content-muted">
      <span class="w-3 h-3 border border-content-muted border-t-transparent rounded-full animate-spin" />
      Loading candidates…
    </div>
    <div v-else-if="loadError" class="text-[11px] text-content-muted italic">
      Couldn't load candidates ({{ loadError }}). The current selection will stay as is.
    </div>
    <HitlSelectInline
      v-else-if="rawCandidates.length > 0"
      :candidates="rawCandidates"
      :count="count"
      :initial-selection="resultValues"
      mode="reselect"
      @resolve="onResolve"
    />
    <div v-else class="text-[11px] text-content-muted italic">
      No candidates recorded for this step.
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import axios from 'axios'
import { getApiBase } from '../../apiConfig'
import HitlSelectInline from './HitlSelectInline.vue'
import type { RecipeEquation } from '../../composables/useRecipesApi'

interface TraceCacheEntry {
  candidates: any[]
  count: number
}

const traceCache = new Map<string, TraceCacheEntry>()

interface Props {
  equation: RecipeEquation
  recipeId: number | null
}
const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'reselect', resolution: any): void
}>()

const loading = ref(false)
const loadError = ref<string | null>(null)
const rawCandidates = ref<any[]>([])
const count = ref<number>(1)

const resultValues = computed<any[]>(() => {
  const r = props.equation.result
  if (Array.isArray(r)) return [...r]
  if (r != null) return [r]
  return []
})

async function fetchTrace() {
  if (props.recipeId == null) return
  const key = cacheKey()
  const cached = traceCache.get(key)
  if (cached) {
    rawCandidates.value = cached.candidates
    count.value = cached.count
    loading.value = false
  } else {
    loading.value = true
  }
  loadError.value = null
  try {
    const url = `${getApiBase()}/recipes/${props.recipeId}/equations/${encodeURIComponent(props.equation.equation_key)}/trace`
    const res = await axios.get(url)
    const data = res.data || {}
    const nextCandidates = Array.isArray(data.candidates) ? data.candidates : []
    const nextCount = Number(data.count ?? 1)
    rawCandidates.value = nextCandidates
    count.value = nextCount
    traceCache.set(key, { candidates: nextCandidates, count: nextCount })
  } catch (err: any) {
    if (!cached) loadError.value = err?.response?.data?.detail || err?.message || 'Failed to load'
  } finally {
    loading.value = false
  }
}

function onResolve(resolution: any) {
  emit('reselect', resolution)
}

function cacheKey(): string {
  return `${props.recipeId ?? 'none'}:${props.equation.equation_key}`
}

watch(() => [props.recipeId, props.equation.equation_key], () => {
  fetchTrace()
}, { immediate: true })
</script>
