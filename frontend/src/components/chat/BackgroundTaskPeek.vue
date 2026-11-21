<template>
  <!-- What a running task has made so far, newest first. Nothing here is
       saved: finished results are shown where the task left them. -->
  <div class="pb-2">
    <div
      v-if="items.length"
      class="flex gap-2 overflow-x-auto px-3 pb-1 custom-scrollbar"
      data-testid="background-task-peek"
    >
      <div
        v-for="item in items"
        :key="item.item"
        class="w-28 flex-none sm:w-32"
        :title="item.prompt || undefined"
      >
        <div class="relative aspect-[4/3] w-full overflow-hidden rounded-media bg-matte">
          <OutputImage
            v-if="item.state === 'done' && item.media_id"
            :row="outputRow(item)"
            fill
            playable
            bare
            hide-type-chip
            :fit-thumbnail="256"
            class="!rounded-media !bg-matte"
            @view-image="(id: number) => emit('view', id)"
          />
          <template v-else-if="item.state === 'failed'">
            <div class="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-red-500/10 px-2 text-center">
              <ExclamationCircleIcon class="h-5 w-5 text-red-500" />
              <span class="line-clamp-3 text-[10px] leading-tight text-red-400">{{ errorText(item.error) }}</span>
            </div>
          </template>
          <template v-else>
            <!-- Still to come: its start frame, dimmed, under the pulse dot. -->
            <MediaImage
              v-if="ghost(item)"
              :media-id="ghost(item)!"
              :thumbnail="true"
              :thumbnail-size="256"
              container-class="absolute inset-0 h-full w-full"
              img-class="h-full w-full object-cover opacity-30"
            />
            <span class="absolute inset-0 flex items-center justify-center">
              <span
                class="h-1.5 w-1.5 rounded-full"
                :class="item.state === 'generating' ? 'animate-pulse-soft bg-blue-500' : item.state === 'cancelled' ? 'bg-zinc-600' : 'bg-zinc-500'"
              />
            </span>
          </template>
          <!-- What it starts from: start frame, pinned clip, references. -->
          <div v-if="item.inputs?.length" class="absolute bottom-1 left-1 z-chrome flex items-center gap-0.5">
            <button
              v-for="input in item.inputs.slice(0, 3)"
              :key="input.media_id"
              type="button"
              class="h-5 w-5 flex-none overflow-hidden rounded-media bg-matte ring-1 ring-black/40 hover:ring-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
              :title="roleText(input.role)"
              :aria-label="roleText(input.role)"
              @click.stop="emit('view', input.media_id)"
            >
              <MediaImage
                :media-id="input.media_id"
                :thumbnail="true"
                :thumbnail-size="64"
                container-class="h-full w-full"
                img-class="h-full w-full object-cover"
              />
            </button>
            <span v-if="item.inputs.length > 3" class="rounded-sm bg-black/60 px-1 text-[10px] text-white">+{{ item.inputs.length - 3 }}</span>
          </div>
        </div>
        <p class="mt-1 h-4 truncate text-[11px] leading-4" :class="item.state === 'failed' ? 'text-red-400' : 'text-content-tertiary'">
          {{ stateText(item) }}
        </p>
      </div>
    </div>
    <p v-else class="px-3 pb-1 text-xs text-content-muted">{{ loaded ? 'Nothing made yet' : 'Loading…' }}</p>
    <p v-if="hidden > 0" class="px-3 text-[11px] text-content-muted">and {{ hidden }} earlier</p>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ExclamationCircleIcon } from '@heroicons/vue/24/outline'
import OutputImage from './OutputImage.vue'
import { MediaImage } from '../media'
import { shortDuration } from '../../utils/backgroundTaskLine'

interface PeekInput { media_id: number; role: string }
interface PeekItem {
  item: number
  state: string
  prompt?: string
  media_id?: number
  file_format?: string
  error?: string
  elapsed_s?: number
  generating_for_s?: number
  inputs?: PeekInput[]
}

const props = defineProps<{
  chatId: number
  taskId: string
  /** Changes whenever the task's counts do: time to look again. */
  version: string
}>()
const emit = defineEmits<{ view: [mediaId: number] }>()

const items = ref<PeekItem[]>([])
const total = ref(0)
const loaded = ref(false)
const fetchedAt = ref(Date.now())
const now = ref(Date.now())
const hidden = computed(() => Math.max(0, total.value - items.value.length))

let request = 0
async function load() {
  const mine = ++request
  try {
    const response = await fetch(`/api/chats/${props.chatId}/background/${encodeURIComponent(props.taskId)}/items`)
    if (!response.ok || mine !== request) return
    const data = await response.json()
    items.value = data.items || []
    total.value = data.total_items || 0
    fetchedAt.value = Date.now()
  } catch (error) {
    console.warn('Could not load background task items', error)
  } finally {
    if (mine === request) loaded.value = true
  }
}

onMounted(load)
watch(() => [props.taskId, props.version], load)
// Generating times move on between updates.
const tick = setInterval(() => { now.value = Date.now() }, 5_000)
onBeforeUnmount(() => clearInterval(tick))

function outputRow(item: PeekItem) {
  return {
    id: `peek_${props.taskId}_${item.item}`,
    output: { status: 'complete', media_id: item.media_id, file_format: item.file_format },
  }
}

function ghost(item: PeekItem): number | null {
  return item.inputs?.find(i => i.role === 'start' || i.role === 'pinned')?.media_id ?? null
}

function stateText(item: PeekItem): string {
  const since = (now.value - fetchedAt.value) / 1000
  switch (item.state) {
    case 'done': return ''
    case 'failed': return 'Failed'
    case 'cancelled': return 'Stopped'
    case 'generating': return `Generating · ${shortDuration((item.generating_for_s ?? item.elapsed_s ?? 0) + since)}`
    case 'queued': return 'Queued'
    default: return 'Starting'
  }
}

const ROLES: Record<string, string> = { start: 'Start frame', pinned: 'Pinned', input: 'Reference' }
function roleText(role: string): string {
  return ROLES[role] ?? 'Input'
}

// "RuntimeError: out of memory" reads as "out of memory".
function errorText(error?: string): string {
  if (!error) return 'Failed'
  return error.replace(/^[A-Za-z_][\w.]*(Error|Exception):\s*/, '')
}
</script>
