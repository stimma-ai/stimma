<template>
  <Teleport to="body">
    <template v-if="isActive && anchorRect">
      <!-- Glow ring over the anchored sidebar element. Overlay div instead of
           mutating the target's classes so the sidebar never knows the tour
           exists. Multi-layer glow needs a composed box-shadow, which
           Tailwind can't express — inline style is the exception here. -->
      <div
        class="fixed z-top rounded-lg pointer-events-none transition-all duration-200"
        :style="{
          left: `${anchorRect.left - 3}px`,
          top: `${anchorRect.top - 3}px`,
          width: `${anchorRect.width + 6}px`,
          height: `${anchorRect.height + 6}px`,
          boxShadow:
            '0 0 0 1.5px rgba(59,130,246,0.9), 0 0 0 5px rgba(59,130,246,0.18), 0 0 24px 2px rgba(59,130,246,0.25)',
          background: 'rgba(59,130,246,0.08)',
        }"
      />

      <!-- Coachmark bubble, anchored to the right of the target -->
      <div
        ref="bubbleEl"
        class="fixed z-top w-[272px] bg-surface-raised border border-edge rounded-lg shadow-[0_12px_32px_rgba(0,0,0,0.55),0_2px_8px_rgba(0,0,0,0.4)] px-4 pt-3.5 pb-3"
        :style="{ left: `${bubblePos.left}px`, top: `${bubblePos.top}px` }"
      >
        <!-- Arrow pointing at the target -->
        <div
          class="absolute -left-[6px] w-2.5 h-2.5 bg-surface-raised border-l border-b border-edge rotate-45"
          :style="{ top: `${bubblePos.arrowTop}px` }"
        />
        <div class="text-[13px] font-semibold text-content mb-1">{{ currentStep.title }}</div>
        <div class="text-[12.5px] leading-relaxed text-content-secondary mb-3">
          {{ currentStep.body }}
          <template v-if="currentStep.links?.length">
            You can also find us on
            <template v-for="(link, i) in currentStep.links" :key="link.path">
              <button
                @click="openCommunityLink(link.path)"
                class="text-blue-400 hover:text-blue-300 underline underline-offset-2 bg-transparent border-none p-0 cursor-pointer text-[12.5px]"
              >{{ link.label }}</button><span v-if="i < currentStep.links.length - 1"> and </span>
            </template>.
          </template>
        </div>
        <div class="flex items-center justify-between">
          <div class="flex gap-1.5">
            <div
              v-for="(s, i) in activeSteps"
              :key="s.id"
              class="w-[5px] h-[5px] rounded-full transition-colors"
              :class="i === stepIndex ? 'bg-accent-hi' : 'bg-overlay-strong'"
            />
          </div>
          <div class="flex items-center gap-1.5">
            <button
              @click="endTour('dismissed')"
              class="px-2 py-1 rounded-md text-xs text-content-tertiary hover:text-content hover:bg-overlay-subtle border-none bg-transparent cursor-pointer"
            >
              Skip
            </button>
            <button
              @click="nextStep"
              class="px-3 py-1 rounded-md text-xs font-medium text-white bg-accent hover:bg-accent/90 border-none cursor-pointer"
            >
              {{ stepIndex >= activeSteps.length - 1 ? 'Done' : 'Next' }}
            </button>
          </div>
        </div>
      </div>
    </template>
  </Teleport>
</template>

<script setup>
/**
 * First-run tour renderer + trigger (see useTour.js for the state model).
 *
 * Trigger: the tour starts once per session when ALL of these hold —
 *  - the backend says it's due (tour_seen_version behind, via readiness)
 *  - the setup wizard is not showing (it runs first; tour fires after any
 *    dismissal path, including "start anyway")
 *  - the route is home (a fresh user's landing spot)
 *  - desktop-width viewport (the sidebar is an overlay on mobile)
 * plus a settle delay so it never pops mid-transition.
 */
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useTour } from '../composables/useTour'
import { useReadiness } from '../composables/useReadiness'
import { useCloudAccount } from '../composables/useCloudAccount'

const SETTLE_DELAY_MS = 1000

const route = useRoute()
const { isDue, isActive, currentStep, stepIndex, activeSteps, anchorFor, startTour, nextStep, endTour } = useTour()
const { shouldShowPanel } = useReadiness()

const anchorRect = ref(null)
const bubbleEl = ref(null)
const bubblePos = ref({ left: 0, top: 0, arrowTop: 20 })

// ── Trigger ──────────────────────────────────────────────────────────────

let startTimer = null

const canStart = computed(() =>
  isDue.value
  && !shouldShowPanel.value
  && route.name === 'home'
  && !isActive.value
)

watch(canStart, (ok) => {
  if (ok) {
    clearTimeout(startTimer)
    startTimer = setTimeout(tryStart, SETTLE_DELAY_MS)
  } else if (!isActive.value) {
    clearTimeout(startTimer)
  }
}, { immediate: true })

function tryStart() {
  if (!canStart.value) return
  if (!window.matchMedia('(min-width: 768px)').matches) return
  // Anchors missing (layout not settled?) — one quiet retry, then leave the
  // seen-version alone so a later launch gets another chance.
  if (!startTour()) {
    clearTimeout(startTimer)
    startTimer = setTimeout(() => { if (canStart.value) startTour() }, SETTLE_DELAY_MS)
  }
}

// ── Positioning ──────────────────────────────────────────────────────────

function reposition() {
  const step = currentStep.value
  if (!step) {
    anchorRect.value = null
    return
  }
  const el = anchorFor(step.id)
  if (!el) {
    // Anchor vanished mid-tour (e.g. sidebar relayout) — skip forward.
    nextStep()
    return
  }
  const r = el.getBoundingClientRect()
  anchorRect.value = { left: r.left, top: r.top, width: r.width, height: r.height }

  const bubbleHeight = bubbleEl.value?.offsetHeight ?? 150
  const desiredTop = r.top + r.height / 2 - 30
  const top = Math.max(12, Math.min(desiredTop, window.innerHeight - bubbleHeight - 12))
  bubblePos.value = {
    left: r.right + 14,
    top,
    arrowTop: r.top + r.height / 2 - top - 5,
  }
}

watch([currentStep, isActive], async () => {
  await nextTick()
  reposition()
  // First reposition may have run before the bubble existed (its height was
  // estimated); measure again now that it's in the DOM so the bottom-edge
  // clamp (the Feedback stop) is exact.
  await nextTick()
  reposition()
})

// ── Community links (feedback stop) ──────────────────────────────────────

// Same /link/* redirect scheme as Settings → Updates: the cloud owns the
// destination so an expired invite never needs an app update.
async function openCommunityLink(path) {
  const base = await useCloudAccount().ensureCloudBaseUrl()
  const url = `${base.replace(/\/$/, '')}${path}`
  try {
    const { open } = await import('@tauri-apps/plugin-shell')
    await open(url)
  } catch {
    window.open(url, '_blank', 'noopener,noreferrer')
  }
}

// ── Global listeners while active ────────────────────────────────────────

function onKeydown(e) {
  if (e.key === 'Escape' && isActive.value) endTour('dismissed')
}

function onDocClick(e) {
  if (!isActive.value) return
  if (bubbleEl.value && !bubbleEl.value.contains(e.target)) endTour('dismissed')
}

function onLayoutChange() {
  if (isActive.value) reposition()
}

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
  // Capture-phase click so nav clicks both navigate AND dismiss the tour.
  document.addEventListener('click', onDocClick, true)
  window.addEventListener('resize', onLayoutChange)
  document.addEventListener('scroll', onLayoutChange, true)
})

onBeforeUnmount(() => {
  clearTimeout(startTimer)
  document.removeEventListener('keydown', onKeydown)
  document.removeEventListener('click', onDocClick, true)
  window.removeEventListener('resize', onLayoutChange)
  document.removeEventListener('scroll', onLayoutChange, true)
})
</script>
