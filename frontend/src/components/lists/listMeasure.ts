// The list-content measure for the collection lists (chats, flows). The measure
// is anchored to the left page margin, the same edge the page header's title
// and every other page start on. Rows keep a full-width hover target but pad
// themselves so their content, and the header above them, stop at one maximum
// width (56rem) from that edge on broad panes. Below that width the padding is
// the page margin on both sides, as everywhere else.
// Class strings are spelled out in full so Tailwind sees them.

/** Side padding for rows: page margin on the left, the measure's remainder on the right. */
export const listMeasureX = 'pl-page pr-[max(var(--page-margin),calc(100%-56rem-var(--page-margin)))]'

/** The same padding for the page header, which already sets `px-page`. */
export const listMeasureHeaderX = '!pr-[max(var(--page-margin),calc(100%-56rem-var(--page-margin)))]'

/** Left edge of the measure, for absolutely placed row furniture. */
export const listMeasureLeft = 'left-page'
