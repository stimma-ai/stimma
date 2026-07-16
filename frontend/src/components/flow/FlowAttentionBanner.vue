<template>
  <section
    v-if="visible"
    :class="[
      'border rounded-lg px-3 py-2 text-sm',
      agentBusy
        ? 'bg-blue-500/10 border-blue-500/40 text-blue-400'
        : 'bg-red-500/10 border-red-500/40 text-red-400',
    ]"
  >
    <div class="flex items-start gap-2">
      <span
        v-if="agentBusy"
        class="w-3.5 h-3.5 flex-shrink-0 mt-1 border-2 border-blue-400 border-t-transparent rounded-full animate-spin"
      />
      <svg v-else class="w-4 h-4 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
      </svg>
      <div class="flex-1 min-w-0">
        <template v-if="agentBusy">
          <div class="font-semibold">The assistant is working on this flow.</div>
          <div class="mt-1 text-blue-300/90">This may take a moment.</div>
        </template>
        <template v-else>
          <div class="font-semibold">{{ title }}</div>
          <div class="mt-1 text-red-300/90">{{ body }}</div>
          <div class="mt-2 flex flex-wrap items-center gap-1.5">
            <button
              v-if="error"
              class="text-[12px] px-2.5 py-1 rounded bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
              :disabled="fixing"
              @click="$emit('fix')"
            >{{ fixing ? 'Sending…' : 'Ask the assistant to fix it' }}</button>
            <button
              v-else-if="blocked"
              class="text-[12px] px-2.5 py-1 rounded bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
              :disabled="fixing"
              @click="$emit('unblock')"
            >{{ fixing ? 'Sending…' : 'Ask the assistant' }}</button>
            <button
              v-if="blocked && canPause"
              class="text-[12px] px-2 py-1 rounded bg-overlay-subtle border border-edge text-content hover:bg-overlay-hover"
              @click="$emit('pause')"
            >Pause</button>
          </div>
        </template>
      </div>
    </div>
    <div v-if="devMode && error" class="mt-2 rounded border border-amber-500/40 bg-overlay-light text-[11px] font-mono text-content-secondary">
      <div class="flex items-center gap-2 px-2.5 py-1.5 border-b border-amber-500/30">
        <span class="text-[9px] font-bold uppercase tracking-wider text-amber-600 dark:text-amber-400 bg-amber-500/15 px-1.5 py-0.5 rounded-sm">Dev</span>
        <span class="text-content-muted">raw build error</span>
        <span class="flex-1" />
        <span v-if="error.category" class="uppercase tracking-wider text-content-muted">{{ error.category }}</span>
      </div>
      <pre class="px-2.5 py-2 whitespace-pre-wrap break-words select-text">{{ error.message }}</pre>
      <div v-if="error.suggestion" class="px-2.5 pb-2 text-content-muted">hint: {{ error.suggestion }}</div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  error: {
    category: string
    message: string
    suggestion?: string | null
    failedCount?: number
  } | null
  errorSource?: 'build' | 'runtime'
  blocked?: boolean
  agentBusy: boolean
  fixing: boolean
  devMode: boolean
  canPause?: boolean
}>()

defineEmits<{
  (e: 'fix'): void
  (e: 'unblock'): void
  (e: 'pause'): void
}>()

const visible = computed(() => !!props.error || !!props.blocked || props.agentBusy)

const title = computed(() => {
  if (props.error && props.errorSource === 'runtime') {
    const count = props.error.failedCount || 0
    return count > 1 ? `${count} steps failed.` : 'A step failed.'
  }
  if (props.blocked && !props.error) return 'This flow is blocked by errors.'
  return 'This flow has build errors.'
})

const body = computed(() => {
  if (props.error && props.errorSource === 'runtime') {
    return props.error.message || 'Ask the assistant to inspect the failed step and update the flow.'
  }
  if (props.blocked && !props.error) {
    return "It can't continue until something changes. Ask the assistant for help or pause the flow."
  }
  return "It can't run until the flow is fixed."
})
</script>
