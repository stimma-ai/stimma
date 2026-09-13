import { createApp, h } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import ChatView from '../../src/views/ChatView.vue'
import '../../src/style.css'
import { useTheme } from '../../src/composables/useTheme'
useTheme().setTheme('dark')
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/chat/:id', component: ChatView }] })
const app = createApp({ render: () => h(ChatView, { ref: instance => { window.fileRefsTest = instance }, chatId: 1 }) })
app.use(router)
router.push('/chat/1').then(() => app.mount('#app'))
