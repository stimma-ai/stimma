import test from 'node:test'
import assert from 'node:assert/strict'
import { isMiniMaxH3VideoModel } from './promptModel.ts'

test('H3 image tools and checkpoints do not enable video prompt handling', () => {
  for (const model of ['minimax-h3-image', 'MiniMax H3 Image Inpaint', 'minimax-h3-image-outpaint', 'minimax_h3_image_pruned_int8_convrot.safetensors', null, 'flux3-klein']) {
    assert.equal(isMiniMaxH3VideoModel(model), false, String(model))
  }
})

test('H3 video tools and aliases retain their prompt handling', () => {
  for (const model of ['MiniMax H3', 'minimax-h3-t2v-turbo', 'minimax_h3_fl2va_pruned_int8_convrot.safetensors', 'Hailuo-03', 'Hailuo 3.0']) {
    assert.equal(isMiniMaxH3VideoModel(model), true, model)
  }
})
