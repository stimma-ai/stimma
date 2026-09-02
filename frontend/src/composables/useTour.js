/**
 * First-run tour — three sidebar coachmarks (Chats, Tools, Feedback) shown
 * once, after the setup wizard is out of the way.
 *
 * Like the setup wizard, the tour is VERSIONED on the backend
 * (FIRST_RUN_TOUR_VERSION in routes/settings.py, persisted as config
 * `tour_seen_version`, carried on `settings.readiness`): it is due whenever
 * the persisted seen version is behind the current version, and any
 * dismissal marks the current version seen via POST /api/settings/tour-seen.
 * Bumping the backend constant re-runs the tour for every install that
 * hasn't seen the new one.
 *
 * Steps anchor to sidebar elements tagged data-tour="<id>". A step whose
 * anchor is missing at start time is dropped silently — this is how the
 * Feedback stop disappears under Privacy Lockdown and in source builds
 * (where the feedback button doesn't render at all).
 *
 * Ending the tour (completed or dismissed) also sets the pre-existing
 * feedback `coachmark_shown` flag when the Feedback stop was part of the
 * run — the tour's last stop IS that coachmark.
 *
 * FirstRunTour.vue owns triggering and rendering; this composable owns the
 * step list, run state, and seen persistence.
 */
import { ref, computed, readonly } from 'vue'
import axios from 'axios'
import { getApiBase } from '../apiConfig'
import { useReadiness } from './useReadiness'
import { useFeedback } from './useFeedback'
import { useTelemetry } from './useTelemetry'

/**
 * The multi-device coachmark is a SEPARATE track from the first-run tour.
 *
 * It fires on an event ("this account now has a serving device"), not on
 * first run, and it has its own seen-flag: folding it into TOUR_STEPS would
 * mean bumping FIRST_RUN_TOUR_VERSION, which re-runs all three first-run
 * stops for every existing install.
 */
export const DEVICE_COACHMARK = {
  id: 'device-chip',
  title: 'Atelier is available',
  body: 'Another Stimma Server is running on your account. Switch to it here.',
}

const DEVICE_COACHMARK_KEY = 'stimma_device_coachmark_seen'

export function isDeviceCoachmarkDue() {
  try {
    return localStorage.getItem(DEVICE_COACHMARK_KEY) !== '1'
  } catch {
    return false
  }
}

export function markDeviceCoachmarkSeen() {
  try {
    localStorage.setItem(DEVICE_COACHMARK_KEY, '1')
  } catch {
    // A browser that refuses storage just shows it again; harmless.
  }
}

export const TOUR_STEPS = [
  {
    id: 'chats',
    title: 'Chats',
    body: 'The fastest way to make something. Describe it, and the agent picks the tools and does the work.',
  },
  {
    id: 'tools',
    title: 'Your workbench',
    body: 'ComfyUI workflows, cloud models, your own providers — they all show up here as tools you can run directly.',
  },
  {
    id: 'feedback',
    title: 'Help us make it better',
    body: 'Stimma is young. Tell us what’s broken, confusing, or missing — it shapes what we build next.',
    // Community links route through the cloud's /link/* redirects (same as
    // Settings → Updates) so destinations can change without an app update.
    links: [
      { label: 'Discord', path: '/link/discord' },
      { label: 'Reddit', path: '/link/reddit' },
    ],
  },
]

// Global reactive state (shared across all components)
const activeSteps = ref([]) // steps whose anchors resolved, frozen at start
const stepIndex = ref(-1) // -1 = not running
const endedForSession = ref(false) // never auto-restart within a session

// Dev-only override: forces the tour to run regardless of the seen version
// (Settings → Developer → Replay First-Run Tour).
const forceShowForDev = ref(false)
// Set by startTour when a caller runs its own separately-gated coachmark.
let endHook = null

const isActive = computed(() => stepIndex.value >= 0)
const currentStep = computed(() => activeSteps.value[stepIndex.value] ?? null)

/**
 * The tour is DUE (backend seen-version is behind) — not necessarily
 * startable right now; FirstRunTour.vue layers on the situational gates
 * (wizard closed, home route, desktop width, settle delay).
 */
const isDue = computed(() => {
  if (forceShowForDev.value) return true
  if (endedForSession.value) return false
  const { readiness } = useReadiness()
  const r = readiness.value
  if (!r) return false
  return (r.tour_seen_version ?? 0) < (r.tour_version ?? 0)
})

function anchorFor(stepId) {
  return document.querySelector(`[data-tour="${stepId}"]`)
}

/**
 * Begin the tour with whichever steps have live anchors. Returns false when
 * nothing could anchor (nothing is marked seen in that case — we retry on a
 * later launch rather than burning the one showing on a broken layout).
 */
function startTour(steps = TOUR_STEPS, options = {}) {
  if (isActive.value) return true
  const live = steps.filter((s) => anchorFor(s.id))
  if (live.length === 0) return false
  activeSteps.value = live
  stepIndex.value = 0
  // A caller-supplied track (the device coachmark) owns its own seen-flag and
  // must NOT mark the first-run tour version as seen when it ends.
  endHook = options.onEnd || null
  useTelemetry().track('tour_started', { steps: live.map((s) => s.id) })
  return true
}

function nextStep() {
  if (!isActive.value) return
  if (stepIndex.value >= activeSteps.value.length - 1) {
    endTour('completed')
  } else {
    stepIndex.value += 1
  }
}

/**
 * Any exit path: Done on the last bubble ('completed'), Skip, Escape, or a
 * click elsewhere ('dismissed'). Every path marks the current version seen —
 * the tour never nags.
 */
function endTour(reason) {
  if (!isActive.value) return
  const { track } = useTelemetry()
  if (reason === 'completed') {
    track('tour_completed')
  } else {
    track('tour_skipped_at_step', {
      step: activeSteps.value[stepIndex.value]?.id,
      step_index: stepIndex.value,
    })
  }
  const includedFeedback = activeSteps.value.some((s) => s.id === 'feedback')
  const hook = endHook
  endHook = null
  stepIndex.value = -1
  activeSteps.value = []
  forceShowForDev.value = false

  // A separately-gated coachmark persists its own flag and leaves both the
  // first-run tour version and the once-per-session guard untouched.
  if (hook) {
    hook()
    return
  }

  endedForSession.value = true
  void markTourSeen()
  // The tour's Feedback stop is the one-time feedback coachmark — seeing the
  // tour (or opting out of it) satisfies that flag too.
  if (includedFeedback) {
    void useFeedback().markCoachmarkShown()
  }
}

/**
 * Persist that this install has seen the current tour version. The cached
 * readiness object keeps its stale seen-version until the next settings
 * fetch; endedForSession covers the gap.
 */
async function markTourSeen() {
  try {
    await axios.post(`${getApiBase()}/settings/tour-seen`)
  } catch (e) {
    console.error('[useTour] failed to persist tour seen version:', e)
  }
}

/**
 * Dev helper: force the tour to run now, regardless of the seen version.
 */
function relaunchTour() {
  endedForSession.value = false
  forceShowForDev.value = true
}

export function useTour() {
  return {
    isDue,
    isActive,
    currentStep,
    stepIndex: readonly(stepIndex),
    activeSteps: readonly(activeSteps),

    anchorFor,
    startTour,
    nextStep,
    endTour,
    relaunchTour,
  }
}
