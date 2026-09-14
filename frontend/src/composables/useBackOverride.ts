import { computed, onActivated, onDeactivated, onMounted, onBeforeUnmount, shallowReactive } from 'vue'

interface BackOverride { enabled: () => boolean; back: () => void }
const overrides = shallowReactive<BackOverride[]>([])
export const hasBackOverride = computed(() => overrides.some(entry => entry.enabled()))

export function consumeBackOverride(): boolean {
  const entry = [...overrides].reverse().find(entry => entry.enabled())
  if (!entry) return false
  entry.back()
  return true
}

/** A mounted, visible view may consume header Back before route navigation. */
export function useBackOverride(enabled: () => boolean, back: () => void) {
  const entry = { enabled, back }
  function activate() { if (!overrides.includes(entry)) overrides.push(entry) }
  function deactivate() {
    const index = overrides.indexOf(entry)
    if (index >= 0) overrides.splice(index, 1)
  }
  onMounted(activate)
  onActivated(activate)
  onDeactivated(deactivate)
  onBeforeUnmount(deactivate)
}
