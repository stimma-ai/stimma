// Escape dismisses one visible layer. Resolve by the same z-tier and document
// order used to paint teleported dialogs and menus, not listener mount order.
export function hasEscapeLayer() {
  return [...document.querySelectorAll('[data-modal-layer], [data-escape-layer]')]
    .some(layer => layer.getClientRects().length > 0)
}

function stackingContexts(element, styles) {
  const path = []
  for (let node = element; node; node = node.parentElement) {
    if (!styles.has(node)) styles.set(node, getComputedStyle(node))
    const style = styles.get(node)
    if (style.zIndex !== 'auto' || ['fixed', 'sticky'].includes(style.position)
      || style.transform !== 'none' || style.filter !== 'none'
      || Number(style.opacity) < 1 || style.isolation === 'isolate') {
      path.unshift({ node, z: Number.parseInt(style.zIndex, 10) || 0 })
    }
  }
  return path
}

function paintsAbove(left, right) {
  let i = 0
  while (i < left.length && i < right.length && left[i].node === right[i].node) i++
  if (i === left.length || i === right.length) return left.length > right.length
  if (left[i].z !== right[i].z) return left[i].z > right[i].z
  // Equal-tier stacking contexts paint in document order.
  return Boolean(right[i].node.compareDocumentPosition(left[i].node) & Node.DOCUMENT_POSITION_FOLLOWING)
}

export function isTopmostEscapeLayer(layer) {
  if (!layer?.isConnected || !layer.getClientRects().length) return false
  let top = null
  let topPath = []
  const styles = new Map()
  for (const candidate of document.querySelectorAll('[data-modal-layer], [data-escape-layer]')) {
    if (!candidate.getClientRects().length) continue
    const path = stackingContexts(candidate, styles)
    if (!top || paintsAbove(path, topPath)) {
      top = candidate
      topPath = path
    }
  }
  return top === layer
}

export function consumeEscape(event) {
  event.preventDefault()
  event.stopImmediatePropagation()
}
