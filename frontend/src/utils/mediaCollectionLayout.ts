// Sizing rules for an agent's image collection in chat. Pure so the rules can
// be read and tested without a browser.
export type CollectionSize = 's' | 'm' | 'l'
export type CollectionView = 'grid' | 'preview'

export const COLLECTION_SIZES: CollectionSize[] = ['s', 'm', 'l']
const GRID_TARGET: Record<CollectionSize, number> = { s: 96, m: 152, l: 240 }
const PHONE_COLUMNS: Record<CollectionSize, number> = { s: 4, m: 3, l: 2 }
const STRIP_SIZE: Record<CollectionSize, number> = { s: 56, m: 72, l: 96 }
const HERO_SCALE: Record<CollectionSize, number> = { s: 0.62, m: 0.84, l: 1 }
const GRID_GAP = 2
const COLLAPSED_ROWS = 3
const HEADER_HEIGHT = 44
const HERO_MIN = 200
const HERO_MAX = 640
const CHAT_MARGIN = 24

// Grid when the whole set fits on screen without paging; past that, Preview,
// whose height stays bounded however many images the agent shows.
export function startingView(count: number, compact: boolean): CollectionView {
  return count <= (compact ? 9 : 12) ? 'grid' : 'preview'
}

export function gridColumns({ count, width, size, compact }: { count: number; width: number; size: CollectionSize; compact: boolean }): number {
  if (count <= 4) return compact && count === 4 ? 2 : Math.max(1, count)
  if (compact) return PHONE_COLUMNS[size]
  const fit = Math.max(2, Math.floor((width + GRID_GAP) / (GRID_TARGET[size] + GRID_GAP)))
  if (count > 12) return fit
  // Small sets take the column count that leaves the smallest hole in the last row.
  const hole = (columns: number) => (columns - (count % columns)) % columns
  return [fit, fit - 1, fit - 2].filter(columns => columns >= 2).sort((a, b) => hole(a) - hole(b))[0]
}

export function visibleTiles({ count, columns, expanded }: { count: number; columns: number; expanded: boolean }): number {
  return expanded ? count : Math.min(count, columns * COLLAPSED_ROWS)
}

export function stripTileSize(size: CollectionSize, compact: boolean): number {
  return compact ? Math.round(STRIP_SIZE[size] * 0.86) : STRIP_SIZE[size]
}

// The picture, its strip and the header fit the chat together, so moving
// through a set never asks for a vertical scroll.
export function heroHeight({ chatHeight, width, size, stripSize }: { chatHeight: number; width: number; size: CollectionSize; stripSize: number }): number {
  const fit = Math.max(HERO_MIN, chatHeight - HEADER_HEIGHT - stripSize - CHAT_MARGIN)
  return Math.min(HERO_MAX, Math.round(width * 1.1) || HERO_MAX, Math.round(fit * HERO_SCALE[size]))
}
