function getFileName(filePath) {
  if (!filePath) return 'Unknown'
  return filePath.split('/').pop()
}

/**
 * Create a print-only overlay that covers the entire page with just the printable content,
 * invoke the native print dialog via Tauri's webview.print(), then remove the overlay.
 *
 * The overlay uses @media print styles to hide the app and show only print content.
 * WKWebView ignores @page { size } so we don't try to control orientation — the user
 * can pick portrait/landscape in the print dialog.
 */
async function printWithOverlay(contentHtml) {
  // Remove any previous print styles
  const prev = document.getElementById('stimma-print-styles')
  if (prev) prev.remove()

  const styleEl = document.createElement('style')
  styleEl.id = 'stimma-print-styles'
  styleEl.textContent = `
    @media print {
      html, body {
        margin: 0 !important;
        padding: 0 !important;
        height: auto !important;
        overflow: visible !important;
      }
      body > *:not(#stimma-print-overlay) { display: none !important; }
      #stimma-print-overlay {
        display: block !important;
        position: static !important;
        background: white !important;
        margin: 0;
        padding: 0;
        page-break-after: avoid;
        page-break-inside: avoid;
      }
      @page {
        margin: 0.25in;
      }
    }
  `
  document.head.appendChild(styleEl)

  // Create the overlay (hidden on screen, visible only in print)
  const overlay = document.createElement('div')
  overlay.id = 'stimma-print-overlay'
  overlay.style.cssText = 'display:none;'
  overlay.innerHTML = contentHtml
  document.body.appendChild(overlay)

  // Wait for images to load
  const images = Array.from(overlay.querySelectorAll('img'))
  const imagePromises = images.map(img => {
    if (img.complete) return Promise.resolve()
    return new Promise(resolve => {
      img.onload = resolve
      img.onerror = resolve
    })
  })
  await Promise.race([
    Promise.all(imagePromises),
    new Promise(resolve => setTimeout(resolve, 10000))
  ])

  // Trigger print
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('print_webview')
  } catch {
    // Fallback for browser mode
    window.print()
  }

  // Clean up after a short delay to let the print dialog finish
  setTimeout(() => {
    overlay.remove()
    styleEl.remove()
  }, 2000)
}

export function usePrint() {

  function printAssetDetail(mediaItem, imageUrl) {
    const isLandscape = mediaItem.width && mediaItem.height && mediaItem.width > mediaItem.height

    let html
    if (isLandscape) {
      // Rotate -90° (clockwise). The image is laid out at 10in × 7.5in (landscape dims),
      // then rotated to fill the portrait page. The wrapper is sized to the post-rotation
      // dimensions (7.5in × 10in) so nothing clips.
      html = `
        <div style="width:7.5in;height:10in;margin:0 auto;display:flex;align-items:center;justify-content:center;overflow:hidden;">
          <img src="${imageUrl}" style="max-width:10in;max-height:7.5in;object-fit:contain;transform:rotate(-90deg);" />
        </div>
      `
    } else {
      html = `<img src="${imageUrl}" style="max-width:7.5in;max-height:10in;object-fit:contain;display:block;margin:0 auto;" />`
    }
    printWithOverlay(html)
  }

  function printContactSheet(mediaItems, getThumbnailUrlFn) {
    const items = mediaItems.slice(0, 100)

    const cells = items.map(item => {
      const thumbUrl = getThumbnailUrlFn(item.file_hash || item.id, 512)
      const name = getFileName(item.file_path)
      const truncName = name.length > 30 ? name.substring(0, 27) + '...' : name

      return `<div style="break-inside:avoid;text-align:center;">
        <div style="width:100%;aspect-ratio:1;overflow:hidden;background:#f0f0f0;border-radius:4px;margin-bottom:4px;">
          <img src="${thumbUrl}" style="width:100%;height:100%;object-fit:cover;" />
        </div>
        <div style="font-size:10px;font-weight:500;color:#111;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${truncName}</div>
      </div>`
    }).join('')

    const html = `
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;width:100%;">
        ${cells}
      </div>
    `
    printWithOverlay(html)
  }

  return { printAssetDetail, printContactSheet }
}
