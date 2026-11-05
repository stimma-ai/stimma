// One icon-button style for every phone header (DESIGN.md §1.11): a bare 44px
// target, secondary glyph at the canvas size, no fill. A toggle that is on
// takes the neutral raised fill. The only filled treatment is a primary create.
// The first and last button pull 8px into the row's 12px padding so their
// glyphs sit on the 16px page margin, not on the button edge.
export const compactIconButton =
  'w-11 h-11 flex-none first:-ml-2 last:-mr-2 flex items-center justify-center rounded-md border-none bg-transparent text-content-secondary transition-colors duration-150 hover:text-content disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 ring-accent/60'
export const compactIconButtonOn = 'bg-overlay-light text-content'
// The one filled button: a solid accent 36px square inside the 44px target.
// Its edge (not the glyph) sits on the page margin when it is last in the strip.
export const compactPrimaryCreate = 'relative isolate last:!mr-0 !text-accent-on hover:!text-accent-on before:absolute before:inset-1 before:-z-10 before:rounded-md before:bg-accent before:transition-colors hover:before:bg-accent/90'
export const compactIcon = 'h-icon-canvas w-icon-canvas'
export const compactTitle = 'font-brand text-[18px] font-semibold leading-6 text-content'
