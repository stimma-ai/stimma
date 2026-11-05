import { createApp, h } from 'vue'
import { createRouter, createMemoryHistory, RouterView } from 'vue-router'
import ChatsLandingView from '../../src/views/ChatsLandingView.vue'
import PrivacySection from '../../src/components/settings/sections/PrivacySection.vue'
import ToastContainer from '../../src/components/ToastContainer.vue'
import { initApiConfig } from '../../src/apiConfig'

const telemetryUpdates: boolean[] = []
Object.assign(window, { httpActionErrors: { telemetryUpdates } })
const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/', component: ChatsLandingView },
] })
const app = createApp({ render: () => h('div', [
  h(RouterView),
  h(PrivacySection, { telemetryEnabled: false, onTelemetryUpdated: (value: boolean) => telemetryUpdates.push(value) }),
  h(ToastContainer),
]) })
app.use(router)
initApiConfig().then(() => router.push('/')).then(() => app.mount('#app'))
