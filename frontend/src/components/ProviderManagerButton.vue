<template>
  <!-- One entry point per tool provider that advertises a management UI
       (STP presentation.management_url). Sits left of the profile picker.
       Click → popover with the provider's own manager, proxied through the
       local backend. Spinner = management work in progress · amber = warning ·
       red = error · dimmed icon = provider disconnected. -->
  <div v-if="managed.length" class="flex items-center gap-0.5 h-[30px] px-[3px] rounded-[7px] bg-overlay-subtle compact:h-11 compact:px-0 compact:bg-transparent compact:rounded-none">
  <div v-for="p in managed" :key="p.provider_id" class="relative provider-manager" :data-provider="p.provider_id">
    <button
      class="relative w-6 h-6 compact:w-11 compact:h-11 flex items-center justify-center rounded-[5px] compact:rounded-md transition-colors cursor-pointer border-none bg-transparent"
      :class="[
        openId === p.provider_id ? 'bg-overlay-light text-content' : 'text-content-secondary hover:bg-overlay-subtle hover:text-content',
        p.status !== 'connected' ? 'opacity-40' : '',
      ]"
      :title="titleFor(p)"
      @click.stop="toggle(p.provider_id)"
    >
      <!-- Provider-supplied icon (STP presentation.icon, a data URI) rendered
           as a CSS mask so it takes currentColor and follows the theme. The
           bundled ComfyUI mark is only a fallback for providers that send none. -->
      <span v-if="p.icon" class="block w-[15px] h-[15px] compact:w-[22px] compact:h-[22px]" :style="iconMaskStyle(p.icon)" aria-hidden="true"></span>
      <ComfyUIIcon v-else-if="isComfy(p)" class="w-[15px] h-[15px] compact:w-[22px] compact:h-[22px]" />
      <span v-else class="w-[15px] h-[15px] compact:w-[22px] compact:h-[22px] rounded-full bg-overlay-light"></span>
      <Spinner
        v-if="p.status === 'connected' && p.state === 'in_progress'"
        size="sm"
        hue="border-t-content-secondary"
        class="absolute -top-0.5 -right-0.5 !w-[8px] !h-[8px] !border-[1.5px] [filter:drop-shadow(0_1px_1px_rgba(0,0,0,0.55))]"
      />
      <span
        v-if="p.status === 'connected' && p.state !== 'in_progress' && dotClassFor(p)"
        class="absolute top-px right-px w-[7px] h-[7px] rounded-full ring-2 ring-surface"
        :class="dotClassFor(p)"
      ></span>
    </button>

    <!-- First-connect hint (once). Not on phones: there is no room to hang it. -->
    <div
      v-if="!isCompact && hintFor === p.provider_id && openId !== p.provider_id"
      class="absolute top-[calc(100%+0.75rem)] right-0 w-[240px] bg-surface-raised border border-edge-subtle rounded-lg shadow-[0_8px_16px_rgba(0,0,0,0.5)] p-3 text-xs text-content-secondary z-menu"
    >
      <span class="absolute -top-[6px] right-[10px] w-[10px] h-[10px] bg-surface-raised border-l border-t border-edge-subtle rotate-45"></span>
      <div class="text-content font-medium mb-0.5">Manage {{ shortName(p) }}</div>
      <div>Set up workflows, install required models and custom nodes, and track downloads and running jobs.</div>
      <button class="mt-1.5 text-accent-hi hover:underline" @click.stop="toggle(p.provider_id)">Open {{ shortName(p) }}</button>
    </div>

    <!-- Popover on wide; on compact a full-screen sheet with its own back
         row, because a 420px panel hanging off a header icon is not a phone
         surface. -->
    <div
      v-if="openId === p.provider_id"
      class="bg-surface z-menu overflow-hidden flex flex-col absolute top-[calc(100%+0.5rem)] right-0 w-[420px] border border-edge-subtle rounded-lg shadow-[0_8px_16px_rgba(0,0,0,0.5)] compact:fixed compact:inset-0 compact:top-0 compact:w-auto compact:border-0 compact:rounded-none compact:shadow-none compact:pt-safe compact:pb-safe"
      :style="isCompact ? undefined : { height: popoverHeight }"
      @click.stop
    >
      <div v-if="isCompact" class="flex-none h-12 flex items-center gap-1 px-2 border-b border-edge-subtle">
        <button type="button" class="w-11 h-11 flex items-center justify-center rounded-md text-content-secondary border-none bg-transparent" aria-label="Back" @click="close">
          <svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="m15 6-6 6 6 6" /></svg>
        </button>
        <div class="flex-1 min-w-0 px-1">
          <div class="truncate text-[17px] font-semibold tracking-tight text-content leading-tight">{{ shortName(p) }}</div>
          <div v-if="p.status === 'connected' && p.state_summary" class="truncate text-[11px] font-mono text-content-tertiary leading-tight">{{ p.state_summary }}</div>
        </div>
      </div>
      <div v-if="p.status !== 'connected'" class="flex-1 flex flex-col items-center justify-center gap-2 p-6 text-center">
        <ComfyUIIcon v-if="isComfy(p)" class="w-6 h-6 text-content-muted" />
        <div class="text-sm text-content">{{ p.provider_name }} · {{ p.status === 'connecting' ? 'connecting' : 'not connected' }}</div>
      </div>
      <iframe
        v-else
        :ref="setFrame"
        :src="frameSrc(p)"
        class="flex-1 w-full border-0 bg-surface transition-opacity duration-150"
        :class="frameReady ? 'opacity-100' : 'opacity-0'"
        :title="`${p.provider_name} manager`"
        referrerpolicy="no-referrer"
        @load="onFrameLoad"
      ></iframe>
    </div>
  </div>
  </div>
  <span v-if="managed.length && showSeparator" class="w-px h-[18px] mx-1 bg-edge-subtle" aria-hidden="true"></span>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useProvidersApi, type Provider } from '../composables/useProvidersApi'
import { useWebSocket } from '../composables/useWebSocket'
import { useTheme } from '../composables/useTheme'
import { useViewport } from '../composables/useViewport'
import { useToasts } from '../composables/useToasts'
import { getApiBase } from '../apiConfig'
import { isComfyUIProvider } from '../utils/toolProviderBrands'
import { makeGlobalKey } from '../utils/storageKeys'
import ComfyUIIcon from './tools/ComfyUIIcon.vue'
import Spinner from './ui/Spinner.vue'

type ManagedProvider = Provider

defineProps<{ showSeparator?: boolean }>()

const { listProviders, cachedProviders, subscribeToProviderChanges } = useProvidersApi()
const { on, off } = useWebSocket()
const { resolvedTheme } = useTheme()
const { isCompact } = useViewport()
const { addToast } = useToasts()

const providers = ref<ManagedProvider[]>([])
const openId = ref<string | null>(null)
const anchor = ref<string>('')
const frameEl = ref<HTMLIFrameElement | null>(null)
function setFrame(el: unknown) { frameEl.value = (el as HTMLIFrameElement | null) }
const HINT_KEY = makeGlobalKey('providerManager', 'hintDismissed')
const hintDismissed = ref(localStorage.getItem(HINT_KEY) === '1')

const managed = computed(() => providers.value.filter(p => !!p.management_url))
const hintFor = computed(() => {
  if (hintDismissed.value) return null
  const first = managed.value.find(p => p.status === 'connected')
  return first ? first.provider_id : null
})
const MAX_H = 640
const MIN_H = 220
const DEFAULT_H = 300
// Height reported by the embedded manager; remembered per provider so
// reopening lands at the right size immediately (no resize hitch).
const wantedHeight = ref<number | null>(null)
const lastHeights = new Map<string, number>()
const frameReady = ref(false)
const popoverHeight = computed(() => {
  const h = wantedHeight.value ? Math.max(MIN_H, Math.min(MAX_H, wantedHeight.value)) : DEFAULT_H
  return `min(${h}px, calc(100vh - 5rem))`
})
let revealTimer: ReturnType<typeof setTimeout> | null = null
let managerRefreshTimer: ReturnType<typeof setTimeout> | null = null
// Managers that don't report a size (third-party UIs) still get shown: reveal
// shortly after load at full height.
function onFrameLoad() {
  if (revealTimer) clearTimeout(revealTimer)
  revealTimer = setTimeout(() => {
    if (!frameReady.value) {
      if (!wantedHeight.value) wantedHeight.value = MAX_H
      frameReady.value = true
    }
  }, 500)
}
function onFrameMessage(e: MessageEvent) {
  const d = e.data
  if (!d || d.type !== 'stimma-manage-size' || typeof d.height !== 'number') return
  if (frameEl.value && e.source !== frameEl.value.contentWindow) return
  wantedHeight.value = d.height + 2 // border
  if (openId.value) lastHeights.set(openId.value, wantedHeight.value)
  frameReady.value = true
}

function isComfy(p: ManagedProvider) { return isComfyUIProvider({ id: p.provider_id, name: p.provider_name }) }
function shortName(p: ManagedProvider) { return isComfy(p) ? 'ComfyUI' : p.provider_name }
function iconMaskStyle(icon: string) {
  const url = `url("${icon}")`
  return { backgroundColor: 'currentColor', maskImage: url, WebkitMaskImage: url, maskRepeat: 'no-repeat', WebkitMaskRepeat: 'no-repeat', maskSize: 'contain', WebkitMaskSize: 'contain', maskPosition: 'center', WebkitMaskPosition: 'center' }
}
function dotClassFor(p: ManagedProvider) {
  if (p.state === 'warning') return 'bg-amber-500'
  if (p.state === 'error') return 'bg-red-500'
  if (p.attention === 'update_available') return 'bg-amber-500'
  return ''
}
function titleFor(p: ManagedProvider) {
  if (p.status !== 'connected') return `${p.provider_name} · not connected`
  if (p.state && p.state !== 'ready' && p.state_summary) return `${p.provider_name} · ${p.state_summary}`
  if (p.attention === 'update_available') return `${p.provider_name} · update available`
  return p.provider_name
}
function frameSrc(p: ManagedProvider) {
  // getApiBase() already ends in /api ('/api' in dev, 'http://127.0.0.1:PORT/api' in Tauri)
  const base = getApiBase().replace(/\/$/, '')
  const theme = resolvedTheme.value === 'light' ? 'light' : 'dark'
  return `${base}/provider-manage/${encodeURIComponent(p.provider_id)}/?theme=${theme}${anchor.value ? '#' + anchor.value : ''}`
}

async function refresh() {
  try { providers.value = (await listProviders()) as ManagedProvider[] } catch { /* keep last */ }
}
function toggle(id: string, tab?: string) {
  if (openId.value === id && !tab) { openId.value = null; return }
  anchor.value = tab || ''
  wantedHeight.value = lastHeights.get(id) ?? null
  frameReady.value = false
  openId.value = id
  if (hintFor.value === id) dismissHint()
}
function close() { openId.value = null }
function dismissHint() { hintDismissed.value = true; localStorage.setItem(HINT_KEY, '1') }

function onDocClick(e: MouseEvent) {
  const t = e.target as HTMLElement | null
  if (t && t.closest && t.closest('.provider-manager')) return
  close()
}
function onKey(e: KeyboardEvent) { if (e.key === 'Escape') close() }

function handleStateChanged(data: { provider_id: string; state: string; summary?: string | null; attention?: 'update_available' | null }) {
  const p = providers.value.find(x => x.provider_id === data.provider_id)
  if (p) {
    p.state = data.state as any
    p.state_summary = data.summary ?? null
    p.attention = data.attention ?? null
  }
  else refresh()
}
function handleNotification(data: { provider_id: string; provider_name?: string; level: string; title: string; body?: string | null; action?: string | null; anchor?: string | null }) {
  const type = data.level === 'error' ? 'error' : data.level === 'warning' ? 'warning' : 'info'
  const message = data.body ? `${data.title} — ${data.body}` : data.title
  const action = data.action === 'manage'
    ? { label: 'Open', onClick: () => toggle(data.provider_id, data.anchor || '') }
    : undefined
  addToast(message, type, type === 'error' ? 8000 : 5000, action)
}

const MANAGER_JOB_EVENTS = [
  'generation_job_queued',
  'generation_job_started',
  'generation_job_progress',
  'generation_job_completed',
  'generation_job_failed',
  'generation_job_cancelled',
]
function handleManagerJobEvent() {
  if (!frameEl.value?.contentWindow || !openId.value) return
  const provider = providers.value.find(p => p.provider_id === openId.value)
  if (!provider || !isComfy(provider)) return
  if (managerRefreshTimer) return
  managerRefreshTimer = setTimeout(() => {
    managerRefreshTimer = null
    try { frameEl.value?.contentWindow?.postMessage({ type: 'stimma-manage-refresh' }, '*') } catch { /* */ }
  }, 100)
}

let unsubscribe: (() => void) | null = null
onMounted(() => {
  if (cachedProviders.value.length) providers.value = cachedProviders.value as ManagedProvider[]
  refresh()
  unsubscribe = subscribeToProviderChanges(() => refresh())
  on('provider_state_changed', handleStateChanged)
  on('provider_notification', handleNotification)
  for (const event of MANAGER_JOB_EVENTS) on(event, handleManagerJobEvent)
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKey)
  window.addEventListener('message', onFrameMessage)
})
onUnmounted(() => {
  window.removeEventListener('message', onFrameMessage)
  unsubscribe?.()
  off('provider_state_changed', handleStateChanged)
  off('provider_notification', handleNotification)
  for (const event of MANAGER_JOB_EVENTS) off(event, handleManagerJobEvent)
  if (managerRefreshTimer) clearTimeout(managerRefreshTimer)
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKey)
})
watch(resolvedTheme, (t) => {
  try { frameEl.value?.contentWindow?.postMessage({ type: 'stimma-theme', theme: t === 'light' ? 'light' : 'dark' }, '*') } catch { /* */ }
})
</script>
