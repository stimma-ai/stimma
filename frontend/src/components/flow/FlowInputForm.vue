<template>
  <div class="flow-input-form" @keydown.capture="onCommitShortcut">
    <div v-if="fields.length === 0" class="text-[12px] text-content-muted italic">
      This flow has no inputs yet. Ask the assistant to add the inputs you want to vary.
    </div>

    <div v-else class="rounded-lg border border-edge-subtle bg-overlay-faint divide-y divide-white/[0.06]">
      <!-- Resolution-family pickers — same controls ToolView uses, so the flow
           and the tool it freezes into look identical. -->
      <div v-if="res.allowedDimensions" class="px-4 py-3">
        <label class="block text-sm font-medium text-content mb-2">Resolution</label>
        <ConstrainedResolutionPicker
          :allowed-dimensions="res.allowedDimensions"
          :width="numVal('width', res.allowedDimensions[0][0])"
          :height="numVal('height', res.allowedDimensions[0][1])"
          @update="setDims"
        />
      </div>
      <div v-else-if="res.hasWidthHeight && !res.hasMegapixels" class="px-4 py-3">
        <label class="block text-sm font-medium text-content mb-2">Resolution</label>
        <ResolutionPicker
          :width="numVal('width', 1024)"
          :height="numVal('height', 1024)"
          :has-reference-images="hasReferenceImages"
          @update="setDims"
        />
      </div>

      <div v-if="res.hasAspectRatio" class="px-4 py-3">
        <label class="block text-sm font-medium text-content mb-2">Aspect ratio</label>
        <GeminiResolutionPicker
          :aspect-ratio="String(values.aspect_ratio ?? '1:1')"
          :image-size="String(values.image_size ?? '1K')"
          :image-size-choices="imageSizeChoices"
          @update:aspect-ratio="values.aspect_ratio = $event"
          @update:image-size="setImageSize($event)"
        />
      </div>

      <div v-if="res.hasMegapixels" class="px-4 py-3">
        <label class="block text-sm font-medium text-content mb-2">Megapixels</label>
        <MegapixelsPicker
          :model-value="numVal('megapixels', 1)"
          :min-megapixels="megapixelsMin"
          :max-megapixels="megapixelsMax"
          @update:model-value="values.megapixels = $event"
        />
      </div>

      <div v-if="res.showUpscalePicker" class="px-4 py-3">
        <label class="block text-sm font-medium text-content mb-2">Upscale</label>
        <UpscaleResolutionPicker
          v-model="upscaleModel"
          :support-scale-factor="res.hasScaleFactor"
          :support-resolution="res.hasUpscaleResolution"
        />
      </div>

    <div
      v-for="field in visibleFields"
      :key="field.name"
      class="px-4 py-3"
    >
      <div :class="isStacked(field) ? '' : 'flex items-center justify-between gap-4'">
      <div :class="isStacked(field) ? 'mb-2' : 'min-w-0 flex-1'">
        <label class="block text-sm font-medium text-content" :title="field.label">
          {{ field.label }}<span v-if="field.required" class="text-red-400 ml-0.5">*</span>
        </label>
        <div v-if="field.description" class="text-xs text-content-muted mt-0.5 leading-snug">
          {{ field.description }}
        </div>
      </div>
      <div :class="isStacked(field) ? 'w-full' : 'flex-shrink-0'">
        <select
          v-if="field.kind === 'enum'"
          v-model="values[field.name]"
          class="w-56 max-w-full bg-base border rounded px-2 py-1.5 text-sm text-content focus:outline-none"
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
                class="flex-1 min-w-0 bg-surface border border-transparent rounded px-2 py-1.5 text-sm text-content focus:outline-none focus:border-accent"
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
              class="w-full bg-surface border border-transparent rounded px-2 py-1.5 text-sm text-content focus:outline-none focus:border-accent"
              placeholder="Paste one item per line, or comma-separated items"
            />
            <button type="button" class="px-2 py-1 rounded-md bg-accent text-white text-[12px] hover:bg-accent/90" @click="importPastedList(field)">
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
                    class="w-full min-w-0 bg-surface border border-transparent rounded px-2 py-1.5 text-sm text-content focus:outline-none focus:border-accent"
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

        <!-- Seed: committed value + dice (reroll). No auto-randomize on flows. -->
        <div v-else-if="field.kind === 'seed'" class="flex items-center gap-2">
          <input
            v-model.number="values[field.name]"
            type="number"
            class="w-32 bg-base border rounded px-2 py-1.5 text-sm text-content focus:outline-none"
            :class="fieldInputClass(field)"
            :min="field.min"
            :max="field.max"
            :step="field.step ?? 1"
          />
          <button
            type="button"
            class="flex items-center justify-center w-8 h-8 rounded-md border border-edge bg-overlay-subtle text-content-secondary hover:text-content hover:bg-overlay-hover transition-colors"
            title="Roll a new seed"
            @click="rerollSeed(field)"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.6" stroke="currentColor" class="w-4 h-4">
              <rect x="3.5" y="3.5" width="17" height="17" rx="3.5" />
              <circle cx="8.5" cy="8.5" r="1.15" fill="currentColor" stroke="none" />
              <circle cx="15.5" cy="8.5" r="1.15" fill="currentColor" stroke="none" />
              <circle cx="12" cy="12" r="1.15" fill="currentColor" stroke="none" />
              <circle cx="8.5" cy="15.5" r="1.15" fill="currentColor" stroke="none" />
              <circle cx="15.5" cy="15.5" r="1.15" fill="currentColor" stroke="none" />
            </svg>
          </button>
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
          class="w-4 h-4 rounded"
        />

        <div
          v-else-if="field.kind === 'media'"
          class="w-20 h-20 relative group bg-base border rounded overflow-hidden flex-shrink-0 transition-colors"
          :class="mediaTileClass(field)"
          @dragover.prevent="() => (dragHover[field.name] = true)"
          @dragleave="() => (dragHover[field.name] = false)"
          @drop.prevent="(e) => onDropMedia(field.name, e, false)"
        >
          <button
            v-if="!values[field.name]"
            type="button"
            class="w-full h-full flex items-center justify-center text-content-muted text-[11px] italic text-center px-1 cursor-pointer hover:text-content-secondary hover:bg-overlay-subtle transition-colors"
            @click="openPicker(field, false, $event)"
          >
            Click or drop {{ fieldAccept(field) }}
          </button>
          <template v-else>
            <MediaImage :mediaId="values[field.name]" :contain="true" container-class="w-full h-full" />
            <button
              type="button"
              class="absolute top-1 right-1 w-6 h-6 bg-black/60 hover:bg-red-500/80 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity text-white"
              @click.prevent="values[field.name] = null"
              title="Remove"
            >×</button>
            <button
              type="button"
              class="absolute bottom-1 right-1 w-6 h-6 bg-black/60 hover:bg-blue-500/80 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity text-white"
              title="Replace from library"
              @click.prevent="openPicker(field, false, $event)"
            >
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-3.5 h-3.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99" />
              </svg>
            </button>
          </template>
        </div>

        <div
          v-else-if="field.kind === 'media_list'"
          class="w-full bg-base border rounded p-2 text-[13px] transition-colors"
          :class="mediaTileClass(field)"
          @dragover.prevent="() => (dragHover[field.name] = true)"
          @dragleave="() => (dragHover[field.name] = false)"
          @drop.prevent="(e) => onDropMedia(field.name, e, true)"
        >
          <div class="flex flex-wrap gap-2">
            <div v-for="(mid, idx) in (values[field.name] || [])" :key="mid" class="relative group">
              <MediaImage :mediaId="mid" :contain="true" container-class="w-12 h-12 rounded" />
              <button
                type="button"
                class="absolute -top-1 -right-1 bg-red-500 text-white rounded-full w-4 h-4 text-[10px] opacity-0 group-hover:opacity-100 transition-opacity"
                @click.prevent="removeMediaAt(field.name, idx)"
                title="Remove"
              >×</button>
            </div>
            <button
              type="button"
              class="w-12 h-12 rounded border border-dashed border-edge text-content-muted hover:text-content-secondary hover:border-edge-strong hover:bg-overlay-subtle flex items-center justify-center text-lg cursor-pointer transition-colors"
              title="Add from library"
              @click="openPicker(field, true, $event)"
            >+</button>
            <span
              v-if="!(values[field.name] && values[field.name].length)"
              class="self-center text-content-muted italic text-[12px]"
            >Click + or drop media items here.</span>
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
      </div>
      </div>
      <div v-if="errors[field.name]" class="text-[11px] text-red-400 mt-1.5">
        {{ errors[field.name] }}
      </div>
    </div>
    </div>

    <!-- In-app library picker anchored to the clicked media tile; its
         "Browse Files…" footer falls through to the OS dialog below. -->
    <MediaPickerPopover
      v-if="picker"
      :accept="picker.accept"
      :anchor-el="picker.anchor"
      :exclude-ids="pickerExcludeIds"
      @pick="onPickerPick"
      @browse="onPickerBrowse"
      @close="picker = null"
    />
    <input
      ref="pickerFileInput"
      type="file"
      :accept="pickerFileAccept"
      class="hidden"
      @change="onPickerFileSelect"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import axios from 'axios'
import { MediaImage } from '../media'
import MediaPickerPopover from '../generation/MediaPickerPopover.vue'
import AIPromptEditor from '../generation/AIPromptEditor.vue'
import ResolutionPicker from '../ResolutionPicker.vue'
import MegapixelsPicker from '../generation/MegapixelsPicker.vue'
import GeminiResolutionPicker from '../generation/GeminiResolutionPicker.vue'
import ConstrainedResolutionPicker from '../generation/ConstrainedResolutionPicker.vue'
import UpscaleResolutionPicker from '../generation/UpscaleResolutionPicker.vue'
import { detectResolutionControls, paramsConsumedByResolutionPickers } from '../../utils/resolutionControls'
import { getDroppedMediaIds } from '../../composables/useDragPreview'
import { draggedMediaType } from '../../stores/dragStore'
import { fieldAcceptsDraggedType } from '../../utils/flowMediaInputs'
import { useMediaApi } from '../../composables/useMediaApi'
import { recordMediaInputUse, type RecentInputKind } from '../../composables/useRecentMediaInputs'
import { getMediaType } from '../../utils/mediaTypes'

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

type FieldKind = 'text' | 'prompt' | 'number' | 'seed' | 'enum' | 'list' | 'table' | 'boolean' | 'media' | 'media_list'
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
  const source = raw?.items?.properties || raw?.item?.fields || raw?.fields || {}
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
    // Canonical STP property (with tolerant fallbacks to any legacy shape).
    const type = String(d.type || d.kind || 'string')
    const ui = d.ui || {}
    const validation = d.validation || {}
    const format = String(d.format || '')
    const control = String(d['x-control'] || ui.control || d.control || '')
    const enumVals = Array.isArray(d.enum) ? d.enum : (Array.isArray(d.options) ? d.options : null)
    const itemFormat = String(d.items?.format || '')
    const columns = parseColumns(d)
    const isArray = type === 'array' || type.startsWith('list')
    let kind: FieldKind = 'text'
    if (enumVals) kind = 'enum'
    else if (control === 'prompt' || type === 'prompt') kind = 'prompt'
    else if (isArray && (itemFormat === 'file-path' || control === 'image_picker' || type === 'list[media]' || type === 'media_list' || type === 'list[image]')) kind = 'media_list'
    else if (format === 'file-path' || control === 'image_picker' || type === 'media' || type === 'image' || type === 'video') kind = 'media'
    else if (isArray && (control === 'table' || columns.length > 0)) kind = 'table'
    else if (isArray || Array.isArray(d.default)) kind = 'list'
    // Seed: a committed integer value with a dice (reroll) button — no
    // auto-randomize on the flow screen (that behavior is tool-screen only).
    else if (control === 'seed') kind = 'seed'
    else if (type === 'integer' || type === 'number' || type === 'int' || type === 'float') kind = 'number'
    else if (type === 'boolean' || type === 'bool') kind = 'boolean'
    const promptDefault = props.defaultPromptLines
    const rawLines = d.lines ?? ui.rows
    const wantsTextarea = control === 'textarea' || Number(rawLines) > 1
    const linesRaw = Number(rawLines ?? (kind === 'prompt' ? promptDefault : (wantsTextarea ? 4 : 1)))
    const lines = Number.isFinite(linesRaw) && linesRaw > 0
      ? Math.floor(linesRaw)
      : (kind === 'prompt' ? promptDefault : (wantsTextarea ? 4 : 1))
    const required = d.required ?? (d.optional ? false : true)
    out.push({
      name,
      label: d['x-label'] || d.display_name || d.label || humanizeName(name),
      description: d.description || '',
      type,
      kind,
      control: wantsTextarea && !control ? 'textarea' : control,
      options: enumVals || undefined,
      optionLabels: d['x-enum-labels'] || d.option_labels || d.enumLabels,
      required,
      default: d.default,
      lines,
      itemLabel: ui.item_label || d.item_label || 'Item',
      itemType: String(d.items?.type || d.item?.type || listElementType(type)),
      columns,
      min: d.minimum ?? validation.min ?? d.min,
      max: d.maximum ?? validation.max ?? d.max,
      step: d['x-step'] ?? validation.step ?? d.step,
      minItems: d.minItems ?? validation.min_items ?? d.min_items,
      maxItems: d.maxItems ?? validation.max_items ?? d.max_items,
      unique: Boolean(validation.unique ?? d.unique ?? false),
    })
  }
  return out
})

// ----- Resolution-family special controls (shared with ToolView) -----
// Same detection ToolView uses, so a flow's width/height/megapixels/aspect_ratio/
// upscale inputs render with the dedicated pickers here AND after freezing.
const normalizedProps = computed<Record<string, any>>(() => {
  const schema = props.schema || {}
  const out: Record<string, any> = {}
  for (const [name, def] of Object.entries(schema)) out[name] = normalizeSpec(def)
  return out
})
const res = computed(() => detectResolutionControls(normalizedProps.value))
const pickerConsumed = computed(() => paramsConsumedByResolutionPickers(normalizedProps.value))

// Rendered fields = all fields minus those a picker owns. `fields` stays the full
// list so values are still seeded + submitted for the picker-driven params.
const visibleFields = computed(() => fields.value.filter((f) => !pickerConsumed.value.has(f.name)))

// The resolution picker's "when reference images change" options only make
// sense if the flow actually takes reference images.
const hasReferenceImages = computed(() => 'input_images' in normalizedProps.value)
const imageSizeChoices = computed<string[]>(() => normalizedProps.value.image_size?.enum || [])
const megapixelsMin = computed<number | undefined>(() => normalizedProps.value.megapixels?.minimum)
const megapixelsMax = computed<number | undefined>(() => normalizedProps.value.megapixels?.maximum)

function numVal(name: string, fallback: number): number {
  const v = values[name]
  if (typeof v === 'number' && Number.isFinite(v)) return v
  const d = normalizedProps.value[name]?.default
  return typeof d === 'number' ? d : fallback
}
function setDims(width: number, height: number) {
  values.width = width
  values.height = height
}
// Only persist image_size if the flow actually declares it — otherwise an
// undeclared key would leak into the submitted values.
function setImageSize(value: string) {
  if ('image_size' in normalizedProps.value) values.image_size = value
}

// Upscale picker: a composite UI state ({mode, scaleFactor, targetResolution})
// over the flow's scale_factor / resolution inputs. Mode is UI-only (kept out of
// `values` so it isn't submitted to the flow).
const upscaleMode = ref<'relative' | 'pixels'>(
  // pixels if only a resolution value is present at start; else relative.
  props.initialValues?.resolution != null && props.initialValues?.scale_factor == null
    ? 'pixels'
    : 'relative',
)
const upscaleModel = computed({
  get: () => ({
    resolutionMode: upscaleMode.value,
    scaleFactor: numVal('scale_factor', 2),
    targetResolution: numVal('resolution', 1080),
  }),
  set: (v: { resolutionMode: 'relative' | 'pixels'; scaleFactor: number; targetResolution: number }) => {
    upscaleMode.value = v.resolutionMode
    if (res.value.hasScaleFactor) values.scale_factor = v.scaleFactor
    if (res.value.hasUpscaleResolution) values.resolution = v.targetResolution
  },
})

const isDirty = computed(() => JSON.stringify(values) !== savedSnapshot)

// A fresh random seed within the field's declared range. A seed should arrive
// pre-filled with a usable value (not empty), and a random default means repeat
// first-runs aren't identical.
function randomSeedFor(f: Field): number {
  const min = Number.isFinite(f.min as number) ? (f.min as number) : 0
  const max = Number.isFinite(f.max as number) ? (f.max as number) : 2147483647
  const span = Math.max(0, max - min)
  return min + Math.floor(Math.random() * (span + 1))
}

function defaultValueFor(f: Field): any {
  if (f.default !== undefined) return clone(f.default)
  if (f.kind === 'list' || f.kind === 'media_list' || f.kind === 'table') return []
  if (f.kind === 'boolean') return false
  if (f.kind === 'seed') return randomSeedFor(f)
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

// Roll a fresh seed into the field. This just sets a new committed value — the
// user still applies params as usual (no auto-randomize on the flow screen).
function rerollSeed(field: Field): void {
  values[field.name] = randomSeedFor(field)
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

const { getMediaItem } = useMediaApi()

// Feed the picker popover's frecency "All" tab, same as ToolView's
// addFromMediaId. Fire-and-forget: the value is already applied.
async function recordInputUse(mediaId: number) {
  try {
    const item = await getMediaItem(mediaId)
    const kind = getMediaType(item)
    if (kind === 'image' || kind === 'video' || kind === 'audio') {
      recordMediaInputUse({
        mediaId: item.id,
        fileHash: item.file_hash,
        fileFormat: item.file_format,
        kind: kind as RecentInputKind,
      })
    }
  } catch { /* frecency only — never block the assignment */ }
}

// Single entry point for library media landing in a field, whatever the path
// (tile drop, popover pick, chat-panel drop zone in FlowView).
function applyMediaIds(name: string, ids: number[], multi: boolean) {
  if (!ids.length) return
  if (multi) {
    const merged = [...listValue(name)]
    for (const id of ids) if (!merged.includes(id)) merged.push(id)
    values[name] = merged
  } else {
    values[name] = ids[0]
  }
  for (const id of ids) recordInputUse(id)
}

async function uploadFileToField(name: string, file: File, multi: boolean) {
  const endpoint = file.type.startsWith('video/')
    ? '/api/generate/upload-reference-video'
    : '/api/generate/upload-reference'
  try {
    const formData = new FormData()
    formData.append('file', file)
    const res = await axios.post(endpoint, formData, {
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
    console.error('Failed to upload file:', err)
  }
}

async function onDropMedia(name: string, e: DragEvent, multi: boolean) {
  dragHover[name] = false
  const ids = getDroppedMediaIds(e.dataTransfer)
  if (ids.length) {
    applyMediaIds(name, ids, multi)
    return
  }

  const files = e.dataTransfer?.files
  if (files && files.length > 0) {
    const mediaFiles = Array.from(files).filter(f => f.type.startsWith('image/') || f.type.startsWith('video/'))
    if (!mediaFiles.length) return
    const filesToUpload = multi ? mediaFiles : [mediaFiles[0]]
    for (const file of filesToUpload) await uploadFileToField(name, file, multi)
  }
}

// ----- Library picker popover + OS browse fallback -----

const picker = ref<{ field: string; multi: boolean; accept: 'image' | 'video' | 'audio'; anchor: HTMLElement } | null>(null)
const pickerFileInput = ref<HTMLInputElement | null>(null)

function fieldAccept(f: Field): 'image' | 'video' | 'audio' {
  const t = f.kind === 'media_list' ? f.itemType : f.type
  if (t === 'video') return 'video'
  if (t === 'audio') return 'audio'
  return 'image'
}

function openPicker(field: Field, multi: boolean, event: MouseEvent) {
  picker.value = {
    field: field.name,
    multi,
    accept: fieldAccept(field),
    anchor: event.currentTarget as HTMLElement,
  }
}

const pickerExcludeIds = computed<number[]>(() => {
  if (!picker.value) return []
  const v = values[picker.value.field]
  if (Array.isArray(v)) return v.filter((x) => typeof x === 'number')
  return typeof v === 'number' ? [v] : []
})

// Survives the popover closing: the file-input change event arrives after
// `picker` is already null.
const browseTarget = ref<{ field: string; multi: boolean; accept: 'image' | 'video' | 'audio' } | null>(null)

const pickerFileAccept = computed(() => {
  const accept = browseTarget.value?.accept ?? picker.value?.accept
  if (accept === 'video') return 'video/*'
  if (accept === 'audio') return 'audio/*'
  return 'image/*'
})

function onPickerPick(mediaId: number) {
  if (!picker.value) return
  const { field, multi } = picker.value
  applyMediaIds(field, [mediaId], multi)
  if (!multi) picker.value = null
}

function onPickerBrowse() {
  if (!picker.value) return
  const { field, multi, accept } = picker.value
  browseTarget.value = { field, multi, accept }
  picker.value = null
  nextTick(() => pickerFileInput.value?.click())
}

async function onPickerFileSelect(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  const target = browseTarget.value
  browseTarget.value = null
  if (!file || !target) return
  await uploadFileToField(target.field, file, target.multi)
}

// ----- Drag-compatibility highlight -----

// While an in-app media drag is under way (dragStore is set on dragstart),
// light up the fields that can take the dragged type so they read as live
// targets even before the cursor reaches them.
function acceptsDraggedType(f: Field): boolean {
  return fieldAcceptsDraggedType(fieldAccept(f), draggedMediaType.value)
}

function mediaTileClass(f: Field): string {
  if (dragHover[f.name]) return 'border-blue-500/70 bg-blue-500/5'
  if (acceptsDraggedType(f)) return 'border-blue-500/40 bg-blue-500/[0.03]'
  return fieldInputClass(f)
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
  // Only validate visible fields. Picker-consumed fields (width/height/etc.) are
  // hidden and managed by their pickers, so a required-but-hidden field must not
  // produce an invisible blocker with no on-screen error to fix.
  for (const f of visibleFields.value) {
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

// Larger controls render label-on-top with the control full-width below
// (matching ToolView's textarea rows); compact controls sit label-left /
// control-right on a single line.
function isStacked(f: Field): boolean {
  return f.kind === 'prompt' || f.kind === 'text' || f.kind === 'list'
    || f.kind === 'table' || f.kind === 'media_list'
}

function fieldInputClass(f: Field): string {
  return errors.value[f.name]
    ? 'border-red-500/60 focus:border-red-500/80'
    : 'border-transparent focus:border-accent'
}

function formatOption(field: Field, opt: any): string {
  return field.optionLabels?.[String(opt)] || String(opt)
}
</script>
