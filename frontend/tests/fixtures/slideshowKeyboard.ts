import { createApp, h, ref } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import SlideshowMode from '../../src/components/SlideshowMode.vue'
import Modal from '../../src/components/ui/Modal.vue'
import { useGlobalKeyboardShortcuts } from '../../src/composables/useGlobalKeyboardShortcuts'
import '../../src/style.css'

const show = ref(false), index = ref(0)
const grid: string[] = []
const items = [1, 2, 3].map(id => ({ id, file_format: 'png', file_hash: `image-${id}`, width: 32, height: 32 }))
const chatMode = Boolean((window as any).slideshowChatTest)
// Two chat images whose page can be held, to step while the next is loading.
const navMode = Boolean((window as any).slideshowNavTest)
const liveIds = ref(navMode ? ['image:31', 'image:32'] : ['progress:22'])
const video = { id: 22, file_format: 'mp4', file_hash: 'finished-video', width: 32, height: 32 }
const stills = [31, 32].map(id => ({ id, file_format: 'png', file_hash: `still-${id}`, width: 32, height: 32 }))
let pendingPage: Promise<void> | null = null
let releasePage: (() => void) | null = null
const pageProvider = async () => {
  if (pendingPage) await pendingPage
  if (navMode) return stills.map((item, i) => ({ ...item, _slideshowItemKey: liveIds.value[i] }))
  return [{ ...video, _slideshowItemKey: liveIds.value[0] }]
}
Object.assign(window, { slideshowKeys: {
  grid, modal: () => { show.value = true },
  refreshChat: () => {
    pendingPage = new Promise(resolve => { releasePage = resolve })
    liveIds.value = navMode ? ['output:31', 'output:32'] : ['output:22']
  },
  finishRefresh: () => { releasePage?.(); pendingPage = null },
} })
const app = createApp({
  setup() {
    useGlobalKeyboardShortcuts({ onKeydown: (event: KeyboardEvent) => { grid.push(event.key) } })
    return () => h('div', [
      h('output', { 'data-current-index': '' }, String(index.value)),
      h(SlideshowMode, {
        ...(chatMode || navMode ? { totalCount: liveIds.value.length, liveItemIds: liveIds.value, pageProvider } : { items }),
        'onUpdate:index': (value: number) => { index.value = value },
      }),
      h(Modal, { show: show.value, onClose: () => { show.value = false } }, () => h('button', {}, 'Modal action')),
    ])
  },
})
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { render: () => null } }] })
app.use(router)
router.push('/').then(() => app.mount('#app'))
