<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import Button from '../components/ui/Button.vue'
import Spinner from '../components/ui/Spinner.vue'
import { mobileNative as native } from '../desktop/mobileNative'

interface Device { deviceId: string; name: string; serving: boolean }
interface ConnectionInfo {
  authenticated: boolean
  user?: { email?: string; display_name?: string } | null
  devices: Device[]
  selectedDeviceId?: string | null
  busy: boolean
  restoring: boolean
  message?: string | null
}

const info = ref<ConnectionInfo | null>(null)
const operation = ref<string | null>(null)
const failure = ref<string | null>(null)
const attemptedDevice = ref<string | null>(null)
const slowRestore = ref(false)
const restoring = computed(() => !info.value || info.value.restoring)
const pending = computed(() => Boolean(operation.value || info.value?.busy))
const devices = computed(() => info.value?.devices ?? [])
const message = computed(() => failure.value || info.value?.message)
const retryDevice = computed(() => attemptedDevice.value || info.value?.selectedDeviceId)
let mounted = false
let timer: ReturnType<typeof setTimeout> | undefined
let reading = false
let restoreTimer: ReturnType<typeof setTimeout> | undefined

watch(() => Boolean(info.value && !info.value.restoring), async (ready) => {
  if (!ready) return
  await nextTick()
  await document.fonts.load('500 42px "General Sans"', 'stimma').catch(() => {})
  await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))
  await native('interfaceReady').catch(() => {})
})

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : typeof error === 'string' ? error : 'Something went wrong. Please try again.'
}

async function readInfo() {
  if (reading || !mounted) return
  reading = true
  try {
    const state = await native<ConnectionInfo>('connectionInfo')
    if (mounted) info.value = state
  } catch (error) {
    if (mounted) failure.value = errorMessage(error)
  } finally { reading = false }
}

function schedule() {
  clearTimeout(timer)
  if (!mounted) return
  timer = setTimeout(async () => {
    if (document.visibilityState === 'visible' && (restoring.value || !info.value?.authenticated || pending.value)) await readInfo()
    schedule()
  }, 1000)
}

async function act(method: string, args: Record<string, unknown> = {}) {
  if (pending.value) return
  operation.value = method
  failure.value = null
  try {
    await native(method, args)
    await readInfo()
  } catch (error) {
    if (mounted) failure.value = errorMessage(error)
  } finally {
    operation.value = null
    if (mounted) await readInfo()
  }
}

function select(deviceId: string) {
  attemptedDevice.value = deviceId
  return act('selectServer', { deviceId })
}

async function chooseAnotherServer() {
  try {
    info.value = await native<ConnectionInfo>('cancelRestore')
    // Discovery might still have been in flight when restoration was cancelled.
    await act('refreshDevices')
  } catch (error) { failure.value = errorMessage(error) }
}

async function retry() {
  failure.value = null
  if (info.value?.authenticated && retryDevice.value) await select(retryDevice.value)
  else if (info.value?.authenticated) await act('refreshDevices')
  else if (info.value) await act('signIn')
  else await readInfo()
}

function openLegal(page: 'terms' | 'privacy') {
  return act('openExternal', { url: `https://stimma.ai/${page}` })
}

onMounted(async () => {
  mounted = true
  window.addEventListener('stimma:connection-info', readInfo)
  restoreTimer = setTimeout(() => { slowRestore.value = true }, 4500)
  await readInfo()
  schedule()
})
onUnmounted(() => {
  mounted = false
  window.removeEventListener('stimma:connection-info', readInfo)
  clearTimeout(timer)
  clearTimeout(restoreTimer)
})
</script>

<template>
  <main class="h-dvh w-full overflow-y-auto bg-base text-content pt-safe pb-safe">
    <div v-if="restoring && !failure" class="flex min-h-full flex-col items-center justify-center px-7" role="status" aria-label="Connecting to your Stimma Server">
      <Spinner />
      <div class="mt-6 text-center" :class="slowRestore ? 'visible' : 'invisible'" :aria-hidden="!slowRestore">
        <p class="text-sm text-content-secondary">Connecting to your Stimma Server…</p>
        <Button variant="link" class="mt-3 min-h-11" :tabindex="slowRestore ? 0 : -1" @click="chooseAnotherServer">Choose another server</Button>
      </div>
    </div>
    <div v-else class="mx-auto flex min-h-full w-full max-w-md flex-col px-7">
      <header class="flex min-h-20 items-center justify-end py-3">
        <Button v-if="info?.selectedDeviceId" variant="ghost" class="min-h-11" :disabled="pending" @click="act('closeConnections')">
          Back to Stimma
        </Button>
      </header>

      <section class="flex flex-1 flex-col justify-center pb-12" aria-labelledby="welcome-title">
        <div class="mb-10 flex items-center gap-3.5">
          <img src="/logo.svg" alt="" width="52" height="52" class="h-[52px] w-[52px] shrink-0">
          <span class="font-brand text-[42px] font-medium leading-none tracking-[0.12em]">stimma</span>
        </div>

        <template v-if="!info?.authenticated">
          <h1 id="welcome-title" class="font-brand text-[34px] font-medium leading-[1.15] tracking-tight">
            Stimma,<br>wherever you are.
          </h1>
          <p class="mt-5 max-w-[290px] text-[16px] leading-relaxed text-content-secondary">
            Create, explore, and pick up where you left off. Connect to your Stimma Server.
          </p>
          <Button class="mt-9 min-h-[52px] w-full text-[16px]" :loading="pending" :disabled="!info" @click="act('signIn')">
            {{ pending ? 'Signing in…' : 'Sign in' }}
          </Button>
          <p class="mt-4 text-center text-xs leading-relaxed text-content-tertiary">
            Use the same account as your Stimma Server.
          </p>
        </template>

        <template v-else>
          <h1 id="welcome-title" class="font-brand text-[30px] font-medium leading-tight tracking-tight">Connect to your Stimma Server</h1>
          <p class="mt-3 text-[15px] leading-relaxed text-content-secondary">Choose the server you want to connect to.</p>

          <div v-if="devices.length" class="mt-7 divide-y divide-edge-subtle">
            <button
              v-for="device in devices" :key="device.deviceId" type="button"
              class="flex min-h-[84px] w-full items-center gap-4 py-4 text-left transition-colors hover:bg-overlay-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
              :disabled="pending || !device.serving" @click="select(device.deviceId)"
            >
              <svg class="h-6 w-6 shrink-0 text-content-tertiary" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
                <rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4"/>
              </svg>
              <span class="min-w-0 flex-1">
                <span class="block truncate text-[16px] font-medium">{{ device.name }}</span>
                <span class="mt-1 block text-xs text-content-tertiary">{{ device.serving ? (device.deviceId === info.selectedDeviceId ? 'Current server' : 'Ready to connect') : 'Not sharing remote access' }}</span>
              </span>
              <Spinner v-if="pending && attemptedDevice === device.deviceId" />
              <svg v-else class="h-4 w-4 shrink-0 text-accent-hi" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg>
            </button>
          </div>
          <p v-else-if="!pending" class="mt-7 text-[15px] leading-relaxed text-content-secondary">
            No servers are available yet. Enable remote access on your Stimma Server, then refresh.
          </p>
          <div v-else class="mt-7 flex items-center gap-3 text-sm text-content-secondary" role="status"><Spinner /> Finding your servers…</div>
          <Button variant="secondary" class="mt-5 min-h-12 w-full" :loading="operation === 'refreshDevices'" :disabled="pending" @click="act('refreshDevices')">Refresh</Button>
          <p class="mt-5 text-xs leading-relaxed text-content-tertiary">Keep your server running and connected. If you use Tailscale, connect it on this phone too.</p>
        </template>

        <div v-if="message" class="mt-6 text-sm leading-relaxed text-content-secondary" role="alert">
          <p>{{ message }}</p>
          <Button variant="link" class="mt-1 min-h-11" :disabled="pending" @click="retry">Try again</Button>
        </div>
        <div v-else-if="!info" class="mt-6 flex items-center justify-center gap-2 text-xs text-content-tertiary" role="status"><Spinner size="sm" /> Getting ready…</div>
      </section>

      <footer class="pb-5 text-center">
        <template v-if="info?.authenticated">
          <p v-if="info.user?.email" class="truncate text-xs text-content-tertiary">{{ info.user.email }}</p>
          <Button variant="ghost" class="min-h-11" :disabled="pending" @click="act('logout')">Sign out</Button>
        </template>
        <nav class="flex items-center justify-center gap-3" aria-label="Legal">
          <Button variant="ghost" size="sm" class="min-h-11" :disabled="pending" @click="openLegal('privacy')">Privacy</Button>
          <Button variant="ghost" size="sm" class="min-h-11" :disabled="pending" @click="openLegal('terms')">Terms</Button>
        </nav>
      </footer>
    </div>
  </main>
</template>
