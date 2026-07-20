<template>
  <div class="w-full h-full flex">
    <!-- Left: Image (letterboxed, full resolution) -->
    <div class="w-2/3 bg-black flex-shrink-0">
      <MediaImage
        :media-id="mediaId"
        :file-hash="media.file_hash"
        :thumbnail="false"
        :contain="true"
        :has-alpha="media.has_alpha"
        container-class="w-full h-full"
      />
    </div>

    <!-- Right: Info -->
    <div class="w-1/3 overflow-y-auto overflow-x-hidden p-4 space-y-3 select-text">
      <!-- Markers (editable) -->
      <div v-if="availableMarkers.length > 0">
        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="marker in availableMarkers"
            :key="marker.id"
            @click="toggleMarkerFn(mediaId, marker)"
            :class="[
              'px-2.5 py-1.5 rounded-lg text-xs font-semibold cursor-pointer transition-all border-2 flex items-center gap-1.5',
              hasMarker(mediaId, marker.id)
                ? 'bg-opacity-30 border-opacity-100'
                : 'bg-overlay-subtle border-edge-subtle text-content-tertiary hover:bg-overlay-light hover:text-content'
            ]"
            :style="hasMarker(mediaId, marker.id) ? { backgroundColor: marker.color + '33', borderColor: marker.color, color: marker.color } : {}"
            :title="marker.name"
          >
            <span v-html="sanitizeSvg(marker.icon_svg)" class="w-4 h-4 flex-shrink-0 icon-container"></span>
          </button>
        </div>
      </div>

      <!-- Tool name -->
      <h4 v-if="genStep?.tool_id" class="m-0 text-sm font-semibold text-content">
        {{ humanizeToolName(getToolDisplayName(genStep)) }}
      </h4>

      <!-- Input Assets (source images used to create this) -->
      <div v-if="resolvedSourceInputs.length > 0">
        <div class="text-xs font-semibold text-content-secondary mb-2">Input Assets</div>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="(source, si) in resolvedSourceInputs"
            :key="si"
            class="relative rounded-lg overflow-hidden border border-edge hover:border-blue-500 transition-colors p-0 cursor-pointer"
            :class="source.inTree === false ? 'opacity-50 pointer-events-none' : ''"
            :style="{ width: '80px', height: '80px' }"
            :title="sourceTitle(source)"
            @click="source.media_id && $emit('navigate', source.media_id)"
          >
            <MediaImage
              v-if="source.media_id"
              :media-id="source.media_id"
              :thumbnail-size="128"
              container-class="w-full h-full"
              img-class="w-full h-full object-cover"
            />
            <!-- Preprocessor badge (e.g. ControlNet canny applied to this input) -->
            <div v-if="source.preprocessor" class="absolute top-0 inset-x-0 bg-blue-500/80 text-white text-[9px] text-center py-0.5 truncate px-1">
              {{ source.preprocessor }}
            </div>
            <div v-if="source.role" class="absolute bottom-0 inset-x-0 bg-black/60 text-white text-[9px] text-center py-0.5 truncate px-1">
              {{ formatSourceRole(source.role) }}
            </div>
          </button>
        </div>
      </div>

      <!-- Sources from lineage edges (parents not in source_inputs) -->
      <div v-if="parentNodes.length > 0">
        <div class="text-xs font-semibold text-content-secondary mb-2">{{ inspiredParentCount > 0 ? 'Remix Of' : 'Source' }}</div>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="parent in parentNodes"
            :key="parent.id"
            class="relative rounded-lg overflow-hidden border transition-colors p-0 cursor-pointer"
            :class="parent.inspired ? 'border-purple-500/50 hover:border-purple-500' : 'border-edge hover:border-blue-500'"
            :style="{ width: '80px', height: '80px' }"
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

      <!-- Prompt: read-only prose is typeset, never boxed like a form field -->
      <div v-if="genStep?.prompt">
        <div class="text-content-tertiary text-xs mb-1">Prompt</div>
        <p class="text-content-secondary text-xs leading-relaxed m-0 select-text">{{ genStep.prompt }}</p>
      </div>
      <!-- Fallback: extracted_prompt when no gen metadata -->
      <div v-else-if="media.extracted_prompt">
        <div class="text-content-tertiary text-xs mb-1">Prompt</div>
        <p class="text-content-secondary text-xs leading-relaxed m-0 select-text">{{ media.extracted_prompt }}</p>
      </div>

      <!-- Negative prompt -->
      <div v-if="genStep?.negative_prompt">
        <div class="text-content-tertiary text-xs mb-1">Negative Prompt</div>
        <p class="text-content-secondary text-xs leading-relaxed m-0 select-text">{{ genStep.negative_prompt }}</p>
      </div>

      <!-- Caption -->
      <div v-if="media.vlm_caption">
        <div class="text-content-tertiary text-xs mb-1">Description</div>
        <p class="text-content-secondary text-xs leading-relaxed m-0 select-text">{{ media.vlm_caption }}</p>
      </div>

      <!-- Flow origin -->
      <div v-if="flowLineage?.flow_id" class="flex items-baseline justify-between gap-4 py-1.5 border-b border-edge-subtle">
        <span class="text-xs text-content-tertiary flex-shrink-0">Flow</span>
        <button
          class="text-blue-400 hover:underline text-xs truncate"
          :title="flowLineage.phase_path?.join(' / ') || ''"
          @click="$emit('open-flow', flowLineage.flow_id)"
        >
          Open flow #{{ flowLineage.flow_id }}
          <span v-if="flowLineage.phase_path?.length" class="text-content-muted">— {{ flowLineage.phase_path.join(' / ') }}</span>
        </button>
      </div>

      <!-- Generation facts: typeset key·value, not field tiles -->
      <div v-if="genStep?.model || displayParams.length > 0 || genStep?.generated_at">
        <div class="text-xs font-semibold text-content-secondary mb-1">Generation</div>
        <KeyValueList :rows="generationRows" />
      </div>

      <!-- LoRAs -->
      <div v-if="genMetaLoras?.length > 0">
        <div class="text-xs font-semibold text-content-secondary mb-1">LoRAs</div>
        <div class="flex flex-wrap gap-1">
          <span
            v-for="(lora, i) in genMetaLoras"
            :key="i"
            class="bg-purple-500/20 text-purple-500 px-2 py-0.5 rounded text-xs"
          >
            {{ lora.name || lora.lora || lora.filename || 'LoRA' }}
            <span v-if="lora.weight != null" class="text-purple-400/60">({{ lora.weight }})</span>
          </span>
        </div>
      </div>

      <!-- Derivatives (children of this node) -->
      <div v-if="childNodes.length > 0">
        <div class="text-xs font-semibold text-content-secondary mb-2">Made From This</div>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="child in childNodes"
            :key="child.id"
            class="relative rounded-lg overflow-hidden border transition-colors p-0 cursor-pointer"
            :class="child.inspired ? 'border-purple-500/50 hover:border-purple-500' : 'border-edge hover:border-blue-500'"
            :style="{ width: '56px', height: '56px' }"
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

      <!-- File Info -->
      <div>
        <div class="text-xs font-semibold text-content-secondary mb-1 mt-1">File</div>
        <KeyValueList :rows="fileRows" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, watch, onMounted } from 'vue'
import { MediaImage } from './index'
import KeyValueList from '../ui/KeyValueList.vue'
import { useMarkers } from '../../composables/useMarkers'
import { getFilterDisplayLabel } from '@stimma/image-editor'
import { sanitizeSvg } from '../../utils/sanitizeHtml'

const props = defineProps({
  // Full media item (must include `id` and generation_metadata)
  media: {
    type: Object,
    required: true
  },
  // Optional source-input overrides (with `inTree` flags) supplied by a tree context.
  // When omitted, derived from the media's generation_metadata.
  sourceInputs: {
    type: Array,
    default: null
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

const mediaId = computed(() => props.media.id)

function parseMeta(media) {
  const raw = media?.generation_metadata
  if (!raw) return null
  try {
    return typeof raw === 'string' ? JSON.parse(raw) : raw
  } catch {
    return null
  }
}

// Build generation step from generation_metadata
const genStep = computed(() => {
  const meta = parseMeta(props.media)
  if (!meta) return null

  const params = { ...((meta.parameters) || {}) }
  if (params.seed === undefined && meta.seed !== undefined && meta.seed !== null) {
    params.seed = meta.seed
  }

  return {
    media_id: mediaId.value,
    task_type: meta.task_type,
    model: meta.model,
    prompt: meta.prompt,
    negative_prompt: meta.negative_prompt || params.negative_prompt,
    parameters: params,
    generated_at: meta.generated_at,
    source_inputs: Array.isArray(meta.source_inputs) ? meta.source_inputs : [],
    tool_id: meta.tool_id || null
  }
})

// Flow lineage (pulled from generation_metadata when source=flow)
const flowLineage = computed(() => {
  const meta = parseMeta(props.media)
  if (!meta || meta.source !== 'flow') return null
  return {
    flow_id: meta.flow_id ?? null,
    equation_key: meta.equation_key ?? null,
    phase_path: Array.isArray(meta.phase_path) ? meta.phase_path : [],
  }
})

// Source inputs: prefer tree-supplied list (carries inTree flags), else derive from metadata.
const resolvedSourceInputs = computed(() => {
  if (props.sourceInputs) return props.sourceInputs
  const inputs = genStep.value?.source_inputs
  if (!inputs?.length) return []
  return inputs.filter(s => s.media_id)
})

const inspiredParentCount = computed(() => props.parentNodes.filter(p => p.inspired).length)

// Parameters to exclude from generic display
const excludedParams = new Set([
  'prompt', 'negative_prompt', 'selected_loras', 'loras',
  'width', 'height', 'input_width', 'input_height', 'output_width', 'output_height',
  'output_size', 'bbox', 'checkpoint'
])

const stepLabelOverrides = {
  seed: 'Seed', cfg: 'CFG', fps: 'FPS', generation_time: 'Gen Time',
  frame_count: 'Frames', color_correction: 'Color Correction',
  target_megapixels: 'Target MP', aspect_ratio: 'Aspect Ratio',
  padding_percent: 'Padding', padding: 'Padding', item_count: 'Items',
  cell_count: 'Cells', clip_skip: 'Clip Skip', checkpoint: 'Model',
  filter_id: 'Filter',
}

const displayParams = computed(() => {
  const params = genStep.value?.parameters
  if (!params) return []
  const result = []

  if (params.width && params.height && !params.input_width) {
    result.push({ label: 'Size', value: `${params.width}×${params.height}`, fullWidth: false })
  }
  if (params.input_width && params.input_height) {
    result.push({ label: 'Input Size', value: `${params.input_width}×${params.input_height}`, fullWidth: false })
  }
  if (params.output_width && params.output_height) {
    result.push({ label: 'Output Size', value: `${params.output_width}×${params.output_height}`, fullWidth: false })
  }

  for (const [key, value] of Object.entries(params)) {
    if (excludedParams.has(key)) continue
    if (value === null || value === undefined) continue
    if (typeof value === 'object') continue

    const label = stepLabelOverrides[key] || key.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
    let fv = String(value)
    if (key === 'filter_id' || key === 'filter') fv = getFilterDisplayLabel(fv)
    if (typeof value === 'boolean') fv = value ? 'Yes' : 'No'
    if (key === 'generation_time') fv = `${value}s`
    if (key === 'padding_percent' || key === 'confidence') fv = `${(value * 100).toFixed(0)}%`
    if (key === 'scale') fv = `${value}×`
    result.push({ label, value: fv, fullWidth: fv.length > 16 })
  }

  // Post-processing chain (the steps that ran) — compact summary, no JSON wall
  const chain = params.post_processing_chain
  if (Array.isArray(chain) && chain.length) {
    const names = chain.map(s => s.kind === 'filter' ? s.filter_id : (s.tool_name || s.tool_id)).filter(Boolean)
    result.push({ label: 'Post-processing', value: names.join(' → '), fullWidth: true })
  }
  return result
})

// Atelier KeyValueList rows — facts voice (mono), model/tool names stay sans.
const generationRows = computed(() => {
  const rows = []
  if (genStep.value?.model) rows.push({ label: 'Model', value: genStep.value.model, mono: false, truncate: true })
  for (const p of displayParams.value) {
    rows.push({ label: p.label, value: p.value, truncate: p.fullWidth })
  }
  if (genStep.value?.generated_at) rows.push({ label: 'Generated', value: formatDate(genStep.value.generated_at) })
  return rows
})

const fileRows = computed(() => {
  const m = props.media
  const rows = []
  if (m.file_path) rows.push({ label: 'Name', value: m.file_path.split('/').pop(), truncate: true })
  if (m.file_format) rows.push({ label: 'Format', value: String(m.file_format).toUpperCase() })
  if (m.file_size) rows.push({ label: 'Size', value: formatFileSize(m.file_size) })
  if (m.width > 0) rows.push({ label: 'Resolution', value: `${m.width} × ${m.height}` })
  if (m.duration) rows.push({ label: 'Duration', value: formatDuration(m.duration) })
  if (m.audio_sample_rate) rows.push({ label: 'Sample rate', value: formatSampleRate(m.audio_sample_rate) })
  if (m.audio_bit_depth) rows.push({ label: 'Bit depth', value: `${m.audio_bit_depth}-bit` })
  if (m.audio_channels) rows.push({ label: 'Channels', value: formatChannels(m.audio_channels), mono: false })
  if (m.created_date) rows.push({ label: 'Created', value: formatDate(m.created_date) })
  return rows
})

const genMetaLoras = computed(() => {
  const params = genStep.value?.parameters
  if (!params) return []
  return params.loras || params.selected_loras || []
})

function formatSourceRole(role) {
  if (!role) return 'Input'
  const labels = { image: 'Image', style: 'Style', reference: 'Reference', mask: 'Mask', depth: 'Depth', pose: 'Pose' }
  return labels[role] || role.charAt(0).toUpperCase() + role.slice(1)
}

function sourceTitle(source) {
  const role = source.role ? formatSourceRole(source.role) : 'Input'
  return source.preprocessor ? `${role} · ${source.preprocessor}` : role
}

function humanizeToolName(name) {
  return name.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
}

function getToolDisplayName(step) {
  if (step?.task_type === 'agent_edit') return 'Edited by Agent'
  if (step?.tool_id) {
    const colonIndex = step.tool_id.indexOf(':')
    if (colonIndex !== -1) return step.tool_id.substring(colonIndex + 1)
    return step.tool_id
  }
  return step?.task_type || 'Imported'
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' })
}

function formatFileSize(bytes) {
  if (!bytes) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDuration(seconds) {
  if (!seconds || isNaN(seconds)) return ''
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

function formatSampleRate(hz) {
  if (!hz) return ''
  if (hz >= 1000) return `${(hz / 1000).toFixed(hz % 1000 === 0 ? 0 : 1)} kHz`
  return `${hz} Hz`
}

function formatChannels(channels) {
  if (channels === 1) return 'Mono'
  if (channels === 2) return 'Stereo'
  return `${channels} channels`
}

// Markers: load for the displayed media (idempotent shared-singleton calls).
async function loadMarkers(id) {
  if (!id) return
  await initMarkers()
  await loadMarkersForMedia([id])
}

onMounted(() => loadMarkers(mediaId.value))
watch(mediaId, (id) => loadMarkers(id))
</script>
