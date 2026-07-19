<template>
  <div class="flow-input-form" @keydown.capture="onCommitShortcut">
    <div v-if="fields.length === 0" class="text-xs text-content-muted italic">
      This flow has no inputs yet. Ask the assistant to add the inputs you want to vary.
    </div>

    <!-- Hairline budget: multi-line field rows separate by whitespace only;
         the compact single-line list rows below keep their per-row rules. -->
    <div v-else>
      <!-- Resolution-family pickers — same controls ToolView uses, so the flow
           and the tool it freezes into look identical. -->
      <div v-if="res.allowedDimensions" class="py-2.5">
        <label class="block text-xs font-semibold text-content-secondary mb-2">Resolution</label>
        <ConstrainedResolutionPicker
          :allowed-dimensions="res.allowedDimensions"
          :width="numVal('width', res.allowedDimensions[0][0])"
          :height="numVal('height', res.allowedDimensions[0][1])"
          @update="setDims"
        />
      </div>
      <div v-else-if="res.hasWidthHeight && !res.hasMegapixels" class="py-2.5">
        <label class="block text-xs font-semibold text-content-secondary mb-2">Resolution</label>
        <ResolutionPicker
          :width="numVal('width', 1024)"
          :height="numVal('height', 1024)"
          :has-reference-images="hasReferenceImages"
          @update="setDims"
        />
      </div>

      <div v-if="res.hasAspectRatio" class="py-2.5">
        <label class="block text-xs font-semibold text-content-secondary mb-2">Aspect ratio</label>
        <GeminiResolutionPicker
          :aspect-ratio="String(values.aspect_ratio ?? '1:1')"
          :image-size="String(values.image_size ?? '1K')"
          :image-size-choices="imageSizeChoices"
          @update:aspect-ratio="values.aspect_ratio = $event"
          @update:image-size="setImageSize($event)"
        />
      </div>

      <div v-if="res.hasMegapixels" class="py-2.5">
        <label class="block text-xs font-semibold text-content-secondary mb-2">Megapixels</label>
        <MegapixelsPicker
          :model-value="numVal('megapixels', 1)"
          :min-megapixels="megapixelsMin"
          :max-megapixels="megapixelsMax"
          @update:model-value="values.megapixels = $event"
        />
      </div>

      <div v-if="res.showUpscalePicker" class="py-2.5">
        <label class="block text-xs font-semibold text-content-secondary mb-2">Upscale</label>
        <UpscaleResolutionPicker
          v-model="upscaleModel"
          :support-scale-factor="res.hasScaleFactor"
          :support-resolution="res.hasUpscaleResolution"
        />
      </div>

    <div
      v-for="field in visibleFields"
      :key="field.name"
      class="py-2.5"
    >
      <div :class="isStacked(field) ? '' : 'flex items-center justify-between gap-4'">
      <div :class="isStacked(field) ? 'mb-2' : 'min-w-0 flex-1'">
        <label class="block text-[13px] text-content-secondary" :title="field.label">
          {{ field.label }}<span v-if="field.required" class="text-red-400 ml-0.5">*</span>
        </label>
        <div v-if="field.description" class="text-xs text-content-muted mt-0.5 leading-snug">
          {{ field.description }}
        </div>
      </div>
      <div :class="isStacked(field) ? 'w-full' : 'flex-shrink-0'">
        <SettingsDropdown
          v-if="field.kind === 'enum'"
          :model-value="String(values[field.name] ?? '')"
          @update:model-value="values[field.name] = coerceEnumValue(field, $event)"
          :options="(field.options || []).map((opt) => ({ value: String(opt), label: formatOption(field, opt) }))"
          quiet
        />

        <!-- List: compact chip wrap panel; the popup editor handles reorder,
             fast entry, and bulk paste. -->
        <div v-else-if="field.kind === 'list'" class="w-full">
          <div class="flex flex-wrap items-center gap-1.5">
            <button
              v-for="(item, idx) in listValue(field.name)"
              :key="idx"
              type="button"
              class="group/chip inline-flex items-center gap-1 pl-2.5 pr-1.5 py-1 bg-surface-raised rounded-full text-xs text-content-secondary hover:text-content transition-colors max-w-full"
              @click="openListEditor(field, $event)"
            >
              <span class="truncate">{{ String(item) }}</span>
              <span
                role="button"
                class="w-3.5 h-3.5 flex items-center justify-center rounded-full text-content-muted hover:text-red-400 opacity-0 group-hover/chip:opacity-100 transition-opacity"
                title="Remove"
                @click.stop="removeListItem(field.name, idx)"
              >
                <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </span>
            </button>
            <button
              type="button"
              class="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs text-content-muted hover:text-content-secondary hover:bg-overlay-subtle transition-colors"
              @click="openListEditor(field, $event)"
            >
              <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path stroke-linecap="round" d="M12 5v14M5 12h14" /></svg>
              {{ listValue(field.name).length ? 'Edit' : `Add ${field.itemLabel.toLowerCase()}s` }}
            </button>
          </div>
        </div>

        <div
          v-else-if="field.kind === 'table'"
          class="w-full text-sm overflow-x-auto"
        >
          <table class="w-full min-w-[420px] border-collapse">
            <thead>
              <tr class="text-left text-xs text-content-tertiary">
                <th v-for="col in field.columns" :key="col.name" class="font-normal pb-1.5 pr-2 border-b border-edge-subtle">{{ col.label }}</th>
                <th class="w-16 pb-1.5 border-b border-edge-subtle"></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(_row, idx) in listValue(field.name)" :key="idx" class="group border-b border-edge-subtle last:border-0">
                <td v-for="col in field.columns" :key="col.name" class="pr-2 py-1.5 align-top">
                  <input
                    v-if="col.kind !== 'boolean'"
                    :type="col.kind === 'number' ? 'number' : 'text'"
                    :value="tableCellValue(field.name, idx, col.name)"
                    class="w-full min-w-0 bg-overlay-subtle border border-transparent rounded-md px-3 py-1.5 text-sm text-content focus:outline-none focus:border-accent focus-visible:ring-2 ring-accent/40"
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
                <td class="py-1.5 align-top">
                  <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button type="button" class="w-6 h-6 rounded-md text-content-tertiary hover:text-content hover:bg-overlay-subtle" title="Move up" @click="moveListItem(field.name, idx, -1)">↑</button>
                    <button type="button" class="w-6 h-6 rounded-md text-content-tertiary hover:text-red-400 hover:bg-overlay-subtle" title="Remove" @click="removeListItem(field.name, idx)">×</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-if="listValue(field.name).length === 0" class="text-content-muted text-center py-2 italic text-xs">
            No rows yet.
          </div>
          <div class="mt-2 flex items-center gap-3">
            <button type="button" class="text-xs text-content-secondary hover:text-content" @click="addTableRow(field)">
              + Add row
            </button>
            <span class="text-xs font-mono tabular-nums text-content-tertiary">{{ listValue(field.name).length }} row{{ listValue(field.name).length === 1 ? '' : 's' }}</span>
          </div>
        </div>

        <!-- Seed: committed mono value + dice (reroll). No auto-randomize on flows. -->
        <div v-else-if="field.kind === 'seed'" class="flex items-center justify-end gap-1.5">
          <input
            v-model.number="values[field.name]"
            type="number"
            class="w-24 text-right bg-transparent border-b border-transparent font-mono tabular-nums text-xs text-content-secondary focus:border-accent focus:text-content outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
            :class="errors[field.name] ? 'border-red-500/60' : ''"
            :min="field.min"
            :max="field.max"
            :step="field.step ?? 1"
          />
          <button
            type="button"
            class="flex items-center justify-center w-6 h-6 rounded-md text-content-tertiary hover:text-content hover:bg-overlay-subtle transition-colors"
            title="Roll a new seed"
            @click="rerollSeed(field)"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor" class="w-4 h-4">
              <rect x="3.5" y="3.5" width="17" height="17" rx="3.5" />
              <circle cx="8.5" cy="8.5" r="1.15" fill="currentColor" stroke="none" />
              <circle cx="15.5" cy="8.5" r="1.15" fill="currentColor" stroke="none" />
              <circle cx="12" cy="12" r="1.15" fill="currentColor" stroke="none" />
              <circle cx="8.5" cy="15.5" r="1.15" fill="currentColor" stroke="none" />
              <circle cx="15.5" cy="15.5" r="1.15" fill="currentColor" stroke="none" />
            </svg>
          </button>
        </div>

        <!-- Number: the ToolView value-row grammar — drag the mono value to
             scrub, click to open the slider/text popover. -->
        <ScrubValue
          v-else-if="field.kind === 'number'"
          :model-value="Number(values[field.name] ?? field.default ?? field.min ?? 0)"
          @update:model-value="values[field.name] = $event"
          :min="field.min ?? 0"
          :max="field.max ?? 100"
          :step="field.step ?? (field.type === 'int' || field.type === 'integer' ? 1 : 0.1)"
          :non-default="field.default !== undefined && values[field.name] !== field.default"
        />

        <input
          v-else-if="field.kind === 'boolean'"
          v-model="values[field.name]"
          type="checkbox"
          class="w-4 h-4 rounded accent-[rgb(var(--color-accent-rgb))] cursor-pointer"
        />

        <!-- Media (single): ToolView reference-slot grammar — tall tile on
             matte when filled, dashed add tile when empty. -->
        <div
          v-else-if="field.kind === 'media'"
          class="w-full transition-colors rounded-md"
          :class="mediaTileClass(field)"
          @dragover.prevent="() => (dragHover[field.name] = true)"
          @dragleave="() => (dragHover[field.name] = false)"
          @drop.prevent="(e) => onDropMedia(field.name, e, false)"
        >
          <div
            v-if="!values[field.name]"
            class="border border-dashed rounded-lg flex flex-col items-center justify-center gap-1 transition-colors cursor-pointer h-24 w-full border-edge text-content-muted hover:border-accent"
            @click="openPicker(field, false, $event)"
          >
            <span class="text-xs text-content-muted flex items-center gap-1.5">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              {{ dragHover[field.name] ? 'Drop here' : `Add ${fieldAccept(field)} — drop or browse` }}
            </span>
          </div>
          <div v-else class="relative group bg-matte overflow-hidden rounded-media w-full h-[18.5rem]">
            <MediaImage :mediaId="values[field.name]" :contain="true" container-class="w-full h-full" />
            <button
              type="button"
              class="absolute top-1 right-1 w-6 h-6 bg-black/60 hover:bg-red-500/80 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
              @click.prevent="values[field.name] = null"
              title="Remove"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 text-white">
                <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
              </svg>
            </button>
            <button
              type="button"
              class="absolute bottom-1 right-1 w-6 h-6 bg-black/60 hover:bg-accent/80 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity text-white"
              title="Replace from library"
              @click.prevent="openPicker(field, false, $event)"
            >
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor" class="w-3.5 h-3.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99" />
              </svg>
            </button>
          </div>
        </div>

        <!-- Media list: ToolView reference-images grammar — tile grid on
             matte, order badges, hover remove; dashed tile when empty and a
             compact ghost Add row once items exist. -->
        <div
          v-else-if="field.kind === 'media_list'"
          class="w-full transition-colors rounded-md"
          :class="mediaTileClass(field)"
          @dragover.prevent="() => (dragHover[field.name] = true)"
          @dragleave="() => (dragHover[field.name] = false)"
          @drop.prevent="(e) => onDropMedia(field.name, e, true)"
        >
          <div
            v-if="!(values[field.name] && values[field.name].length)"
            class="border border-dashed rounded-lg flex flex-col items-center justify-center gap-1 transition-colors cursor-pointer h-24 w-full border-edge text-content-muted hover:border-accent"
            @click="openPicker(field, true, $event)"
          >
            <span class="text-xs text-content-muted flex items-center gap-1.5">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              {{ dragHover[field.name] ? 'Drop here' : `Add ${fieldAccept(field)}s — drop or browse` }}
            </span>
          </div>
          <template v-else>
            <div class="grid gap-3 items-start [grid-template-columns:repeat(auto-fill,minmax(min(100%,15rem),1fr))]">
              <div
                v-for="(mid, idx) in (values[field.name] || [])"
                :key="mid"
                class="relative group bg-matte overflow-hidden rounded-media w-full h-[18.5rem]"
              >
                <MediaImage :mediaId="mid" :contain="true" container-class="w-full h-full" />
                <div v-if="(values[field.name] || []).length > 1" class="absolute top-1 left-1 w-5 h-5 bg-black/70 rounded-full flex items-center justify-center pointer-events-none">
                  <span class="text-xs text-white font-medium">{{ idx + 1 }}</span>
                </div>
                <button
                  type="button"
                  class="absolute top-1 right-1 w-6 h-6 bg-black/60 hover:bg-red-500/80 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                  @click.prevent="removeMediaAt(field.name, idx)"
                  title="Remove"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 text-white">
                    <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
                  </svg>
                </button>
              </div>
            </div>
            <button
              type="button"
              class="mt-1.5 w-full flex items-center gap-1.5 rounded-md px-1 py-1.5 text-xs cursor-pointer transition-colors text-content-muted hover:text-content-secondary hover:bg-overlay-subtle"
              @click="openPicker(field, true, $event)"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
                <path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z" />
              </svg>
              {{ dragHover[field.name] ? 'Drop here' : 'Add' }}
            </button>
          </template>
        </div>

        <textarea
          v-else-if="field.kind === 'text' && (field.lines > 1 || field.control === 'textarea')"
          v-model="values[field.name]"
          :rows="field.lines"
          class="w-full bg-overlay-subtle border border-transparent rounded-md px-3 py-2 text-sm text-content focus:outline-none focus-visible:ring-2 ring-accent/40 resize-y"
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
          class="w-full bg-overlay-subtle border border-transparent rounded-md px-3 py-2 text-sm text-content focus:outline-none focus-visible:ring-2 ring-accent/40"
          :class="fieldInputClass(field)"
          :placeholder="field.description || ''"
        />
      </div>
      </div>
      <div v-if="errors[field.name]" class="text-xs text-red-400 mt-1.5">
        {{ errors[field.name] }}
      </div>
    </div>
    </div>

    <!-- List popup editor: drag to reorder, fast Enter-to-add entry (the
         settings-wildcards pattern), multi-line/comma paste import. -->
    <Teleport to="body">
      <template v-if="listEditor">
        <div class="fixed inset-0 z-menu" @click="closeListEditor" @contextmenu.prevent="closeListEditor"></div>
        <div
          class="fixed z-submenu w-80 bg-surface border border-edge-subtle rounded-lg shadow-lg flex flex-col"
          :style="listEditorStyle"
          @keydown.escape.stop="closeListEditor"
        >
          <div class="px-3 pt-2.5 pb-1.5 flex items-baseline justify-between gap-2">
            <span class="text-xs font-semibold text-content-secondary truncate">{{ listEditorField?.label }}</span>
            <span class="text-[10px] font-mono tabular-nums text-content-tertiary">{{ listValue(listEditor.field).length }} item{{ listValue(listEditor.field).length === 1 ? '' : 's' }}</span>
          </div>
          <div class="max-h-72 overflow-y-auto custom-scrollbar px-1.5">
            <div
              v-for="(item, idx) in listValue(listEditor.field)"
              :key="idx"
              class="group flex items-center gap-1 py-0.5 rounded-md"
              :class="listDropIdx === idx && listDragIdx !== null && listDragIdx !== idx ? 'ring-1 ring-accent/50' : ''"
              draggable="true"
              @dragstart="onListDragStart(idx, $event)"
              @dragover.prevent="listDropIdx = idx"
              @dragend="onListDragEnd"
              @drop.prevent="onListDrop(idx)"
            >
              <span class="w-4 flex-shrink-0 text-content-muted/60 cursor-grab text-center select-none" title="Drag to reorder">⠿</span>
              <input
                :value="String(item ?? '')"
                type="text"
                class="flex-1 min-w-0 bg-transparent border-b border-transparent rounded-none px-1 py-1 text-xs text-content focus:outline-none focus:border-accent"
                :placeholder="listEditorField?.itemLabel"
                @input="listEditorField && setListItem(listEditorField, idx, ($event.target as HTMLInputElement).value)"
              />
              <button
                type="button"
                class="w-5 h-5 flex-shrink-0 rounded-md flex items-center justify-center text-content-tertiary hover:text-red-400 hover:bg-overlay-subtle opacity-0 group-hover:opacity-100 transition-opacity"
                title="Remove"
                @click="removeListItem(listEditor.field, idx)"
              >
                <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </div>
          <div class="px-3 py-2 border-t border-edge-subtle">
            <input
              ref="listEntryInput"
              v-model="listEntryText"
              type="text"
              class="w-full bg-transparent text-xs text-content py-0.5 focus:outline-none placeholder:text-content-muted"
              placeholder="Type and press Enter…"
              @keydown.enter.prevent="commitListEntry"
              @keydown.delete="onListEntryBackspace"
              @paste="onListEntryPaste"
            />
          </div>
        </div>
      </template>
    </Teleport>

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
import SettingsDropdown from '../ui/SettingsDropdown.vue'
import ScrubValue from '../ui/ScrubValue.vue'
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

// ----- List popup editor (chips panel opens this) -----

const listEditor = ref<{ field: string } | null>(null)
const listEditorStyle = ref<Record<string, string>>({})
const listEntryText = ref('')
const listEntryInput = ref<HTMLInputElement | null>(null)
const listDragIdx = ref<number | null>(null)
const listDropIdx = ref<number | null>(null)

const listEditorField = computed<Field | null>(() =>
  listEditor.value ? fields.value.find(f => f.name === listEditor.value!.field) || null : null)

function openListEditor(field: Field, event: MouseEvent) {
  const anchor = (event.currentTarget as HTMLElement).closest('.flex-wrap') || (event.currentTarget as HTMLElement)
  const r = anchor.getBoundingClientRect()
  const W = 320
  const left = Math.max(8, Math.min(window.innerWidth - W - 8, r.left))
  // Below the panel by default; flip above when the lower half is tight.
  const top = r.bottom + 320 > window.innerHeight && r.top > window.innerHeight / 2
    ? Math.max(8, r.top - 328)
    : Math.min(window.innerHeight - 328, r.bottom + 6)
  listEditorStyle.value = { left: `${left}px`, top: `${Math.max(8, top)}px` }
  listEditor.value = { field: field.name }
  listEntryText.value = ''
  nextTick(() => listEntryInput.value?.focus())
}

function closeListEditor() {
  commitListEntry()
  listEditor.value = null
  listDragIdx.value = null
  listDropIdx.value = null
}

function commitListEntry() {
  const f = listEditorField.value
  const text = listEntryText.value.trim()
  if (!f || !text) return
  values[f.name] = [...listValue(f.name), coerceListItem(f, text)]
  listEntryText.value = ''
}

// Backspace in an empty entry field removes the last item (wildcards behavior).
function onListEntryBackspace(event: KeyboardEvent) {
  const f = listEditorField.value
  if (!f || listEntryText.value !== '') return
  const arr = listValue(f.name)
  if (!arr.length) return
  event.preventDefault()
  removeListItem(f.name, arr.length - 1)
}

// Pasting multiple lines / comma-separated text imports them as items.
function onListEntryPaste(event: ClipboardEvent) {
  const f = listEditorField.value
  if (!f) return
  const parsed = parsePastedItems(event.clipboardData?.getData('text') || '')
  if (parsed.length <= 1) return
  event.preventDefault()
  values[f.name] = [...listValue(f.name), ...parsed.map(item => coerceListItem(f, item))]
}

function onListDragStart(idx: number, event: DragEvent) {
  listDragIdx.value = idx
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}

function onListDragEnd() {
  listDragIdx.value = null
  listDropIdx.value = null
}

function onListDrop(idx: number) {
  const f = listEditorField.value
  if (!f || listDragIdx.value === null || listDragIdx.value === idx) { onListDragEnd(); return }
  const arr = [...listValue(f.name)]
  const [item] = arr.splice(listDragIdx.value, 1)
  arr.splice(idx, 0, item)
  values[f.name] = arr
  onListDragEnd()
}

// SettingsDropdown round-trips strings; map back to the original option so
// numeric enums keep their type.
function coerceEnumValue(field: Field, raw: string): any {
  const match = (field.options || []).find(opt => String(opt) === raw)
  return match !== undefined ? match : raw
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
  if (dragHover[f.name]) return 'ring-1 ring-accent/50 bg-accent/10'
  if (acceptsDraggedType(f)) return 'ring-1 ring-accent/30'
  return ''
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
    : 'focus:border-accent'
}

function formatOption(field: Field, opt: any): string {
  return field.optionLabels?.[String(opt)] || String(opt)
}
</script>
