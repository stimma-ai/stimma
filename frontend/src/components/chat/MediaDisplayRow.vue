<template>
  <div :class="rowClass">
    <!-- Library mode compact: small clickable thumbnails -->
    <template v-if="libraryMode && compact">
      <div
        v-if="row.output.status === 'complete' && row.output.media_id"
        class="w-16 h-16 rounded-media overflow-hidden cursor-pointer hover:ring-2 hover:ring-accent-selection transition-colors flex-shrink-0"
        @click="$emit('view-image', row.output.media_id)"
      >
        <MediaImage
          :media-id="row.output.media_id"
          :thumbnail="true"
          :contain="true"
          container-class="w-full h-full"
        />
      </div>
    </template>

    <!-- Library mode expanded: use OutputImage at reasonable size -->
    <template v-else-if="libraryMode && !compact">
      <OutputImage
        :row="row"
        :size="107"
        :use-thumbnail="false"
        @view-image="(id) => $emit('view-image', id)"
        @retry="(id) => $emit('retry', id)"
        @cancel="(id) => $emit('cancel', id)"
        @show-job-info="(jobId) => $emit('show-job-info', jobId)"
      />
    </template>

    <!-- Compact mode: all row types render as just the output image -->
    <template v-else-if="compact && row.input.type !== 'output_only'">
      <OutputImage
        :row="row"
        :size="134"
        :use-thumbnail="false"
        @view-image="(id) => $emit('view-image', id)"
        @retry="(id) => $emit('retry', id)"
        @cancel="(id) => $emit('cancel', id)"
        @show-job-info="(jobId) => $emit('show-job-info', jobId)"
      />
    </template>

    <!-- Style 0: Output Only (no input side, no arrow) -->
    <template v-else-if="row.input.type === 'output_only'">
      <div class="flex items-center gap-2" :class="{ 'w-full': fill }">
        <!-- Output image - smaller when compact -->
        <OutputImage
          :row="row"
          :size="compact ? 134 : 160"
          :fill="fill"
          :use-thumbnail="false"
          @view-image="(id) => $emit('view-image', id)"
          @retry="(id) => $emit('retry', id)"
          @cancel="(id) => $emit('cancel', id)"
          @show-job-info="(jobId) => $emit('show-job-info', jobId)"
        />
        <!-- Optional label -->
        <span v-if="row.input.label" class="text-xs text-content-muted">
          {{ row.input.label }}
        </span>
      </div>
    </template>

    <!-- Style 3: Image Only - input image → operation → output image -->
    <template v-else-if="row.input.type === 'image_only'">
      <!-- Input image at 160px -->
      <div
        v-if="row.input.input_image"
        class="w-[160px] h-[160px] rounded-media overflow-hidden cursor-pointer hover:opacity-90 transition-opacity flex-shrink-0"
        @click="$emit('view-image', row.input.input_image.media_id)"
      >
        <MediaImage
          :mediaId="row.input.input_image.media_id"
          :contain="true"
          containerClass="w-full h-full"
        />
      </div>
      <!-- Arrow with operation label -->
      <div class="flex flex-col items-center gap-1 flex-shrink-0 px-2">
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5 text-content-muted">
          <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3" />
        </svg>
        <span v-if="row.input.operation" class="text-[10px] text-content-muted whitespace-nowrap">
          {{ row.input.operation }}
        </span>
      </div>
      <!-- Output image at 160px -->
      <OutputImage
        :row="row"
        :size="160"
        :use-thumbnail="false"
        @view-image="(id) => $emit('view-image', id)"
        @retry="(id) => $emit('retry', id)"
        @cancel="(id) => $emit('cancel', id)"
        @show-job-info="(jobId) => $emit('show-job-info', jobId)"
      />
    </template>

    <!-- Prompt types: prompt_only or refs_and_prompt -->
    <!-- Layout: [prompt area 320px] → [output 160px] (prompt is 2x output width) -->
    <template v-else>
      <!-- Input Side: fixed 320px width (2x the output image) -->
      <div class="w-[320px] flex-shrink-0">
        <!-- Style 1: Prompt Only -->
        <div v-if="row.input.type === 'prompt_only'">
          <p class="text-sm text-content-secondary leading-relaxed">
            "{{ row.input.prompt }}"
          </p>
        </div>

        <!-- Style 2: Reference Images + Prompt -->
        <div v-else-if="row.input.type === 'refs_and_prompt'">
          <!-- Reference image thumbnails at 96px -->
          <div v-if="row.input.ref_images?.length" class="flex flex-wrap gap-2 mb-2">
            <div
              v-for="(ref, idx) in row.input.ref_images"
              :key="idx"
              class="w-[96px] h-[96px] rounded-media overflow-hidden flex-shrink-0 cursor-pointer hover:opacity-90 transition-opacity"
              @click="$emit('view-image', ref.media_id)"
            >
              <MediaImage
                :mediaId="ref.media_id"
                :contain="true"
                containerClass="w-full h-full"
              />
            </div>
          </div>
          <!-- Prompt text -->
          <p v-if="row.input.prompt" class="text-sm text-content-secondary leading-relaxed">
            "{{ row.input.prompt }}"
          </p>
        </div>
      </div>

      <!-- Arrow with operation label -->
      <div class="flex flex-col items-center gap-1 flex-shrink-0 px-2">
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5 text-content-muted">
          <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3" />
        </svg>
        <span v-if="row.input.operation" class="text-[10px] text-content-muted whitespace-nowrap">
          {{ row.input.operation }}
        </span>
      </div>

      <!-- Output Side: 160px -->
      <OutputImage
        :row="row"
        :size="160"
        :use-thumbnail="false"
        @view-image="(id) => $emit('view-image', id)"
        @retry="(id) => $emit('retry', id)"
        @cancel="(id) => $emit('cancel', id)"
        @show-job-info="(jobId) => $emit('show-job-info', jobId)"
      />
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { MediaImage } from '../media'
import OutputImage from './OutputImage.vue'

const props = defineProps({
  row: {
    type: Object,
    required: true
  },
  compact: {
    type: Boolean,
    default: false
  },
  // Output-only rows fill the parent's width instead of using a fixed tile size
  fill: {
    type: Boolean,
    default: false
  },
  libraryMode: {
    type: Boolean,
    default: false
  }
})

defineEmits(['view-image', 'retry', 'cancel', 'show-job-info'])

const rowClass = computed(() => {
  if (props.compact && props.row.input?.type === 'output_only') {
    return props.fill
      ? 'media-display-row flex items-center justify-center w-full'
      : 'media-display-row flex items-center justify-center'
  }
  return 'media-display-row flex items-center gap-3'
})
</script>

<style scoped>
/* Prompts expand to show full text */
</style>
