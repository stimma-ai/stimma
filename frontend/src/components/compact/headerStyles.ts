// One icon-button style for every phone header (DESIGN.md §1.11): a bare 44px
// target, secondary glyph at the canvas size, no fill. A toggle that is on
// takes the neutral raised fill. The only filled treatment is a primary create.
export const compactIconButton =
  'w-11 h-11 flex-none flex items-center justify-center rounded-md border-none bg-transparent text-content-secondary transition-colors duration-150 hover:text-content disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 ring-accent/60'
export const compactIconButtonOn = 'bg-overlay-light text-content'
export const compactPrimaryCreate = 'bg-accent/15 text-accent-hi hover:bg-accent/25'
export const compactIcon = 'h-icon-canvas w-icon-canvas'
export const compactTitle = 'font-brand text-[18px] font-semibold leading-6 text-content'
