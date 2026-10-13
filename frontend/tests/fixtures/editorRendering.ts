import { createApp, h, KeepAlive } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import ImageEditorView from '../../src/views/ImageEditorView.vue'
import { editorLiveFrame } from '../../src/imageEditor/liveEditorPreview'
import '../../src/style.css'

const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: ImageEditorView }] })
const app = createApp({ render: () => h(KeepAlive, {}, () => h(ImageEditorView, {
  assetId: '1', ref: instance => { if (instance) window.editorTest = instance },
})) })
app.use(router)
router.push('/').then(() => app.mount('#app'))
Object.assign(window, { unmountEditor: () => app.unmount(), editorLiveFrame })
