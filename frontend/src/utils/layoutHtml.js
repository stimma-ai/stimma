export function sanitizeLayoutHtmlForSandbox(html) {
  if (!html || typeof html !== 'string') return ''

  try {
    const doc = new DOMParser().parseFromString(html, 'text/html')

    doc.querySelectorAll('script').forEach(el => el.remove())
    doc.querySelectorAll('*').forEach(el => {
      for (const attr of [...el.attributes]) {
        const name = attr.name.toLowerCase()
        const value = attr.value.trim().toLowerCase()
        if (name.startsWith('on') || value.startsWith('javascript:')) {
          el.removeAttribute(attr.name)
        }
      }
    })

    return `<!DOCTYPE html>\n${doc.documentElement.outerHTML}`
  } catch {
    return html
      .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
      .replace(/\son[a-z]+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi, '')
      .replace(/\s(href|src)\s*=\s*("|')\s*javascript:[\s\S]*?\2/gi, '')
  }
}
