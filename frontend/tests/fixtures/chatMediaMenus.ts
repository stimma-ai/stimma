import { computed, createApp, h, provide, ref } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import ArtifactStage from '../../src/components/chat/ArtifactStage.vue'
import MediaCollection from '../../src/components/chat/MediaCollection.vue'
import MediaSelectionBar from '../../src/components/chat/MediaSelectionBar.vue'
import MediaContextMenu from '../../src/components/media/MediaContextMenu.vue'
import { CHAT_MEDIA_COLLECTIONS, useChatMediaCollections } from '../../src/composables/useChatMediaCollections'
import { useMediaContextMenu } from '../../src/composables/useMediaContextMenu'
import '../../src/style.css'

const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { render: () => null } }] })
const params = new URLSearchParams(location.search)
const kind = params.get('kind') || 'png'
const count = Number(params.get('count') || 3)

// One artifact asset (50) with three revisions; the panel starts on v1.
const revisions = [1, 2, 3].map(n => ({ id: n, revision_number: n, media_id: 500 + n, file_format: kind, width: 64, height: 64, filename: `v${n}.${kind}` }))
const asset = { id: 50, title: 'Poster', current_revision_id: 3 }

createApp({
  setup() {
    const viewed = ref(1)
    const events = { closed: 0, slideshow: [] as number[], opened: [] as number[] }
    const attachments = ref([])
    const collections = useChatMediaCollections({ attachments, canAttach: () => true, compare: () => {},
      panelAvailable: false, panelItemId: ref(null), openPanel: () => {}, closePanel: () => {}, projectId: () => 7 })
    collections.viewState(1, () => (params.get('view') === 'preview' ? 'preview' : 'grid'))
    provide(CHAT_MEDIA_COLLECTIONS, collections)
    // ?mixed: the second image is a chat-only working result with no asset.
    const mixed = params.has('mixed')
    const rows = Array.from({ length: count }, (_, i) => ({ id: i + 1, output: { status: 'complete', media_id: 101 + i, asset_id: mixed && i === 1 ? null : 201 + i, file_format: 'png' } }))
    const showStage = ref(params.get('surface') !== 'collection')
    const viewedRevision = computed(() => revisions.find(rev => rev.id === viewed.value) || null)
    Object.assign(window, { chatMenus: { menu: useMediaContextMenu(), events, collections, viewed, printed: [] as string[] } })
    window.print = () => { (window as any).chatMenus.printed.push(document.getElementById('stimma-print-overlay')?.innerHTML || '') }
    return () => h('div', { style: 'display:flex; height: 900px' }, [
      h('div', { 'data-chat-scroller': '', style: 'height: 800px; width: 700px; overflow:auto' }, [
        h('textarea', { 'aria-label': 'Message', style: 'width: 300px' }),
        h(MediaCollection, { rows, itemId: 1, onViewImage: (id: number) => events.opened.push(id) }),
        collections.selection.selecting.value ? h(MediaSelectionBar) : null,
      ]),
      showStage.value ? h(ArtifactStage, {
        style: 'width: 600px; height: 800px', active: true, chatId: 9, projectId: 7, asset, revisions,
        viewedRevisionId: viewed.value, viewedRevision: viewedRevision.value, latestRevisionId: 3,
        onNewest: viewed.value === 3, loading: false,
        onClose: () => { events.closed++ },
        'onSelect-revision': (id: number) => { viewed.value = id },
        'onOpen-slideshow': (id: number) => events.slideshow.push(id),
      }) : null,
      h(MediaContextMenu),
    ])
  },
}).use(router).mount('#app')
