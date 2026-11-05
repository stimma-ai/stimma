// Filmstrip tokens (DESIGN.md §1.11 "Filmstrips"), shared by the slideshow strip
// and the tool view's result strip so the two read as one control. Tile size is
// chosen by the height the strip has: `sm` for the phone strips (about 60-74px
// tall), `lg` where the strip has a full row (desktop slideshow, a roomy tool
// view). The matching CSS variables live in style.css (`--strip-*`); keep them
// in step with these numbers.
export const STRIP_TILE = { sm: 52, lg: 96 } as const
export const STRIP_GAP = { sm: 6, lg: 8 } as const
/** Distance from the strip edge to the first tile, room enough for the ring. */
export const STRIP_GUTTER = 8

/** Pick the tile tier for a strip that is `availableHeight` px tall. */
export function stripTier(availableHeight: number): 'sm' | 'lg' {
  return availableHeight < 96 ? 'sm' : 'lg'
}

/** The current tile: one ring, one offset, on the strip's own matte. */
export const STRIP_RING = 'ring-2 ring-selection ring-offset-2 ring-offset-matte'
/** Tiles that are not current: restrained, still identifiable. */
export const STRIP_DIM = 'opacity-80 hover:opacity-100'
