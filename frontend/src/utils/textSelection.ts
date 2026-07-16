const TEXT_SELECTION_SELECTOR = [
  'input',
  'textarea',
  '[contenteditable]:not([contenteditable="false"])',
  '[role="textbox"]',
  '.select-text',
].join(', ')

function targetElement(target: EventTarget | null): Element | null {
  if (target instanceof Element) return target
  return target instanceof Node ? target.parentElement : null
}

/**
 * Stimma is an interaction-first desktop UI, so incidental drag-selection is
 * blocked by default. Native editors and explicit Tailwind `select-text`
 * content boundaries retain ordinary browser selection.
 *
 * This is event-based rather than `user-select: none` on the app root because
 * Chromium/WebKit do not let a descendant opt back into selection beneath a
 * nonselectable ancestor.
 */
export function installTextSelectionPolicy(doc: Document = document): void {
  doc.addEventListener('selectstart', (event) => {
    const target = targetElement(event.target)
    if (!target?.closest(TEXT_SELECTION_SELECTOR)) event.preventDefault()
  }, { capture: true })
}
