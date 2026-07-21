<template>
  <div class="w-full h-full bg-slideshow-matt flex flex-col overflow-hidden" @click.stop>
    <div v-if="loading" class="flex-1 flex items-center justify-center text-content-tertiary">
      Loading timeline...
    </div>
    <div v-else-if="error" class="flex-1 flex items-center justify-center text-red-400">
      {{ error }}
    </div>

    <template v-else-if="state">
      <!-- Stage: what's on screen at the playhead -->
      <div class="flex-1 min-h-0 relative flex items-center justify-center pt-14 px-6">
        <div class="relative rounded-media overflow-hidden bg-matte w-full h-full">
          <!-- Clip videos: current + preloaded next, keyed by entry id so the
               preloaded element is reused across the cut (gapless leapfrog) -->
          <video
            v-for="clip in stageClips"
            :key="clip.entry.id"
            :ref="(el) => setVideoRef(clip.entry.id, el)"
            :src="fileUrl(clip.entry)"
            class="absolute inset-0 w-full h-full object-contain"
            :class="clip.current ? 'opacity-100' : 'opacity-0 pointer-events-none'"
            preload="auto"
            playsinline
          />

          <!-- Still image clip -->
          <MediaImage
            v-if="stageImage"
            :key="`img-${stageImage.entry.id}`"
            :media-id="stageImage.entry.media.media_id"
            :file-hash="mediaOf(stageImage.entry)?.file_hash"
            :file-format="mediaOf(stageImage.entry)?.file_format"
            :thumbnail="false"
            contain
            :draggable="false"
            container-class="absolute inset-0"
            img-class="w-full h-full object-contain"
          />

          <!-- Slot: the hole's brief card -->
          <div
            v-if="stageSlot"
            class="absolute inset-0 flex items-center justify-center p-8"
          >
            <div class="max-w-md text-center space-y-2">
              <div class="text-xs font-semibold text-content-secondary">Hole</div>
              <div class="text-lg font-brand font-semibold text-content">
                {{ stageSlot.entry.brief || 'Untitled slot' }}
              </div>
              <div class="text-xs font-mono tabular-nums text-content-tertiary">
                {{ formatTimecode(stageSlot.duration) }}
              </div>
            </div>
          </div>

          <div
            v-if="!videoEval"
            class="absolute inset-0 flex items-center justify-center text-content-muted text-sm"
          >
            {{ totalDuration > 0 ? 'End' : 'Empty timeline — drop media below or ask the agent for a skeleton' }}
          </div>
        </div>

        <!-- Audio underlay -->
        <audio ref="audioElement" preload="auto" />
      </div>

      <!-- Transport + strips -->
      <div class="shrink-0 px-6 pb-4 pt-2 space-y-2" @pointerdown.stop>
        <!-- Scrubber -->
        <div
          ref="scrubberRef"
          class="relative h-4 flex items-center cursor-pointer group"
          @pointerdown="onScrubStart"
        >
          <div class="w-full h-[3px] rounded-full bg-overlay-subtle">
            <div
              class="h-full rounded-full bg-live"
              :style="{ width: `${totalDuration ? (playhead / totalDuration) * 100 : 0}%` }"
            />
          </div>
          <div
            class="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-2.5 h-2.5 rounded-full bg-live opacity-0 group-hover:opacity-100 transition-opacity duration-150"
            :style="{ left: `${totalDuration ? (playhead / totalDuration) * 100 : 0}%` }"
          />
        </div>

        <!-- Transport row -->
        <div class="flex items-center gap-2">
          <IconButton :title="playing ? 'Pause' : 'Play'" @click="togglePlay">
            <svg v-if="!playing" class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
              <path d="M8 5.14v13.72c0 .77.83 1.25 1.5.87l11-6.86a1 1 0 0 0 0-1.74l-11-6.86A1 1 0 0 0 8 5.14z" />
            </svg>
            <svg v-else class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
              <rect x="6" y="5" width="4" height="14" rx="1" />
              <rect x="14" y="5" width="4" height="14" rx="1" />
            </svg>
          </IconButton>
          <span class="text-xs font-mono tabular-nums text-content-secondary select-none">
            {{ formatTimecode(playhead) }} / {{ formatTimecode(totalDuration) }}
          </span>

          <div class="flex-1" />

          <template v-if="selectedEntry">
            <template v-if="selectedEntry.kind === 'clip' && selectedHasSourceTime">
              <label class="text-xs text-content-tertiary select-none">in</label>
              <input
                v-model="editIn"
                class="w-14 bg-overlay-subtle rounded-md px-1.5 py-0.5 text-xs font-mono tabular-nums text-content border border-transparent focus:border-accent outline-none"
                @keydown.enter="commitTrim"
                @blur="commitTrim"
              />
              <label class="text-xs text-content-tertiary select-none">out</label>
              <input
                v-model="editOut"
                class="w-14 bg-overlay-subtle rounded-md px-1.5 py-0.5 text-xs font-mono tabular-nums text-content border border-transparent focus:border-accent outline-none"
                @keydown.enter="commitTrim"
                @blur="commitTrim"
              />
            </template>
            <template v-else>
              <label class="text-xs text-content-tertiary select-none">length</label>
              <input
                v-model="editDuration"
                class="w-14 bg-overlay-subtle rounded-md px-1.5 py-0.5 text-xs font-mono tabular-nums text-content border border-transparent focus:border-accent outline-none"
                @keydown.enter="commitTrim"
                @blur="commitTrim"
              />
            </template>
            <IconButton title="Remove entry" variant="danger" @click="removeSelected">
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
              </svg>
            </IconButton>
            <div class="w-px h-4 bg-edge-subtle" />
          </template>

          <IconButton title="Undo" :disabled="!canUndo" @click="doUndo">
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 15 3 9m0 0 6-6M3 9h12a6 6 0 0 1 0 12h-3" />
            </svg>
          </IconButton>
          <IconButton title="Redo" :disabled="!canRedo" @click="doRedo">
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="m15 15 6-6m0 0-6-6m6 6H9a6 6 0 0 0 0 12h3" />
            </svg>
          </IconButton>
          <Button size="sm" variant="secondary" :disabled="saving" @click="save">
            {{ saving ? 'Saving…' : 'Save version' }}
          </Button>
        </div>

        <!-- Video strip -->
        <div
          class="flex gap-0.5 overflow-x-auto custom-scrollbar pb-1"
          @dragover.prevent="onStripDragOver($event, 'video')"
          @drop.prevent="onStripDrop($event, 'video')"
        >
          <div
            v-for="placement in videoPlacements"
            :key="placement.entry.id"
            class="relative shrink-0 h-24 rounded-media overflow-hidden bg-matte cursor-pointer group"
            :class="[
              selectedId === placement.entry.id ? 'ring-2 ring-selection ring-inset' : '',
              dropTargetId === placement.entry.id ? 'ring-1 ring-accent/50 bg-accent/10' : '',
            ]"
            :style="{ width: `${tileWidth(placement)}px` }"
            draggable="true"
            @click="selectEntry(placement)"
            @dragstart="onTileDragStart($event, placement, 'video')"
            @dragend="onTileDragEnd"
            @dragover.prevent="onTileDragOver($event, placement, 'video')"
            @drop.prevent.stop="onTileDrop($event, placement, 'video')"
          >
            <template v-if="placement.entry.kind === 'clip'">
              <MediaImage
                :media-id="placement.entry.media.media_id"
                :file-hash="mediaOf(placement.entry)?.file_hash"
                :file-format="mediaOf(placement.entry)?.file_format"
                thumbnail
                :thumbnail-size="256"
                :draggable="false"
                container-class="w-full h-full"
                img-class="w-full h-full object-cover"
              />
              <div
                v-if="placement.entry.label"
                class="absolute top-1 left-1 max-w-[calc(100%-8px)] truncate text-[11px] text-white/90 bg-black/55 backdrop-blur rounded-md px-1.5 py-0.5"
              >
                {{ placement.entry.label }}
              </div>
            </template>
            <template v-else>
              <div class="w-full h-full border border-dashed border-edge rounded-media flex flex-col items-center justify-center gap-1 px-2">
                <div class="text-[11px] text-content-secondary text-center line-clamp-2">
                  {{ placement.entry.brief || 'Empty hole' }}
                </div>
              </div>
            </template>

            <div class="absolute bottom-1 right-1 text-[10px] font-mono tabular-nums text-white/90 bg-black/55 backdrop-blur rounded-md px-1 py-px">
              {{ placement.duration.toFixed(1) }}s
            </div>
            <div
              v-if="activeVideoId === placement.entry.id"
              class="absolute bottom-0 left-0 right-0 h-[2px] bg-live"
            />
          </div>

          <div
            v-if="videoPlacements.length === 0"
            class="h-24 flex-1 border border-dashed border-edge rounded-media flex items-center justify-center text-xs text-content-muted"
          >
            Drop video or images here
          </div>
        </div>

        <!-- Audio strip -->
        <div
          class="flex gap-0.5 overflow-x-auto custom-scrollbar"
          @dragover.prevent="onStripDragOver($event, 'audio')"
          @drop.prevent="onStripDrop($event, 'audio')"
        >
          <div
            v-for="placement in audioPlacements"
            :key="placement.entry.id"
            class="relative shrink-0 h-8 rounded-media cursor-pointer flex items-center gap-1.5 px-2 bg-overlay-subtle"
            :class="[
              selectedId === placement.entry.id ? 'ring-2 ring-selection ring-inset' : '',
              dropTargetId === placement.entry.id ? 'ring-1 ring-accent/50 bg-accent/10' : '',
            ]"
            :style="{ width: `${tileWidth(placement)}px` }"
            @click="selectEntry(placement)"
            @dragover.prevent="onTileDragOver($event, placement, 'audio')"
            @drop.prevent.stop="onTileDrop($event, placement, 'audio')"
          >
            <span class="text-[11px] truncate" :class="placement.entry.kind === 'slot' && placement.entry.silence ? 'text-content-muted' : 'text-content-secondary'">
              {{ audioLabel(placement.entry) }}
            </span>
            <span class="ml-auto text-[10px] font-mono tabular-nums text-content-tertiary">
              {{ placement.duration.toFixed(1) }}s
            </span>
            <div
              v-if="activeAudioId === placement.entry.id"
              class="absolute bottom-0 left-0 right-0 h-[2px] bg-live"
            />
          </div>
          <div
            v-if="audioPlacements.length === 0"
            class="h-8 flex-1 border border-dashed border-edge rounded-media flex items-center justify-center text-[11px] text-content-muted"
          >
            Drop audio here
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import axios from 'axios'
import { MediaImage } from '../media'
import Button from '../ui/Button.vue'
import IconButton from '../ui/IconButton.vue'
import { useMediaApi } from '../../composables/useMediaApi'
import { useWebSocket } from '../../composables/useWebSocket'
import { addToast } from '../../composables/useToasts'
import { draggedMediaInfo, draggedMediaType } from '../../stores/dragStore'
import { getMediaType } from '../../utils/mediaTypes'
import {
  evaluate,
  formatTimecode,
  timelineDuration,
  trackPlacements,
} from '../../utils/timelineEval'

const props = defineProps({
  mediaId: { type: Number, required: true },
})
const emit = defineEmits(['loaded'])

const { getMediaFileUrl } = useMediaApi()
const { on } = useWebSocket()

const loading = ref(true)
const error = ref(null)
const assetId = ref(null)
const state = ref(null)
const mediaMap = ref({})
const cursor = ref(0)
const canUndo = ref(false)
const canRedo = ref(false)
const saving = ref(false)

const playing = ref(false)
const playhead = ref(0)
const selectedId = ref(null)
const dropTargetId = ref(null)

const audioElement = ref(null)
const scrubberRef = ref(null)
const videoRefs = new Map()

// --- document access ---------------------------------------------------

const totalDuration = computed(() => (state.value ? timelineDuration(state.value) : 0))
const videoTrack = computed(() => state.value?.tracks.find((t) => t.kind === 'video'))
const audioTrack = computed(() => state.value?.tracks.find((t) => t.kind === 'audio'))
const videoPlacements = computed(() => (videoTrack.value ? trackPlacements(videoTrack.value) : []))
const audioPlacements = computed(() => (audioTrack.value ? trackPlacements(audioTrack.value) : []))

const selectedEntry = computed(() => {
  if (!selectedId.value || !state.value) return null
  for (const track of state.value.tracks) {
    const entry = track.entries.find((e) => e.id === selectedId.value)
    if (entry) return entry
  }
  return null
})

function mediaOf(entry) {
  return mediaMap.value[String(entry.media?.media_id)]
}

function fileUrl(entry) {
  const media = mediaOf(entry)
  return media ? getMediaFileUrl(media.file_hash) : undefined
}

function isVideoMedia(entry) {
  const media = mediaOf(entry)
  return media && getMediaType(media) === 'video'
}

const selectedHasSourceTime = computed(() => {
  const entry = selectedEntry.value
  if (!entry || entry.kind !== 'clip') return false
  return entry.out != null
})

// --- evaluation + stage --------------------------------------------------

const videoEval = computed(() => (state.value ? evaluate(state.value, playhead.value).video : null))
const audioEval = computed(() => (state.value ? evaluate(state.value, playhead.value).audio : null))
const activeVideoId = computed(() => videoEval.value?.entry.id || null)
const activeAudioId = computed(() => audioEval.value?.entry.id || null)

const stageSlot = computed(() =>
  videoEval.value && videoEval.value.entry.kind === 'slot' ? videoEval.value : null
)
const stageImage = computed(() =>
  videoEval.value && videoEval.value.entry.kind === 'clip' && !isVideoMedia(videoEval.value.entry)
    ? videoEval.value
    : null
)

// Current video clip plus the next video clip in the track (preloaded, hidden).
const stageClips = computed(() => {
  if (!videoTrack.value) return []
  const clips = []
  const current = videoEval.value
  const placements = videoPlacements.value
  if (current && current.entry.kind === 'clip' && isVideoMedia(current.entry)) {
    clips.push({ entry: current.entry, current: true })
  }
  const fromIndex = current ? current.index + 1 : 0
  const next = placements
    .slice(fromIndex)
    .find((p) => p.entry.kind === 'clip' && isVideoMedia(p.entry))
  if (next && !clips.some((c) => c.entry.id === next.entry.id)) {
    clips.push({ entry: next.entry, current: false })
  }
  return clips
})

function setVideoRef(entryId, el) {
  if (el) videoRefs.set(entryId, el)
  else videoRefs.delete(entryId)
}

// --- playback clock -------------------------------------------------------

let rafId = null
let lastTick = null

function tick(now) {
  if (playing.value) {
    if (lastTick != null) {
      playhead.value = Math.min(totalDuration.value, playhead.value + (now - lastTick) / 1000)
      if (playhead.value >= totalDuration.value) {
        playing.value = false
      }
    }
    lastTick = now
  } else {
    lastTick = null
  }
  syncMedia()
  rafId = requestAnimationFrame(tick)
}

const DRIFT_TOLERANCE = 0.15

function syncMedia() {
  const current = videoEval.value
  for (const [entryId, el] of videoRefs) {
    const isCurrent = current && current.entry.id === entryId && current.entry.kind === 'clip'
    if (isCurrent) {
      const desired = current.sourceTime
      if (Math.abs(el.currentTime - desired) > DRIFT_TOLERANCE) {
        el.currentTime = desired
      }
      if (playing.value && el.paused) el.play().catch(() => {})
      if (!playing.value && !el.paused) el.pause()
    } else {
      if (!el.paused) el.pause()
      // Park preloaded elements at their entry's in-point, ready for the cut
      const placement = videoPlacements.value.find((p) => p.entry.id === entryId)
      if (placement && el.readyState >= 1) {
        const inPoint = placement.entry.in || 0
        if (Math.abs(el.currentTime - inPoint) > DRIFT_TOLERANCE) {
          el.currentTime = inPoint
        }
      }
    }
  }

  const audioEl = audioElement.value
  if (audioEl) {
    const audio = audioEval.value
    if (audio && audio.entry.kind === 'clip') {
      const url = fileUrl(audio.entry)
      if (url && !audioEl.src.endsWith(url)) audioEl.src = url
      if (Math.abs(audioEl.currentTime - audio.sourceTime) > DRIFT_TOLERANCE) {
        audioEl.currentTime = audio.sourceTime
      }
      if (playing.value && audioEl.paused) audioEl.play().catch(() => {})
      if (!playing.value && !audioEl.paused) audioEl.pause()
    } else if (!audioEl.paused) {
      audioEl.pause()
    }
  }
}

function togglePlay() {
  if (!playing.value && playhead.value >= totalDuration.value) {
    playhead.value = 0
  }
  playing.value = !playing.value
}

// --- scrubbing -------------------------------------------------------------

let scrubbing = false

function seekFromPointer(event) {
  const rect = scrubberRef.value.getBoundingClientRect()
  const fraction = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width))
  playhead.value = fraction * totalDuration.value
}

function onScrubStart(event) {
  scrubbing = true
  seekFromPointer(event)
  const move = (e) => scrubbing && seekFromPointer(e)
  const up = () => {
    scrubbing = false
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', up)
  }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', up)
}

// --- selection + inspector ---------------------------------------------------

const editIn = ref('')
const editOut = ref('')
const editDuration = ref('')

watch(selectedEntry, (entry) => {
  if (!entry) return
  editIn.value = entry.in != null ? String(entry.in) : '0'
  editOut.value = entry.out != null ? String(entry.out) : ''
  editDuration.value = entry.duration != null ? String(entry.duration) : ''
})

function selectEntry(placement) {
  selectedId.value = placement.entry.id
  playhead.value = placement.start + 0.001
}

async function commitTrim() {
  const entry = selectedEntry.value
  if (!entry) return
  const args = { entry_id: entry.id }
  if (entry.kind === 'clip' && selectedHasSourceTime.value) {
    const inValue = parseFloat(editIn.value)
    const outValue = parseFloat(editOut.value)
    if (Number.isNaN(inValue) || Number.isNaN(outValue)) return
    if (inValue === (entry.in || 0) && outValue === entry.out) return
    args.in = inValue
    args.out = outValue
  } else {
    const durationValue = parseFloat(editDuration.value)
    if (Number.isNaN(durationValue) || durationValue === entry.duration) return
    args.duration = durationValue
  }
  await postOps([{ op: 'trim_clip', args }], 'Trim')
}

async function removeSelected() {
  if (!selectedEntry.value) return
  await postOps(
    [{ op: 'remove_entry', args: { entry_id: selectedEntry.value.id } }],
    'Remove entry'
  )
  selectedId.value = null
}

// --- drag: reorder within strip + drops from the library ---------------------

let draggingEntryId = null

function onTileDragStart(event, placement, trackKind) {
  draggingEntryId = placement.entry.id
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('text/plain', placement.entry.id)
}

function onTileDragEnd() {
  draggingEntryId = null
  dropTargetId.value = null
}

function libraryDragMedia(trackKind) {
  const info = draggedMediaInfo.value
  if (!info || info.loading) return null
  const type = draggedMediaType.value
  const ok = trackKind === 'video' ? type === 'video' || type === 'image' : type === 'audio'
  return ok ? { ...info, mediaType: type } : null
}

function onTileDragOver(event, placement, trackKind) {
  if (draggingEntryId || libraryDragMedia(trackKind)) {
    dropTargetId.value = placement.entry.id
  }
}

function onStripDragOver(event, trackKind) {
  if (!event.target.closest('[draggable]')) dropTargetId.value = null
}

function dropPosition(event, placement) {
  const rect = event.currentTarget.getBoundingClientRect()
  const after = event.clientX > rect.left + rect.width / 2
  return placement.index + (after ? 1 : 0)
}

async function onTileDrop(event, placement, trackKind) {
  dropTargetId.value = null
  if (draggingEntryId && draggingEntryId !== placement.entry.id) {
    const from = [...videoPlacements.value, ...audioPlacements.value].find(
      (p) => p.entry.id === draggingEntryId
    )
    let position = dropPosition(event, placement)
    if (from && from.index < position) position -= 1
    await postOps(
      [{ op: 'move_entry', args: { entry_id: draggingEntryId, position } }],
      'Move entry'
    )
    draggingEntryId = null
    return
  }

  const info = libraryDragMedia(trackKind)
  if (!info) return
  if (placement.entry.kind === 'slot') {
    await postOps(
      [{ op: 'fill_slot', args: fillSlotArgs(placement.entry, info) }],
      'Fill hole'
    )
  } else {
    await postOps(
      [{ op: 'add_clip', args: addClipArgs(info, trackKind, dropPosition(event, placement)) }],
      'Add clip'
    )
  }
}

async function onStripDrop(event, trackKind) {
  dropTargetId.value = null
  if (draggingEntryId) return
  const info = libraryDragMedia(trackKind)
  if (!info) return
  await postOps([{ op: 'add_clip', args: addClipArgs(info, trackKind) }], 'Add clip')
}

function addClipArgs(info, trackKind, position) {
  const args = { track: trackKind, media_id: info.mediaId }
  if (info.mediaType === 'image') args.duration = 3
  if (position != null) args.position = position
  return args
}

function fillSlotArgs(slot, info) {
  const args = { slot_id: slot.id, media_id: info.mediaId }
  if (info.mediaType === 'image') args.duration = slot.duration
  return args
}

// --- strip sizing --------------------------------------------------------

function tileWidth(placement) {
  return Math.max(72, Math.min(280, placement.duration * 28))
}

function audioLabel(entry) {
  if (entry.kind === 'clip') return entry.label || `media ${entry.media.media_id}`
  if (entry.silence) return 'silence'
  return entry.brief || 'Empty hole'
}

// --- API -------------------------------------------------------------------

function adoptResult(data) {
  if (data.state) state.value = data.state
  if (data.media) mediaMap.value = { ...mediaMap.value, ...data.media }
  if (data.cursor != null) cursor.value = data.cursor
  if (data.can_undo != null) canUndo.value = data.can_undo
  if (data.can_redo != null) canRedo.value = data.can_redo
  playhead.value = Math.min(playhead.value, timelineDuration(state.value || { tracks: [] }))
}

async function load() {
  loading.value = true
  error.value = null
  try {
    const { data } = await axios.get(`/api/timelines/by-media/${props.mediaId}`)
    assetId.value = data.asset_id
    adoptResult(data)
    emit('loaded', { title: data.state?.title })
  } catch (err) {
    error.value = err.response?.data?.detail || 'Failed to load timeline'
  } finally {
    loading.value = false
  }
}

async function postOps(ops, label) {
  try {
    const { data } = await axios.post(`/api/timelines/${assetId.value}/ops`, { ops, label })
    adoptResult(data)
  } catch (err) {
    addToast(err.response?.data?.detail || 'Edit failed', 'error')
  }
}

async function doUndo() {
  try {
    const { data } = await axios.post(`/api/timelines/${assetId.value}/undo`)
    adoptResult(data)
  } catch (err) {
    addToast(err.response?.data?.detail || 'Undo failed', 'error')
  }
}

async function doRedo() {
  try {
    const { data } = await axios.post(`/api/timelines/${assetId.value}/redo`)
    adoptResult(data)
  } catch (err) {
    addToast(err.response?.data?.detail || 'Redo failed', 'error')
  }
}

async function save() {
  saving.value = true
  try {
    const { data } = await axios.post(`/api/timelines/${assetId.value}/save`, {})
    addToast(`Saved version ${data.revision_number}`, 'success')
  } catch (err) {
    addToast(err.response?.data?.detail || 'Save failed', 'error')
  } finally {
    saving.value = false
  }
}

// --- lifecycle ---------------------------------------------------------------

let unsubscribe = null

function onKeydownCapture(event) {
  const target = event.target
  if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
    return
  }
  if (event.code === 'Space') {
    event.preventDefault()
    event.stopPropagation()
    togglePlay()
  } else if ((event.key === 'Backspace' || event.key === 'Delete') && selectedEntry.value) {
    event.preventDefault()
    event.stopPropagation()
    removeSelected()
  }
}

onMounted(async () => {
  await load()
  rafId = requestAnimationFrame(tick)
  window.addEventListener('keydown', onKeydownCapture, true)
  unsubscribe = on('timeline_changed', (data) => {
    if (data.asset_id === assetId.value && data.cursor !== cursor.value) {
      // Another writer (the agent) advanced the document — refresh
      axios.get(`/api/timelines/${assetId.value}`).then(({ data: fresh }) => adoptResult(fresh))
    }
  })
})

onBeforeUnmount(() => {
  if (rafId) cancelAnimationFrame(rafId)
  window.removeEventListener('keydown', onKeydownCapture, true)
  if (unsubscribe) unsubscribe()
  playing.value = false
})
</script>
