import { createApp, h, ref, Teleport, nextTick } from 'vue'
import ToolDrawer from '../../src/components/compact/ToolDrawer.vue'
import ToolbarPopover from '../../src/imageEditor/components/ToolbarPopover.vue'
import ScrubValue from '../../src/components/ui/ScrubValue.vue'
import ColorPicker from '../../src/imageEditor/ported/ColorPicker.vue'
import { useAnnotation, type AnnotationState } from '../../src/imageEditor/ported/useAnnotation'

Object.assign(window, { editorTouch: {
  mountPopover() {
    createApp({ render: () => h(ToolbarPopover, { label: 'Brush' }, { default: () => 'Brush controls' }) }).mount('#app')
  },
  mountScrub() {
    createApp({ render: () => h(ScrubValue, { modelValue: 50, title: 'Opacity' }) }).mount('#app')
  },
  mountDrawer() {
    const family = ref('Crop')
    createApp({ render: () => h('div', { style: 'height:700px' }, [
      h(ToolDrawer, { idPrefix: 'test-drawer', initial: 'half' }, {
        default: () => family.value ? h('div', { key: family.value, id: 'family' }, family.value) : null,
      }),
      h(Teleport, { to: '#test-drawer-panels', defer: true }, [h('div', { id: 'properties' }, 'Edits')]),
    ]) }).mount('#app')
    return async (name: string) => { family.value = name; await nextTick() }
  },
  mountColor(initial = { r: 255, g: 0, b: 0 }) {
    const color = ref(initial)
    createApp({ render: () => h(ColorPicker, {
      modelValue: color.value, 'onUpdate:modelValue': value => { color.value = value },
    }) }).mount('#app')
    return () => color.value
  },
  mountAnnotation() {
    const canvas = document.createElement('canvas')
    canvas.width = 300; canvas.height = 300; canvas.style.touchAction = 'none'
    document.querySelector('#app')!.append(canvas)
    let state: AnnotationState = {
      activeTool: 'rectangle', annotations: [], selectedShapeId: null, selectedShapeIds: [],
      annotateStrokeColor: { r: 0, g: 0, b: 0 }, annotateFillColor: null,
      annotateStrokeWidth: 2, annotateOpacity: 1,
    }
    const history: string[] = []
    const annotation = useAnnotation({ value: canvas },
      { value: { zoom: 1, panX: 0, panY: 0, rotation: 0 } },
      { value: { width: 300, height: 300 } }, { value: { width: 300, height: 300 } },
      () => state, partial => { state = { ...state, ...partial } }, action => history.push(action))
    annotation.setupListeners()
    return { state: () => state, history: () => history, commit: annotation.commitGesture }
  },
} })
