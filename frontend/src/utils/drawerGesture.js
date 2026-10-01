/** The compact navigation drawer owns single-finger starts at the left edge. */
export function isDrawerEdgeTouch(event) {
  return event.touches.length === 1 && event.touches[0].clientX >= 0 && event.touches[0].clientX <= 24
}
