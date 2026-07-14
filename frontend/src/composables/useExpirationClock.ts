import { onMounted, onUnmounted, readonly, ref } from 'vue'
import { formatRemainingTime as formatRemainingTimeValue } from '../utils/timeFormat'

const now = ref(Date.now())
let consumers = 0
let timer: ReturnType<typeof setInterval> | null = null

function startClock() {
  consumers += 1
  if (timer) return
  now.value = Date.now()
  timer = setInterval(() => {
    now.value = Date.now()
  }, 10_000)
}

function stopClock() {
  consumers = Math.max(0, consumers - 1)
  if (consumers > 0 || !timer) return
  clearInterval(timer)
  timer = null
}

/** One shared clock for every visible expiration badge and warning. */
export function useExpirationClock() {
  onMounted(startClock)
  onUnmounted(stopClock)

  function formatRemainingTime(deadline?: string | null) {
    // Reading the shared clock makes template/computed callers reactive.
    void now.value
    return formatRemainingTimeValue(deadline)
  }

  return {
    now: readonly(now),
    formatRemainingTime,
  }
}
