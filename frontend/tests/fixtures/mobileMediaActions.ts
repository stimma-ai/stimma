import { createApp, h, KeepAlive, ref } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import MediaContextMenu from '../../src/components/media/MediaContextMenu.vue'
import MultiSelectActionBar from '../../src/components/MultiSelectActionBar.vue'
import EntitySelectionBar from '../../src/components/EntitySelectionBar.vue'
import { useMediaContextMenu } from '../../src/composables/useMediaContextMenu'
import { useWorkingContext } from '../../src/composables/useWorkingContext'
import { useSlideshowPresence, useTabNavigation } from '../../src/composables/useTabNavigation'
import '../../src/style.css'

const item = { id: 7, asset_id: 7, media_id: 42, file_format: 'png' }
const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/', component: { render: () => null } },
  { path: '/tool/:fullToolId', name: 'tool', component: { render: () => null } },
  { path: '/chat/:id', name: 'chat', component: { render: () => null } },
  { path: '/flow/:id', name: 'flow', component: { render: () => null } },
  { path: '/lineage/:mediaId', name: 'lineage', component: { render: () => null } },
] })
const showingSlideshow = ref(false)
const slideshow = { setup() { useSlideshowPresence(); return () => h('div') } }
window.mobileMediaActions = {
  openSlideshowMenu: () => { showingSlideshow.value = true; useMediaContextMenu().showAt({ x: 200, y: 200, mediaId: 42 }) },
  setProject: id => useWorkingContext().selectProject(id),
  route: () => ({ name: router.currentRoute.value.name, params: router.currentRoute.value.params, query: router.currentRoute.value.query }),
}
const app = createApp({ render: () => h('div', [
  h('header', { 'data-test-header': '', style: { display: useTabNavigation().slideshowActive.value ? 'none' : '' } }, 'App header'),
  h(KeepAlive, null, { default: () => showingSlideshow.value && router.currentRoute.value.path === '/' ? h(slideshow) : null }),
  h(MultiSelectActionBar, { visible: true, selectedCount: 1, totalCount: 10, firstSelectedItem: item, selectedItems: [item] }),
  h('div', { class: 'entity-selection-fixture' }, [h(EntitySelectionBar, { visible: true, selectedCount: 1, totalCount: 10 })]),
  h(MediaContextMenu),
]) })
app.use(router)
router.push('/').then(() => app.mount('#app'))
