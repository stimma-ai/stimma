<template>
  <template v-for="paramGroup in groups" :key="paramGroup.group || 'ungrouped'">
    <div :class="flat ? 'mb-3 last:mb-0' : 'mb-6 last:mb-0'">
      <!-- Group header - collapsible if paramGroup.collapsible is true -->
      <div v-if="paramGroup.label" class="mb-3">
        <button
          v-if="paramGroup.collapsible && !disableCollapse"
          @click="toggleCollapsed(paramGroup.group)"
          type="button"
          class="flex items-center gap-2 text-xs font-medium text-content-muted uppercase tracking-wide hover:text-content-tertiary transition-colors"
        >
          <span :class="['transition-transform text-[10px]', isCollapsed(paramGroup.group) ? '' : 'rotate-90']">&#9654;</span>
          {{ paramGroup.label }}
        </button>
        <span v-else class="text-xs font-medium text-content-muted uppercase tracking-wide">{{ paramGroup.label }}</span>
      </div>
      <!-- Parameters list (settings-style: label+desc on left, control on right) -->
      <div v-show="disableCollapse || !paramGroup.collapsible || !isCollapsed(paramGroup.group)" :class="flat ? 'divide-y divide-white/[0.06]' : 'rounded-lg border border-edge-subtle bg-overlay-faint divide-y divide-white/[0.06]'">
        <template v-for="param in paramGroup.params" :key="param.name">
          <!-- Skip if visibleWhen condition not met -->
          <template v-if="!param.visibleWhen || values[param.visibleWhen.param] === param.visibleWhen.value">
            <!-- Seed control with randomize checkbox -->
            <div v-if="param.control === 'seed'" :class="['flex items-center justify-between gap-4', rowPad]">
              <div class="min-w-0 flex-1">
                <div class="text-sm font-medium text-content">{{ param.label }}</div>
                <div v-if="param.description" class="text-xs text-content-muted mt-0.5">{{ param.description }}</div>
              </div>
              <div class="flex items-center justify-end gap-3 flex-wrap">
                <input v-no-autocorrect
                  :value="values[param.name]"
                  @input="emitParam(param.name, parseIntOrNull(($event.target as HTMLInputElement).value))"
                  type="number"
                  :disabled="values.randomizeSeed ?? true"
                  class="w-28 sm:w-36 px-2 py-1.5 bg-base border border-edge rounded text-content text-sm disabled:opacity-40 focus:outline-none focus:border-blue-500"
                >
                <label class="flex items-center gap-1.5 text-xs text-content-tertiary cursor-pointer">
                  <input v-no-autocorrect
                    :checked="values.randomizeSeed ?? true"
                    @change="emitParam('randomizeSeed', ($event.target as HTMLInputElement).checked)"
                    type="checkbox"
                    class="w-3.5 h-3.5 rounded"
                  >
                  <span>Randomize</span>
                </label>
              </div>
            </div>
            <!-- Enum/Select -->
            <div v-else-if="param.enum" :class="['flex items-center justify-between gap-4', rowPad]">
              <div class="min-w-0 flex-1">
                <div class="text-sm font-medium text-content">{{ param.label }}</div>
                <div v-if="param.description" class="text-xs text-content-muted mt-0.5">{{ param.description }}</div>
              </div>
              <div class="min-w-0 max-w-[45%] flex-shrink-0">
                <SettingsDropdown
                  :model-value="String(values[param.name] ?? param.default)"
                  @update:model-value="emitParam(param.name, $event)"
                  :options="param.enum.map((opt: string) => ({ value: opt, label: param.enumLabels?.[opt] || formatEnumOption(opt, param.format) }))"
                />
              </div>
            </div>
            <!-- Number/Slider -->
            <div v-else-if="param.type === 'number' || param.type === 'integer'" :class="['flex items-center justify-between gap-4', rowPad]">
              <div class="min-w-0 flex-1">
                <div class="text-sm font-medium text-content">{{ param.label }}</div>
                <div v-if="param.description" class="text-xs text-content-muted mt-0.5">{{ param.description }}</div>
              </div>
              <div class="flex min-w-0 w-[45%] max-w-[360px] flex-shrink-0 items-center justify-end gap-2">
                <input v-no-autocorrect
                  type="range"
                  :value="values[param.name] ?? param.default"
                  @input="emitParam(param.name, Number(($event.target as HTMLInputElement).value))"
                  :min="param.minimum ?? 0"
                  :max="param.maximum ?? 100"
                  :step="param.step ?? (param.type === 'integer' ? 1 : 0.1)"
                  class="min-w-24 flex-1 h-1 bg-surface-raised rounded-sm appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-blue-500 [&::-webkit-slider-thumb]:rounded-full"
                />
                <input v-no-autocorrect
                  v-if="editingParam === param.name"
                  type="text"
                  :value="values[param.name] ?? param.default"
                  @blur="commitParamEdit(param, $event)"
                  @keydown.enter="commitParamEdit(param, $event)"
                  @keydown.escape="editingParam = null"
                  class="w-16 flex-shrink-0 text-sm text-content-secondary bg-base border border-edge rounded px-2 py-1 text-right focus:outline-none focus:border-blue-500"
                  ref="paramEditInput"
                />
                <span
                  v-else
                  @dblclick="startParamEdit(param.name)"
                  class="w-12 flex-shrink-0 text-sm text-content-tertiary text-right cursor-text hover:text-content-secondary select-none"
                  :title="'Double-click to edit'"
                >{{ formatGenericParamValue(param, values[param.name] ?? param.default) }}</span>
              </div>
            </div>
            <!-- Boolean/Checkbox -->
            <div v-else-if="param.type === 'boolean'" :class="['flex items-center justify-between gap-4', rowPad]">
              <div class="w-[55%] flex-shrink-0">
                <div class="text-sm font-medium text-content">{{ param.label }}</div>
                <div v-if="param.description" class="text-xs text-content-muted mt-0.5">{{ param.description }}</div>
              </div>
              <input v-no-autocorrect
                type="checkbox"
                :checked="values[param.name] ?? param.default"
                @change="emitParam(param.name, ($event.target as HTMLInputElement).checked)"
                class="flex-shrink-0 w-4 h-4 rounded border-edge bg-base text-blue-500 focus:ring-blue-500 focus:ring-offset-0 cursor-pointer"
              />
            </div>
            <!-- String input (textarea for x-control: textarea, otherwise single-line) -->
            <div v-else-if="param.type === 'string'" :class="rowPad">
              <div class="flex items-center justify-between gap-4 mb-2">
                <div class="w-[55%] flex-shrink-0">
                  <div class="text-sm font-medium text-content">{{ param.label }}</div>
                  <div v-if="param.description && param.control !== 'textarea'" class="text-xs text-content-muted mt-0.5">{{ param.description }}</div>
                </div>
              </div>
              <textarea v-no-autocorrect
                v-if="param.control === 'textarea'"
                :value="values[param.name] ?? param.default ?? ''"
                @input="emitParam(param.name, ($event.target as HTMLTextAreaElement).value)"
                rows="4"
                :placeholder="param.description || ''"
                class="w-full px-2 py-1.5 bg-base border border-edge rounded text-content text-sm resize-y focus:outline-none focus:border-blue-500 font-sans"
              ></textarea>
              <input v-no-autocorrect
                v-else
                type="text"
                :value="values[param.name] ?? param.default ?? ''"
                @input="emitParam(param.name, ($event.target as HTMLInputElement).value)"
                :placeholder="param.description"
                class="w-full px-2 py-1.5 bg-base border border-edge rounded text-content text-sm focus:outline-none focus:border-blue-500"
              />
            </div>
          </template>
        </template>
      </div>
    </div>
  </template>
</template>

<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import SettingsDropdown from '../ui/SettingsDropdown.vue'
import type { GenericParam, GenericParamGroup } from '../../composables/useToolSchemaFeatures'

// Standalone, schema-driven settings renderer. Extracted from ToolView's
// inline generic-params section so any tool's parameter schema can be hosted
// anywhere (ToolView's own controls column, post-processing chain step cards).
// Reads from `values`, never mutates — every change is emitted.
const props = defineProps<{
  groups: GenericParamGroup[]
  values: Record<string, any>
  /** Flat variant for embedding inside an already-boxed container (e.g. an
      expanded chain step card) — rows only, no border/background bubble. */
  flat?: boolean
  /** Render collapsible groups (e.g. Advanced) always open, header as a plain
      label. One chevron per surface is enough — drop this prop to restore the
      per-group disclosure behavior. */
  disableCollapse?: boolean
  /** Optional external collapse persistence (ToolView persists per tool). */
  isGroupCollapsed?: (groupLabel: string | null) => boolean
  onToggleGroupCollapsed?: (groupLabel: string | null) => void
}>()

const rowPad = computed(() => (props.flat ? 'px-1 py-2' : 'px-4 py-3'))

const emit = defineEmits<{
  (e: 'update:param', name: string, value: any): void
}>()

function emitParam(name: string, value: any) {
  emit('update:param', name, value)
}

// --- Collapse state (internal fallback when no persistence is provided) ----
const internalCollapsed = ref<Record<string, boolean>>({})

function isCollapsed(groupLabel: string | null): boolean {
  if (props.isGroupCollapsed) return props.isGroupCollapsed(groupLabel)
  if (!groupLabel) return false
  return internalCollapsed.value[groupLabel] ?? true
}

function toggleCollapsed(groupLabel: string | null) {
  if (props.onToggleGroupCollapsed) {
    props.onToggleGroupCollapsed(groupLabel)
    return
  }
  if (!groupLabel) return
  internalCollapsed.value[groupLabel] = !isCollapsed(groupLabel)
}

// --- Inline numeric editing --------------------------------------------------
const editingParam = ref<string | null>(null)
const paramEditInput = ref<HTMLInputElement[] | null>(null)

function startParamEdit(paramName: string) {
  editingParam.value = paramName
  nextTick(() => {
    const input = paramEditInput.value?.[0]
    if (input) {
      input.focus()
      input.select()
    }
  })
}

function commitParamEdit(param: GenericParam, event: Event) {
  const input = event.target as HTMLInputElement
  const rawValue = input.value.replace(/%$/, '')
  const numValue = Number(rawValue)

  if (!isNaN(numValue)) {
    const min = param.minimum ?? 0
    const max = param.maximum ?? 100
    const clamped = Math.max(min, Math.min(max, numValue))
    emitParam(param.name, param.type === 'integer' ? Math.round(clamped) : clamped)
  }

  editingParam.value = null
}

// --- Formatting ---------------------------------------------------------------
function formatEnumOption(value: string, format?: string): string {
  if (format === 'filename') {
    return value
      .replace(/^.*\//, '')
      .replace(/\.(safetensors|ckpt|pt|bin)$/i, '')
  }
  return humanizeEnumOption(value)
}

// Turn raw enum tokens (nearest_neighbor, high-quality, lanczos) into nicely
// title-cased labels. Tokens that carry their own casing or digits (acronyms
// like RGB, sizes like 1024x1024, ratios like 16:9) are left untouched.
function humanizeEnumOption(value: string): string {
  if (!/[a-z]/.test(value)) return value
  return value
    .split(/[_\-\s]+/)
    .filter(Boolean)
    .map(w => (/[A-Z]/.test(w) || /\d/.test(w) ? w : w.charAt(0).toUpperCase() + w.slice(1)))
    .join(' ')
}

function formatGenericParamValue(param: GenericParam, value: any): string {
  if (value === undefined || value === null) return ''
  const step = param.step ?? (param.type === 'integer' ? 1 : 0.1)
  let formatted: string
  if (step < 1) {
    const decimals = step.toString().split('.')[1]?.length || 1
    formatted = Number(value).toFixed(decimals)
  } else {
    formatted = String(value)
  }
  if (param.format === 'percent') {
    formatted += '%'
  } else if ((param as any).unit === 'frames') {
    const fps = props.values.fps || 16
    const seconds = (Number(value) / fps).toFixed(1)
    formatted += ` (~${seconds}s)`
  }
  return formatted
}

function parseIntOrNull(value: string): number | null {
  const parsed = parseInt(value, 10)
  return isNaN(parsed) ? null : parsed
}
</script>
