import { createApp, h, provide, ref } from 'vue'
import OutputImage from '../../src/components/chat/OutputImage.vue'
import FlowMediaTile from '../../src/components/flow/FlowMediaTile.vue'
import MediaImage from '../../src/components/media/MediaImage.vue'
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
      h('div', { style: 'position: absolute; left: 800px; top: 1000px', 'data-testid': 'shown-video' }, [h(OutputImage, { row: rows[0], useThumbnail: false, size: 240 })]),
      h('div', { style: 'position: absolute; left: 800px; top: 1400px', 'data-testid': 'contained-video' }, [h(MediaImage, { mediaId: 1, contain: true, containerClass: 'w-32 h-32' })]),
      h('div', { style: 'position: absolute; left: 800px; top: 1400px', 'data-testid': 'covered-video' }, [h(MediaImage, { mediaId: 1, containerClass: 'w-32 h-32' })]),
      h('div', { style: 'position: absolute; left: 800px; top: 1400px', 'data-testid': 'explicit-crop' }, [h(MediaImage, { mediaId: 1, contain: true, thumbnailMode: 'crop', containerClass: 'w-32 h-32' })]),
      h('div', { style: 'position: absolute; left: 800px; top: 1400px', 'data-testid': 'flow-video' }, [h(FlowMediaTile, { mediaId: 1, contain: true, containerClass: 'w-32 h-32' })]),
      h(MediaCollection, { rows, itemId: 1, onViewImage: id => window.chatVideo.opened.push(id) }),
    ])
  },
}).mount('#app')
