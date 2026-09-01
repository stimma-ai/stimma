import assert from 'node:assert/strict'
import test from 'node:test'

import { editorBarrelAction, heldButtonMask, penTipContactLost } from './tabletButtons.ts'

test('Linux Wacom barrel switches follow their physical tip-side/rear assignments', () => {
  assert.equal(editorBarrelAction({ pointerType: 'pen', button: 2 }, true), 'pan')
  assert.equal(editorBarrelAction({ pointerType: 'pen', button: 1 }, true), 'brush-popup')
})

test('Linux mouse buttons keep their ordinary editor behavior', () => {
  assert.equal(editorBarrelAction({ pointerType: 'mouse', button: 1 }, true), 'pan')
  assert.equal(editorBarrelAction({ pointerType: 'mouse', button: 2 }, true), null)
})

test('existing non-Linux pen mappings stay intact', () => {
  assert.equal(editorBarrelAction({ pointerType: 'pen', button: 1 }, false), 'pan')
  assert.equal(editorBarrelAction({ pointerType: 'pen', button: 2 }, false), 'brush-popup')
  assert.equal(editorBarrelAction({ pointerType: 'pen', button: 3 }, false), 'brush-popup')
  assert.equal(editorBarrelAction({ pointerType: 'pen', button: 4 }, false), 'brush-popup')
})

test('held-button masks match the PointerEvent.buttons layout', () => {
  assert.equal(heldButtonMask(1), 4)
  assert.equal(heldButtonMask(2), 2)
})

test('pen hover ends a stroke when Chromium loses the captured pointerup', () => {
  assert.equal(penTipContactLost({ pointerType: 'pen', buttons: 0 }), true)
  assert.equal(penTipContactLost({ pointerType: 'pen', buttons: 1 }), false)
  assert.equal(penTipContactLost({ pointerType: 'pen', buttons: 3 }), false)
  assert.equal(penTipContactLost({ pointerType: 'mouse', buttons: 0 }), false)
})
