<template>
  <!-- Shared HITL action cell. The same square media frame + footer
       chrome serves every media-bearing HITL action (approve, select)
       so the family reads as one widget with mode-specific footers. -->
  <div
    class="group relative rounded-md border border-edge-subtle overflow-hidden flex flex-col"
    :class="[clickable ? 'cursor-pointer' : '', busy ? 'opacity-60 pointer-events-none' : '']"
    :role="clickable ? 'button' : undefined"
    :tabindex="clickable ? 0 : undefined"
    @mousedown="onCardMouseDown"
    @click="onCardClick"
    @keydown.enter.prevent="onCardClick"
    @keydown.space.prevent="onCardClick"
  >
    <div
      class="pointer-events-none absolute inset-0 z-10 rounded-md border transition-colors"
      :class="frameOverlayClass"
    />
    <div
      class="relative aspect-square w-full bg-overlay-subtle/40"
      v-memo="[mediaId, mediaUrl, label]"
    >
      <FlowMediaTile
        v-if="mediaId"
        :media-id="mediaId"
        :media-ids="mediaIdList"
        :thumbnail="true"
        :thumbnail-size="160"
        :contain="true"
        container-class="w-full h-full"
      />
      <img
        v-else-if="mediaUrl"
        :src="mediaUrl"
        :alt="label || ''"
        class="absolute inset-0 w-full h-full object-contain"
        referrerpolicy="no-referrer"
        loading="lazy"
      />
      <div
        v-else
        class="absolute inset-0 flex items-center justify-center"
      >
        <span
          v-if="state === 'awaiting' || state === 'pending'"
          class="w-4 h-4 border-2 border-content-muted/60 border-t-transparent rounded-full animate-spin"
        />
        <svg
          v-else-if="state === 'failed'"
          class="w-5 h-5 text-red-400"
          fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
        <span
          v-else
          class="text-[10px] text-content-muted text-center px-2 line-clamp-2"
        >{{ label || '' }}</span>
      </div>

    </div>

    <div
      class="border-t border-edge-subtle bg-overlay-subtle/30 flex items-center px-1.5 py-1 min-h-[30px] gap-1.5"
    >
      <!-- Approve mode footer. Awaiting state pulls the eye: the
           Approve action gets the bright solid-blue treatment so the
           user knows where to focus, paired with a quiet Replace.
           Approved state collapses to a single full-width muted-tint
           "Approved" button — already-done, click to undo. The flip
           in chrome (solid → tint) signals "action needed" vs
           "settled" without color noise across cells. -->
      <template v-if="mode === 'approve'">
        <template v-if="state === 'awaiting'">
          <button
            type="button"
            aria-pressed="false"
            class="flex-1 min-w-0 bg-blue-500 text-white border border-blue-500 text-[10px] font-medium px-1 py-0.5 rounded hover:bg-blue-600 transition-colors truncate"
            title="Approve"
            @click.stop="$emit('approve', true)"
          >Approve</button>
          <button
            type="button"
            class="flex-1 min-w-0 bg-overlay-subtle border border-edge-subtle text-content-secondary text-[10px] font-medium px-1 py-0.5 rounded hover:bg-overlay-hover hover:text-content transition-colors truncate"
            title="Replace — regenerates this candidate"
            @click.stop="$emit('approve', false)"
          >Replace</button>
        </template>
        <button
          v-else-if="state === 'approved'"
          type="button"
          aria-pressed="true"
          class="flex-1 min-w-0 bg-blue-500/15 border border-blue-500/50 text-blue-400 text-[10px] font-medium px-1 py-0.5 rounded hover:bg-blue-500/25 transition-colors truncate"
          title="Click to unapprove"
          @click.stop="$emit('unapprove')"
        >Approved</button>
        <span
          v-else-if="state === 'pending'"
          class="text-[10px] text-content-muted truncate"
        >Waiting…</span>
        <button
          v-else-if="state === 'failed'"
          type="button"
          class="text-[10px] px-1.5 py-0.5 rounded bg-overlay-subtle border border-edge-subtle text-content-muted hover:text-content hover:bg-overlay-hover transition-colors"
          @click.stop="$emit('retry')"
        >Retry ↻</button>
      </template>

      <!-- Single-pick select. One click commits the pick. -->
      <template v-else-if="mode === 'select-single'">
        <button
          type="button"
          :aria-pressed="state === 'selected'"
          class="flex-1 min-w-0 text-[10px] font-medium px-1 py-0.5 rounded transition-colors truncate"
          :class="state === 'selected'
            ? 'bg-blue-500/15 border border-blue-500/50 text-blue-400 hover:bg-blue-500/25'
            : 'bg-blue-500/15 border border-blue-500/50 text-blue-400 hover:bg-blue-500/25'"
          @mousedown.prevent
          @click.stop="$emit('select')"
        >{{ state === 'selected' ? 'Selected' : 'Use This' }}</button>
      </template>

      <!-- Multi-pick select. Click to toggle membership. Selected state
           mirrors the approve card's settled tinted treatment. -->
      <template v-else-if="mode === 'select-multi'">
        <button
          type="button"
          :aria-pressed="state === 'selected'"
          class="flex-1 min-w-0 text-[10px] font-medium px-1 py-0.5 rounded transition-colors truncate"
          :class="state === 'selected'
            ? 'bg-blue-500/15 border border-blue-500/50 text-blue-400 hover:bg-blue-500/25'
            : 'bg-blue-500/15 border border-blue-500/50 text-blue-400 hover:bg-blue-500/25'"
          @mousedown.prevent
          @click.stop="$emit('select')"
        >{{ state === 'selected' ? 'Selected' : 'Pick' }}</button>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import FlowMediaTile from './FlowMediaTile.vue'

type Mode = 'approve' | 'select-single' | 'select-multi'
type State = 'awaiting' | 'approved' | 'selected' | 'idle' | 'pending' | 'failed'

interface Props {
  mediaId: number | null
  mediaUrl?: string | null
  mode: Mode
  state: State
  label?: string
  // Keyboard-focus indicator. The parent TaskCard tracks which select
  // candidate is keyboard-focused and passes the matching cell true,
  // so arrow-key nav stays visible through the new chrome.
  focused?: boolean
  busy?: boolean
}
const props = withDefaults(defineProps<Props>(), {
  mediaUrl: null,
  label: '',
  focused: false,
  busy: false,
})
const emit = defineEmits<{
  // Approve mode: arg=true means approve, arg=false means replace.
  (e: 'approve', approved: boolean): void
  // Approve mode: toggle off an already-approved cell.
  (e: 'unapprove'): void
  // Select modes: the user clicked the cell to pick / unpick it.
  (e: 'select'): void
  // Failed state: retry the upstream.
  (e: 'retry'): void
}>()

const mediaIdList = computed(() => props.mediaId ? [props.mediaId] : [])

const frameOverlayClass = computed(() => {
  if (props.state === 'failed') return 'border-red-500/50'
  if (props.state === 'selected') return 'border-blue-500 shadow-[inset_0_0_0_1px_rgba(59,130,246,0.45)]'
  if (props.focused) return 'border-blue-400/70 shadow-[inset_0_0_0_1px_rgba(96,165,250,0.35)]'
  return 'border-transparent group-hover:border-edge-strong'
})

// Whole-card click is wired only in select-multi (matches existing select
// behavior — clicking anywhere toggles), since approve and select-single
// have unambiguous footer buttons for their action.
const clickable = computed(() => props.mode === 'select-multi')
function onCardClick() {
  if (clickable.value) emit('select')
}

function onCardMouseDown(event: MouseEvent) {
  if (clickable.value) event.preventDefault()
}
</script>
