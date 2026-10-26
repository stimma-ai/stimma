import { createApp, h, KeepAlive } from 'vue'
import { createRouter, createMemoryHistory, RouterView } from 'vue-router'
import HomeView from '../../src/views/HomeView.vue'
import { initApiConfig } from '../../src/apiConfig'
import { setCurrentProfileId } from '../../src/composables/useProfile'
import { useAvailableModels } from '../../src/composables/useAvailableModels'
import { recordEntityVisit } from '../../src/composables/useRecentEntities'
import { useProvidersApi } from '../../src/composables/useProvidersApi'
import { setReadDeadlineMs } from '../../src/utils/readDeadline'
import '../../src/style.css'

// A scripted server socket: the test pushes broadcasts and drops the
// connection; the app's own reconnect logic opens the next one.
const sockets: FakeSocket[] = []
class FakeSocket {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3
  readyState = 0
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: ((error: unknown) => void) | null = null
  constructor() {
    sockets.push(this)
    setTimeout(() => { this.readyState = 1; this.onopen?.() }, 0)
  }
  send() {}
  close() { this.readyState = 3 }
}
;(window as any).WebSocket = FakeSocket

// Home under a real KeepAlive, like App.vue. The project route reuses one
// Home instance across project ids, so a switch is a scope change in place.
const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/', component: HomeView },
  { path: '/projects/:projectId', component: HomeView, props: route => ({ project: { id: Number(route.params.projectId), name: `Project ${route.params.projectId}` } }) },
  { path: '/elsewhere', component: { render: () => h('div', { id: 'elsewhere' }, 'Elsewhere') } },
] })
;(window as any).homeLoadTest = {
  router,
  models: useAvailableModels(),
  // Another consumer of the shared tool catalog cache.
  catalog: useProvidersApi(),
  setProfile: setCurrentProfileId,
  recordToolVisit: (id: string, name: string) => recordEntityVisit('tool', id, name),
  serverEvent(event: string, data = {}) {
    sockets[sockets.length - 1]?.onmessage?.({ data: JSON.stringify({ event, data }) })
  },
  dropSocket() {
    const socket = sockets[sockets.length - 1]
    if (!socket) return
    socket.readyState = 3
    socket.onclose?.()
  },
  socketCount: () => sockets.length,
}
const app = createApp({ render: () => h('main', [h('div', { id: 'compact-header-title' }), h('div', { id: 'compact-header-actions' }), h(RouterView, null, {
  default: ({ Component, route }: any) => h(KeepAlive, null, { default: () => h(Component, { key: route.matched[0]?.path }) }),
})]) })
app.use(router)
const query = new URLSearchParams(location.search)
const start = query.get('start') || '/'
if (query.get('deadline')) setReadDeadlineMs(Number(query.get('deadline')))
initApiConfig().then(() => router.push(start)).then(() => app.mount('#app'))
