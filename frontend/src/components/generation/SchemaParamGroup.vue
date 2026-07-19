<template>
  <template v-for="paramGroup in groups" :key="paramGroup.group || 'ungrouped'">
    <!-- Skip the whole section if hidden_when is active -->
    <template v-if="!isSectionHidden(paramGroup.hiddenWhen, values)">
    <div :class="flat ? 'mb-3 last:mb-0' : 'mb-6 last:mb-0'">
      <!-- Group header - collapsible if paramGroup.collapsible is true.
           pt-2 keeps it off the preceding row's hairline when this group sits
           inside a divide-y host (e.g. chain step settings). -->
      <div v-if="paramGroup.label" class="pt-2 mb-1">
        <button
          v-if="paramGroup.collapsible && !disableCollapse"
          @click="toggleCollapsed(paramGroup.group)"
          type="button"
          class="flex items-center gap-2 text-xs font-semibold text-content-secondary hover:text-content transition-colors duration-150 focus:outline-none focus-visible:ring-2 ring-accent/60 rounded"
        >
          <span :class="['transition-transform duration-150 text-[10px]', isCollapsed(paramGroup.group) ? '' : 'rotate-90']">&#9654;</span>
          {{ displayGroupLabel(paramGroup.label) }}
        </button>
        <span v-else class="text-xs font-semibold text-content-secondary">{{ displayGroupLabel(paramGroup.label) }}</span>
      </div>
      <!-- Parameters list (settings-style: label+desc on left, control on right) -->
      <!-- Atelier: ONE hairline under the group label; rows separate by
           whitespace (per-row rules read as a wall of <hr>s on two-line rows). -->
      <div v-show="disableCollapse || !paramGroup.collapsible || !isCollapsed(paramGroup.group)" class="divide-y divide-edge-subtle">
        <template v-for="param in paramGroup.params" :key="param.name">
          <!-- Skip if visibleWhen condition not met, or a hide constraint is active -->
          <template v-if="(!param.visibleWhen || values[param.visibleWhen.param] === param.visibleWhen.value) && !constraintState(param).hidden">
            <!-- Seed control with randomize checkbox -->
            <div v-if="param.control === 'seed'" :class="['flex items-center justify-between gap-4', rowPad]">
              <div class="min-w-0 flex-1">
                <div class="text-[13px] text-content-secondary" :title="constraintState(param).disabled ? undefined : param.description">{{ param.label }}</div>
                <div v-if="constraintState(param).disabled && constraintState(param).reason" class="text-xs mt-0.5 text-amber-500/80">{{ constraintState(param).reason }}</div>
              </div>
              <div class="flex items-center justify-end gap-3">
                <label class="flex items-center gap-1.5 text-xs text-content-tertiary cursor-pointer">
                  <input v-no-autocorrect
                    :checked="values.randomizeSeed ?? true"
                    @change="emitParam('randomizeSeed', ($event.target as HTMLInputElement).checked)"
                    type="checkbox"
                    :disabled="constraintState(param).disabled"
                    class="w-3.5 h-3.5 rounded accent-[rgb(var(--color-accent-rgb))]"
                  >
                  <span>Randomize</span>
                </label>
                <!-- Editable even while Randomize is on — typing a seed means
                     you want that seed, so the first edit unchecks Randomize. -->
                <input v-no-autocorrect
                  :value="values[param.name]"
                  @input="onSeedInput(param.name, ($event.target as HTMLInputElement).value)"
                  type="number"
                  :disabled="constraintState(param).disabled"
                  :class="['w-24 text-right bg-transparent border-b border-transparent font-mono tabular-nums text-xs disabled:opacity-40 focus:border-accent outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none',
                           (values.randomizeSeed ?? true) ? 'text-content-muted focus:text-content-secondary' : 'text-content-secondary']"
                >
                              </div>
            </div>
            <!-- Enum/Select -->
            <div v-else-if="param.enum" :class="['flex items-center justify-between gap-4', rowPad]">
              <div class="min-w-0 flex-1">
                <div class="text-[13px] text-content-secondary" :title="constraintState(param).disabled ? undefined : param.description">{{ param.label }}</div>
                <div v-if="constraintState(param).disabled && constraintState(param).reason" class="text-xs mt-0.5 text-amber-500/80">{{ constraintState(param).reason }}</div>
              </div>
              <!-- Content-sized, capped at 75%: a long selected value (e.g. a
                   TTS model blurb) shifts left into the label's free space
                   instead of overflowing the card; the label keeps ≥25%. -->
              <div class="min-w-0 max-w-[75%]">
                <SettingsDropdown
                  :model-value="String(values[param.name] ?? param.default)"
                  @update:model-value="emitParam(param.name, $event)"
                  :options="param.enum.map((opt: string) => ({ value: opt, label: param.enumLabels?.[opt] || formatEnumOption(opt, param.format) }))"
                  :search-options="remoteSearchFor(param)"
                  :disabled="constraintState(param).disabled"
                  quiet
                />
              </div>
            </div>
            <!-- Number: compact value row — drag the mono value to scrub,
                 click to type (the mock's ValueRow grammar; no slider). -->
            <div v-else-if="param.type === 'number' || param.type === 'integer'" class="py-1.5">
              <div class="flex items-center justify-between gap-4">
                <div class="text-[13px] text-content-secondary" :title="constraintState(param).disabled ? undefined : param.description">{{ param.label }}</div>
                <ScrubValue
                  :model-value="Number(values[param.name] ?? param.default ?? 0)"
                  @update:model-value="emitParam(param.name, $event)"
                  :min="param.minimum ?? 0"
                  :max="param.maximum ?? 100"
                  :step="param.step ?? (param.type === 'integer' ? 1 : 0.1)"
                  :disabled="constraintState(param).disabled"
                  :non-default="(values[param.name] ?? param.default) !== param.default"
                  :format="(v: number) => formatGenericParamValue(param, v)"
                />
              </div>
              <div v-if="constraintState(param).disabled && constraintState(param).reason" class="text-xs mt-0.5 text-amber-500/80">{{ constraintState(param).reason }}</div>
            </div>
            <!-- Boolean/Checkbox -->
            <div v-else-if="param.type === 'boolean'" :class="['flex items-center justify-between gap-4', rowPad]">
              <div class="min-w-0 flex-1">
                <div class="text-[13px] text-content-secondary" :title="constraintState(param).disabled ? undefined : param.description">{{ param.label }}</div>
                <div v-if="constraintState(param).disabled && constraintState(param).reason" class="text-xs mt-0.5 text-amber-500/80">{{ constraintState(param).reason }}</div>
              </div>
              <input v-no-autocorrect
                type="checkbox"
                :checked="values[param.name] ?? param.default"
                @change="emitParam(param.name, ($event.target as HTMLInputElement).checked)"
                :disabled="constraintState(param).disabled"
                class="flex-shrink-0 w-4 h-4 rounded accent-[rgb(var(--color-accent-rgb))] cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
              />
            </div>
            <!-- String input (textarea for x-control: textarea, otherwise single-line) -->
            <div v-else-if="param.type === 'string'" :class="rowPad">
              <div class="flex items-center justify-between gap-4 mb-2">
                <div class="w-[55%] flex-shrink-0">
                  <div class="text-[13px] text-content-secondary">{{ param.label }}</div>
                  <div v-if="param.control !== 'textarea' && paramDescription(param, constraintState(param))" class="text-xs mt-0.5" :class="constraintState(param).disabled ? 'text-amber-500/80' : 'text-content-muted'">{{ paramDescription(param, constraintState(param)) }}</div>
                </div>
              </div>
              <textarea v-no-autocorrect
                v-if="param.control === 'textarea'"
                :value="values[param.name] ?? param.default ?? ''"
                @input="emitParam(param.name, ($event.target as HTMLTextAreaElement).value)"
                rows="4"
                :placeholder="paramDescription(param, constraintState(param)) || ''"
                :disabled="constraintState(param).disabled"
                class="w-full px-3 py-2 bg-overlay-subtle border border-transparent rounded-md text-content text-sm resize-y placeholder:text-content-muted focus:border-accent focus-visible:ring-2 ring-accent/40 outline-none font-sans disabled:opacity-40 disabled:cursor-not-allowed"
              ></textarea>
              <input v-no-autocorrect
                v-else
                type="text"
                :value="values[param.name] ?? param.default ?? ''"
                @input="emitParam(param.name, ($event.target as HTMLInputElement).value)"
                :placeholder="paramDescription(param, constraintState(param))"
                :disabled="constraintState(param).disabled"
                class="w-full px-3 py-2 bg-overlay-subtle border border-transparent rounded-md text-content text-sm placeholder:text-content-muted focus:border-accent focus-visible:ring-2 ring-accent/40 outline-none disabled:opacity-40 disabled:cursor-not-allowed"
              />
            </div>
          </template>
        </template>
      </div>
    </div>
    </template>
  </template>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import SettingsDropdown from '../ui/SettingsDropdown.vue'
import ScrubValue from '../ui/ScrubValue.vue'
import type { GenericParam, GenericParamGroup } from '../../composables/useToolSchemaFeatures'
import { resolveParamConstraints, isSectionHidden, type ParamConstraintState } from '../../utils/paramConstraints'
import { useProvidersApi, type ProviderParameterOption } from '../../composables/useProvidersApi'

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
  /** Full provider-scoped tool id used for x-search-options lookups. */
  fullToolId?: string
}>()

const { searchToolOptions } = useProvidersApi()

const rowPad = computed(() => (props.flat ? 'px-0 py-1.5' : 'px-0 py-1.5'))

const emit = defineEmits<{
  (e: 'update:param', name: string, value: any): void
}>()

function emitParam(name: string, value: any) {
  emit('update:param', name, value)
}

function remoteSearchFor(param: GenericParam) {
  if (!param.searchOptions || !props.fullToolId) return undefined
  return async (query: string) => {
    const options = await searchToolOptions(props.fullToolId!, param.name, query)
    return options.map((option: ProviderParameterOption) => ({
      value: option.value,
      label: option.label,
      description: option.description,
      meta: option.meta,
      previewUrl: option.preview_url,
    }))
  }
}

// Schema authors sometimes ship ALL-CAPS group labels; the UI voice is
// sentence case, so de-shout purely for display.
function displayGroupLabel(l: string): string {
  if (!l || l !== l.toUpperCase() || !/[A-Z]/.test(l)) return l
  return l.charAt(0) + l.slice(1).toLowerCase()
}

// x-constraints — evaluated against props.values, which callers may enrich
// beyond the raw submitted params (e.g. ToolView merges in live frame-picker
// state so a constraint can reference input_images even though that param
// isn't rendered by this component).
function constraintState(param: GenericParam): ParamConstraintState {
  return resolveParamConstraints(param.constraints, props.values)
}

// While disabled by a constraint, prefer explaining why over the normal
// description — so a greyed-out control reads as explained, not just inert.
function paramDescription(param: GenericParam, state: ParamConstraintState): string | undefined {
  return (state.disabled && state.reason) || param.description
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

// Typing into the seed field claims the seed: commit the value and drop
// Randomize so the typed seed actually takes effect on the next run.
function onSeedInput(paramName: string, raw: string) {
  emitParam(paramName, parseIntOrNull(raw))
  if (props.values.randomizeSeed ?? true) emitParam('randomizeSeed', false)
}

function parseIntOrNull(value: string): number | null {
  const parsed = parseInt(value, 10)
  return isNaN(parsed) ? null : parsed
}
</script>
