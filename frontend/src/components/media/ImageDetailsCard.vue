<template>
  <!-- Media left, how-it-was-made right; on compact the two stack. -->
  <div class="w-full h-full flex compact:flex-col compact:h-auto">
    <div class="w-2/3 bg-matte flex-shrink-0 compact:w-full compact:h-[45dvh]">
      <MediaImage
        :media-id="mediaId"
        :file-hash="media.file_hash"
        :thumbnail="false"
        :contain="true"
        :has-alpha="media.has_alpha"
        container-class="w-full h-full"
      />
    </div>

    <div class="w-1/3 compact:w-full overflow-y-auto overflow-x-hidden custom-scrollbar p-4 pr-12 compact:pr-4 space-y-5 select-text">
      <!-- Markers (editable) -->
      <div v-if="availableMarkers.length > 0" class="flex flex-wrap items-center gap-0.5">
        <Tooltip v-for="marker in availableMarkers" :key="marker.id" :text="marker.name">
          <button
            type="button"
            :aria-label="marker.name"
            class="inline-flex items-center justify-center w-7 h-7 rounded-md cursor-pointer border-none bg-transparent transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
            :class="hasMarker(mediaId, marker.id) ? '' : 'text-content-tertiary hover:bg-overlay-subtle hover:text-content-secondary'"
            :style="hasMarker(mediaId, marker.id) ? { color: marker.color } : {}"
            @click="toggleMarkerFn(mediaId, marker)"
          >
            <span v-html="sanitizeSvg(marker.icon_svg)" class="w-5 h-5 flex items-center justify-center icon-container"></span>
          </button>
        </Tooltip>
      </div>

      <!-- How it was made, newest step first (same grammar as the Info panel) -->
      <div v-if="provenance.steps.length">
        <h4 class="m-0 mb-3 text-xs font-semibold text-content-secondary">Lineage</h4>
        <ProvenanceSteps
          :steps="provenance.steps"
          input-size="sm"
          @navigate="$emit('navigate', $event)"
        />
        <button
          v-if="provenance.flow"
          type="button"
          class="mt-3 flex w-full items-baseline justify-between gap-4 bg-transparent border-none p-0 text-xs cursor-pointer group"
          @click="$emit('open-flow', provenance.flow.flowId)"
        >
          <span class="text-content-tertiary flex-shrink-0">Flow</span>
          <span class="min-w-0 truncate text-accent group-hover:text-accent-hi">
            {{ provenance.flow.phasePath.length ? provenance.flow.phasePath.join(' / ') : 'Open flow' }}
          </span>
        </button>
      </div>

      <!-- Lineage-graph parents not already shown as a step input -->
      <div v-if="parentNodes.length > 0">
        <h4 class="m-0 mb-2 text-xs font-semibold text-content-secondary">{{ inspiredParentCount > 0 ? 'Remix of' : 'Source' }}</h4>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="parent in parentNodes"
            :key="parent.id"
            type="button"
            :class="relationThumbClass"
            class="w-20 h-20"
            @click="$emit('navigate', parent.id)"
          >
            <MediaImage
              :media-id="parent.id"
              :file-hash="parent.media?.file_hash"
              :thumbnail-size="128"
              container-class="w-full h-full"
              img-class="w-full h-full object-cover"
            />
          </button>
        </div>
      </div>

      <PromptBlock :text="media.vlm_caption" label="Description" />

      <!-- Derivatives (children of this node) -->
      <div v-if="childNodes.length > 0">
        <h4 class="m-0 mb-2 text-xs font-semibold text-content-secondary">Made from this</h4>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="child in childNodes"
            :key="child.id"
            type="button"
            :class="relationThumbClass"
            class="w-14 h-14"
            @click="$emit('navigate', child.id)"
          >
            <MediaImage
              :media-id="child.id"
              :file-hash="child.media?.file_hash"
              :thumbnail-size="128"
              container-class="w-full h-full"
              img-class="w-full h-full object-cover"
            />
          </button>
        </div>
      </div>

      <div>
        <h4 class="m-0 mb-1 text-xs font-semibold text-content-secondary">File</h4>
        <KeyValueList :rows="fileRows" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, watch, onMounted } from 'vue'
import { MediaImage } from './index'
import KeyValueList from '../ui/KeyValueList.vue'
import Tooltip from '../ui/Tooltip.vue'
import PromptBlock from './PromptBlock.vue'
import ProvenanceSteps from './ProvenanceSteps.vue'
import { useMarkers } from '../../composables/useMarkers'
import { useProvenanceBuilder } from '../../composables/useMediaProvenance'
import { factRows } from '../../utils/mediaProvenance'
import { sanitizeSvg } from '../../utils/sanitizeHtml'

const props = defineProps({
  // Full media item (must include `id` and generation_metadata)
  media: {
    type: Object,
    required: true
  },
  // Lineage parents/children — only available in a tree context.
  parentNodes: {
    type: Array,
    default: () => []
  },
  childNodes: {
    type: Array,
    default: () => []
  }
})

defineEmits(['navigate', 'open-flow'])

const { availableMarkers, hasMarker, toggleMarker: toggleMarkerFn, init: initMarkers, loadMarkersForMedia } = useMarkers()
const { build } = useProvenanceBuilder()

const mediaId = computed(() => props.media.id)
const provenance = computed(() => build(props.media))
const fileRows = computed(() => factRows(provenance.value.fileFacts))
const inspiredParentCount = computed(() => props.parentNodes.filter(p => p.inspired).length)

const relationThumbClass = 'relative rounded-media bg-matte overflow-hidden p-0 border-none cursor-pointer transition-shadow hover:ring-2 hover:ring-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60'

// Markers: load for the displayed media (idempotent shared-singleton calls).
async function loadMarkers(id) {
  if (!id) return
  await initMarkers()
  await loadMarkersForMedia([id])
}

onMounted(() => loadMarkers(mediaId.value))
watch(mediaId, (id) => loadMarkers(id))
</script>
