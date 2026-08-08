import { defineComponent, h, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

export const ResizeObserver = defineComponent({
  name: 'ResizeObserver',
  props: {
    emitOnMount: {
      type: Boolean,
      default: false,
    },
    ignoreWidth: {
      type: Boolean,
      default: false,
    },
    ignoreHeight: {
      type: Boolean,
      default: false,
    },
  },
  emits: ['notify'],
  setup(props, { emit }) {
    const element = ref(null)
    let observer = null
    let width = 0
    let height = 0

    function emitSize() {
      emit('notify', { width, height })
    }

    function updateSize() {
      if (!element.value) return

      const nextWidth = element.value.offsetWidth
      const nextHeight = element.value.offsetHeight
      const changed = (!props.ignoreWidth && nextWidth !== width)
        || (!props.ignoreHeight && nextHeight !== height)

      width = nextWidth
      height = nextHeight
      if (changed) emitSize()
    }

    onMounted(async () => {
      await nextTick()
      if (!element.value) return

      width = element.value.offsetWidth
      height = element.value.offsetHeight
      if (props.emitOnMount) emitSize()

      observer = new window.ResizeObserver(updateSize)
      observer.observe(element.value)
    })

    onBeforeUnmount(() => observer?.disconnect())

    return () => h('div', {
      ref: element,
      class: 'resize-observer',
      tabindex: '-1',
      style: {
        position: 'absolute',
        inset: '0',
        zIndex: '-1',
        pointerEvents: 'none',
        overflow: 'hidden',
        opacity: '0',
      },
    })
  },
})

export function install(app) {
  app.component('resize-observer', ResizeObserver)
  app.component('ResizeObserver', ResizeObserver)
}

export default { install }
