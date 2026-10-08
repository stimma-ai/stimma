import { createApp, h, KeepAlive, ref } from 'vue'
import { createRouter, createMemoryHistory, RouterView } from 'vue-router'
import Modal from '../../src/components/ui/Modal.vue'
import HomeView from '../../src/views/HomeView.vue'
import ChatsLandingView from '../../src/views/ChatsLandingView.vue'
import { useViewport } from '../../src/composables/useViewport'
import '../../src/style.css'

const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/', component: HomeView },
  { path: '/projects/:projectId/overview', component: HomeView, props: route => ({ project: { id: Number(route.params.projectId), name: 'Test project' } }) },
  { path: '/chats', component: ChatsLandingView },
  { path: '/browse', component: { render: () => h('div', 'Browse') } },
] })
const modal = ref(false)
window.autofocusTest = { router, viewport: useViewport(), setModal: show => { modal.value = show } }
const app = createApp({ render: () => h('main', [h('button', { id: 'overlay-launcher' }, 'Overlay launcher'), h(Modal, { show: modal.value, onClose: () => { modal.value = false } }, () => h('p', 'Overlay content')), h('div', { id: 'compact-header-title' }), h('div', { id: 'compact-header-actions' }), h(RouterView, null, {
  default: ({ Component }) => h(KeepAlive, null, { default: () => h(Component, { key: router.currentRoute.value.path }) }),
})]) })
app.use(router)
router.push('/').then(() => app.mount('#app'))
