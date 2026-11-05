import { createApp, h, KeepAlive, ref } from 'vue'
import ArtifactStage from '../../src/components/chat/ArtifactStage.vue'
import { useManagedMediaElement } from '../../src/composables/useMediaPlayback'
import FileViewer from '../../src/components/viewers/FileViewer.vue'

const active = ref(true), open = ref(true), surface = ref('artifact'), covered = ref(false), revisionId = ref(1)
const revision = () => ({ id: revisionId.value, media_id: revisionId.value, media_hash: 'video-' + revisionId.value, file_format: 'mp4', revision_number: revisionId.value })
window.mediaLifecycle = { active, open, surface, covered, revisionId }
const OtherPlayer = {
  setup() {
    const element = ref<HTMLAudioElement | null>(null)
    useManagedMediaElement(element)
    return () => h('audio', { ref: element, src: '/other.wav', 'data-other-player': '' })
  },
}
const Screen = {
  setup() {
    return () => !open.value ? h('div') : surface.value === 'artifact'
      ? h(ArtifactStage, { active: !covered.value, asset: { id: 1, title: 'Video', current_revision_id: 1 }, revisions: [revision()],
        viewedRevision: revision(), viewedRevisionId: revisionId.value, latestRevisionId: 1, onNewest: true, loading: false })
      : h(FileViewer, { url: '/clip-' + revisionId.value, name: surface.value === 'audio' ? 'clip.wav' : 'clip.mp4' })
  },
}
createApp({ setup: () => () => h(KeepAlive, null, { default: () => active.value ? h(Screen) : h(OtherPlayer) }) }).mount('#app')
