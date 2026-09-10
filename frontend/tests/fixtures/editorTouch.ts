import { createApp, h, ref, Teleport, nextTick } from 'vue'
import EditRow from '../../src/imageEditor/components/EditRow.vue'
import StackCropCanvas from '../../src/imageEditor/components/StackCropCanvas.vue'
import ToolDrawer from '../../src/components/compact/ToolDrawer.vue'
import ToolbarPopover from '../../src/imageEditor/components/ToolbarPopover.vue'
import ScrubValue from '../../src/components/ui/ScrubValue.vue'
import ColorPicker from '../../src/imageEditor/ported/ColorPicker.vue'
import { useAnnotation, type AnnotationState } from '../../src/imageEditor/ported/useAnnotation'

Object.assign(window, { editorTouch: {
  mountEditRow() {
    const events: string[] = []
    createApp({ render: () => h(EditRow, {
      op: { id: 'crop-test', label: 'Crop', enabled: true, class: 'transform', exec: { kind: 'crop' } } as any,
      selected: false, staleness: 'clean',
      onSelect: () => events.push('select'), onRemove: () => events.push('remove'),
      onToggle: () => events.push('toggle'),
    }) }).mount('#app')
    return () => events
  },
  mountCrop() {
    const source = document.createElement('canvas')
    source.width = 300; source.height = 300
    const ctx = source.getContext('2d')!
    ctx.fillStyle = 'blue'; ctx.fillRect(0, 0, 300, 300)
    const crop = ref({ x: 0.5, y: 0.5, width: 1, height: 1, aspectRatio: null })
    const handle = ref()
    let commits = 0
    createApp({ render: () => h('div', {
      style: 'position:relative;width:300px;height:300px;touch-action:none',
      onPointerdownCapture: event => handle.value.touchDown(event),
      onPointermoveCapture: event => handle.value.touchMove(event),
      onPointerupCapture: event => handle.value.touchUp(event),
      onPointercancelCapture: event => handle.value.touchUp(event),
    }, [h(StackCropCanvas, { ref: handle, source, crop: crop.value, viewWidth: 300, viewHeight: 300,
      onChange: value => { crop.value = value }, onCommit: () => { commits++ },
    })]) }).mount('#app')
    return { crop: () => crop.value, commits: () => commits }
  },
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
