export type BrowserMediaLike = {
  id?: number | null
  asset_id?: number | null
  media_id?: number | null
  revision_id?: number | null
}

/** Stable identity for cards, selection, organization, and browser URLs. */
export function assetIdOf(item: BrowserMediaLike): number | null {
  return item.asset_id ?? item.id ?? null
}

/** Exact current payload for thumbnails, tools, lineage, compare, and editors. */
export function mediaIdOf(item: BrowserMediaLike): number | null {
  return item.media_id ?? item.id ?? null
}

export function hasAssetIdentity(item: BrowserMediaLike): boolean {
  return item.asset_id != null
}
