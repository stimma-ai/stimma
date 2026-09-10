import { createApp, h, ref } from 'vue'
import HorizontalVirtualScroller from '../../src/components/HorizontalVirtualScroller.vue'
import SlideshowMarkerControls from '../../src/components/SlideshowMarkerControls.vue'
import '../../src/style.css'
const current = ref(0), count = ref(4), active = ref(new Set([0])), pending = ref(false)
const items = Array.from({ length: 1000 }, (_, id) => ({ id }))
Object.assign(window, { galleryTest: {
  select: (index: number) => { current.value = index },
  markers: (n: number) => { count.value = n },
  pending: () => { pending.value = true },
} })
createApp({ render: () => h('div', { class: 'bg-matte text-content', style: 'width:100%;padding:12px' }, [
  h(HorizontalVirtualScroller, {
    totalCount: items.length, currentIndex: current.value, itemWidth: 48, itemHeight: 54,
    height: 62, itemGap: 6, gutter: 4, centerEdges: true,
    itemGetter: (index: number) => pending.value ? null : items[index],
    pageProvider: () => pending.value ? new Promise(() => {}) : Promise.resolve(items),
  }, { default: ({ index }: { index: number }) => h('button', {
    'data-index': index, style: 'height:44px;width:44px', onClick: () => { current.value = index },
  }, String(index)) }),
  h('div', { class: 'flex items-center', style: 'height:64px' }, [
    h('button', { style: 'width:44px;height:44px;flex-shrink:0' }, 'Play'),
    h(SlideshowMarkerControls, {
      class: 'min-w-0 flex-1',
      markers: Array.from({ length: count.value }, (_, id) => ({ id, name: `Marker ${id}`, color: '#f472b6', icon_svg: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" fill="currentColor"/></svg>' })),
      isActive: (id: number) => active.value.has(id),
      onToggle: (id: number) => { const next = new Set(active.value); next.has(id) ? next.delete(id) : next.add(id); active.value = next },
    }),
    h('button', { style: 'width:44px;height:44px;flex-shrink:0' }, 'More'),
  ]),
]) }).mount('#app')
