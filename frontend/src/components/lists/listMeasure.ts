// Row padding and the preview measure for the collection lists (chats, flows).
// Rows span the pane's full width with the page margin on both sides, so each
// row's right-aligned facts (counts, date) end at the same edge as the page
// header's controls. Only the preview text keeps a maximum width, so lines stay
// short on a broad pane.
// Class strings are spelled out in full so Tailwind sees them.

/** Side padding for rows: the page margin on both sides. */
export const listMeasureX = 'px-page'

/** Left edge of the row's content, for absolutely placed row furniture. */
export const listMeasureLeft = 'left-page'

/** Longest line of a row's preview text. */
export const listPreviewMax = 'max-w-[40rem]'
