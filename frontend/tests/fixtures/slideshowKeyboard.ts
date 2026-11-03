import { createApp, h, ref } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import SlideshowMode from '../../src/components/SlideshowMode.vue'
import Modal from '../../src/components/ui/Modal.vue'
import { useGlobalKeyboardShortcuts } from '../../src/composables/useGlobalKeyboardShortcuts'
import '../../src/style.css'

const show = ref(false), index = ref(0)
const grid: string[] = []
const items = [1, 2, 3].map(id => ({ id, file_format: 'png', file_hash: `image-${id}`, width: 32, height: 32 }))
Object.assign(window, { slideshowKeys: { grid, modal: () => { show.value = true } } })
const app = createApp({
  setup() {
    useGlobalKeyboardShortcuts({ onKeydown: (event: KeyboardEvent) => { grid.push(event.key) } })
    return () => h('div', [
      h('output', { 'data-current-index': '' }, String(index.value)),
      h(SlideshowMode, { items, 'onUpdate:index': (value: number) => { index.value = value } }),
      h(Modal, { show: show.value, onClose: () => { show.value = false } }, () => h('button', {}, 'Modal action')),
    ])
  },
})
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { render: () => null } }] })
app.use(router)
router.push('/').then(() => app.mount('#app'))
