// One icon-button style for every phone header (DESIGN.md §1.11): a bare 44px
// target, secondary glyph at the canvas size, no fill. A toggle that is on
// takes the neutral raised fill. The only filled treatments are the primary
// create (icon) and the primary label, one fill style: solid accent, 36px
// tall inside the 44px target, rounded-md.
//
// The strip pads itself by --page-margin (`px-page`), the same token the
// desktop header and every other strip read. The first and last bare button
// pull back by the space between the 44px target and its 18px glyph, so the
// glyphs, not the invisible targets, sit on the margin. A filled primary puts
// its FILL's edge on the margin instead.
export const compactIconButton =
  'w-11 h-11 flex-none first:-ml-[13px] last:-mr-[13px] flex items-center justify-center rounded-md border-none bg-transparent text-content-secondary transition-colors duration-150 hover:text-content disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 ring-accent/60'
export const compactIconButtonOn = 'bg-overlay-light text-content'
const compactFill = 'relative isolate !text-accent-on hover:!text-accent-on before:absolute before:-z-10 before:rounded-md before:bg-accent before:transition-colors hover:before:bg-accent/90'
// The icon primary: a 36px square fill centred in the 44px target. Last in the
// strip, the fill's edge (4px in from the target) sits on the margin.
export const compactPrimaryCreate = `${compactFill} before:inset-1 last:!-mr-1`
// The labelled primary (Save, Done): the same fill, 36px tall, as wide as its
// label needs, inside a 44px-tall target. The fill IS the button's width, so its
// edge sits on the margin when it is last. Pair with compactIconButton's
// size overridden: `[compactPrimaryLabel]` replaces w-11 with auto width.
export const compactPrimaryLabel = `${compactFill} before:inset-x-0 before:inset-y-1 !w-auto min-w-11 px-3.5 text-ctl font-medium last:!mr-0`
export const compactIcon = 'h-icon-canvas w-icon-canvas'
export const compactTitle = 'font-brand text-[18px] font-semibold leading-6 text-content'
