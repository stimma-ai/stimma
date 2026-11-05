<script setup lang="ts">
/**
 * The four LLM role selectors, shared by profile settings and project settings.
 *
 * Automatic and inheritance are never options in a menu — nobody picks them,
 * they are what happens when nothing is set. A row always shows the model
 * actually in effect, rendered like any other pick.
 *
 * Rows carry no provenance marker. They used to: "Auto" in a profile when a row
 * was unset, "Override" in a project when it was set. Correct per surface and
 * confusing across them — the same absence of a marker meant "you chose this"
 * on one screen and "you didn't" on the other. Whether a row is explicit is
 * still legible where it can be acted on: the section's "Reset to defaults"
 * appears only when something is set.
 */
import { flowsEnabled } from '../../composables/useExperimentalFlows'
import { computed, onMounted } from 'vue'
import { useAvailableModels } from '../../composables/useAvailableModels'
import { resolveModelVendorId } from '../../utils/modelVendors'
import { modelSourceLine } from '../../utils/modelFunding'
import SettingsDropdown from '../ui/SettingsDropdown.vue'

const props = defineProps<{
  /** role -> saved slug. '' / 'auto' means unset. */
  modelValue: Record<string, string | null>
  /** role -> saved effort. '' / null means unset. */
  efforts?: Record<string, string | null>
  /** Project scope, so the resolved preview reflects this project's overrides. */
  projectId?: number | null
  /** True in project settings, where an unset role inherits the profile. */
  inherits?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:role', role: string, slug: string): void
  (e: 'update:effort', role: string, effort: string): void
}>()

const { selectableModels, roleDefaults, fetchModels } = useAvailableModels()

const ROLES = [
  {
    key: 'quick_task',
    label: 'Quick Tasks',
    description: 'Captions, chat names, background work.',
  },
  {
    key: 'tool_assistant',
    label: 'Tool Assistant',
    description: 'The assistant on the tool screen.',
  },
  {
    key: 'chat',
    label: 'New Chats',
    description: 'The model that new chats use by default.',
  },
  {
    key: 'flow',
    label: 'Flows',
    // Flows run on a deterministic execution environment; an LLM is something
    // they call, not something they run on.
    description: 'The model that is used inside of flow steps.',
  },
]

function optionFor(model: any) {
  return {
    value: model.slug,
    label: model.name,
    vendor: resolveModelVendorId(model) || undefined,
    // Where the request goes: whose balance for hosted models, the host for
    // your own. Menu-only — the trigger hides details, so a long self-hosted
    // name still gets the full width.
    description: modelSourceLine(model),
    meta: model.cost_tier || '',
  }
}

const modelOptions = computed(() => selectableModels.value
  .filter(model => model.source !== 'auto' && !model.collapsed)
  .map(optionFor))

/** Whether this row is running on something the user actually chose. */
function isExplicit(role: string) {
  const slug = props.modelValue?.[role]
  return !!slug && slug !== 'auto'
}

/**
 * The outcome this row shows: model, effort, and that model's ladder.
 *
 * With nothing pinned we read the fallback block the server already sent, so
 * clearing a row — or resetting the whole section — repaints on the spot
 * instead of showing the old value until a refetch lands.
 */
function blockFor(role: string, fallbackOnly = false): Record<string, any> {
  const entry: Record<string, any> = roleDefaults.value[role] || {}
  if (isExplicit(role) && !fallbackOnly) return entry.resolved || {}
  return (props.inherits ? entry.inherited : entry.auto) || {}
}

/**
 * Models to offer, with the value this row falls back to pulled to the top and
 * tagged. Always present, so the default is a stable place in the list rather
 * than something that appears once you have diverged — and picking it is how
 * you hand the row back to automatic selection.
 */
function optionsFor(role: string) {
  // A row pinned to a route the list leads past keeps it: dropping it would
  // show "Default" while the pinned route is still what gets called.
  const pinned = selectableModels.value.find(m => m.collapsed && m.slug === props.modelValue?.[role])
  const options = pinned ? [...modelOptions.value, optionFor(pinned)] : modelOptions.value
  const option = options.find(o => o.value === blockFor(role, true).model)
  if (!option) return options
  // The real entry stays in the list below: an explicit pin on the same model
  // is a different state from tracking it, and the trigger needs a match for
  // whichever one is selected.
  return [{ ...option, value: '', tag: 'Default' }, ...options]
}

/** Levels to offer, same treatment. */
function effortOptionsFor(role: string) {
  const levels = effortLevels(role).map(l => ({ value: l, label: effortLabel(l) }))
  const fallback = blockFor(role, true).effort
  if (!fallback) return levels
  return [{ value: '', label: effortLabel(fallback), tag: 'Default' }, ...levels]
}

function selectedFor(role: string) {
  if (!isExplicit(role)) return ''
  const slug = props.modelValue?.[role]
  return selectableModels.value.some(m => m.source !== 'auto' && m.slug === slug) ? (slug as string) : ''
}

/**
 * The ladder to offer. Read from the model on screen rather than the last
 * server response, so picking a model swaps the levels in the same frame
 * instead of briefly offering the previous model's rungs.
 */
function effortLevels(role: string): string[] {
  const shown = selectableModels.value.find(m => m.slug === selectedFor(role))
  return shown?.reasoning?.levels || blockFor(role).levels || []
}

function selectedEffort(role: string) {
  const pinned = props.efforts?.[role]
  return pinned && effortLevels(role).includes(pinned) ? pinned : ''
}

function effortLabel(level: string) {
  if (level === 'off') return 'Off'
  if (level === 'xhigh') return 'XHigh'
  return level.charAt(0).toUpperCase() + level.slice(1)
}

// Explains the dot on hover, so the mark and the button that clears it read
// together without needing a legend.
const RESET_HINT = 'Set here — “Reset to defaults” clears it.'

onMounted(() => fetchModels(props.projectId ?? null, true))
</script>

<template>
  <div>
    <div
      v-for="role in ROLES.filter(r => flowsEnabled || r.key !== 'flow')"
      :key="role.key"
      class="flex items-center justify-between gap-1 border-b border-edge-subtle py-2.5 last:border-b-0"
    >
      <span class="min-w-0">
        <span class="block text-[13px] text-content">{{ role.label }}</span>
        <span class="mt-0.5 block text-[11.5px] text-content-tertiary">{{ role.description }}</span>
      </span>
      <span class="flex shrink-0 items-center gap-1.5">
        <!-- Provider and cost live in the menu, where you compare models. On the
             trigger they cost ~104px that the description needs, and by then you
             have already chosen. -->
        <SettingsDropdown
          control
          fill
          hide-trigger-details
          class="w-[302px]"
          :menu-width="340"
          :marked="isExplicit(role.key)"
          :title="isExplicit(role.key) ? RESET_HINT : ''"
          :model-value="selectedFor(role.key)"
          :options="optionsFor(role.key)"
          @update:model-value="slug => emit('update:role', role.key, slug)"
        />
        <!-- Fixed width so this reads as a column, and wide enough for "Medium". -->
        <SettingsDropdown
          v-if="effortLevels(role.key).length"
          control
          compact
          fill
          class="w-[100px]"
          :menu-width="180"
          :marked="!!efforts?.[role.key]"
          :title="efforts?.[role.key] ? RESET_HINT : ''"
          :model-value="selectedEffort(role.key)"
          :options="effortOptionsFor(role.key)"
          @update:model-value="level => emit('update:effort', role.key, level)"
        />
        <span v-else class="w-[100px] shrink-0" />
      </span>
    </div>
  </div>
</template>
