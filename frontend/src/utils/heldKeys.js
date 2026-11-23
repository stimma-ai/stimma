import { getCurrentScope, onScopeDispose, ref, watch } from 'vue'

// The keys of `source` that have stayed in it for at least `ms`. A key that
// leaves `source` drops out at once; one that returns starts over.
export function holdKeys(source, ms) {
  const held = ref(new Set())
  const timers = new Map()
  watch(source, (raw) => {
    const next = new Set([...held.value].filter(key => raw.has(key)))
    if (next.size !== held.value.size) held.value = next
    for (const [key, timer] of timers) {
      if (!raw.has(key)) { clearTimeout(timer); timers.delete(key) }
    }
    for (const key of raw) {
      if (held.value.has(key) || timers.has(key)) continue
      timers.set(key, setTimeout(() => {
        timers.delete(key)
        held.value = new Set([...held.value, key])
      }, ms))
    }
  }, { immediate: true })
  if (getCurrentScope()) onScopeDispose(() => { for (const timer of timers.values()) clearTimeout(timer) })
  return held
}
