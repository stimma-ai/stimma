import { domToPng } from 'modern-screenshot'
import { useWebSocket } from './useWebSocket'

/**
 * Layout rendering RPC handler.
 *
 * The backend sends `render_layout_request` over the WS when it needs a
 * `.stimmalayout` HTML bundle rasterized — for thumbnails, the agent's
 * vision pass, or flow rasterize_layout. The UI's real browser engine
 * does the actual rendering and ships PNG bytes back.
 *
 * Strategy:
 * 1. Receive {html, assets: {filename: b64}, width, height, dpr}.
 * 2. Wrap each asset in a Blob + URL.createObjectURL → short blob: URL.
 * 3. Rewrite bundle-relative refs in the HTML (`<img src="foo.png">`,
 *    `url(foo.png)`) to the corresponding blob URL.
 * 4. Inject into a srcdoc iframe (style isolation, scoped body/html selectors).
 * 5. Wait for fonts + image loads + a couple of frames for layout settle.
 * 6. Capture via modern-screenshot (better foreignObject + image inlining
 *    than html-to-image; multi-MB image payloads no longer cause silent
 *    drop-outs because images are loaded from short blob URLs, not data URIs
 *    embedded in the source HTML).
 *
 * One render at a time. Layout renders are not bursty enough to need
 * parallelism, and serialization keeps debugging simple.
 */

let installed = false
let queue = Promise.resolve()

const _MIME_BY_EXT = {
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  gif: 'image/gif',
  webp: 'image/webp',
  bmp: 'image/bmp',
  svg: 'image/svg+xml',
}

function _mimeFromName(name) {
  const dot = name.lastIndexOf('.')
  const ext = dot >= 0 ? name.slice(dot + 1).toLowerCase() : ''
  return _MIME_BY_EXT[ext] || 'application/octet-stream'
}

function _b64ToBlob(b64, mime) {
  const bin = atob(b64)
  const len = bin.length
  const bytes = new Uint8Array(len)
  for (let i = 0; i < len; i++) bytes[i] = bin.charCodeAt(i)
  return new Blob([bytes], { type: mime })
}

function _escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function _rewriteRefs(html, blobUrls) {
  // Replace src="filename" / src='filename' and url(filename), url("filename"),
  // url('filename') for each known asset name. Operates on bare filenames only —
  // refs that don't match a known asset (data:, http(s):, absolute paths, etc.)
  // pass through untouched.
  let out = html
  for (const [name, url] of Object.entries(blobUrls)) {
    const esc = _escapeRegex(name)
    // src="name" or src='name'
    out = out.replace(
      new RegExp(`(src\\s*=\\s*)(["'])${esc}\\2`, 'gi'),
      `$1$2${url}$2`,
    )
    // url(name), url("name"), url('name')
    out = out.replace(
      new RegExp(`url\\(\\s*(["']?)${esc}\\1\\s*\\)`, 'gi'),
      `url("${url}")`,
    )
  }
  return out
}

function _waitForImages(doc) {
  const imgs = doc.querySelectorAll('img')
  return Promise.all([...imgs].map(img => {
    if (img.complete && img.naturalWidth > 0) return Promise.resolve()
    return new Promise(resolve => {
      img.addEventListener('load', resolve, { once: true })
      img.addEventListener('error', resolve, { once: true })
    })
  }))
}

function _enqueue(work) {
  const next = queue.then(() => work().catch(err => err))
  queue = next.then(() => undefined, () => undefined)
  return next
}

function _withDeadline(promise, ms, label) {
  // Reject if `promise` doesn't settle within `ms`. The underlying work can't
  // be cancelled, but rejecting lets _renderOne's finally tear down the iframe
  // and, crucially, lets the serial queue advance instead of wedging behind a
  // stuck render.
  let timer
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} exceeded ${ms}ms`)), ms)
  })
  return Promise.race([promise, deadline]).finally(() => clearTimeout(timer))
}

async function _renderOne({ html, width, height, dpr, assets, deadlineMs }) {
  const t0 = performance.now()

  // 1. Materialize assets as blob URLs
  const blobUrls = {}
  for (const [name, b64] of Object.entries(assets || {})) {
    try {
      blobUrls[name] = URL.createObjectURL(_b64ToBlob(b64, _mimeFromName(name)))
    } catch (e) {
      console.warn(`[LayoutRenderer] failed to wrap asset ${name}:`, e)
    }
  }

  // 2. Rewrite refs
  const rewritten = _rewriteRefs(html, blobUrls)

  // 3. Build iframe
  const iframe = document.createElement('iframe')
  iframe.setAttribute('aria-hidden', 'true')
  iframe.setAttribute('tabindex', '-1')
  // Keep srcdoc layouts measurable via contentDocument while preventing bundle
  // scripts from running during thumbnail/rasterization renders.
  iframe.setAttribute('sandbox', 'allow-same-origin')
  iframe.style.cssText = [
    'position:fixed',
    'left:-99999px',
    'top:0',
    `width:${width}px`,
    `height:${height === 'auto' || !height ? '10px' : height + 'px'}`,
    'border:0',
    'background:transparent',
    'pointer-events:none',
    'opacity:0',
  ].join(';')
  iframe.srcdoc = rewritten
  document.body.appendChild(iframe)

  // Bound the whole prep+capture sequence so a hung iframe load, font wait, or
  // capture can't stall the renderer forever. Trim a small margin off the
  // backend's budget so our error response beats its timeout.
  const budget = Math.max(5000, (deadlineMs || 30000) - 1000)

  const work = (async () => {
    await new Promise((resolve, reject) => {
      iframe.addEventListener('load', resolve, { once: true })
      iframe.addEventListener('error', () => reject(new Error('iframe load error')), { once: true })
    })

    const innerDoc = iframe.contentDocument
    if (!innerDoc) throw new Error('iframe contentDocument unavailable')

    // 4. Wait for fonts + images + a frame
    if (innerDoc.fonts && typeof innerDoc.fonts.ready?.then === 'function') {
      try { await innerDoc.fonts.ready } catch { /* ignore */ }
    }
    await _waitForImages(innerDoc)
    // Two animation frames to let the layout fully settle after image decode.
    await new Promise(r => requestAnimationFrame(() => r(null)))
    await new Promise(r => requestAnimationFrame(() => r(null)))

    // 5. Auto-height: measure rendered content
    let renderHeight = height
    if (renderHeight === 'auto' || !renderHeight) {
      const measured = Math.max(
        innerDoc.documentElement.scrollHeight,
        innerDoc.body ? innerDoc.body.scrollHeight : 0,
        1,
      )
      // Cap at 5x width to guard against viewport-unit blowups in headless ctx.
      renderHeight = Math.min(measured, width * 5)
      iframe.style.height = renderHeight + 'px'
      await new Promise(r => requestAnimationFrame(() => r(null)))
    }

    // 6. Capture
    const node = innerDoc.body || innerDoc.documentElement
    const imgCount = innerDoc.querySelectorAll('img').length
    const tBeforeCapture = performance.now()

    const dataUrl = await domToPng(node, {
      width,
      height: renderHeight,
      scale: dpr || 2,
      backgroundColor: null,
      timeout: budget,
      style: { margin: '0', padding: '0' },
    })

    const tEnd = performance.now()
    console.log(
      `[LayoutRenderer] ${width}x${renderHeight} dpr=${dpr} imgs=${imgCount} ` +
      `assets=${Object.keys(blobUrls).length} ` +
      `prep=${(tBeforeCapture - t0).toFixed(0)}ms ` +
      `capture=${(tEnd - tBeforeCapture).toFixed(0)}ms`,
    )

    const comma = dataUrl.indexOf(',')
    const b64 = comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl
    return { png_b64: b64 }
  })()

  try {
    return await _withDeadline(work, budget, 'layout render')
  } finally {
    iframe.remove()
    Object.values(blobUrls).forEach(url => {
      try { URL.revokeObjectURL(url) } catch { /* ignore */ }
    })
  }
}

export function setupLayoutRenderer() {
  if (installed) return
  installed = true

  const { on, send } = useWebSocket()

  on('render_layout_request', (data) => {
    if (!data || !data.request_id) return
    const { request_id, html, width, height, dpr, assets, deadline_ms } = data

    _enqueue(async () => {
      try {
        const result = await _renderOne({ html, width, height, dpr, assets, deadlineMs: deadline_ms })
        send('render_layout_response', { request_id, png_b64: result.png_b64 })
      } catch (err) {
        const msg = err && err.message ? err.message : String(err)
        console.error('[LayoutRenderer] render failed:', err)
        send('render_layout_response', { request_id, error: msg })
      }
    })
  })

  console.log('[LayoutRenderer] installed (modern-screenshot)')
}

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    installed = false
  })
}
