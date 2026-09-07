/** One-finger navigation belongs to the unzoomed picture, never its controls. */
export function createSlideshowSwipe({ canNavigate, navigate, now = () => Date.now() }) {
  let start = null
  let suppressUntil = 0
  function cancel() {
    start = null
    suppressUntil = now() + 400
  }
  return {
    cancel,
    suppressClick: () => now() < suppressUntil,
    start(event) {
      start = null
      if (event.touches.length !== 1 || !canNavigate()) { cancel(); return }
      if (event.target?.closest?.('button, a, input, select, textarea, [role="slider"], [role="button"], [contenteditable="true"], [data-slideshow-interactive]')) return
      const touch = event.touches[0]
      start = { id: touch.identifier, x: touch.clientX, y: touch.clientY, time: now() }
    },
    move(event) {
      if (event.touches.length !== 1 || !canNavigate()) cancel()
    },
    end(event) {
      const previous = start
      start = null
      if (!previous || event.touches.length || !canNavigate()) return
      const touch = Array.from(event.changedTouches).find(t => t.identifier === previous.id)
      if (!touch) return
      const dx = touch.clientX - previous.x, dy = touch.clientY - previous.y
      if (Math.hypot(dx, dy) > 12) suppressUntil = now() + 400
      if (now() - previous.time > 800) return
      if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) navigate(dx < 0 ? 'next' : 'previous')
      else if (dy < -80 && Math.abs(dy) > Math.abs(dx) * 1.5) navigate('info')
    },
  }
}
