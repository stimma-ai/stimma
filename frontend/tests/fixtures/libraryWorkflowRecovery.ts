import { createApp, h, ref } from 'vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import SettingsModal from '../../src/components/settings/SettingsModal.vue'
import CompareMode from '../../src/components/CompareMode.vue'
import GlobalSearchBox from '../../src/components/search/GlobalSearchBox.vue'
import SearchResultsView from '../../src/views/SearchResultsView.vue'
import UploadView from '../../src/views/UploadView.vue'
import ToastContainer from '../../src/components/ToastContainer.vue'
import { useGenerationJobs } from '../../src/composables/useGenerationJobs'
import { useAssetTrash } from '../../src/composables/useAssetTrash'
import { useProfile } from '../../src/composables/useProfile'
import { useToasts } from '../../src/composables/useToasts'
import { initApiConfig } from '../../src/apiConfig'
import { setReadDeadlineMs } from '../../src/utils/readDeadline'
import '../../src/style.css'

const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/search', component: SearchResultsView },
  { path: '/upload', component: UploadView },
  { path: '/elsewhere', component: { render: () => h('p', 'Another view') } },
] })
const settingsOpen = ref(false)
const compareOpen = ref(false)
const slider = ref(50)
const left = { id: 101, file_hash: 'left', file_format: 'png', width: 512, height: 512 }
const right = { id: 102, file_hash: 'right', file_format: 'png', width: 512, height: 512 }
const app = createApp({ setup() {
  const jobs = useGenerationJobs()
  ;(window as any).workflowTest = { router, jobs, trash: useAssetTrash(), profile: useProfile(), toasts: useToasts(), slider, settingsOpen, compareOpen }
  return () => h('main', { class: 'h-dvh flex flex-col' }, [
    h('div', { id: 'compact-header-title' }), h('div', { id: 'compact-header-actions' }),
    h('nav', { class: 'flex shrink-0 gap-2 p-2' }, [
      h('button', { onClick: () => { settingsOpen.value = true } }, 'Settings'),
      h('button', { onClick: () => { compareOpen.value = true } }, 'Compare'),
      h('div', { class: 'w-80' }, [h(GlobalSearchBox)]),
    ]),
    h('div', { class: 'flex-1 min-h-0 flex flex-col' }, [h(RouterView)]),
    h(SettingsModal, { show: settingsOpen.value, onClose: () => { settingsOpen.value = false } }),
    compareOpen.value ? h(CompareMode, { leftItem: left, rightItem: right, onClose: () => { compareOpen.value = false }, 'onUpdate:slider-position': (value: number) => { slider.value = value } }) : null,
    h(ToastContainer),
  ])
} })
app.use(router)
const query = new URLSearchParams(location.search)
if (query.get('deadline')) setReadDeadlineMs(Number(query.get('deadline')))
initApiConfig().then(() => router.push(query.get('start') || '/elsewhere')).then(() => app.mount('#app'))
