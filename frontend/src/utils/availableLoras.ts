import type { LoraPoolItem } from '../composables/useLoraPool'

/** Keep pool membership, but deselect LoRAs the provider no longer offers. */
export function disableUnavailableLoras(items: LoraPoolItem[], availablePaths: Set<string> | null): LoraPoolItem[] {
  if (!availablePaths) return items
  let changed = false
  const updated = items.map(item => {
    if (!item.enabled || availablePaths.has(item.lora)) return item
    changed = true
    return { ...item, enabled: false }
  })
  return changed ? updated : items
}
