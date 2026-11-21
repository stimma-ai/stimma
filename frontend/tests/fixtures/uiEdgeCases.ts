import { createApp, h, KeepAlive, ref } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import AgentTimersBar from '../../src/components/chat/AgentTimersBar.vue'
import ToolDrawer from '../../src/components/compact/ToolDrawer.vue'
import HorizontalVirtualScroller from '../../src/components/HorizontalVirtualScroller.vue'
import VirtualMediaGrid from '../../src/components/VirtualMediaGrid.vue'
import LineageView from '../../src/views/LineageView.vue'
import FlowView from '../../src/views/FlowView.vue'
import { useStackDocument } from '../../src/imageEditor/stack/useStackDocument'
import '../../src/style.css'

const mode = (window as any).uiCase as string
const state: any = { ranges: [], pages: [] }
;(window as any).uiState = state

function stackCase() {
  const stack = useStackDocument()
  stack.doc.value = { edits: [{ id: 'op1', class: 'parametric', enabled: true, params: { exposure: 0 } }] } as any
  state.stack = stack
  return () => h('div')
}

function gridCase() {
  const pageProvider = async (page: number, size: number) => {
    state.pages.push(page)
    return Array.from({ length: size }, (_, i) => {
      const id = page * size + i + 1
      return { id, asset_id: id, media_id: id, file_format: 'png', file_hash: `h${id}`, width: 32, height: 32 }
    })
  }
  return () => h('div', { style: 'height:600px;width:600px;display:flex' }, [
    h(VirtualMediaGrid, { totalCount: 600, pageProvider, onShiftClickRange: (e: any) => state.ranges.push(e) }),
  ])
}

function drawerCase() {
  const height = ref(700)
  state.setHeight = (px: number) => { height.value = px }
  return () => h('div', { 'data-parent': '', style: `height:${height.value}px;display:flex;flex-direction:column` }, [
    h('div', { style: 'flex:1' }),
    h(ToolDrawer, { initial: 'full', heroReserve: 100 }, { default: () => h('div', 'Body') }),
  ])
}

function lineageCase() {
  const shown = ref(true)
  state.hide = () => { shown.value = false }
  return () => h('div', [
    h('button', { 'data-test-button': '' }, 'Focusable'),
    h(KeepAlive, () => shown.value ? h(LineageView, { mediaId: 1 }) : h('div')),
  ])
}

function flowCase() {
  const shown = ref(true)
  state.hide = () => { shown.value = false }
  state.show = () => { shown.value = true }
  return () => h(KeepAlive, () => shown.value ? h(FlowView, { id: 1 }) : h('div'))
}

function filmstripCase() {
  // Newest first: a prepend puts new ids at index 0.
  const ids = ref(Array.from({ length: 60 }, (_, i) => 1000 - i))
  const index = ref(0)
  const itemGetter = (i: number) => (ids.value[i] == null ? null : { id: ids.value[i] })
  const pageProvider = async (offset: number, limit: number) => ids.value.slice(offset, offset + limit).map(id => ({ id }))
  Object.assign(state, {
    prepend: (n: number) => { ids.value = [...Array.from({ length: n }, (_, i) => 2000 + i), ...ids.value] },
    go: (i: number) => { index.value = i },
  })
  return () => h('div', { style: 'width:600px' }, [
    h(HorizontalVirtualScroller, { totalCount: ids.value.length, pageProvider, itemGetter, currentIndex: index.value, itemWidth: 100, itemGap: 0 },
      { default: ({ item }: any) => h('div', String(item.id)) }),
  ])
}

const setups: Record<string, () => () => any> = {
  timers: () => () => h(AgentTimersBar, { timers: [
    { id: 'a', note: 'Every', repeats: true, every_minutes: 119.5, state: 'scheduled' },
    { id: 'b', note: 'Soon', repeats: true, every_minutes: 59.6, state: 'scheduled' },
  ] }),
  stack: stackCase,
  grid: gridCase,
  drawer: drawerCase,
  lineage: lineageCase,
  filmstrip: filmstripCase,
  flow: flowCase,
}
const app = createApp({ setup: setups[mode] })
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { render: () => null } }] })
app.use(router)
router.push('/').then(() => app.mount('#app'))
