import { createApp, h } from 'vue'
import { createRouter, createMemoryHistory, RouterView } from 'vue-router'
import ChatView from '../../src/views/ChatView.vue'
import '../../src/style.css'
import { initApiConfig } from '../../src/apiConfig'
import { useWebSocket } from '../../src/composables/useWebSocket'
const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/chat/:id', component: ChatView },
] })
const app = createApp({ render: () => h(RouterView) })
app.use(router)
initApiConfig().then(() => {
  useWebSocket().connect()
  return router.push('/chat/1')
}).then(() => app.mount('#app'))
