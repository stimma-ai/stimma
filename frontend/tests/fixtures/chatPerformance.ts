import { createApp, h, ref } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import ChatView from '../../src/views/ChatView.vue'
import ChatInputBox from '../../src/components/chat/ChatInputBox.vue'
import '../../src/style.css'
import { useTheme } from '../../src/composables/useTheme'

window.setChatTheme = useTheme().setTheme

const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/chat/:id', component: ChatView }] })
const app = createApp({ render: () => h(ChatView, { ref: instance => { window.chatTest = instance }, chatId: 1, embedded: true }) })
app.use(router)
router.push('/chat/1').then(() => app.mount('#app'))

window.mountLegacyComposer = () => {
  app.unmount()
  const text = ref('')
  window.legacyDraft = text
  createApp({ render: () => h(ChatInputBox, {
    modelValue: text.value,
    'onUpdate:modelValue': value => { text.value = value },
  }) }).mount('#app')
}
