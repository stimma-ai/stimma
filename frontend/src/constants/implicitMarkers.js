export const EDITED_MARKER_ID = 'implicit:edited'

export const EDITED_MARKER = Object.freeze({
  id: EDITED_MARKER_ID,
  key: 'edited',
  name: 'edited',
  icon_svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" data-slot="icon"><path d="M21.731 2.269a2.625 2.625 0 0 0-3.712 0l-1.157 1.157 3.712 3.712 1.157-1.157a2.625 2.625 0 0 0 0-3.712ZM19.513 8.199l-3.712-3.712-12.15 12.15a5.25 5.25 0 0 0-1.32 2.214l-.8 2.685a.75.75 0 0 0 .933.933l2.685-.8a5.25 5.25 0 0 0 2.214-1.32L19.513 8.2Z" /></svg>',
  color: '#14b8a6',
  implicit: true,
  source: 'system',
})

// Filter-only: offered while something is scheduled to auto-delete. Tiles
// carry their own countdown instead of this glyph.
export const EXPIRING_MARKER_ID = 'implicit:expiring'

export const EXPIRING_MARKER = Object.freeze({
  id: EXPIRING_MARKER_ID,
  key: 'expiring',
  name: 'expiring',
  icon_svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" data-slot="icon"><path fill-rule="evenodd" d="M12 2.25c-5.385 0-9.75 4.365-9.75 9.75s4.365 9.75 9.75 9.75 9.75-4.365 9.75-9.75S17.385 2.25 12 2.25ZM12.75 6a.75.75 0 0 0-1.5 0v6c0 .414.336.75.75.75h4.5a.75.75 0 0 0 0-1.5h-3.75V6Z" clip-rule="evenodd" /></svg>',
  color: '#f59e0b',
  implicit: true,
  source: 'system',
})

export const IMPLICIT_MARKERS = Object.freeze([EDITED_MARKER, EXPIRING_MARKER])
