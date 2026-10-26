import { createApp, h, KeepAlive } from 'vue'
import { createRouter, createMemoryHistory, RouterView } from 'vue-router'
import HomeView from '../../src/views/HomeView.vue'
import '../../src/style.css'

// Home under a real KeepAlive, like App.vue. The project route reuses one
// Home instance across project ids, so a switch is a scope change in place.
const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/', component: HomeView },
  { path: '/projects/:projectId', component: HomeView, props: route => ({ project: { id: Number(route.params.projectId), name: `Project ${route.params.projectId}` } }) },
  { path: '/elsewhere', component: { render: () => h('div', { id: 'elsewhere' }, 'Elsewhere') } },
] })
;(window as any).homeLoadTest = { router }
const app = createApp({ render: () => h('main', [h('div', { id: 'compact-header-title' }), h('div', { id: 'compact-header-actions' }), h(RouterView, null, {
  default: ({ Component, route }: any) => h(KeepAlive, null, { default: () => h(Component, { key: route.matched[0]?.path }) }),
})]) })
app.use(router)
const start = new URLSearchParams(location.search).get('start') || '/'
router.push(start).then(() => app.mount('#app'))
