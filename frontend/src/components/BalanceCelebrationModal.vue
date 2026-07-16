<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="celebration"
        data-testid="balance-celebration"
        class="fixed inset-0 z-[10010] flex items-center justify-center bg-black/50 backdrop-blur-sm"
        @click.self="dismissCelebration"
      >
        <div class="bg-surface border border-edge rounded-xl shadow-2xl max-w-md w-full mx-4 overflow-hidden relative">
          <!-- Celebration hero -->
          <div class="celebration-hero px-6 pt-10 pb-8 text-center relative overflow-hidden">
            <div class="glow-base" aria-hidden="true" />
            <span
              v-for="mote in motes"
              :key="mote.id"
              class="mote"
              :style="mote.style"
              aria-hidden="true"
            />
            <div class="relative">
              <div class="badge mx-auto w-14 h-14 relative">
                <div class="pulse" aria-hidden="true" />
                <svg class="w-full h-full overflow-visible" viewBox="0 0 60 60" fill="none">
                  <defs>
                    <linearGradient id="celebration-cloud-grad" x1="0%" y1="0%" x2="100%" y2="0%">
                      <stop offset="0%" stop-color="#0d9488" />
                      <stop offset="50%" stop-color="#06b6d4" />
                      <stop offset="100%" stop-color="#6366f1" />
                    </linearGradient>
                  </defs>
                  <circle class="ring" cx="30" cy="30" r="28" stroke="url(#celebration-cloud-grad)" />
                  <path class="tick" d="M18 31 l8 8 l16 -18" stroke="url(#celebration-cloud-grad)" />
                </svg>
              </div>
              <h3 class="stagger stagger-1 mt-5 text-xl font-semibold text-content tracking-tight">
                Your <span class="stimma-cloud-text whitespace-nowrap">Stimma account</span> is ready
              </h3>
              <p class="stagger stagger-2 mt-1.5 mx-auto max-w-[340px] text-sm text-content-secondary leading-relaxed">
                {{ balanceLine }}
              </p>
            </div>
          </div>

          <!-- Footer -->
          <div class="stagger stagger-3 px-6 py-5 border-t border-edge flex justify-center">
            <button
              data-testid="celebration-dismiss"
              @click="dismissCelebration"
              class="px-6 py-2.5 bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 hover:from-teal-500 hover:via-cyan-400 hover:to-indigo-400 text-white rounded-lg text-sm font-semibold transition-all"
            >
              Start creating
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed } from 'vue'
import { useBalanceCelebration } from '../composables/useAccountEvents'
import { formatBalance } from '../composables/useCloudAccount'

const { celebration, dismissCelebration } = useBalanceCelebration()

const balanceLine = computed(() => {
  const amount = formatBalance(celebration.value?.credits)
  const credits = amount ? `${amount} in credits added.` : 'Credits added.'
  return `${credits} Generation and the agent are ready to use.`
})

// Gradient motes drifting up from the base glow; positions/timings are
// fixed so the animation is identical every time (no runtime randomness).
const MOTES = [
  { left: '12%', size: 5, duration: 2.6, delay: 0.4, drift: 14, color: '#2dd4bf' },
  { left: '24%', size: 4, duration: 3.1, delay: 0.9, drift: -10, color: '#06b6d4' },
  { left: '38%', size: 6, duration: 2.4, delay: 0.6, drift: 18, color: '#67e8f9' },
  { left: '52%', size: 4, duration: 2.9, delay: 1.2, drift: -8, color: '#818cf8' },
  { left: '66%', size: 5, duration: 2.5, delay: 0.5, drift: 12, color: '#6366f1' },
  { left: '78%', size: 4, duration: 3.2, delay: 1.0, drift: -14, color: '#22d3ee' },
  { left: '88%', size: 5, duration: 2.7, delay: 0.7, drift: 10, color: '#0d9488' },
  { left: '45%', size: 3, duration: 3.4, delay: 1.5, drift: 6, color: '#67e8f9' },
]
const motes = MOTES.map((m, i) => ({
  id: i,
  style: {
    left: m.left,
    width: `${m.size}px`,
    height: `${m.size}px`,
    backgroundColor: m.color,
    animationDuration: `${m.duration}s`,
    animationDelay: `${m.delay}s`,
    '--drift': `${m.drift}px`,
  },
}))
</script>

<style scoped>
/* Radial washes and draw-in animations aren't expressible with Tailwind utilities. */
.celebration-hero {
  background:
    radial-gradient(ellipse at 50% -40%, rgba(6, 182, 212, 0.22), transparent 65%),
    radial-gradient(ellipse at 100% 0%, rgba(99, 102, 241, 0.16), transparent 55%),
    radial-gradient(ellipse at 0% 0%, rgba(13, 148, 136, 0.14), transparent 55%);
}

/* Check badge: ring draws in, then the tick strokes in, then a pulse ring expands. */
.ring {
  stroke-width: 2.5;
  stroke-linecap: round;
  stroke-dasharray: 176;
  stroke-dashoffset: 176;
  transform: rotate(-90deg);
  transform-origin: center;
  animation: draw-ring 0.55s cubic-bezier(0.6, 0, 0.3, 1) 0.1s forwards;
}

.tick {
  stroke-width: 4;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-dasharray: 36;
  stroke-dashoffset: 36;
  animation: draw-tick 0.35s cubic-bezier(0.5, 0, 0.3, 1) 0.55s forwards;
}

@keyframes draw-ring {
  to { stroke-dashoffset: 0; }
}

@keyframes draw-tick {
  to { stroke-dashoffset: 0; }
}

.pulse {
  position: absolute;
  inset: -4px;
  border-radius: 50%;
  border: 2px solid rgba(6, 182, 212, 0.5);
  opacity: 0;
  transform: scale(0.7);
  animation: pulse-out 0.9s ease-out 0.8s forwards;
}

@keyframes pulse-out {
  0% { opacity: 0.8; transform: scale(0.75); }
  100% { opacity: 0; transform: scale(1.7); }
}

/* Gradient glow settling at the modal base, feeding the rising motes. */
.glow-base {
  position: absolute;
  left: 50%;
  bottom: -60px;
  width: 320px;
  height: 120px;
  transform: translateX(-50%);
  background: radial-gradient(ellipse at center, rgba(6, 182, 212, 0.3), rgba(99, 102, 241, 0.12) 55%, transparent 75%);
  filter: blur(14px);
  opacity: 0;
  pointer-events: none;
  animation: glow-in 1.2s ease 0.2s forwards;
}

@keyframes glow-in {
  to { opacity: 1; }
}

.mote {
  position: absolute;
  bottom: -10px;
  border-radius: 50%;
  opacity: 0;
  pointer-events: none;
  filter: blur(0.5px);
  animation-name: float-up;
  animation-timing-function: ease-out;
  animation-fill-mode: forwards;
}

@keyframes float-up {
  0% { opacity: 0; transform: translateY(0) translateX(0); }
  15% { opacity: 0.9; }
  100% { opacity: 0; transform: translateY(-240px) translateX(var(--drift)); }
}

/* Title, subtitle, and footer rise in three beats after the check lands. */
.stagger {
  opacity: 0;
  transform: translateY(8px);
  animation: rise 0.5s cubic-bezier(0.2, 0.6, 0.2, 1) forwards;
}

.stagger-1 { animation-delay: 0.75s; }
.stagger-2 { animation-delay: 0.9s; }
.stagger-3 { animation-delay: 1.05s; }

@keyframes rise {
  to { opacity: 1; transform: translateY(0); }
}

@media (prefers-reduced-motion: reduce) {
  .ring,
  .tick,
  .pulse,
  .glow-base,
  .mote,
  .stagger {
    animation-duration: 0.01s !important;
    animation-delay: 0s !important;
  }
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.15s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active .bg-surface,
.modal-leave-active .bg-surface {
  transition: transform 0.15s ease;
}

.modal-enter-from .bg-surface,
.modal-leave-to .bg-surface {
  transform: scale(0.95);
}
</style>
