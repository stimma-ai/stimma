import { createApp, h, provide, ref } from 'vue'
import MediaCollection from '../../src/components/chat/MediaCollection.vue'
import { CHAT_MEDIA_COLLECTIONS, useChatMediaCollections } from '../../src/composables/useChatMediaCollections'
import { useMediaContextMenu } from '../../src/composables/useMediaContextMenu'
import '../../src/style.css'

createApp({
  setup() {
    const attachments = ref([])
    const collections = useChatMediaCollections({ attachments, canAttach: () => true,
      compare: () => {}, panelAvailable: false, panelItemId: ref(null), openPanel: () => {}, closePanel: () => {} })
    collections.viewState(1, () => 'preview')
    provide(CHAT_MEDIA_COLLECTIONS, collections)
    const rows = [1, 2].map(id => ({ id, output: { status: 'complete', media_id: id, file_format: id === 1 ? 'webm' : 'png' } }))
    window.chatVideo = { collections, attachments, opened: [], menu: useMediaContextMenu() }
    return () => h('div', { 'data-chat-scroller': '', style: 'height: 800px; width: 100%; max-width: 700px' }, [
      h(MediaCollection, { rows, itemId: 1, onViewImage: id => window.chatVideo.opened.push(id) }),
    ])
  },
}).mount('#app')
