import { createApp, h, ref } from 'vue'
import JobsGrid from '../../src/components/generation/JobsGrid.vue'
import '../../src/style.css'
// 80 finished results, newest first: more than the grid mounts at once.
const jobs = Array.from({ length: 80 }, (_, index) => ({
  id: 80 - index, status: 'completed', result_media_id: 1000 + 80 - index,
  completed_at: new Date(Date.UTC(2026, 0, 1, 0, 80 - index)).toISOString(),
  parameters: JSON.stringify({ width: 512, height: 512 }),
}))
const grid = ref<any>(null)
Object.assign(window, { revealJob: (id: number) => grid.value.revealJob(id) })
createApp({ render: () => h('div', {
  id: 'rail', style: { height: '400px', width: '200px', overflowY: 'auto' },
}, [h(JobsGrid, { ref: grid, jobs, imageMode: 'cover' })]) }).mount('#app')
