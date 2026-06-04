<template>
  <div
    class="analysis-result bg-surface rounded-xl border border-edge/50 transition-all duration-200"
    :class="expanded ? 'p-4' : 'py-2 px-3'"
  >
    <!-- Header (clickable to expand/collapse) -->
    <div
      class="flex items-center gap-2 cursor-pointer select-none rounded-lg transition-colors"
      :class="expanded ? 'mb-3' : 'hover:bg-overlay-subtle -mx-1 px-1 py-0.5'"
      @click="expanded = !expanded"
    >
      <ChevronRightIcon
        class="w-3.5 h-3.5 text-content-muted transition-transform duration-200 flex-shrink-0"
        :class="{ 'rotate-90': expanded }"
      />

      <!-- Image thumbnail -->
      <div
        v-if="analysisData.media_id"
        class="w-8 h-8 bg-surface-raised rounded overflow-hidden flex-shrink-0"
        @click.stop="$emit('view-image', analysisData.media_id)"
      >
        <img
          :src="getThumbnailUrl(analysisData.media_id, 64)"
          class="w-full h-full object-cover bg-checker hover:opacity-80 transition-opacity"
          alt="Analyzed image"
        />
      </div>

      <!-- Title -->
      <div class="text-sm font-medium text-content">Image Analysis</div>

      <!-- Spacer -->
      <div class="flex-1"></div>
    </div>

    <!-- Expanded content -->
    <div v-show="expanded" class="space-y-3">
      <!-- Subjects -->
      <div v-if="analysisData.subjects?.length" class="text-xs text-content-tertiary">
        {{ analysisData.subjects.join(', ') }}
      </div>

      <!-- Description -->
      <p class="text-sm text-content-secondary leading-relaxed whitespace-pre-wrap">
        {{ analysisData.description }}
      </p>

      <!-- Additional details -->
      <div v-if="hasAdditionalDetails" class="space-y-1.5 text-xs text-content-tertiary pt-2 border-t border-edge/50">
        <div v-if="analysisData.mood" class="flex gap-2">
          <span class="text-content-muted w-16 flex-shrink-0">Mood</span>
          <span>{{ analysisData.mood }}</span>
        </div>
        <div v-if="analysisData.style" class="flex gap-2">
          <span class="text-content-muted w-16 flex-shrink-0">Style</span>
          <span>{{ analysisData.style }}</span>
        </div>
        <div v-if="analysisData.technical" class="flex gap-2">
          <span class="text-content-muted w-16 flex-shrink-0">Technical</span>
          <span>{{ analysisData.technical }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ChevronRightIcon } from '@heroicons/vue/24/outline'
import { useMediaApi } from '../../composables/useMediaApi'

const { getThumbnailUrl } = useMediaApi()

const props = defineProps({
  analysisData: {
    type: Object,
    required: true
    // Expected shape:
    // {
    //   media_id: number,
    //   title?: string,
    //   description: string,
    //   subjects?: string[],
    //   mood?: string,
    //   style?: string,
    //   technical?: string,
    // }
  }
})

defineEmits(['view-image'])

const expanded = ref(false)

const hasAdditionalDetails = computed(() =>
  props.analysisData.mood || props.analysisData.style || props.analysisData.technical
)
</script>
