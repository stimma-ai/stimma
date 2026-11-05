import { createApp, h } from 'vue'
import ToastContainer from '../../src/components/ToastContainer.vue'
import './chatQueue'

const root = document.createElement('div')
document.body.append(root)
createApp({ render: () => h(ToastContainer) }).mount(root)
