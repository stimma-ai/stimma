/**
 * One width-based sizing rule for every grid of square media tiles (browse,
 * collections, and any strip that wants to match them). The column count comes from
 * the real content width, never from the layout tier: a folded phone, an
 * unfolded one and a desktop pane all ask the same question.
 *
 * - A tile is never narrower than the density's minimum, so the count falls as
 *   the pane narrows.
 * - Three columns is the floor: the phone's rhythm, kept at any width.
 * - Tiles share the width left after the gutters and so grow to fill it; a
 *   short last row keeps the tile size.
 * - Gutters are 2px between tiles and equal to the matte's outer padding.
 *
 * Density is a documented choice per surface (DESIGN.md "Tile grids"):
 * `browse` scans many assets, `collection` is a curated sheet and runs a touch larger.
 */
export const TILE_GAP_PX = 2
export const MIN_COLUMNS = 3
export type TileDensity = 'browse' | 'collection'
export const MIN_TILE_PX: Record<TileDensity, number> = { browse: 200, collection: 220 }

/** `inner` is the width the tiles and their gutters share (outer padding excluded). */
export function tileColumns(inner: number, density: TileDensity): number {
  const min = MIN_TILE_PX[density]
  return Math.max(MIN_COLUMNS, Math.floor((inner + TILE_GAP_PX) / (min + TILE_GAP_PX)))
}

/** Width of one tile for `columns` across `inner`. */
export function tileWidth(inner: number, columns: number): number {
  return (inner - TILE_GAP_PX * (columns - 1)) / columns
}
