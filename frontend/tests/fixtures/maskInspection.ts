import { createApp, h, reactive, nextTick } from 'vue'
import StackSelectCanvas from '../../src/imageEditor/components/StackSelectCanvas.vue'
import { useSelection } from '../../src/imageEditor/ported/useSelection'
const source = document.createElement('canvas')
source.width = 120
source.height = 60
const model = useSelection()
model.initSelection({ width: 120, height: 60 })
const mask = document.createElement('canvas')
mask.width = 120
mask.height = 60
const ctx = mask.getContext('2d')!
ctx.fillStyle = 'rgba(255,0,0,1)'
ctx.fillRect(0, 0, 40, 60)
ctx.fillStyle = 'rgba(0,255,0,0.5)'
ctx.fillRect(40, 0, 40, 60)
model.applyMaskCanvas(mask, 'new')
const state = reactive({ preview: true })
createApp({ setup: () => () => h(StackSelectCanvas, {
  source, model, displayWidth: 120, displayHeight: 60, coveragePreview: state.preview,
}) }).mount('#app')
Object.assign(window, { maskTest: { state, model, nextTick } })
