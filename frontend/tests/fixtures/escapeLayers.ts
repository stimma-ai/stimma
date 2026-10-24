import { createApp, h, ref } from 'vue'
import Modal from '../../src/components/ui/Modal.vue'
import Sheet from '../../src/components/ui/Sheet.vue'
import SettingsDropdown from '../../src/components/ui/SettingsDropdown.vue'
import GenerationDetailsModal from '../../src/components/generation/GenerationDetailsModal.vue'
import SelectIsland from '../../src/imageEditor/components/SelectIsland.vue'
import { hasEscapeLayer } from '../../src/utils/escapeLayers'
import '../../src/style.css'

const parent = ref(true), sheet = ref(false), details = ref(false), confirm = ref(false), scoped = ref(false)
const aiSelection = ref(false), aiBusy = ref(false), cancellations = ref(0)
Object.assign(window, { escapeLayers: {
  hasLayer: hasEscapeLayer,
  scopedMenu: () => { scoped.value = true },
  sheet: () => { sheet.value = true },
  details: () => { details.value = true },
  confirm: () => { confirm.value = true },
  aiSelection: () => { parent.value = false; aiSelection.value = true; aiBusy.value = true; cancellations.value = 0 },
  cancellations: () => cancellations.value,
} })
createApp({ render: () => h('div', [
  h('div', { 'data-escape-layer': '', style: 'display:none;z-index:400' }, 'Cached hidden layer'),
  scoped.value ? h('div', { style: 'position:relative;z-index:10' }, [
    h('div', { 'data-escape-layer': '', 'data-test-scoped-menu': '', style: 'position:fixed;z-index:9999;top:10px;left:10px' }, 'Menu below the dialog'),
  ]) : null,
  // Deliberately before the lower-tier parent in DOM and listener order.
  h(Sheet, { show: sheet.value, onClose: () => { sheet.value = false } }, () => h('div', { 'data-test-sheet': '' }, 'Top sheet')),
  h(Modal, { show: parent.value, onClose: () => { parent.value = false } }, () => h('div', { 'data-test-parent': '', class: 'p-4' }, [
    h('input', { 'aria-label': 'Dialog field' }),
    h(SettingsDropdown, { modelValue: 'a', options: [{ value: 'a', label: 'Alpha' }, { value: 'b', label: 'Beta' }] }),
  ])),
  h(GenerationDetailsModal, { show: details.value, title: 'Generation details', onClose: () => { details.value = false } }),
  h(Modal, { show: confirm.value, nested: true, onClose: () => { confirm.value = false } }, () => h('div', { 'data-test-confirm': '' }, 'Confirmation')),
  aiSelection.value ? h(SelectIsland, {
    armed: null, hasSelection: false, combine: 'new', featherPx: 0, tolerance: 20,
    spread: 0, growPx: 0, antialias: true, brushSize: 20,
    gradientSoftness: 50, gradientFeather: 50, aiBusy: aiBusy.value,
    onAiCancel: () => { cancellations.value++; aiBusy.value = false },
  }) : null,
]) }).mount('#app')
