/** Preserve visible dwell time while suspension spans one or more callbacks. */
export function createSlideshowDwell(now = () => performance.now()) {
  let shownAt = now()
  let pausedAt = null
  return {
    shown() { shownAt = pausedAt ?? now() },
    pause() { if (pausedAt === null) pausedAt = now() },
    resume() {
      if (pausedAt === null) return
      shownAt += now() - pausedAt
      pausedAt = null
    },
    elapsed: () => (pausedAt ?? now()) - shownAt,
  }
}
