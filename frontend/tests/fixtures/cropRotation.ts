import { createApp, h, reactive } from 'vue'
import StackCropCanvas from '../../src/imageEditor/components/StackCropCanvas.vue'
import { applyCrop } from '../../src/imageEditor/stack/opExecutors'

const source = document.createElement('canvas')
source.width = 240
source.height = 120
const ctx = source.getContext('2d')!
ctx.fillStyle = 'red'; ctx.fillRect(0, 0, 120, 60)
ctx.fillStyle = 'lime'; ctx.fillRect(120, 0, 120, 60)
ctx.fillStyle = 'blue'; ctx.fillRect(0, 60, 120, 60)
ctx.fillStyle = 'yellow'; ctx.fillRect(120, 60, 120, 60)
const state = reactive({ crop: { x: 0.5, y: 0.5, width: 1, height: 1, aspectRatio: null, rotation: 0 }, rotation90: 1, flipX: false, flipY: false, commits: 0 })
createApp({ render: () => h(StackCropCanvas, {
  source, crop: state.crop, rotation90: state.rotation90, flipX: state.flipX, flipY: state.flipY, viewWidth: 500, viewHeight: 500,
  onChange: crop => { state.crop = crop }, onCommit: () => { state.commits++ },
}) }).mount('#app')
Object.assign(window, { cropTest: { state, source, applyCrop } })
