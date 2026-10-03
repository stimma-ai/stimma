import { createApp, h } from 'vue'
import JobsGrid from '../../src/components/generation/JobsGrid.vue'
import '../../src/style.css'
const jobs = ['processing', 'completed', 'failed'].flatMap((status, group) =>
  [0.5, 1, 2].map((aspect, index) => ({ id: group * 3 + index + 1, status,
    parameters: JSON.stringify({ width: 512 * aspect, height: 512 }),
    result_media_id: status === 'completed' ? index + 1 : undefined,
    error: status === 'failed' ? 'Test failure' : undefined })))
createApp({ render: () => h('div', {
  id: 'rail', style: { height: '60px', padding: '2px', overflow: 'hidden', width: '100%' },
}, [h(JobsGrid, { jobs, imageMode: 'fit', compactOverlays: true, previewTiles: true })]) }).mount('#app')
