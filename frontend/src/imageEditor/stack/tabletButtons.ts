export type EditorBarrelAction = 'pan' | 'brush-popup' | null

/**
 * Resolve browser button numbers to the editor's physical barrel-button actions.
 *
 * Chromium on Linux exposes this Wacom pen's tip-side switch as right-click
 * and its rear switch as middle-click. Other platforms use Stimma's existing
 * middle-to-pan and pen-right/back/forward-to-popup convention.
 */
export function editorBarrelAction(
  event: Pick<PointerEvent, 'button' | 'pointerType'>,
  linux: boolean,
): EditorBarrelAction {
  if (linux && event.pointerType === 'pen') {
    if (event.button === 2) return 'pan'
    if (event.button === 1) return 'brush-popup'
    return null
  }
  if (event.button === 1) return 'pan'
  if (event.button === 3 || event.button === 4) return 'brush-popup'
  if (event.button === 2 && event.pointerType === 'pen') return 'brush-popup'
  return null
}

/** PointerEvent.buttons bit belonging to a PointerEvent.button value. */
export function heldButtonMask(button: number): number {
  if (button === 0) return 1
  if (button === 1) return 4
  if (button === 2) return 2
  if (button === 3) return 8
  if (button === 4) return 16
  return 0
}
