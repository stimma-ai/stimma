import { createApp, h, ref } from 'vue'
import ArtifactStage from '../../src/components/chat/ArtifactStage.vue'
import { useMarkers } from '../../src/composables/useMarkers'
import '../../src/style.css'

const kind = ref<'mp4' | 'png' | 'stimmaset.json'>('mp4')
const width = ref(900)
const opened: number[] = []
const members: Array<[number[], number]> = []
const ids = { mp4: 1, png: 2, 'stimmaset.json': 3 } as const
const revision = () => ({ id: ids[kind.value], media_id: ids[kind.value], media_hash: 'hash-' + ids[kind.value], file_format: kind.value, revision_number: 1, width: 320, height: 180 })
;(window as any).stage = { kind, width, opened, members }
useMarkers().init()
createApp({
  setup: () => () => h('div', { style: `display: flex; height: 600px; width: ${width.value}px` }, [
    h(ArtifactStage, {
      key: kind.value,
      active: true, chatId: 1, projectId: null,
      asset: { id: 1, title: 'Artwork', current_revision_id: ids[kind.value] }, revisions: [revision()],
      viewedRevision: revision(), viewedRevisionId: ids[kind.value], latestRevisionId: ids[kind.value], onNewest: true, loading: false,
      onOpenSlideshow: (id: number) => opened.push(id),
      onOpenMembers: (list: number[], index: number) => members.push([list, index]),
    }),
  ]),
}).mount('#app')
