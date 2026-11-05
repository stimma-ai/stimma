import { createApp, h, reactive, ref } from 'vue'
import ChatInputBox from '../../src/components/chat/ChatInputBox.vue'
import '../../src/style.css'

const draft = reactive({ text: '' })
const composer = ref()
window.chatInputScrollTest = { draft, composer, submits: 0 }
createApp({
  render: () => h('main', { class: 'max-w-xl mx-auto' }, [h(ChatInputBox, {
    ref: composer,
    draft,
    onSubmit: () => { window.chatInputScrollTest.submits++ },
  })]),
}).mount('#app')
