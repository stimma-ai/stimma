// The list-content measure for the collection lists (chats, flows). Rows keep a
// full-width hover target but pad themselves so their content, and the page
// header above them, stop at one maximum width on broad panes and sit centred
// in it. Below that width the padding is the page margin, as everywhere else.
// Class strings are spelled out in full so Tailwind sees them.

/** Side padding that centres content on the measure (rows). */
export const listMeasureX = 'px-[max(var(--page-margin),calc((100%-56rem)/2))]'

/** The same padding for the page header, which already sets `px-page`. */
export const listMeasureHeaderX = '!px-[max(var(--page-margin),calc((100%-56rem)/2))]'

/** Left edge of the measure, for absolutely placed row furniture. */
export const listMeasureLeft = 'left-[max(var(--page-margin),calc((100%-56rem)/2))]'
