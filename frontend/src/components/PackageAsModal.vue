<template>
  <Modal :show="show" size="lg" @close="$emit('close')">
    <template #header>
      <div class="flex items-center justify-between">
        <h3 class="text-lg font-semibold text-content">Package as…</h3>
        <IconButton @click="$emit('close')">
          <XMarkIcon class="h-5 w-5" />
        </IconButton>
      </div>
    </template>

    <div class="max-h-[60vh] space-y-5 overflow-y-auto px-6 py-5 custom-scrollbar">
      <div v-if="loadingRecipes" class="flex items-center gap-2 text-xs text-content-tertiary">
        <Spinner size="sm" />
        <span>Loading recipes…</span>
      </div>

      <template v-else>
        <!-- Recipe -->
        <div class="space-y-2">
          <label class="block text-xs font-semibold text-content-secondary" for="package-recipe">Recipe</label>
          <select id="package-recipe" v-model="recipeId" :class="FIELD_CLASS">
            <option value="">No recipe — just bundle these files</option>
            <option v-for="recipe in recipes" :key="recipe.id" :value="recipe.id">{{ recipe.display_name }}</option>
          </select>
          <p v-if="selectedRecipe?.description" class="text-xs text-content-tertiary">{{ selectedRecipe.description }}</p>
        </div>

        <!-- Roles -->
        <div v-if="inputs.length" class="space-y-2">
          <p class="text-xs font-semibold text-content-secondary">Inputs</p>
          <div v-for="input in inputs" :key="input.name" class="space-y-1">
            <label class="flex items-baseline gap-1.5 text-xs text-content" :for="`package-role-${input.name}`">
              <span class="font-mono">{{ input.name }}</span>
              <span v-if="!input.required" class="text-[11px] text-content-tertiary">optional</span>
            </label>
            <select :id="`package-role-${input.name}`" v-model="roles[input.name]" :class="FIELD_CLASS">
              <option :value="null">— none —</option>
              <option v-for="item in items" :key="item.mediaId" :value="item.mediaId">{{ item.label }}</option>
            </select>
            <p v-if="input.description" class="text-xs text-content-tertiary">{{ input.description }}</p>
          </div>
        </div>

        <!-- Params -->
        <div v-if="visibleParams.length" class="space-y-3">
          <p class="text-xs font-semibold text-content-secondary">Options</p>

          <div v-for="param in visibleParams" :key="param.name" class="space-y-1">
            <!-- Boolean reads as the label's own control, so no separate label row. -->
            <label v-if="param.type === 'boolean'" class="flex cursor-pointer items-center gap-2">
              <input v-model="params[param.name]" type="checkbox" class="h-3.5 w-3.5 rounded accent-accent">
              <span class="text-xs text-content">{{ labelFor(param) }}</span>
            </label>

            <template v-else>
              <label class="block text-xs text-content" :for="`package-param-${param.name}`">{{ labelFor(param) }}</label>

              <input
                v-if="param.type === 'string'"
                :id="`package-param-${param.name}`"
                v-model="params[param.name]"
                type="text"
                :class="FIELD_CLASS"
              >

              <input
                v-else-if="param.type === 'integer' || param.type === 'number'"
                :id="`package-param-${param.name}`"
                v-model.number="params[param.name]"
                type="number"
                :min="param.minimum ?? undefined"
                :max="param.maximum ?? undefined"
                :step="param.type === 'integer' ? 1 : 'any'"
                :class="[FIELD_CLASS, 'font-mono tabular-nums']"
              >

              <div v-else-if="param.type === 'color'" class="flex items-center gap-2">
                <input
                  :id="`package-param-${param.name}`"
                  v-model="params[param.name]"
                  type="color"
                  class="h-9 w-10 cursor-pointer rounded-md border border-edge-subtle bg-transparent"
                >
                <input
                  v-model="params[param.name]"
                  type="text"
                  spellcheck="false"
                  :class="[FIELD_CLASS, 'font-mono uppercase']"
                >
              </div>

              <select
                v-else-if="param.type === 'choice'"
                :id="`package-param-${param.name}`"
                v-model="params[param.name]"
                :class="FIELD_CLASS"
              >
                <option v-for="option in param.options || []" :key="option" :value="option">{{ option }}</option>
              </select>

              <div v-else-if="param.type === 'multi'" class="flex flex-wrap gap-x-4 gap-y-1.5">
                <label v-for="option in param.options || []" :key="option" class="flex cursor-pointer items-center gap-1.5">
                  <input
                    type="checkbox"
                    class="h-3.5 w-3.5 rounded accent-accent"
                    :checked="(params[param.name] || []).includes(option)"
                    @change="toggleMulti(param.name, option)"
                  >
                  <span class="text-xs text-content-secondary">{{ option }}</span>
                </label>
              </div>

              <template v-else-if="param.type === 'naming'">
                <div class="flex items-center gap-2">
                  <input
                    :id="`package-param-${param.name}`"
                    v-model="params[param.name].template"
                    type="text"
                    spellcheck="false"
                    :class="[FIELD_CLASS, 'font-mono']"
                  >
                  <select v-model="params[param.name].case" :class="[FIELD_CLASS, 'w-auto flex-none']">
                    <option v-for="option in NAMING_CASES" :key="option" :value="option">{{ option }}</option>
                  </select>
                </div>
                <p class="text-xs text-content-tertiary">
                  Fields: <span class="font-mono">{{ fieldTokens(param) }}</span>
                </p>
              </template>
            </template>

            <p v-if="param.description && param.type !== 'boolean'" class="text-xs text-content-tertiary">{{ param.description }}</p>
          </div>
        </div>

        <!-- Title -->
        <div class="space-y-2">
          <label class="block text-xs font-semibold text-content-secondary" for="package-title">Title</label>
          <input id="package-title" v-model="title" type="text" placeholder="Package" :class="FIELD_CLASS">
        </div>

        <p class="text-xs text-content-tertiary">
          {{ mediaIds.length }} {{ mediaIds.length === 1 ? 'item' : 'items' }} will be bundled.
        </p>
      </template>

      <p v-if="errorText" role="alert" class="text-sm text-red-500">{{ errorText }}</p>
    </div>

    <template #footer>
      <Button variant="secondary" @click="$emit('close')">Cancel</Button>
      <Button variant="primary" :loading="creating" :disabled="!canCreate" @click="create">
        {{ creating ? 'Creating…' : 'Create' }}
      </Button>
    </template>
  </Modal>
</template>

<script setup>
// "Package as…": pick a recipe (or none), hand its input roles the selected
// items, fill in its parameters, and post one package. No agent involved.
import { computed, ref, watch } from 'vue'
import axios from 'axios'
import { XMarkIcon } from '@heroicons/vue/24/outline'
import Modal from './ui/Modal.vue'
import Button from './ui/Button.vue'
import IconButton from './ui/IconButton.vue'
import Spinner from './ui/Spinner.vue'
import { getApiBase } from '../apiConfig'
import { addToast } from '../composables/useToasts'
import { mediaIdOf } from '../utils/assetIdentity'

const props = defineProps({
  show: { type: Boolean, default: false },
  mediaIds: { type: Array, default: () => [] },
  mediaItems: { type: Array, default: () => [] },
  projectId: { type: Number, default: null },
})

const emit = defineEmits(['close', 'created'])

// Fill-only field recipe (DESIGN §3 "Text input"): never border + fill.
const FIELD_CLASS = 'w-full rounded-md border border-transparent bg-overlay-subtle px-3 py-2 text-sm text-content outline-none placeholder:text-content-muted focus:border-accent focus-visible:ring-2 ring-accent/40'
const NAMING_CASES = ['kebab', 'snake', 'camel', 'pascal', 'as-is']

const recipes = ref([])
const loadingRecipes = ref(false)
const recipeId = ref('')
const roles = ref({})
const params = ref({})
const title = ref('')
const creating = ref(false)
const errorText = ref('')

const selectedRecipe = computed(() => recipes.value.find(r => r.id === recipeId.value) || null)
const inputs = computed(() => selectedRecipe.value?.inputs || [])
// 'renames' is a post-build correction, not a creation-time choice.
const visibleParams = computed(() => (selectedRecipe.value?.params || []).filter(p => p.type !== 'renames'))

const items = computed(() => {
  const rows = props.mediaItems.length
    ? props.mediaItems.map(item => ({ mediaId: mediaIdOf(item), label: labelForItem(item) }))
    : props.mediaIds.map(id => ({ mediaId: id, label: `#${id}` }))
  return rows.filter(row => row.mediaId != null)
})

const canCreate = computed(() => {
  if (creating.value || loadingRecipes.value) return false
  if (!props.mediaIds.length) return false
  return inputs.value.every(input => !input.required || roles.value[input.name] != null)
})

function labelForItem(item) {
  const id = mediaIdOf(item)
  return item.asset_title || item.title || item.filename || item.original_filename || `#${id}`
}

function labelFor(param) {
  // Param names are snake_case identifiers; show them as words.
  return param.name.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase())
}

// The braces are part of the template syntax the caption is teaching, so they
// are built here rather than interpolated inside a mustache.
function fieldTokens(param) {
  return (param.fields || []).map(field => '{' + field + '}').join(' ')
}

function toggleMulti(name, option) {
  const current = params.value[name] || []
  params.value[name] = current.includes(option)
    ? current.filter(v => v !== option)
    : [...current, option]
}

function defaultParamValue(param) {
  if (param.type === 'naming') {
    return { template: typeof param.default === 'string' ? param.default : '', case: param.case || 'kebab' }
  }
  if (param.type === 'multi') return Array.isArray(param.default) ? [...param.default] : []
  if (param.type === 'boolean') return !!param.default
  if (param.type === 'choice') return param.default ?? (param.options?.[0] ?? '')
  if (param.type === 'color') return param.default || '#FFFFFF'
  return param.default ?? (param.type === 'string' ? '' : null)
}

function resetForRecipe() {
  errorText.value = ''
  const recipe = selectedRecipe.value
  title.value = recipe?.display_name || ''

  const nextRoles = {}
  const declared = recipe?.inputs || []
  const available = items.value
  declared.forEach((input, index) => {
    // One required role and one item is the common case; otherwise the
    // selection's own order is the best guess the dialog can make.
    nextRoles[input.name] = available[index]?.mediaId ?? null
  })
  roles.value = nextRoles

  const nextParams = {}
  for (const param of recipe?.params || []) {
    if (param.type === 'renames') continue
    nextParams[param.name] = defaultParamValue(param)
  }
  params.value = nextParams
}

async function loadRecipes() {
  loadingRecipes.value = true
  errorText.value = ''
  try {
    const { data } = await axios.get(`${getApiBase()}/packages/recipes`)
    recipes.value = data.recipes || []
  } catch (error) {
    errorText.value = error?.response?.data?.detail || error?.message || 'Could not load recipes.'
    recipes.value = []
  } finally {
    loadingRecipes.value = false
  }
}

watch(() => props.show, (open) => {
  if (!open) return
  recipeId.value = ''
  resetForRecipe()
  void loadRecipes()
})

watch(recipeId, resetForRecipe)

function buildParams() {
  const out = {}
  for (const param of visibleParams.value) {
    const value = params.value[param.name]
    if (value === null || value === undefined || value === '') continue
    if (param.type === 'naming') {
      if (!value.template) continue
      out[param.name] = { template: value.template, case: value.case }
    } else {
      out[param.name] = value
    }
  }
  return out
}

async function create() {
  if (!canCreate.value) return
  creating.value = true
  errorText.value = ''
  try {
    const inputsPayload = {}
    for (const input of inputs.value) {
      const mediaId = roles.value[input.name]
      if (mediaId != null) inputsPayload[input.name] = mediaId
    }

    const payload = {
      media_ids: props.mediaIds.map(id => Number(id)),
      title: title.value.trim() || undefined,
      project_id: props.projectId || undefined,
    }
    if (recipeId.value) {
      payload.recipe = recipeId.value
      payload.inputs = inputsPayload
      payload.params = buildParams()
    }

    await axios.post(`${getApiBase()}/packages`, payload)
    addToast(`Packaged as “${title.value.trim() || 'Package'}”`, 'success')
    emit('created')
    emit('close')
  } catch (error) {
    errorText.value = error?.response?.data?.detail || error?.message || 'Could not create the package.'
  } finally {
    creating.value = false
  }
}
</script>
