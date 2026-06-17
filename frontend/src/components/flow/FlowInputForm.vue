<template>
  <div class="flow-input-form space-y-3" @keydown.capture="onCommitShortcut">
    <div v-if="fields.length === 0" class="text-[12px] text-content-muted italic">
      This flow has no inputs yet. Ask the assistant to add the inputs you want to vary.
    </div>

    <div
      v-for="field in fields"
      :key="field.name"
      class="rounded-lg border border-edge-subtle bg-overlay-faint px-4 py-3"
      :class="field.kind === 'prompt' ? 'space-y-3' : 'flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-6'"
    >
      <div :class="field.kind === 'prompt' ? '' : 'sm:w-[42%] sm:flex-shrink-0'">
        <label class="block text-sm font-medium text-content" :title="field.label">
          {{ field.label }}<span v-if="field.required" class="text-red-400 ml-0.5">*</span>
        </label>
        <div v-if="field.description" class="text-xs text-content-muted mt-0.5 leading-snug">
          {{ field.description }}
        </div>
      </div>
      <div :class="field.kind === 'prompt' ? 'w-full' : 'flex-1 min-w-0 sm:max-w-xl'">
        <select
          v-if="field.kind === 'enum'"
          v-model="values[field.name]"
          class="w-full bg-base border rounded px-2 py-1.5 text-sm text-content focus:outline-none"
          :class="fieldInputClass(field)"
        >
          <option v-for="opt in field.options" :key="String(opt)" :value="opt">{{ formatOption(field, opt) }}</option>
        </select>

        <div
          v-else-if="field.kind === 'list'"
          class="w-full bg-base border rounded p-2 text-sm transition-colors"
          :class="fieldInputClass(field)"
        >
          <div v-if="listValue(field.name).length === 0" class="text-content-muted text-center py-2 italic">
            No items yet.
          </div>
          <div v-else class="space-y-1.5">
            <div v-for="(_item, idx) in listValue(field.name)" :key="idx" class="flex items-center gap-1.5">
              <input
                :value="String(listValue(field.name)[idx] ?? '')"
                type="text"
                class="flex-1 min-w-0 bg-surface border border-edge rounded px-2 py-1.5 text-sm text-content focus:outline-none focus:border-blue-500/70"
                :placeholder="field.itemLabel"
                @input="setListItem(field, idx, ($event.target as HTMLInputElement).value)"
                @paste="(event) => onPasteList(field, idx, event)"
              />
              <button type="button" class="w-7 h-7 rounded border border-edge text-content-muted hover:text-content hover:bg-overlay-subtle" title="Move up" @click="moveListItem(field.name, idx, -1)">↑</button>
              <button type="button" class="w-7 h-7 rounded border border-edge text-content-muted hover:text-content hover:bg-overlay-subtle" title="Move down" @click="moveListItem(field.name, idx, 1)">↓</button>
              <button type="button" class="w-7 h-7 rounded border border-edge text-content-muted hover:text-red-400 hover:bg-overlay-subtle" title="Remove" @click="removeListItem(field.name, idx)">×</button>
            </div>
          </div>
          <div class="mt-2 flex flex-wrap items-center gap-2">
            <button type="button" class="px-2 py-1 rounded border border-edge text-[12px] text-content-secondary hover:bg-overlay-subtle" @click="addListItem(field)">
              Add {{ field.itemLabel.toLowerCase() }}
            </button>
            <button type="button" class="px-2 py-1 rounded border border-edge text-[12px] text-content-secondary hover:bg-overlay-subtle" @click="showPaste[field.name] = !showPaste[field.name]">
              Paste items
            </button>
            <span class="text-[11px] text-content-tertiary">{{ listValue(field.name).length }} item{{ listValue(field.name).length === 1 ? '' : 's' }}</span>
          </div>
          <div v-if="showPaste[field.name]" class="mt-2 space-y-1.5">
            <textarea
              v-model="pasteText[field.name]"
              rows="3"
              class="w-full bg-surface border border-edge rounded px-2 py-1.5 text-sm text-content focus:outline-none focus:border-blue-500/70"
              placeholder="Paste one item per line, or comma-separated items"
            />
            <button type="button" class="px-2 py-1 rounded bg-blue-600 text-white text-[12px] hover:bg-blue-500" @click="importPastedList(field)">
              Import
            </button>
          </div>
        </div>

        <div
          v-else-if="field.kind === 'table'"
          class="w-full bg-base border rounded p-2 text-sm transition-colors overflow-x-auto"
          :class="fieldInputClass(field)"
        >
          <table class="w-full min-w-[420px] border-collapse">
            <thead>
              <tr class="text-left text-[11px] text-content-muted">
                <th v-for="col in field.columns" :key="col.name" class="font-medium pb-1 pr-2">{{ col.label }}</th>
                <th class="w-20 pb-1"></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(_row, idx) in listValue(field.name)" :key="idx">
                <td v-for="col in field.columns" :key="col.name" class="pr-2 py-1 align-top">
                  <input
                    v-if="col.kind !== 'boolean'"
                    :type="col.kind === 'number' ? 'number' : 'text'"
                    :value="tableCellValue(field.name, idx, col.name)"
                    class="w-full min-w-0 bg-surface border border-edge rounded px-2 py-1.5 text-sm text-content focus:outline-none focus:border-blue-500/70"
                    @input="setTableCell(field, idx, col, ($event.target as HTMLInputElement).value)"
                  />
                  <input
                    v-else
                    type="checkbox"
                    :checked="Boolean(tableCellValue(field.name, idx, col.name))"
                    class="mt-1.5"
                    @change="setTableCell(field, idx, col, ($event.target as HTMLInputElement).checked)"
                  />
                </td>
                <td class="py-1 align-top">
                  <div class="flex items-center gap-1">
                    <button type="button" class="w-7 h-7 rounded border border-edge text-content-muted hover:text-content hover:bg-overlay-subtle" title="Move up" @click="moveListItem(field.name, idx, -1)">↑</button>
                    <button type="button" class="w-7 h-7 rounded border border-edge text-content-muted hover:text-red-400 hover:bg-overlay-subtle" title="Remove" @click="removeListItem(field.name, idx)">×</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-if="listValue(field.name).length === 0" class="text-content-muted text-center py-2 italic">
            No rows yet.
          </div>
          <div class="mt-2 flex items-center gap-2">
            <button type="button" class="px-2 py-1 rounded border border-edge text-[12px] text-content-secondary hover:bg-overlay-subtle" @click="addTableRow(field)">
              Add row
            </button>
            <span class="text-[11px] text-content-tertiary">{{ listValue(field.name).length }} row{{ listValue(field.name).length === 1 ? '' : 's' }}</span>
          </div>
        </div>

        <div v-else-if="field.kind === 'number'" class="flex items-center gap-2">
          <input
            v-if="field.control === 'slider'"
            v-model.number="values[field.name]"
            type="range"
            class="w-48 h-1 bg-surface-raised rounded-sm appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-blue-500 [&::-webkit-slider-thumb]:rounded-full"
            :min="field.min ?? 0"
            :max="field.max ?? 100"
            :step="field.step ?? (field.type === 'int' ? 1 : 0.1)"
          />
          <input
            v-model.number="values[field.name]"
            type="number"
            class="w-32 bg-base border rounded px-2 py-1.5 text-sm text-content focus:outline-none"
            :class="fieldInputClass(field)"
            :min="field.min"
            :max="field.max"
            :step="field.step"
          />
        </div>

        <input
          v-else-if="field.kind === 'boolean'"
          v-model="values[field.name]"
          type="checkbox"
          class="mt-1.5"
        />

        <div
          v-else-if="field.kind === 'media'"
          class="w-20 h-20 relative group bg-base border rounded overflow-hidden flex-shrink-0 transition-colors"
          :class="dragHover[field.name] ? 'border-blue-500/70 bg-blue-500/5' : fieldInputClass(field)"
          @dragover.prevent="() => (dragHover[field.name] = true)"
          @dragleave="() => (dragHover[field.name] = false)"
          @drop.prevent="(e) => onDropMedia(field.name, e, false)"
        >
          <div v-if="!values[field.name]" class="w-full h-full flex items-center justify-center text-content-muted text-[11px] italic text-center px-1">
            Drop image here
          </div>
          <template v-else>
            <MediaImage :mediaId="values[field.name]" :contain="true" container-class="w-full h-full" />
            <button
              type="button"
              class="absolute top-1 right-1 w-6 h-6 bg-black/60 hover:bg-red-500/80 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity text-white"
              @click.prevent="values[field.name] = null"
              title="Remove"
            >×</button>
          </template>
        </div>

        <div
          v-else-if="field.kind === 'media_list'"
          class="w-full bg-base border rounded p-2 text-[13px] transition-colors"
          :class="dragHover[field.name] ? 'border-blue-500/70 bg-blue-500/5' : fieldInputClass(field)"
          @dragover.prevent="() => (dragHover[field.name] = true)"
          @dragleave="() => (dragHover[field.name] = false)"
          @drop.prevent="(e) => onDropMedia(field.name, e, true)"
        >
          <div v-if="!(values[field.name] && values[field.name].length)" class="text-content-muted text-center py-2 italic">
            Drop media items here.
          </div>
          <div v-else class="flex flex-wrap gap-2">
            <div v-for="(mid, idx) in (values[field.name] || [])" :key="mid" class="relative group">
              <MediaImage :mediaId="mid" :contain="true" container-class="w-12 h-12 rounded" />
              <button
                type="button"
                class="absolute -top-1 -right-1 bg-red-500 text-white rounded-full w-4 h-4 text-[10px] opacity-0 group-hover:opacity-100 transition-opacity"
                @click.prevent="removeMediaAt(field.name, idx)"
                title="Remove"
              >×</button>
            </div>
          </div>
        </div>

        <textarea
          v-else-if="field.kind === 'text' && (field.lines > 1 || field.control === 'textarea')"
          v-model="values[field.name]"
          :rows="field.lines"
          class="w-full bg-base border rounded px-2 py-1.5 text-sm text-content focus:outline-none resize-y"
          :class="fieldInputClass(field)"
          :placeholder="field.description || ''"
        />

        <AIPromptEditor
          v-else-if="field.kind === 'prompt'"
          v-model="values[field.name]"
          :rows="field.lines"
          :expanded="promptExpanded[field.name] || false"
          :prompt-options="promptOptions[field.name] || defaultPromptOptions()"
          :placeholder="field.description || 'Describe what you want...'"
          :hide-auto-improve="true"
          @update:expanded="promptExpanded[field.name] = $event"
          @update:prompt-options="promptOptions[field.name] = $event"
        />

        <input
          v-else
          v-model="values[field.name]"
          type="text"
          class="w-full bg-base border rounded px-2 py-1.5 text-sm text-content focus:outline-none"
          :class="fieldInputClass(field)"
          :placeholder="field.description || ''"
        />

        <div v-if="errors[field.name]" class="text-[11px] text-red-400 mt-0.5">
          {{ errors[field.name] }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import axios from 'axios'
import { MediaImage } from '../media'
import AIPromptEditor from '../generation/AIPromptEditor.vue'
import { getDroppedMediaIds } from '../../composables/useDragPreview'

interface Props {
  schema: Record<string, any> | null | undefined
  initialValues?: Record<string, any> | null
  applying?: boolean
  // Default prompt-field row count when the schema doesn't specify `lines`
  // / `ui.rows`. The full-page steps-view input card has plenty of vertical
  // room so it stays at 8; the workflow inspect panel passes a smaller
  // value so a single-field form doesn't dominate the panel.
  defaultPromptLines?: number
}
const props = withDefaults(defineProps<Props>(), {
  initialValues: null,
  applying: false,
  defaultPromptLines: 8,
})

const emit = defineEmits<{
  (e: 'submit', values: Record<string, any>): void
  (e: 'update:dirty', value: boolean): void
  (e: 'update:valid', value: boolean): void
}>()

type FieldKind = 'text' | 'prompt' | 'number' | 'enum' | 'list' | 'table' | 'boolean' | 'media' | 'media_list'
type ColumnKind = 'text' | 'number' | 'boolean'

interface TableColumn {
  name: string
  label: string
  kind: ColumnKind
  default?: any
}

interface Field {
  name: string
  label: string
  description: string
  type: string
  kind: FieldKind
  control: string
  options?: any[]
  optionLabels?: Record<string, string>
  required: boolean
  default?: any
  lines: number
  itemLabel: string
  itemType: string
  columns: TableColumn[]
  min?: number
  max?: number
  step?: number
  minItems?: number
  maxItems?: number
  unique?: boolean
}

const values = reactive<Record<string, any>>({})
const dragHover = reactive<Record<string, boolean>>({})
const showPaste = reactive<Record<string, boolean>>({})
const pasteText = reactive<Record<string, string>>({})
const promptExpanded = reactive<Record<string, boolean>>({})
const promptOptions = reactive<Record<string, any>>({})
let savedSnapshot = '{}'

function defaultPromptOptions() {
  return {
    autoImprove: { enabled: false, instructions: '' },
    varyPrompt: { enabled: false, instructions: '' },
  }
}

function humanizeName(name: string): string {
  const spaced = name.replace(/_+/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2').trim()
  if (!spaced) return name
  return spaced.charAt(0).toUpperCase() + spaced.slice(1).toLowerCase()
}

function normalizeSpec(def: any): any {
  return def && typeof def === 'object' ? def : { type: String(def || 'str') }
}

function typeToColumnKind(type: string): ColumnKind {
  if (type === 'bool' || type === 'boolean') return 'boolean'
  if (type === 'int' || type === 'integer' || type === 'float' || type === 'number') return 'number'
  return 'text'
}

function parseColumns(raw: any): TableColumn[] {
  const source = raw?.item?.fields || raw?.fields || {}
  return Object.entries(source).map(([name, def]) => {
    const d = normalizeSpec(def)
    const type = String(d.type || d.kind || 'str')
    return {
      name,
      label: d.display_name || d.label || humanizeName(name),
      kind: typeToColumnKind(type),
      default: d.default,
    }
  })
}

function listElementType(type: string): string {
  const match = type.match(/^list\[(.+)\]$/)
  return match ? match[1] : 'str'
}

const fields = computed<Field[]>(() => {
  const out: Field[] = []
  const schema = props.schema || {}
  for (const [name, rawDef] of Object.entries(schema)) {
    const d: any = normalizeSpec(rawDef)
    const type = String(d.type || d.kind || 'str')
    const ui = d.ui || {}
    const validation = d.validation || {}
    const control = String(ui.control || d.control || '')
    const columns = parseColumns(d)
    let kind: FieldKind = 'text'
    if (type === 'enum' || Array.isArray(d.options)) kind = 'enum'
    else if (type === 'prompt' || control === 'prompt') kind = 'prompt'
    else if (type === 'list[media]' || type === 'media_list' || type === 'list[image]') kind = 'media_list'
    else if (type === 'media' || type === 'image' || type === 'video') kind = 'media'
    else if ((type === 'list[json]' || type === 'list[dict]') && (control === 'table' || columns.length > 0)) kind = 'table'
    else if (type.startsWith('list') || Array.isArray(d.default)) kind = 'list'
    else if (type === 'int' || type === 'integer' || type === 'number' || type === 'float') kind = 'number'
    else if (type === 'bool' || type === 'boolean') kind = 'boolean'
    const rawLines = d.lines ?? ui.rows
    const promptDefault = props.defaultPromptLines
    const linesRaw = Number(rawLines ?? (kind === 'prompt' ? promptDefault : 1))
    const lines = Number.isFinite(linesRaw) && linesRaw > 0
      ? Math.floor(linesRaw)
      : (kind === 'prompt' ? promptDefault : 1)
    const required = d.required ?? (d.optional ? false : true)
    out.push({
      name,
      label: d.display_name || d.label || humanizeName(name),
      description: d.description || '',
      type,
      kind,
      control,
      options: d.options,
      optionLabels: d.option_labels || d.enumLabels,
      required,
      default: d.default,
      lines,
      itemLabel: ui.item_label || d.item_label || 'Item',
      itemType: String(d.item?.type || listElementType(type)),
      columns,
      min: validation.min ?? d.minimum ?? d.min,
      max: validation.max ?? d.maximum ?? d.max,
      step: validation.step ?? d.step,
      minItems: validation.min_items ?? d.min_items,
      maxItems: validation.max_items ?? d.max_items,
      unique: Boolean(validation.unique ?? d.unique ?? false),
    })
  }
  return out
})

const isDirty = computed(() => JSON.stringify(values) !== savedSnapshot)

function defaultValueFor(f: Field): any {
  if (f.default !== undefined) return clone(f.default)
  if (f.kind === 'list' || f.kind === 'media_list' || f.kind === 'table') return []
  if (f.kind === 'boolean') return false
  if (f.kind === 'number') return f.min ?? 0
  if (f.kind === 'media') return null
  return ''
}

function clone<T>(value: T): T {
  return value == null ? value : JSON.parse(JSON.stringify(value))
}

function applyInitial() {
  const seed = { ...(props.initialValues || {}) }
  for (const key of Object.keys(values)) delete values[key]
  for (const f of fields.value) {
    values[f.name] = seed[f.name] !== undefined ? clone(seed[f.name]) : defaultValueFor(f)
    if ((f.kind === 'list' || f.kind === 'table' || f.kind === 'media_list') && !Array.isArray(values[f.name])) {
      values[f.name] = []
    }
    pasteText[f.name] = ''
    showPaste[f.name] = false
    if (f.kind === 'prompt') {
      promptExpanded[f.name] = false
      promptOptions[f.name] = defaultPromptOptions()
    }
  }
  savedSnapshot = JSON.stringify(values)
}

applyInitial()

watch(() => [props.schema, props.initialValues], () => {
  const incoming = JSON.stringify(props.initialValues || {})
  if (!isDirty.value || incoming === savedSnapshot) applyInitial()
}, { deep: true })

function listValue(name: string): any[] {
  return Array.isArray(values[name]) ? values[name] : []
}

function coerceListItem(field: Field, value: any): any {
  if (field.itemType === 'int' || field.itemType === 'integer') {
    const n = Number(value)
    return Number.isFinite(n) ? Math.round(n) : 0
  }
  if (field.itemType === 'float' || field.itemType === 'number') {
    const n = Number(value)
    return Number.isFinite(n) ? n : 0
  }
  if (field.itemType === 'bool' || field.itemType === 'boolean') return Boolean(value)
  return String(value)
}

function setListItem(field: Field, idx: number, raw: any) {
  const arr = [...listValue(field.name)]
  arr[idx] = coerceListItem(field, raw)
  values[field.name] = arr
}

function addListItem(field: Field) {
  values[field.name] = [...listValue(field.name), coerceListItem(field, '')]
}

function removeListItem(name: string, idx: number) {
  const arr = [...listValue(name)]
  arr.splice(idx, 1)
  values[name] = arr
}

function moveListItem(name: string, idx: number, delta: number) {
  const arr = [...listValue(name)]
  const next = idx + delta
  if (next < 0 || next >= arr.length) return
  const [item] = arr.splice(idx, 1)
  arr.splice(next, 0, item)
  values[name] = arr
}

function parsePastedItems(text: string): string[] {
  return text
    .split(/\r?\n|,/)
    .map(s => s.trim())
    .filter(Boolean)
}

function importPastedList(field: Field) {
  const parsed = parsePastedItems(pasteText[field.name] || '').map(item => coerceListItem(field, item))
  if (!parsed.length) return
  values[field.name] = [...listValue(field.name), ...parsed]
  pasteText[field.name] = ''
  showPaste[field.name] = false
}

function onPasteList(field: Field, idx: number, event: ClipboardEvent) {
  const text = event.clipboardData?.getData('text') || ''
  const parsed = parsePastedItems(text)
  if (parsed.length <= 1) return
  event.preventDefault()
  const arr = [...listValue(field.name)]
  arr.splice(idx, 1, ...parsed.map(item => coerceListItem(field, item)))
  values[field.name] = arr
}

function emptyTableRow(field: Field): Record<string, any> {
  const row: Record<string, any> = {}
  for (const col of field.columns) {
    if (col.default !== undefined) row[col.name] = clone(col.default)
    else if (col.kind === 'boolean') row[col.name] = false
    else if (col.kind === 'number') row[col.name] = 0
    else row[col.name] = ''
  }
  return row
}

function addTableRow(field: Field) {
  values[field.name] = [...listValue(field.name), emptyTableRow(field)]
}

function tableCellValue(name: string, idx: number, colName: string): any {
  const row = listValue(name)[idx]
  return row && typeof row === 'object' ? row[colName] : ''
}

function setTableCell(field: Field, idx: number, col: TableColumn, raw: any) {
  const arr = [...listValue(field.name)]
  const row = { ...(arr[idx] || {}) }
  if (col.kind === 'number') {
    const n = Number(raw)
    row[col.name] = Number.isFinite(n) ? n : 0
  } else if (col.kind === 'boolean') {
    row[col.name] = Boolean(raw)
  } else {
    row[col.name] = String(raw)
  }
  arr[idx] = row
  values[field.name] = arr
}

async function onDropMedia(name: string, e: DragEvent, multi: boolean) {
  dragHover[name] = false
  const ids = getDroppedMediaIds(e.dataTransfer)
  if (ids.length) {
    if (multi) {
      const merged = [...listValue(name)]
      for (const id of ids) if (!merged.includes(id)) merged.push(id)
      values[name] = merged
    } else {
      values[name] = ids[0]
    }
    return
  }

  const files = e.dataTransfer?.files
  if (files && files.length > 0) {
    const imageFiles = Array.from(files).filter(f => f.type.startsWith('image/'))
    if (!imageFiles.length) return
    const filesToUpload = multi ? imageFiles : [imageFiles[0]]
    for (const file of filesToUpload) {
      try {
        const formData = new FormData()
        formData.append('file', file)
        const res = await axios.post('/api/generate/upload-reference', formData, {
          headers: { 'Content-Type': 'multipart/form-data' }
        })
        const mediaId = res.data.media_id
        if (multi) {
          const existing = listValue(name)
          if (!existing.includes(mediaId)) values[name] = [...existing, mediaId]
        } else {
          values[name] = mediaId
        }
      } catch (err) {
        console.error('Failed to upload dropped file:', err)
      }
    }
  }
}

function removeMediaAt(name: string, idx: number) {
  removeListItem(name, idx)
}

function resetToDefaults() {
  for (const f of fields.value) values[f.name] = defaultValueFor(f)
}

function discardChanges() {
  const saved = JSON.parse(savedSnapshot || '{}')
  for (const key of Object.keys(values)) delete values[key]
  for (const f of fields.value) values[f.name] = saved[f.name] !== undefined ? saved[f.name] : defaultValueFor(f)
}

function applyChanges() {
  if (!isValid.value || props.applying) return
  savedSnapshot = JSON.stringify(values)
  emit('submit', clone(values))
}

function onCommitShortcut(event: KeyboardEvent) {
  if (event.key !== 'Enter') return
  if (!event.metaKey && !event.ctrlKey) return
  if (event.isComposing) return
  event.preventDefault()
  event.stopPropagation()
  applyChanges()
}

defineExpose({ resetToDefaults, discardChanges, applyChanges })

const errors = computed<Record<string, string>>(() => {
  const out: Record<string, string> = {}
  for (const f of fields.value) {
    const v = values[f.name]
    if (f.required) {
      if (v === null || v === undefined) { out[f.name] = 'Required.'; continue }
      if (typeof v === 'string' && v.trim() === '') { out[f.name] = 'Required.'; continue }
      if (Array.isArray(v) && v.length === 0) { out[f.name] = 'Provide at least one item.'; continue }
    }
    if (f.kind === 'number' && v !== '' && v !== null && v !== undefined) {
      if (typeof v !== 'number' || Number.isNaN(v)) { out[f.name] = 'Must be a number.'; continue }
      if (f.min !== undefined && v < f.min) { out[f.name] = `Must be at least ${f.min}.`; continue }
      if (f.max !== undefined && v > f.max) { out[f.name] = `Must be at most ${f.max}.`; continue }
    }
    if (f.kind === 'enum' && v !== null && v !== undefined && v !== '') {
      if (Array.isArray(f.options) && !f.options.includes(v)) out[f.name] = `Must be one of: ${f.options.join(', ')}.`
    }
    if ((f.kind === 'list' || f.kind === 'table' || f.kind === 'media_list') && Array.isArray(v)) {
      if (f.minItems !== undefined && v.length < f.minItems) { out[f.name] = `Provide at least ${f.minItems} item${f.minItems === 1 ? '' : 's'}.`; continue }
      if (f.maxItems !== undefined && v.length > f.maxItems) { out[f.name] = `Provide at most ${f.maxItems} item${f.maxItems === 1 ? '' : 's'}.`; continue }
      if (f.unique) {
        const seen = new Set(v.map(item => JSON.stringify(item)))
        if (seen.size !== v.length) { out[f.name] = 'Items must be unique.'; continue }
      }
      if (f.kind === 'list' && v.some(item => String(item).trim() === '')) { out[f.name] = 'Remove empty items or fill them in.'; continue }
    }
    if (f.kind === 'media' && v !== null && v !== undefined && typeof v !== 'number') out[f.name] = 'Must be a media reference.'
    if (f.kind === 'media_list' && Array.isArray(v) && v.some(x => typeof x !== 'number')) out[f.name] = 'Media list contains invalid entries.'
  }
  return out
})

const isValid = computed(() => Object.keys(errors.value).length === 0)

watch(isDirty, (v) => emit('update:dirty', v), { immediate: true })
watch(isValid, (v) => emit('update:valid', v), { immediate: true })

function fieldInputClass(f: Field): string {
  return errors.value[f.name]
    ? 'border-red-500/60 focus:border-red-500/80'
    : 'border-edge focus:border-blue-500/70'
}

function formatOption(field: Field, opt: any): string {
  return field.optionLabels?.[String(opt)] || String(opt)
}
</script>
