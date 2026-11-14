import { ref } from 'vue'

/**
 * A part's row under the prompt flashes when something is used in it from an image, so the eye
 * finds what changed. `n` restarts the flash when the same row is used again.
 */
export const slotFlash = ref<{ id: string; n: number } | null>(null)
let n = 0
let timer: ReturnType<typeof setTimeout> | null = null

export function flashSlot(id: string) {
  slotFlash.value = { id, n: ++n }
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => { slotFlash.value = null; timer = null }, 900)
}
