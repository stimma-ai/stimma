import { createApp, h, KeepAlive } from 'vue'
import { createRouter, createMemoryHistory, RouterView } from 'vue-router'
import HomeView from '../../src/views/HomeView.vue'
import ToolView from '../../src/views/ToolView.vue'
import NavigationSidebar from '../../src/components/NavigationSidebar.vue'
import ProviderManagerButton from '../../src/components/ProviderManagerButton.vue'
import { initApiConfig } from '../../src/apiConfig'
import { setCurrentProfileId } from '../../src/composables/useProfile'
import { useProvidersApi } from '../../src/composables/useProvidersApi'
import { planToolHandoff } from '../../src/utils/toolHandoff'
import { setReadDeadlineMs } from '../../src/utils/readDeadline'
import '../../src/style.css'

// A scripted server socket: the test pushes broadcasts.
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

// The desktop launch surfaces that read the tool catalog: the sidebar (pins,
// availability, drag targets), the top bar's provider manager, and Home under
// a KeepAlive like App.vue. The tool route opens the real ToolView.
const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/', component: HomeView },
  { path: '/tools/:fullToolId(.*)', name: 'tool', component: ToolView, props: true },
  { path: '/elsewhere', component: { render: () => h('div', { id: 'elsewhere' }, 'Elsewhere') } },
] })

;(window as any).toolCatalogTest = {
  router,
  catalog: useProvidersApi(),
  planToolHandoff,
  setProfile: setCurrentProfileId,
  serverEvent(event: string, data = {}) {
    sockets[sockets.length - 1]?.onmessage?.({ data: JSON.stringify({ event, data }) })
  },
  // Lose the socket; the app's own reconnect logic opens the next one.
  dropSocket() {
    const socket = sockets[sockets.length - 1]
    if (!socket) return
    socket.readyState = 3
    socket.onclose?.()
  },
  socketCount: () => sockets.length,
}

const app = createApp({ render: () => h('div', { class: 'flex h-screen' }, [
  h(NavigationSidebar, { isOpen: true, isMobile: false }),
  h('main', { class: 'flex-1 flex flex-col' }, [
    h('div', { id: 'compact-header-title' }),
    h('div', { id: 'compact-header-actions' }),
    h(ProviderManagerButton),
    h(RouterView, null, {
      default: ({ Component, route }: any) => h(KeepAlive, null, { default: () => h(Component, { key: route.fullPath }) }),
    }),
  ]),
]) })
app.use(router)
const query = new URLSearchParams(location.search)
const start = query.get('start') || '/'
if (query.get('deadline')) setReadDeadlineMs(Number(query.get('deadline')))
initApiConfig().then(() => router.push(start)).then(() => app.mount('#app'))
