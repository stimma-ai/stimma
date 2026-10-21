<template>
  <div class="mb-6">
    <div class="text-sm font-medium text-content mb-2">{{ label }}</div>
    <div
      ref="boxRef"
      class="rounded-lg border px-3 pt-2 pb-1 transition-colors"
      :class="dropAt !== null ? 'border-transparent ring-1 ring-accent/50 bg-accent/10' : 'border-edge-subtle bg-overlay-faint'"
      @dragover="onDragOver"
      @dragleave="onDragLeave"
      @drop="onDrop"
    >
      <!-- Strip: the output's timeline, as long as the duration -->
      <div
        ref="stripRef"
        class="relative select-none cursor-pointer h-[118px] compact:h-[96px]"
        data-testid="keyframes-strip"
        @click="onStripClick"
        @pointermove="onStripHover"
        @pointerleave="hoverAt = null"
      >
        <div class="absolute h-1.5 rounded-full bg-surface-raised top-[82px] compact:top-[64px]" :style="trackStyle" />
        <div class="absolute top-[98px] compact:top-[78px] inset-x-0 h-3 pointer-events-none">
          <span
            v-for="tick in ticks"
            :key="tick"
            class="absolute -translate-x-1/2 text-[9.5px] text-content-muted tabular-nums"
            :style="{ left: pct(tick) }"
          >{{ formatTick(tick) }}</span>
        </div>

        <!-- Pins -->
        <div
          v-for="item in sortedItems"
          :key="item.id"
          class="absolute top-0 flex flex-col items-center"
          :class="isClip(item) ? '' : '-translate-x-1/2'"
          :style="{ left: pct(effectiveAt(item, duration)) }"
          :data-testid="`keyframe-pin-${item.id}`"
          draggable="true"
          @dragstart="onPinDragStart($event, item)"
          @dragend="onPinDragEnd"
          @click.stop="select(item)"
          @dblclick.stop="viewItem(item)"
          @contextmenu.prevent.stop="openMenu($event, item)"
        >
          <span
            class="h-3.5 text-[10px] leading-3 whitespace-nowrap tabular-nums"
            :class="problemFor(item) ? 'text-red-400' : 'text-accent-hi'"
          >{{ capLabel(item) }}</span>
          <div
            class="relative w-[72px] h-[44px] compact:w-[56px] compact:h-[34px] rounded-media overflow-hidden border bg-matte"
            :class="[
              selectedId === item.id ? 'outline outline-2 outline-offset-1 outline-selection' : '',
              problemFor(item) ? 'border-red-400' : 'border-edge-strong',
            ]"
          >
            <MediaImage
              v-if="!item.isVideo && item.mediaId"
              :media-id="item.mediaId"
              :file-hash="item.hash"
              :thumbnail="true"
              :thumbnail-size="128"
              :draggable="false"
              :enable-context-menu="false"
              container-class="w-full h-full"
              class="w-full h-full object-cover"
            />
            <AppImage
              v-else-if="thumbUrl(item)"
              :src="thumbUrl(item)"
              container-class="w-full h-full"
              img-class="w-full h-full object-cover"
            />
            <div v-if="item.isVideo" class="absolute bottom-0.5 right-0.5 w-3.5 h-3.5 rounded-sm bg-black/60 flex items-center justify-center pointer-events-none">
              <svg viewBox="0 0 24 24" fill="currentColor" class="w-2 h-2 text-white"><polygon points="6 3 20 12 6 21 6 3" /></svg>
            </div>
          </div>
          <div class="w-0.5 h-[24px] compact:h-[16px]" :class="problemFor(item) ? 'bg-red-400' : 'bg-accent-hi'" />
        </div>

        <!-- Clip spans (and their sound) on the track -->
        <template v-for="item in sortedItems" :key="`span-${item.id}`">
          <div
            v-if="isClip(item)"
            class="absolute h-2.5 rounded-sm border border-accent-hi bg-accent-hi/25 pointer-events-none top-[80px] compact:top-[62px]"
            :style="{ left: pct(effectiveAt(item, duration)), width: spanWidth(item.length!) }"
          >
            <div
              v-if="item.sound"
              class="absolute left-0 right-0 top-[11px] h-2"
              style="background: repeating-linear-gradient(90deg, rgb(var(--color-accent-hi-rgb) / .95) 0 2px, transparent 2px 4px)"
            />
          </div>
        </template>

        <!-- Drop / add indicator -->
        <template v-if="indicatorAt !== null">
          <span class="absolute top-0 -translate-x-1/2 text-[10px] text-accent-hi tabular-nums pointer-events-none" :style="{ left: pct(indicatorAt) }">
            {{ formatTime(indicatorAt) }}
          </span>
          <div class="absolute top-[14px] h-[70px] compact:h-[52px] border-l-2 border-dashed border-accent-hi pointer-events-none" :style="{ left: pct(indicatorAt) }" />
        </template>
        <div ref="anchorRef" class="absolute top-[40px] w-px h-px pointer-events-none" :style="{ left: pct(popoverAt ?? 0) }" />
      </div>

      <!-- Frame / clip panel for the selected keyframe -->
      <div
        v-if="selected"
        class="mt-2 pt-2 border-t border-edge-subtle flex flex-wrap gap-3"
        data-testid="keyframe-panel"
      >
        <div class="w-[168px] flex-none">
          <div class="relative w-full aspect-video rounded-media overflow-hidden bg-matte cursor-zoom-in" @click="viewItem(selected)">
            <video
              v-if="selected.isVideo && videoUrl(selected)"
              :ref="setPreviewVideo"
              :src="videoUrl(selected)"
              class="w-full h-full object-contain"
              muted
              playsinline
              preload="auto"
              @loadedmetadata="seekPreview"
            />
            <MediaImage
              v-else-if="selected.mediaId"
              :media-id="selected.mediaId"
              :file-hash="selected.hash"
              :thumbnail="true"
              :draggable="false"
              container-class="w-full h-full"
              class="w-full h-full object-contain"
            />
          </div>
          <div class="mt-1 flex items-center gap-2 text-[11px] text-content-tertiary">
            <span class="flex-1 truncate">{{ formatTime(effectiveAt(selected, duration)) }}<template v-if="problemFor(selected)"> · <span class="text-red-400">{{ problemFor(selected) }}</span></template></span>
            <button class="text-content-muted hover:text-content-secondary px-1" title="More" @click.stop="openMenu($event, selected)">⋯</button>
          </div>
        </div>

        <div v-if="selected.isVideo" class="flex-1 min-w-[260px] space-y-1.5">
          <div class="flex items-center gap-2">
            <SegmentedControl
              v-if="lengths.length"
              :model-value="isClip(selected) ? 'clip' : 'frame'"
              :options="[{ label: 'Frame', value: 'frame' }, { label: 'Clip', value: 'clip' }]"
              aria-label="Frame or clip"
              @update:model-value="setMode"
            />
            <span class="flex-1" />
            <span class="text-[10px] font-mono text-accent-hi tabular-nums">{{ sourceReadout(selected) }}</span>
          </div>
          <div
            class="relative w-full rounded-md overflow-hidden border border-edge-subtle bg-black/30 cursor-pointer select-none touch-none"
            style="min-height: 38px"
            @pointerdown="onScrubDown"
            @pointermove="onScrubMove"
            @pointerup="onScrubUp"
            @pointercancel="scrubbing = false"
            @dragstart.prevent
          >
            <img
              v-if="stripUrl(selected)"
              :src="stripUrl(selected)"
              class="block w-full h-auto pointer-events-none"
              draggable="false"
            />
            <div
              v-if="isClip(selected)"
              class="absolute top-0 bottom-0 border-2 border-accent-hi rounded-[3px] bg-accent-hi/10 pointer-events-none"
              :style="{ left: srcPct(selected.from || 0), width: srcPct(selected.length || 0) }"
            />
            <div class="absolute top-0 bottom-0 w-0.5 bg-accent-hi pointer-events-none" :style="{ left: srcPct(selected.from || 0) }">
              <div class="absolute -top-[3px] left-1/2 -translate-x-1/2 w-2.5 h-2.5 rounded-full bg-accent-hi" />
            </div>
          </div>
          <div class="flex w-full rounded-md border border-edge-subtle overflow-hidden">
            <button class="flex-shrink-0 w-9 flex items-center justify-center py-1 border-r border-edge-subtle text-content-muted hover:bg-overlay-medium hover:text-content" title="Previous frame" @click="step(-1)">
              <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.5 5 7.5 10l5 5"/></svg>
            </button>
            <template v-if="isClip(selected)">
              <button
                v-for="len in lengths"
                :key="len"
                class="flex-1 py-1 text-[11px] border-r border-edge-subtle tabular-nums"
                :class="Math.abs((selected.length || 0) - len) < 1e-3 ? 'bg-accent/15 text-accent-hi font-medium' : 'text-content-muted hover:bg-overlay-medium'"
                @click="setLength(len)"
              >{{ len.toFixed(1) }} s</button>
            </template>
            <template v-else>
              <button
                v-for="pos in (['first', 'middle', 'last'] as const)"
                :key="pos"
                class="flex-1 py-1 text-[11px] capitalize border-r border-edge-subtle text-content-muted hover:bg-overlay-medium"
                @click="setFramePosition(pos)"
              >{{ pos }}</button>
            </template>
            <button class="flex-shrink-0 w-9 flex items-center justify-center py-1 text-content-muted hover:bg-overlay-medium hover:text-content" title="Next frame" @click="step(1)">
              <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M7.5 5l5 5-5 5"/></svg>
            </button>
          </div>
          <label v-if="isClip(selected) && config.sound" class="inline-flex items-center gap-1.5 text-[11.5px] text-content-secondary cursor-pointer pt-0.5">
            <input type="checkbox" class="accent-[rgb(var(--color-accent-rgb))]" :checked="!!selected.sound" @change="patch(selected.id, { sound: ($event.target as HTMLInputElement).checked })" />
            Sound
          </label>
        </div>
      </div>
    </div>

    <MediaPickerPopover
      v-if="popoverAt !== null"
      accept="image"
      :anchor-el="anchorRef"
      @pick="onPick"
      @browse="fileInputRef?.click()"
      @close="popoverAt = null; replacingId = null"
    />
    <input ref="fileInputRef" type="file" class="hidden" accept="image/jpeg,image/png,image/webp,video/mp4,video/webm,video/quicktime,video/x-matroska" @change="onFileChosen" />

    <ActionMenu
      v-if="menu"
      :x="menu.x"
      :y="menu.y"
      :actions="menuActions"
      @close="menu = null"
    />

    <Modal :show="moveDialog !== null" size="sm" @close="moveDialog = null">
      <div v-if="moveDialog" class="p-4 space-y-3">
        <div class="text-sm font-medium text-content">Move to</div>
        <div class="flex items-center gap-2">
          <input
            ref="moveInputRef"
            v-model.number="moveDialog.value"
            type="number"
            min="0"
            :max="duration"
            step="0.1"
            class="w-28 rounded-md border border-edge bg-overlay-faint px-2 py-1 text-sm text-content tabular-nums"
            @keydown.enter="applyMove"
          />
          <span class="text-sm text-content-secondary">s</span>
        </div>
        <div class="flex justify-end gap-2">
          <Button variant="ghost" size="sm" @click="moveDialog = null">Cancel</Button>
          <Button size="sm" @click="applyMove">Move</Button>
        </div>
      </div>
    </Modal>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import axios from 'axios'
import { useMediaApi } from '../../composables/useMediaApi'
import { getCurrentProfileId } from '../../composables/useProfile'
import { getCachedPin } from '../../composables/usePinLock'
import { getApiBase } from '../../apiConfig'
import { useVideoFrameExtraction, type FramePosition } from '../../composables/useVideoFrameExtraction'
import { createDragPreview, getDroppedMediaIds, handleDragEnd as clearDragPreview } from '../../composables/useDragPreview'
import { addToast } from '../../composables/useToasts'
import { useViewport } from '../../composables/useViewport'
import { recordMediaInputUse } from '../../composables/useRecentMediaInputs'
import { getMediaType } from '../../utils/mediaTypes'
import { useOwnerProject } from '../../composables/useProjectScope'
import { appendProjectId } from '../../utils/projectScope'
import {
  clipLengths, effectiveAt, isClip, keyframesProblems, newKeyframeId,
  type KeyframeItem, type KeyframesConfig,
} from '../../utils/keyframes'
import AppImage from '../media/AppImage.vue'
import MediaImage from '../media/MediaImage.vue'
import MediaPickerPopover from './MediaPickerPopover.vue'
import ActionMenu from '../ActionMenu.vue'
import SegmentedControl from '../ui/SegmentedControl.vue'
import Modal from '../ui/Modal.vue'
import Button from '../ui/Button.vue'

const props = withDefaults(defineProps<{
  config: KeyframesConfig
  modelValue: KeyframeItem[]
  duration: number
  label?: string
}>(), { label: 'Keyframes' })

const emit = defineEmits<{
  'update:modelValue': [items: KeyframeItem[]]
  'view-media': [mediaId: number]
  'move-to-references': [mediaId: number]
}>()

const { getMediaItem, getMediaFileUrl } = useMediaApi()
const { extractFrame } = useVideoFrameExtraction()
const { isCompact } = useViewport()
const uploadProjectId = useOwnerProject()

const boxRef = ref<HTMLElement | null>(null)
const stripRef = ref<HTMLElement | null>(null)
const anchorRef = ref<HTMLElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const moveInputRef = ref<HTMLInputElement | null>(null)

const selectedId = ref<string | null>(null)
const dropAt = ref<number | null>(null)
const hoverAt = ref<number | null>(null)
const popoverAt = ref<number | null>(null)
const replacingId = ref<string | null>(null)
const menu = ref<{ x: number; y: number; item: KeyframeItem } | null>(null)
const moveDialog = ref<{ id: string; value: number } | null>(null)
let draggingPinId: string | null = null

const duration = computed(() => Math.max(0.1, Number(props.duration) || 0.1))
const items = computed(() => props.modelValue || [])
const sortedItems = computed(() => [...items.value].sort((a, b) => effectiveAt(a, duration.value) - effectiveAt(b, duration.value)))
const selected = computed(() => items.value.find(i => i.id === selectedId.value) || null)
const problems = computed(() => keyframesProblems(items.value, duration.value, props.config))
const lengths = computed(() => {
  const src = selected.value?.sourceDuration || duration.value
  return clipLengths(props.config, Math.min(src, duration.value))
})
const indicatorAt = computed(() => dropAt.value ?? (popoverAt.value === null ? hoverAt.value : popoverAt.value))

// ── Geometry: the track is inset so thumbs at 0 and the end stay inside ──
const INSET = 4.5
const trackStyle = { left: `${INSET}%`, right: `${INSET}%` }
function pct(t: number): string {
  const f = Math.min(1, Math.max(0, t / duration.value))
  return `${INSET + f * (100 - 2 * INSET)}%`
}
function spanWidth(seconds: number): string {
  return `${(seconds / duration.value) * (100 - 2 * INSET)}%`
}
function timeAt(clientX: number): number {
  const rect = stripRef.value!.getBoundingClientRect()
  const inset = rect.width * INSET / 100
  const f = (clientX - rect.left - inset) / Math.max(1, rect.width - 2 * inset)
  const t = Math.min(1, Math.max(0, f)) * duration.value
  if (props.config.positions === 'ends') return t < duration.value / 2 ? 0 : duration.value
  return Math.round(t * 10) / 10
}
const ticks = computed(() => {
  const d = duration.value
  const step = d <= 6 ? 1 : d <= 12 ? 2 : 5
  const out: number[] = []
  for (let t = 0; t < d - 1e-6; t += step) out.push(t)
  out.push(d)
  return out
})
function formatTick(t: number): string {
  return `${Number.isInteger(t) ? t : t.toFixed(1)}s`
}
function formatTime(t: number): string {
  return `${t.toFixed(1)} s`
}
function capLabel(item: KeyframeItem): string {
  if (item.anchor === 'start') return 'Start'
  if (item.anchor === 'end') return 'End'
  return formatTime(effectiveAt(item, duration.value))
}
function problemFor(item: KeyframeItem): string | null {
  return problems.value.find(p => p.id === item.id)?.reason ?? null
}
function anchorFor(t: number): 'start' | 'end' | null {
  if (t <= 0.05) return 'start'
  if (t >= duration.value - 0.05) return 'end'
  return null
}

// ── URLs ──
function withProfile(url: string): string {
  const profileId = getCurrentProfileId()
  const pin = getCachedPin(profileId)
  return `${url}&profile=${encodeURIComponent(profileId)}${pin ? `&pin=${encodeURIComponent(pin)}` : ''}`
}
function thumbUrl(item: KeyframeItem): string {
  const still = item.thumbPath || (item.isVideo ? '' : item.path)
  if (!still) return ''
  return withProfile(`${getApiBase()}/generate/reference-file?path=${encodeURIComponent(still)}`)
}
function videoUrl(item: KeyframeItem): string {
  if (item.mediaId) return getMediaFileUrl(item.mediaId)
  if (!item.sourcePath) return ''
  return withProfile(`${getApiBase()}/generate/reference-video-file?path=${encodeURIComponent(item.sourcePath)}`)
}
function stripUrl(item: KeyframeItem): string {
  if (!item.sourcePath) return ''
  return withProfile(`${getApiBase()}/generate/frame-strip?source_path=${encodeURIComponent(item.sourcePath)}&count=8&w=120`)
}

// ── Mutations ──
function commit(next: KeyframeItem[]) {
  emit('update:modelValue', next)
}
function patch(id: string, changes: Partial<KeyframeItem>) {
  commit(items.value.map(i => (i.id === id ? { ...i, ...changes } : i)))
}
function remove(id: string) {
  if (selectedId.value === id) selectedId.value = null
  commit(items.value.filter(i => i.id !== id))
}
function select(item: KeyframeItem) {
  selectedId.value = selectedId.value === item.id ? null : item.id
}
function viewItem(item: KeyframeItem) {
  if (item.mediaId) emit('view-media', item.mediaId)
}

async function addMedia(mediaId: number, at: number) {
  if (!replacingId.value && items.value.length >= props.config.max) {
    addToast(`Up to ${props.config.max} keyframes`, 'error')
    return
  }
  try {
    const media = await getMediaItem(mediaId)
    const kind = getMediaType(media)
    if (kind !== 'image' && kind !== 'video') {
      addToast('Keyframes take an image or a video', 'error')
      return
    }
    recordMediaInputUse({ mediaId: media.id, fileHash: media.file_hash, fileFormat: media.file_format, kind })
    let item: KeyframeItem = {
      id: newKeyframeId(),
      mediaId: media.id,
      hash: media.file_hash,
      path: media.file_path,
      isVideo: kind === 'video',
      at,
      anchor: anchorFor(at),
    }
    if (item.isVideo) {
      const position: FramePosition = item.anchor === 'start' ? 'last' : 'first'
      const frame = await extractFrame({ sourcePath: media.file_path, position })
      item = {
        ...item,
        sourcePath: media.file_path,
        sourceDuration: frame.duration,
        sourceFps: frame.fps,
        from: frame.time,
        path: frame.path,
        thumbPath: frame.path,
      }
    }
    if (replacingId.value) {
      const old = items.value.find(i => i.id === replacingId.value)
      item = { ...item, id: replacingId.value, at: old?.at ?? at, anchor: old?.anchor ?? null }
      commit(items.value.map(i => (i.id === item.id ? item : i)))
      replacingId.value = null
    } else {
      commit([...items.value, item])
    }
    selectedId.value = item.isVideo ? item.id : selectedId.value
  } catch (e: any) {
    console.error('Failed to add keyframe:', e)
    addToast(e?.response?.data?.detail || e?.message || "Couldn't add that keyframe.", 'error')
  }
}

// ── Strip interactions ──
function onStripClick(event: MouseEvent) {
  selectedId.value = null
  popoverAt.value = timeAt(event.clientX)
}
function onStripHover(event: PointerEvent) {
  if (event.pointerType === 'mouse' && !(event.target as HTMLElement).closest('[draggable="true"]')) {
    hoverAt.value = timeAt(event.clientX)
  } else {
    hoverAt.value = null
  }
}
async function onPick(mediaId: number) {
  const at = popoverAt.value ?? 0
  popoverAt.value = null
  await addMedia(mediaId, at)
}
async function onFileChosen(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  const at = popoverAt.value ?? 0
  popoverAt.value = null
  if (!file) return
  const isVideo = file.type.startsWith('video/')
  const fd = new FormData()
  fd.append('file', file)
  appendProjectId(fd, uploadProjectId.value)
  try {
    const { data } = await axios.post(isVideo ? '/api/generate/upload-reference-video' : '/api/generate/upload-reference', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    if (typeof data?.media_id === 'number') await addMedia(data.media_id, at)
  } catch (e: any) {
    addToast(e?.response?.data?.detail || e?.message || "Couldn't upload that file.", 'error')
  }
}

// ── Drag and drop: references, results, and moving pins ──
function acceptsDrag(event: DragEvent): boolean {
  const types = Array.from(event.dataTransfer?.types || [])
  return draggingPinId !== null || types.includes('application/x-media-id') || types.includes('application/x-media-ids')
}
function onDragOver(event: DragEvent) {
  if (!acceptsDrag(event) || !stripRef.value) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = draggingPinId ? 'move' : 'copy'
  dropAt.value = timeAt(event.clientX)
}
function onDragLeave(event: DragEvent) {
  if (!boxRef.value?.contains(event.relatedTarget as Node)) dropAt.value = null
}
async function onDrop(event: DragEvent) {
  if (!acceptsDrag(event)) return
  event.preventDefault()
  const at = timeAt(event.clientX)
  dropAt.value = null
  if (draggingPinId) {
    patch(draggingPinId, { at, anchor: anchorFor(at) })
    draggingPinId = null
    return
  }
  const [mediaId] = getDroppedMediaIds(event.dataTransfer)
  if (mediaId) await addMedia(mediaId, at)
}
function onPinDragStart(event: DragEvent, item: KeyframeItem) {
  draggingPinId = item.id
  // Carries the source media id, so dropping a pin on a reference picker adds it there.
  createDragPreview(event, item.isVideo ? thumbUrl(item) : (item.mediaId ? getMediaFileUrl(item.mediaId) : thumbUrl(item)), item.mediaId, undefined, item.isVideo)
}
function onPinDragEnd() {
  draggingPinId = null
  dropAt.value = null
  clearDragPreview()
}

// ── Frame / clip panel ──
let previewVideo: HTMLVideoElement | null = null
function setPreviewVideo(el: any) {
  previewVideo = el as HTMLVideoElement | null
}
function seekPreview() {
  if (previewVideo && selected.value) previewVideo.currentTime = selected.value.from || 0
}
watch(() => selected.value?.from, () => seekPreview())

function sourceDuration(item: KeyframeItem): number {
  return item.sourceDuration || previewVideo?.duration || 0
}
function srcPct(t: number): string {
  const d = sourceDuration(selected.value!)
  return d > 0 ? `${Math.min(100, Math.max(0, (t / d) * 100))}%` : '0%'
}
function sourceReadout(item: KeyframeItem): string {
  const from = item.from || 0
  return isClip(item) ? `${from.toFixed(2)} – ${(from + item.length!).toFixed(2)} s` : `${from.toFixed(2)} s`
}

let commitTimer: ReturnType<typeof setTimeout> | null = null
function scheduleFrameCommit(id: string, from: number) {
  if (commitTimer) clearTimeout(commitTimer)
  commitTimer = setTimeout(() => commitFrame(id, 'custom', from), 280)
}
async function commitFrame(id: string, position: FramePosition, timeSeconds?: number) {
  const item = items.value.find(i => i.id === id)
  if (!item?.sourcePath) return
  try {
    const frame = await extractFrame({ sourcePath: item.sourcePath, position, timeSeconds })
    const clip = isClip(item)
    patch(id, {
      from: frame.time,
      thumbPath: frame.path,
      sourceDuration: frame.duration || item.sourceDuration,
      sourceFps: frame.fps || item.sourceFps,
      ...(clip ? {} : { path: frame.path }),
    })
  } catch (e: any) {
    addToast(e?.response?.data?.detail || e?.message || "Couldn't pick that frame.", 'error')
  }
}
function setFrom(t: number) {
  const item = selected.value
  if (!item) return
  const d = sourceDuration(item)
  const max = Math.max(0, d - (isClip(item) ? item.length! : 0))
  const from = Math.min(max || t, Math.max(0, t))
  patch(item.id, { from })
  scheduleFrameCommit(item.id, from)
}
function step(direction: number) {
  const item = selected.value
  if (!item) return
  const fps = item.sourceFps || props.config.fps
  setFrom((item.from || 0) + direction / fps)
}
function setFramePosition(pos: FramePosition) {
  if (selected.value) commitFrame(selected.value.id, pos)
}
function setMode(mode: string | number) {
  const item = selected.value
  if (!item) return
  if (mode === 'clip') {
    const length = lengths.value[1] ?? lengths.value[0]
    if (!length) return
    const d = sourceDuration(item)
    const from = d ? Math.min(item.from || 0, Math.max(0, d - length)) : (item.from || 0)
    patch(item.id, { length, from, path: item.sourcePath || item.path, sound: props.config.sound })
  } else {
    patch(item.id, { length: undefined, sound: undefined, path: item.thumbPath || item.path })
    commitFrame(item.id, 'custom', item.from || 0)
  }
}
function setLength(len: number) {
  const item = selected.value
  if (!item) return
  const d = sourceDuration(item)
  patch(item.id, { length: len, from: d ? Math.min(item.from || 0, Math.max(0, d - len)) : item.from })
}

const scrubbing = ref(false)
function scrubTime(event: PointerEvent): number {
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const f = Math.min(1, Math.max(0, (event.clientX - rect.left) / Math.max(1, rect.width)))
  return f * sourceDuration(selected.value!)
}
function onScrubDown(event: PointerEvent) {
  scrubbing.value = true
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
  setFrom(scrubTime(event))
}
function onScrubMove(event: PointerEvent) {
  if (scrubbing.value) setFrom(scrubTime(event))
}
function onScrubUp(event: PointerEvent) {
  if (!scrubbing.value) return
  scrubbing.value = false
  setFrom(scrubTime(event))
}

// Clips restored from a past job have no still yet; grab one for the strip.
const thumbsRequested = new Set<string>()
watch(items, (list) => {
  for (const item of list) {
    if (item.isVideo && !item.thumbPath && item.sourcePath && !thumbsRequested.has(item.id)) {
      thumbsRequested.add(item.id)
      commitFrame(item.id, 'custom', item.from || 0)
    }
  }
}, { immediate: true })

// ── Menu ──
function openMenu(event: MouseEvent, item: KeyframeItem) {
  menu.value = { x: event.clientX, y: event.clientY, item }
}
const menuActions = computed(() => {
  const item = menu.value?.item
  if (!item) return []
  const actions: any[] = [
    { id: 'move', label: 'Move to…', action: () => openMove(item) },
    { id: 'start', label: 'Snap to Start', action: () => patch(item.id, { at: 0, anchor: 'start' }) },
    { id: 'end', label: 'Snap to End', action: () => patch(item.id, { at: duration.value, anchor: 'end' }) },
    { id: 'change', label: 'Change frame…', action: () => { replacingId.value = item.id; popoverAt.value = effectiveAt(item, duration.value) } },
  ]
  // Touch has no drag, so the move to references lives here.
  if (isCompact.value && item.mediaId) {
    actions.push({ id: 'to-refs', label: 'Move to Reference Images', action: () => { emit('move-to-references', item.mediaId!); remove(item.id) } })
  }
  actions.push({ id: 'divider', divider: true }, { id: 'remove', label: 'Remove', danger: true, action: () => remove(item.id) })
  return actions
})
function openMove(item: KeyframeItem) {
  moveDialog.value = { id: item.id, value: Math.round(effectiveAt(item, duration.value) * 10) / 10 }
  nextTick(() => moveInputRef.value?.select())
}
function applyMove() {
  if (!moveDialog.value) return
  const at = Math.min(duration.value, Math.max(0, Number(moveDialog.value.value) || 0))
  patch(moveDialog.value.id, { at, anchor: anchorFor(at) })
  moveDialog.value = null
}

defineExpose({ addMedia })
</script>
