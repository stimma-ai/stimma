/** One-finger navigation belongs to the unzoomed picture, never its controls. */
export function createSlideshowSwipe({ canNavigate, navigate, drag = () => {}, release = () => {}, now = () => Date.now() }) {
  let start = null
  let suppressUntil = 0
  function cancel() {
    start = null
    release(null)
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
      if (event.touches.length !== 1 || !canNavigate()) { cancel(); return }
      if (!start) return
      const touch = Array.from(event.touches).find(t => t.identifier === start.id)
      if (!touch) { cancel(); return }
      const dx = touch.clientX - start.x, dy = touch.clientY - start.y
      if (Math.abs(dx) > 12 && Math.abs(dx) > Math.abs(dy) * 1.5) start.horizontal = true
      drag(Math.abs(dx) > Math.abs(dy) * 1.5 ? dx : 0)
    },
    end(event) {
      const previous = start
      start = null
      if (!previous || event.touches.length || !canNavigate()) { release(null); return }
      const touch = Array.from(event.changedTouches).find(t => t.identifier === previous.id)
      if (!touch) { release(null); return }
      const dx = touch.clientX - previous.x, dy = touch.clientY - previous.y
      if (Math.hypot(dx, dy) > 12) suppressUntil = now() + 400
      const direction = (previous.horizontal || now() - previous.time <= 800) && Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5
        ? dx < 0 ? 'next' : 'previous' : null
      release(direction)
      if (direction) navigate(direction)
      else if (now() - previous.time <= 800 && dy < -80 && Math.abs(dy) > Math.abs(dx) * 1.5) navigate('info')
    },
  }
}
