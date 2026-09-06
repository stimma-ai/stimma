import { createApp } from 'vue'
import ConnectionApp from './ConnectionApp.vue'
import '../style.css'

// This entry has no backend dependencies: it also runs before a server is selected.
const preference = localStorage.getItem('stimma-theme') || 'system'
const theme = preference === 'system'
  ? (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark')
  : preference
document.documentElement.dataset.theme = theme === 'light' ? 'light' : 'dark'
createApp(ConnectionApp).mount('#app')
