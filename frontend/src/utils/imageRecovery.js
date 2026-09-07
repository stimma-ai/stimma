/** Retry failed visible media once per confirmed connection recovery. */
export function subscribeImageRecovery({ element, failed, retry, win = window }) {
  let observer = null
  function recover() {
    observer?.disconnect()
    observer = null
    if (!failed()) return
    const target = element()
    if (!target) return
    const rect = target.getBoundingClientRect()
    if (target.isConnected && rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0 && rect.top < win.innerHeight && rect.left < win.innerWidth) {
      retry()
    } else if (win.IntersectionObserver) {
      observer = new win.IntersectionObserver(entries => {
        if (!entries.some(entry => entry.isIntersecting)) return
        observer?.disconnect()
        observer = null
        if (failed()) retry()
      })
      observer.observe(target)
    }
  }
  win.addEventListener('stimma:media-reconnected', recover)
  return () => {
    observer?.disconnect()
    win.removeEventListener('stimma:media-reconnected', recover)
  }
}

export function recoveredImageUrl(src, revision) {
  if (!src || !revision || /^(data|blob):/.test(src)) return src
  const [base, hash] = src.split('#', 2)
  return `${base}${base.includes('?') ? '&' : '?'}_recovery=${revision}${hash === undefined ? '' : `#${hash}`}`
}
