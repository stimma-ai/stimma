/**
 * Applying an element resolution plan to a tool's slots, without touching what the user owns.
 * Pure functions; useToolElements.ts drives them.
 */

export interface RefPick { element_asset_id: number; member_key: string; mediaId: number }
export interface LoraPick {
  element_asset_id: number
  lora_key: string
  path: string
  weight: number
  /** What the user's pool had for this LoRA before the element switched it on (null: nothing). */
  prior: { weight: number; enabled: boolean } | null
}
export interface ResolvedRef {
  element_asset_id: number
  member_key: string
  media_id: number
  file_hash?: string
  file_path?: string
  width?: number
  height?: number
}
export interface ResolvedLora { element_asset_id: number; lora_key: string; path: string; weight: number }

export type SlotItem = { mediaId?: number; path?: string; [k: string]: any }
export type LoraItem = { lora: string; weight: number; enabled: boolean }

/**
 * The slots after a plan: the element's picks swap in place, the user's images stay where
 * they are, new picks fill the end up to `maxItems`. Returns the new items and picks.
 */
export function applyRefs(
  items: SlotItem[], picks: RefPick[], selected: ResolvedRef[], maxItems: number,
): { items: SlotItem[]; picks: RefPick[] } {
  const owned = new Set(picks.map(p => p.mediaId))
  const wanted = selected.filter(r => r.media_id != null)
  const wantedIds = new Set(wanted.map(r => r.media_id))
  const userIds = new Set(items.filter(i => i.mediaId == null || !owned.has(i.mediaId)).map(i => i.mediaId))
  // The user's own copy of an image wins: it's never placed twice.
  const toPlace = wanted.filter(r => !userIds.has(r.media_id))
  const present = new Set(items.filter(i => i.mediaId != null && owned.has(i.mediaId) && wantedIds.has(i.mediaId)).map(i => i.mediaId))
  const fresh = toPlace.filter(r => !present.has(r.media_id))
  const out: SlotItem[] = []
  for (const item of items) {
    if (item.mediaId == null || !owned.has(item.mediaId) || wantedIds.has(item.mediaId)) {
      out.push(item)
      continue
    }
    const next = fresh.shift()
    if (next) out.push(slotItem(next))
  }
  for (const r of fresh) {
    if (out.length >= maxItems) break
    out.push(slotItem(r))
  }
  const placed = new Set(out.map(i => i.mediaId))
  return {
    items: out,
    picks: toPlace.filter(r => placed.has(r.media_id)).map(r => ({
      element_asset_id: r.element_asset_id, member_key: r.member_key, mediaId: r.media_id,
    })),
  }
}

function slotItem(r: ResolvedRef): SlotItem {
  const path = r.file_path || ''
  return {
    path,
    filename: path.split('/').pop() || `${r.media_id}`,
    hash: r.file_hash,
    mediaId: r.media_id,
    width: r.width,
    height: r.height,
  }
}

/** The LoRA list after a plan. The user's own (enabled) LoRAs are never touched. */
export function applyLoras(
  loras: LoraItem[], picks: LoraPick[], selected: ResolvedLora[],
): { loras: LoraItem[]; picks: LoraPick[] } {
  let out = loras.map(l => ({ ...l }))
  const wanted = new Map(selected.map(s => [s.path, s]))
  const kept: LoraPick[] = []
  // Undo the element's picks that are no longer wanted.
  for (const pick of picks) {
    if (wanted.has(pick.path)) { kept.push(pick); continue }
    const index = out.findIndex(l => l.lora === pick.path)
    if (index < 0) continue
    if (pick.prior) out[index] = { lora: pick.path, ...pick.prior }
    else out = out.filter((_, i) => i !== index)
  }
  const ownedPaths = new Set(kept.map(p => p.path))
  for (const s of selected) {
    const index = out.findIndex(l => l.lora === s.path)
    const pick = kept.find(p => p.path === s.path)
    if (pick) {
      if (index >= 0) out[index] = { ...out[index], weight: s.weight, enabled: true }
      pick.weight = s.weight
      continue
    }
    if (index >= 0 && out[index].enabled && !ownedPaths.has(s.path)) continue  // the user's
    const prior = index >= 0 ? { weight: out[index].weight, enabled: out[index].enabled } : null
    if (index >= 0) out[index] = { lora: s.path, weight: s.weight, enabled: true }
    else out = [{ lora: s.path, weight: s.weight, enabled: true }, ...out]
    kept.push({ element_asset_id: s.element_asset_id, lora_key: s.lora_key, path: s.path, weight: s.weight, prior })
  }
  return { loras: out, picks: kept }
}

/**
 * The resolver's guidance as the prompt writer reads it. The resolver names each chosen image
 * `{ref:N}` (N: its place in selected_refs); here each becomes "image K", K its place among the
 * tool's input images now, which the user's own images and the order picks landed in decide.
 */
export function renderGuidance(guidance: string, selected: ResolvedRef[], items: SlotItem[]): string {
  return guidance.replace(/\{ref:(\d+)\}/g, (_m, n, offset: number) => {
    const ref = selected[Number(n) - 1]
    const index = ref ? items.findIndex(i => i.mediaId != null && i.mediaId === ref.media_id) : -1
    const text = index >= 0 ? `image ${index + 1}` : 'a reference image'
    // At the start of a sentence it starts with a capital.
    return /(^|[.!?]\s+)$/.test(guidance.slice(0, offset)) ? text[0].toUpperCase() + text.slice(1) : text
  })
}
