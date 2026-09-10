import assert from 'node:assert/strict'
import test from 'node:test'
import { useCropInteraction, type CropRect } from '../ported/useCropInteraction.ts'

function fixture() {
  const canvasHandlers = new Map<string, Function>()
  const windowHandlers = new Map<string, Function>()
  let capture: number | null = null
  const canvas = {
    getBoundingClientRect: () => ({ left: 0, top: 0 }),
    addEventListener: (type: string, fn: Function) => canvasHandlers.set(type, fn),
    removeEventListener: (type: string) => canvasHandlers.delete(type),
    setPointerCapture: (id: number) => { capture = id },
    hasPointerCapture: (id: number) => capture === id,
    releasePointerCapture: () => { capture = null },
  } as unknown as HTMLCanvasElement
  const previousWindow = globalThis.window
  Object.assign(globalThis, { window: {
    addEventListener: (type: string, fn: Function) => windowHandlers.set(type, fn),
    removeEventListener: (type: string) => windowHandlers.delete(type),
  } })
  let rect: CropRect = { x: 0.5, y: 0.5, width: 0.5, height: 0.5, aspectRatio: null }
  let commits = 0
  const crop = useCropInteraction(
    { value: canvas }, { value: { zoom: 1, panX: 0, panY: 0, rotation: 0 } },
    { value: { width: 200, height: 200 } }, { value: { width: 200, height: 200 } },
    () => rect, value => { rect = value }, () => { commits++ },
  )
  crop.setupListeners()
  const pointer = (x: number, y: number, id = 1) => ({
    clientX: x, clientY: y, button: 0, pointerId: id,
    pointerType: 'touch', isPrimary: id === 1, shiftKey: false, preventDefault() {},
  })
  return {
    crop, canvasHandlers, windowHandlers, pointer,
    rect: () => rect, commits: () => commits,
    cleanup() { crop.cleanupListeners(); Object.assign(globalThis, { window: previousWindow }) },
  }
}

test('finger grabs a crop corner outside the mouse target and commits one resize', () => {
  const f = fixture()
  try {
    assert.equal(f.crop.hitTestCropHandle({ x: 32, y: 50 }), null)
    assert.equal(f.crop.hitTestCropHandle({ x: 32, y: 50 }, true), 'nw')
    f.canvasHandlers.get('pointerdown')!(f.pointer(32, 50))
    f.windowHandlers.get('pointermove')!(f.pointer(52, 70))
    assert.ok(f.rect().width < 0.5)
    assert.ok(f.rect().height < 0.5)
    f.windowHandlers.get('pointerup')!(f.pointer(52, 70))
    assert.equal(f.commits(), 1)
    f.windowHandlers.get('pointerup')!(f.pointer(52, 70))
    assert.equal(f.commits(), 1)
  } finally { f.cleanup() }
})

test('a second finger cannot resize or finish the active crop gesture', () => {
  const f = fixture()
  try {
    f.canvasHandlers.get('pointerdown')!(f.pointer(50, 50))
    f.canvasHandlers.get('pointerdown')!(f.pointer(150, 150, 2))
    f.windowHandlers.get('pointermove')!(f.pointer(120, 120, 2))
    f.windowHandlers.get('pointerup')!(f.pointer(120, 120, 2))
    assert.equal(f.rect().width, 0.5)
    assert.equal(f.commits(), 0)
    f.crop.commit()
    assert.equal(f.commits(), 0)
    assert.equal(f.crop.interaction.value.type, 'idle')
  } finally { f.cleanup() }
})
