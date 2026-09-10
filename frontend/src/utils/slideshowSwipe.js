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
      start = { id: touch.identifier, x: touch.clientX, y: touch.clientY, time: now(), samples: [{ x: touch.clientX, time: now() }] }
    },
    move(event) {
      if (event.touches.length !== 1 || !canNavigate()) { cancel(); return }
      if (!start) return
      const touch = Array.from(event.touches).find(t => t.identifier === start.id)
      if (!touch) { cancel(); return }
      const dx = touch.clientX - start.x, dy = touch.clientY - start.y
      // Lock the axis once intent is clear; small vertical drift must not
      // make a picture jump back underneath a horizontal drag.
      if (!start.axis && Math.max(Math.abs(dx), Math.abs(dy)) > 12) {
        if (Math.abs(dx) > Math.abs(dy) * 1.5) start.axis = 'horizontal'
        else if (Math.abs(dy) > Math.abs(dx) * 1.5) start.axis = 'vertical'
      }
      start.samples.push({ x: touch.clientX, time: now() })
      start.samples = start.samples.filter(sample => now() - sample.time <= 100)
      if (start.axis === 'horizontal') {
        if (event.cancelable) event.preventDefault()
        drag(dx)
      }
    },
    end(event) {
      const previous = start
      start = null
      if (!previous || event.touches.length || !canNavigate()) { release(null); return }
      const touch = Array.from(event.changedTouches).find(t => t.identifier === previous.id)
      if (!touch) { release(null); return }
      const dx = touch.clientX - previous.x, dy = touch.clientY - previous.y
      if (Math.hypot(dx, dy) > 12) suppressUntil = now() + 400
      const sample = previous.samples.find(sample => now() - sample.time <= 100)
      const velocity = sample ? (touch.clientX - sample.x) / Math.max(1, now() - sample.time) : 0
      const flick = Math.abs(dx) > 20 && Math.abs(velocity) > 0.5 && Math.sign(velocity) === Math.sign(dx)
      const horizontal = previous.axis === 'horizontal' || (!previous.axis && now() - previous.time <= 800 && Math.abs(dx) > Math.abs(dy) * 1.5)
      const direction = horizontal && (Math.abs(dx) > 60 || flick)
        ? dx < 0 ? 'next' : 'previous' : null
      release(direction)
      if (direction) navigate(direction)
      else if (previous.axis !== 'horizontal' && now() - previous.time <= 800 && dy < -80 && Math.abs(dy) > Math.abs(dx) * 1.5) navigate('info')
    },
  }
}
