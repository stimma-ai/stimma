import { createApp, h } from 'vue'
import { createRouter, createMemoryHistory, RouterView } from 'vue-router'
import ChatView from '../../src/views/ChatView.vue'
import { setPendingMedia } from '../../src/composables/usePendingMedia'
const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/chat/:id', component: ChatView },
  { path: '/embedded/:id', component: ChatView, props: route => ({ chatId: Number(route.params.id), embedded: true }) },
  { path: '/browse', component: { render: () => h('div', 'Browse') } },
] })
window.draftTest = { router, drop: (id, media) => setPendingMedia('chat', media, id) }
const app = createApp({ render: () => h(RouterView) })
app.use(router)
router.push('/chat/1').then(() => app.mount('#app'))
