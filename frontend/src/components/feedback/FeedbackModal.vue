<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="modal.open"
        class="fixed inset-0 z-[10020] flex items-center justify-center bg-black/60 backdrop-blur-sm"
        @click.self="close"
      >
        <div class="bg-surface border border-edge rounded-xl shadow-2xl w-[560px] max-w-[92vw] max-h-[88vh] flex flex-col overflow-hidden">
          <!-- Header -->
          <div class="flex items-center justify-between px-5 py-4 border-b border-edge">
            <div class="flex items-center gap-2.5">
              <h2 class="text-base font-semibold text-content">
                {{ isThumb ? 'Send feedback on this response' : 'Send feedback' }}
              </h2>
              <span
                v-if="isThumb"
                class="inline-flex items-center justify-center w-6 h-6 rounded-full text-sm"
                :class="modal.thumb === 'down' ? 'bg-red-500/15' : 'bg-blue-500/15'"
              >{{ modal.thumb === 'down' ? '👎' : '👍' }}</span>
            </div>
            <button
              @click="close"
              class="w-8 h-8 flex items-center justify-center text-content-tertiary hover:text-content hover:bg-surface-raised rounded-lg transition-colors"
            >
              <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <!-- Body -->
          <div class="flex-1 overflow-y-auto px-5 py-4 space-y-4">
            <p class="text-xs text-content-tertiary">
              {{ isThumb
                ? 'Your rating includes this conversation so the team can see what happened. Add a comment if you like.'
                : 'Tell us what you think — it goes straight to the team.' }}
            </p>

            <!-- Message + voice -->
            <div class="bg-surface-raised/50 border border-edge rounded-2xl pt-1 overflow-hidden">
              <textarea v-no-autocorrect
                ref="textareaRef"
                v-model="message"
                :rows="isThumb ? 3 : 5"
                :placeholder="isThumb ? 'Optional comment…' : 'What\'s working, what isn\'t, what you wish Stimma did…'"
                class="w-full bg-transparent text-content text-sm px-3 pt-2 pb-1 focus:outline-none resize-none block"
                @keydown="onTextareaKeydown"
                @keyup="onTextareaKeyup"
              />
              <div class="flex items-center justify-between px-2 pb-1.5">
                <VoiceInputButton
                  ref="voiceBtn"
                  icon-class="w-4 h-4"
                  :get-text="getText"
                  :set-text="setText"
                  :focus="focusTextarea"
                  surface="feedback"
                />
                <span class="text-[10px] text-content-muted pr-1">{{ message.length > 0 ? `${message.length} chars` : '' }}</span>
              </div>
            </div>

            <!-- Attachment checkboxes (menu variant only) -->
            <div v-if="!isThumb" class="space-y-2.5">
              <label class="flex items-start gap-2.5 cursor-pointer">
                <input type="checkbox" v-model="includeLogs" class="mt-0.5 accent-blue-500 w-3.5 h-3.5 shrink-0" />
                <div class="min-w-0">
                  <div class="text-xs text-content">Include logs</div>
                  <div class="text-[11px] text-content-muted mt-0.5">The last 200 lines of the app log, with secret-shaped values redacted.</div>
                </div>
              </label>
              <label class="flex items-start gap-2.5 cursor-pointer">
                <input type="checkbox" v-model="includeScreenshot" @change="onScreenshotToggle" class="mt-0.5 accent-blue-500 w-3.5 h-3.5 shrink-0" />
                <div class="min-w-0 flex-1">
                  <div class="text-xs text-content">Include screenshot</div>
                  <div class="text-[11px] text-content-muted mt-0.5">A capture of the app window as it looks right now.</div>
                  <div v-if="capturingScreenshot" class="text-[11px] text-content-muted mt-1">Capturing…</div>
                  <div v-else-if="screenshotError" class="text-[11px] text-red-400 mt-1">Couldn't capture a screenshot — your feedback will be sent without one.</div>
                  <img
                    v-else-if="screenshotDataUrl"
                    :src="screenshotDataUrl"
                    alt="Screenshot preview"
                    class="mt-2 max-h-28 rounded-lg border border-edge"
                  />
                </div>
              </label>
            </div>

            <!-- See what will be sent -->
            <details class="rounded-lg border border-edge bg-surface-raised/30">
              <summary
                class="px-3 py-2 text-xs font-medium text-content-secondary cursor-pointer select-none hover:text-content"
                @click="loadPreview"
              >
                See what will be sent
              </summary>
              <div class="px-3 pb-3 space-y-3">
                <!-- Message -->
                <div>
                  <div class="text-[11px] font-medium text-content-tertiary mb-1">Message</div>
                  <p class="text-xs text-content-secondary whitespace-pre-wrap break-words">{{ message || '(empty)' }}</p>
                </div>

                <!-- Conversation package -->
                <div v-if="modal.packageSource">
                  <div class="text-[11px] font-medium text-content-tertiary mb-1">Conversation package</div>
                  <div v-if="packagePreview" class="text-xs text-content-secondary">
                    {{ packagePreview.message_count }} message{{ packagePreview.message_count === 1 ? '' : 's' }}<template v-if="packagePreview.media_ids?.length">,
                    {{ packagePreview.media_ids.length }} media item{{ packagePreview.media_ids.length === 1 ? '' : 's' }}</template>
                    <div v-if="packagePreview.media_ids?.length" class="flex flex-wrap gap-1.5 mt-2">
                      <MediaImage
                        v-for="mid in packagePreview.media_ids.slice(0, 8)"
                        :key="mid"
                        :mediaId="mid"
                        :thumbnail="true"
                        :thumbnailSize="64"
                        containerClass="w-12 h-12 rounded overflow-hidden"
                      />
                      <span
                        v-if="packagePreview.media_ids.length > 8"
                        class="w-12 h-12 rounded bg-surface-raised flex items-center justify-center text-[10px] text-content-muted"
                      >+{{ packagePreview.media_ids.length - 8 }}</span>
                    </div>
                  </div>
                  <div v-else class="text-xs text-content-muted">Loading…</div>
                </div>

                <!-- Log tail -->
                <div v-if="includeLogs || isThumbLogs">
                  <div class="text-[11px] font-medium text-content-tertiary mb-1">Log tail (last 200 lines, secrets redacted)</div>
                  <pre v-if="logsPreview !== null" class="text-[10px] leading-snug text-content-muted bg-surface-raised rounded p-2 max-h-40 overflow-auto whitespace-pre-wrap break-words">{{ logsPreview }}</pre>
                  <div v-else class="text-xs text-content-muted">Loading…</div>
                </div>

                <!-- Screenshot -->
                <div v-if="includeScreenshot && screenshotDataUrl">
                  <div class="text-[11px] font-medium text-content-tertiary mb-1">Screenshot</div>
                  <img :src="screenshotDataUrl" alt="Screenshot" class="max-h-40 rounded-lg border border-edge" />
                </div>

                <!-- App identity (always sent) -->
                <div class="text-[10px] text-content-muted">
                  Also sent: app version, OS, build channel, and a random install identifier{{ signedInNote }}.
                </div>
              </div>
            </details>

            <p v-if="error" class="text-xs text-red-500">{{ error }}</p>
          </div>

          <!-- Footer -->
          <div class="flex items-center justify-end gap-2 px-5 py-3.5 border-t border-edge">
            <button
              @click="close"
              class="px-3.5 py-2 text-sm text-content-secondary hover:text-content hover:bg-overlay-subtle rounded-lg transition-colors"
            >Cancel</button>
            <button
              @click="submit"
              :disabled="submitting || (!isThumb && !message.trim())"
              class="px-4 py-2 text-sm font-medium bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg transition-colors flex items-center gap-2"
            >
              <svg v-if="submitting" class="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
              </svg>
              <span>{{ submitting ? 'Sending…' : 'Send feedback' }}</span>
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import axios from 'axios'
import { getApiBase } from '../../apiConfig'
import { useFeedback } from '../../composables/useFeedback'
import { useAuth } from '../../composables/useAuth'
import { addToast } from '../../composables/useToasts'
import VoiceInputButton from '../voice/VoiceInputButton.vue'
import MediaImage from '../media/MediaImage.vue'

const { modal, closeModal } = useFeedback()
const { isAuthenticated } = useAuth()

const message = ref('')
const includeLogs = ref(false)
const includeScreenshot = ref(false)
const screenshotDataUrl = ref(null)
const capturingScreenshot = ref(false)
const screenshotError = ref(false)
let captureToken = 0
const submitting = ref(false)
const error = ref(null)
const logsPreview = ref(null)
const packagePreview = ref(null)

const textareaRef = ref(null)
const voiceBtn = ref(null)

const isThumb = computed(() => modal.variant === 'thumb')
const isThumbLogs = computed(() => false) // thumbs send the package, not logs
const signedInNote = computed(() =>
  isAuthenticated.value ? ', linked to your Stimma Cloud account' : ''
)

// Reset transient state each time the modal opens
watch(() => modal.open, async (open) => {
  if (!open) return
  message.value = ''
  includeLogs.value = false
  includeScreenshot.value = false
  screenshotDataUrl.value = null
  screenshotError.value = false
  captureToken++
  error.value = null
  logsPreview.value = null
  packagePreview.value = null
  await nextTick()
  textareaRef.value?.focus()
})

function close() {
  closeModal()
}

// ── Voice wiring (same pattern as ChatInputBox) ─────────────────────────
function getText() {
  return message.value
}
function setText(text) {
  message.value = text
}
function focusTextarea() {
  textareaRef.value?.focus()
}
function onTextareaKeydown(event) {
  voiceBtn.value?.handleInputKeydown(event)
}
function onTextareaKeyup(event) {
  voiceBtn.value?.handleInputKeyup(event)
}

// ── Screenshot (DOM render of the app root; modals are teleported to
//    body so the capture shows the app as the user sees it, sans modal) ──
//
// The whole capture races a hard deadline: modern-screenshot's <video>
// clone path (loadMedia without a timeout + an unconditional wait for
// `seeked`) can block forever in WKWebView, and the modal must never
// wedge at "Capturing…" no matter what the library does.
const CAPTURE_DEADLINE_MS = 8000

function withDeadline(promise, ms) {
  let timer = null
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`screenshot capture timed out after ${ms}ms`)), ms)
    }),
  ]).finally(() => clearTimeout(timer))
}

const sleep = (ms) => new Promise(r => setTimeout(r, ms))

async function captureScreenshot() {
  // modern-screenshot does the hard part (DOM clone + resource inlining),
  // but its built-in rasterizers are unsafe for a whole-app capture in
  // WKWebView: cloneVideo waits unboundedly, and the Safari "fixSvgXmlDecode"
  // redraw loop sleeps per embedded image (quadratic in image count — a
  // media grid takes 10s+). So we build the foreignObject SVG with bounded
  // options and rasterize it ourselves on a fixed schedule.
  const { createContext, destroyContext, domToForeignObjectSvg } =
    await import('modern-screenshot')
  const node = document.getElementById('app')
  // Downscale large windows — a feedback screenshot doesn't need retina.
  const cssWidth = node?.clientWidth || window.innerWidth || 1
  const scale = Math.min(1, 1600 / cssWidth)
  const context = await createContext(node, {
    scale,
    // Bound every internal wait (media readiness, image fetch/decode) well
    // under the outer deadline so slow media degrades to placeholders
    // instead of failing the whole capture.
    timeout: 3000,
    // Skip <video> (unbounded clone path, see above) and nested iframes —
    // neither is needed in a feedback screenshot.
    filter: (el) => el.tagName !== 'VIDEO' && el.tagName !== 'IFRAME',
    // Fonts are already loaded in this document and the SVG rasterizes in
    // the same page, so embedding webfonts only adds fetch round-trips.
    font: false,
  })
  try {
    const svg = await domToForeignObjectSvg(context)
    // Strip control characters that break XML parsing (WebKit is strict).
    const xml = new XMLSerializer().serializeToString(svg)
      .replace(/[\u0000-\u0008\v\f\u000E-\u001F\uD800-\uDFFF\uFFFE\uFFFF]/gu, '')
    const img = new Image()
    img.decoding = 'sync'
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(xml)}`
    await new Promise((resolve) => {
      img.addEventListener('load', resolve, { once: true })
      img.addEventListener('error', resolve, { once: true })
      setTimeout(resolve, 3000)
    })
    try { await img.decode() } catch { /* draw anyway */ }

    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.floor(context.width * scale))
    canvas.height = Math.max(1, Math.floor(context.height * scale))
    const ctx = canvas.getContext('2d')
    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
    }
    // WebKit decodes data-URI sub-images inside the SVG asynchronously and
    // decode() resolves before they're ready; redraw on a short fixed
    // schedule (bounded, unlike the library's per-image loop).
    draw()
    for (const delay of [150, 350, 600]) {
      await sleep(delay)
      draw()
    }
    return canvas.toDataURL('image/png')
  } finally {
    destroyContext(context)
  }
}

async function onScreenshotToggle() {
  const token = ++captureToken
  screenshotError.value = false
  if (!includeScreenshot.value) {
    screenshotDataUrl.value = null
    return
  }
  capturingScreenshot.value = true
  try {
    const dataUrl = await withDeadline(captureScreenshot(), CAPTURE_DEADLINE_MS)
    if (token !== captureToken) return // toggled again / modal reset meanwhile
    screenshotDataUrl.value = dataUrl
  } catch (err) {
    console.error('[feedback] screenshot capture failed:', err)
    if (token !== captureToken) return
    includeScreenshot.value = false
    screenshotDataUrl.value = null
    screenshotError.value = true
  } finally {
    if (token === captureToken) capturingScreenshot.value = false
  }
}

// ── Preview ──────────────────────────────────────────────────────────────
async function loadPreview() {
  if ((includeLogs.value || isThumbLogs.value) && logsPreview.value === null) {
    try {
      const { data } = await axios.get(`${getApiBase()}/feedback/logs-preview`)
      logsPreview.value = data.text || '(empty)'
    } catch {
      logsPreview.value = '(could not load log preview)'
    }
  }
  if (modal.packageSource && packagePreview.value === null) {
    if (modal.packageSource.type === 'chat') {
      try {
        const { data } = await axios.get(
          `${getApiBase()}/feedback/package-preview`,
          { params: { chat_id: modal.packageSource.chatId } }
        )
        packagePreview.value = data
      } catch {
        packagePreview.value = { message_count: 0, media_ids: [] }
      }
    } else if (modal.packageSource.type === 'prompt_agent') {
      const messages = modal.packageSource.conversation?.messages || []
      packagePreview.value = { message_count: messages.length, media_ids: [] }
    }
  }
}

// Re-fetch the log preview when the checkbox flips while preview is open
watch(includeLogs, (on) => {
  if (on) {
    logsPreview.value = null
  }
})

// ── Submit ───────────────────────────────────────────────────────────────
async function submit() {
  if (submitting.value) return
  error.value = null
  submitting.value = true
  try {
    const body = {
      kind: isThumb.value ? 'thumbs' : 'feedback',
      message: message.value,
      include_logs: includeLogs.value,
      screenshot: includeScreenshot.value ? screenshotDataUrl.value : null,
    }
    if (isThumb.value) {
      body.thumb = modal.thumb
      body.agent_context = modal.agentContext
      if (modal.packageSource?.type === 'chat') {
        body.package = { type: 'chat', chat_id: modal.packageSource.chatId }
      } else if (modal.packageSource?.type === 'prompt_agent') {
        body.package = {
          type: 'prompt_agent',
          conversation: modal.packageSource.conversation,
        }
      }
    }
    await axios.post(`${getApiBase()}/feedback/submit`, body)
    closeModal()
    addToast('Feedback sent — thank you!', 'success', 3500)
  } catch (err) {
    const detail = err.response?.data?.detail
    error.value = typeof detail === 'string' ? detail : 'Could not send feedback'
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.15s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
</style>
