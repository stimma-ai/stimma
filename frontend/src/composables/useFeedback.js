/**
 * Feedback / thumbs / crash-report client state (WS-F).
 *
 * One global store driving:
 * - the FeedbackModal (menu feedback, ALL builds — D13),
 * - the thumbs consent popup (the whole thumbs flow in official builds:
 *   [Don't send] sends nothing, not even the rating; [Send this once] /
 *   [Always send] submit the rating directly — no comment step),
 * - the batched crash-report consent dialog (official builds only;
 *   'always' auto-sends fully silently — D12 — so no dialog ever shows),
 * - the one-time post-onboarding Feedback coachmark flag.
 *
 * Consent values mirror backend config: ask | always | never.
 */
import { reactive, computed } from 'vue'
import axios from 'axios'
import { getApiBase } from '../apiConfig'
import { isOfficialBuild } from '../distribution'
import { useToasts } from './useToasts'

export const DEV_THUMBS_TOOLTIP =
  'Feedback sharing is disabled in source builds — your data stays local'

const state = reactive({
  loaded: false,
  thumbsConsent: 'ask',
  crashConsent: 'ask',
  coachmarkShown: true, // pessimistic until /state loads
  pendingCrashes: 0,
})

const modal = reactive({
  open: false,
})

const consentDialog = reactive({
  open: false,
  pendingThumb: null, // payload stashed while the user decides
})

const crashDialog = reactive({
  open: false,
  reports: [],
})

function trackFeedbackEvent(event, properties) {
  axios
    .post(`${getApiBase()}/telemetry/track`, { event, properties, category: 'feedback' })
    .catch(() => {})
}

async function loadState() {
  try {
    const { data } = await axios.get(`${getApiBase()}/feedback/state`)
    state.thumbsConsent = data.thumbs_consent || 'ask'
    state.crashConsent = data.crash_consent || 'ask'
    state.coachmarkShown = data.coachmark_shown !== false
    state.pendingCrashes = data.pending_crashes || 0
    state.loaded = true
  } catch (err) {
    console.warn('[feedback] failed to load state:', err)
  }
  return state
}

async function setConsent(subject, value) {
  const { data } = await axios.patch(`${getApiBase()}/feedback/consent`, { subject, value })
  if (subject === 'thumbs') state.thumbsConsent = value
  else state.crashConsent = value
  return data
}

async function markCoachmarkShown() {
  state.coachmarkShown = true
  try {
    await axios.post(`${getApiBase()}/feedback/coachmark-shown`)
  } catch {
    // Non-fatal — re-shown next launch at worst
  }
}

// ── Entry points ─────────────────────────────────────────────────────────

function openMenuFeedback(source = 'menu') {
  modal.open = true
  trackFeedbackEvent('feedback_opened', { source })
}

/**
 * Thumb click. Official builds only (the UI renders thumbs disabled in
 * dev builds). 'ask' → consent popup; 'always' → submit straight away;
 * 'never' → inert (UI shows the disabled treatment).
 */
function openThumbFeedback({ thumb, agentContext, packageSource }) {
  if (!isOfficialBuild() || state.thumbsConsent === 'never') return
  trackFeedbackEvent('feedback_opened', { source: 'thumb' })
  const payload = { thumb, agentContext, packageSource }
  if (state.thumbsConsent === 'ask') {
    consentDialog.pendingThumb = payload
    consentDialog.open = true
  } else {
    submitThumb(payload)
  }
}

/** Submit a thumb rating (with its conversation package, no comment). */
async function submitThumb({ thumb, agentContext, packageSource }) {
  const body = {
    kind: 'thumbs',
    thumb,
    agent_context: agentContext || null,
  }
  if (packageSource?.type === 'chat') {
    body.package = { type: 'chat', chat_id: packageSource.chatId }
  } else if (packageSource?.type === 'prompt_agent') {
    body.package = { type: 'prompt_agent', conversation: packageSource.conversation }
  }
  try {
    await axios.post(`${getApiBase()}/feedback/submit`, body)
    useToasts().addToast('Feedback sent — thank you!', 'success', 3500)
  } catch (err) {
    console.warn('[feedback] thumb submit failed:', err)
    useToasts().addToast('Could not send feedback', 'error')
  }
}

// Consent popup buttons ([Don't send] [Send this once] [Always send])
function consentDontSend() {
  consentDialog.open = false
  consentDialog.pendingThumb = null
}

function consentSendOnce() {
  const payload = consentDialog.pendingThumb
  consentDialog.open = false
  consentDialog.pendingThumb = null
  if (payload) submitThumb(payload)
}

async function consentAlwaysSend() {
  const payload = consentDialog.pendingThumb
  consentDialog.open = false
  consentDialog.pendingThumb = null
  try {
    await setConsent('thumbs', 'always')
  } catch (err) {
    console.warn('[feedback] failed to persist thumbs consent:', err)
  }
  if (payload) submitThumb(payload)
}

function closeModal() {
  modal.open = false
}

// ── Crash reports ────────────────────────────────────────────────────────

async function checkPendingCrashes() {
  if (!isOfficialBuild()) return
  try {
    const { data } = await axios.get(`${getApiBase()}/feedback/crashes/pending`)
    state.pendingCrashes = (data.reports || []).length
    if (data.consent === 'ask' && data.reports?.length > 0 && !crashDialog.open) {
      crashDialog.reports = data.reports
      crashDialog.open = true
      trackFeedbackEvent('feedback_opened', { source: 'crash_prompt' })
    }
  } catch {
    // backend not ready yet — retried via WS event
  }
}

async function crashDecision(action) {
  try {
    const { data } = await axios.post(`${getApiBase()}/feedback/crashes/decision`, { action })
    if (data?.status === 'rate_limited') {
      // Client-side send throttle — reports stay pending; quiet note only.
      useToasts().addToast('Crash reporting is rate-limited — report saved.', 'info')
    }
  } catch (err) {
    console.warn('[feedback] crash decision failed:', err)
  }
  if (action === 'send_always') state.crashConsent = 'always'
  crashDialog.open = false
  crashDialog.reports = []
  state.pendingCrashes = 0
}

/** Wire the live-crash WS notification. Call once with useWebSocket().on */
function initCrashNotifications(wsOn) {
  if (!isOfficialBuild()) return
  wsOn('crash_reports_pending', () => {
    checkPendingCrashes()
  })
}

// ── Public surface ───────────────────────────────────────────────────────

export function useFeedback() {
  return {
    state,
    modal,
    consentDialog,
    crashDialog,
    thumbsEnabled: computed(() => isOfficialBuild() && state.thumbsConsent !== 'never'),
    thumbsDisabledReason: computed(() => {
      if (!isOfficialBuild()) return DEV_THUMBS_TOOLTIP
      if (state.thumbsConsent === 'never') {
        return 'Thumbs feedback is turned off in Settings → Privacy'
      }
      return null
    }),
    loadState,
    setConsent,
    markCoachmarkShown,
    openMenuFeedback,
    openThumbFeedback,
    consentDontSend,
    consentSendOnce,
    consentAlwaysSend,
    closeModal,
    checkPendingCrashes,
    crashDecision,
    initCrashNotifications,
    trackFeedbackEvent,
  }
}
