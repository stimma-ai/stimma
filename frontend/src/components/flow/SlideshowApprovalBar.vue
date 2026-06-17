<template>
  <div
    class="absolute left-1/2 z-[10001] bg-surface backdrop-blur-md border border-edge-subtle rounded-xl shadow-[0_8px_32px_rgba(0,0,0,0.3),0_4px_8px_rgba(0,0,0,0.2)]"
    :style="{ bottom: `${bottomOffset}px`, transform: 'translateX(-50%)' }"
  >
    <div class="flex items-center gap-3 px-4 py-2.5">
      <span class="text-[10px] font-medium uppercase tracking-wider text-content-muted flex-shrink-0">
        Approval
      </span>
      <span class="h-4 w-px bg-edge-subtle" />

      <template v-if="state === 'awaiting'">
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="bg-blue-500 text-white border border-blue-500 text-[11px] font-medium px-3 py-1 rounded hover:bg-blue-600 transition-colors flex items-center gap-2"
            title="Approve (↑ or W)"
            @click.stop="$emit('approve')"
          >
            <span>Approve</span>
            <kbd class="text-[9px] font-mono bg-white/20 px-1 py-px rounded">↑/W</kbd>
          </button>
          <button
            type="button"
            class="bg-overlay-subtle border border-edge-subtle text-content-secondary text-[11px] font-medium px-3 py-1 rounded hover:bg-overlay-hover hover:text-content transition-colors flex items-center gap-2"
            title="Replace — regenerates this candidate (↓ or S)"
            @click.stop="$emit('reject')"
          >
            <span>Replace</span>
            <kbd class="text-[9px] font-mono bg-white/10 px-1 py-px rounded">↓/S</kbd>
          </button>
        </div>
      </template>

      <button
        v-else-if="state === 'approved'"
        type="button"
        class="bg-blue-500/15 border border-blue-500/50 text-blue-400 text-[11px] font-medium px-3 py-1 rounded hover:bg-blue-500/25 transition-colors flex items-center gap-1.5"
        title="Click to unapprove"
        @click.stop="$emit('unapprove')"
      >
        <svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          <path fill-rule="evenodd" clip-rule="evenodd" d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10zm4.03-12.97a.75.75 0 00-1.06-1.06l-4.72 4.72-2.22-2.22a.75.75 0 10-1.06 1.06l2.75 2.75a.75.75 0 001.06 0l5.25-5.25z" />
        </svg>
        <span>Approved</span>
      </button>

      <span v-else-if="state === 'pending'" class="flex items-center gap-2 text-[11px] text-content-muted">
        <span class="w-3 h-3 border-2 border-content-muted/60 border-t-transparent rounded-full animate-spin" />
        <span>Waiting…</span>
      </span>

      <span v-else-if="state === 'failed'" class="flex items-center gap-1.5 text-[11px] text-red-400">
        <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
        <span>Approval failed</span>
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
interface Props {
  state: 'awaiting' | 'approved' | 'pending' | 'failed'
  bottomOffset?: number
}
withDefaults(defineProps<Props>(), { bottomOffset: 24 })
defineEmits<{
  (e: 'approve'): void
  (e: 'reject'): void
  (e: 'unapprove'): void
}>()
</script>
