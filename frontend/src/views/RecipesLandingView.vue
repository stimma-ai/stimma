<template>
  <div class="h-full flex flex-col bg-base">
    <!-- Header -->
    <div class="flex items-center justify-between px-6 py-5 border-b border-edge-subtle">
      <span class="text-xl font-semibold leading-none text-content">Recipes</span>

      <div class="flex items-center gap-3">
        <button
          class="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-content-tertiary transition-colors hover:bg-overlay-subtle hover:text-content-secondary"
          @click="createRecipe"
        >
          <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          <span>New</span>
        </button>
        <div class="relative">
          <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-content-muted" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
          </svg>
          <input v-no-autocorrect
            v-model="searchQuery"
            type="text"
            placeholder="Search recipes..."
            class="bg-overlay-subtle border border-edge-subtle rounded-lg pl-9 pr-3 py-1.5 text-sm text-content-secondary placeholder-white/30 focus:outline-none focus:border-blue-500/50 w-48"
          />
        </div>
      </div>
    </div>

    <!-- Content -->
    <div class="flex-1 overflow-y-auto">
      <ConnectionError v-if="loadError" @retry="load" />

      <div v-else-if="loading" class="flex items-center justify-center h-32 text-content-muted">
        Loading recipes…
      </div>

      <template v-else>
        <!-- Toolbar: count · sort -->
        <div class="flex items-center gap-3 px-6 py-3 border-b border-edge-subtle text-[12px]">
          <span class="text-content-muted">
            {{ displayed.length }} of {{ recipes.length }} {{ recipes.length === 1 ? 'recipe' : 'recipes' }}
          </span>
          <div class="flex-1" />
          <div class="flex items-center gap-1.5 text-content-muted">
            <span>Sort</span>
            <select
              v-model="sortKey"
              class="bg-overlay-subtle border border-edge-subtle rounded px-2 py-1 text-content-secondary focus:outline-none focus:border-blue-500/50"
            >
              <option value="updated">Recently updated</option>
              <option value="name">Name</option>
              <option value="status">Status</option>
            </select>
          </div>
        </div>

        <!-- Unified list -->
        <div v-if="displayed.length === 0" class="px-6 py-16 text-center">
          <template v-if="recipes.length === 0">
            <div class="mx-auto max-w-md space-y-2">
              <p class="text-content-secondary text-sm">No recipes yet.</p>
              <p class="text-content-muted text-xs leading-relaxed">
                Recipes are repeatable creative workflows — define inputs once, then run them again with different settings to generate new assets.
              </p>
              <button
                class="mt-4 inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm text-content-secondary bg-overlay-subtle border border-edge-subtle transition-colors hover:bg-overlay hover:text-content"
                @click="createRecipe"
              >
                <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
                </svg>
                <span>New recipe</span>
              </button>
            </div>
          </template>
          <template v-else>
            <p class="text-content-muted text-sm">No recipes match your search.</p>
          </template>
        </div>
        <div v-else class="py-2">
          <RecipeCard
            v-for="r in displayed"
            :key="r.id"
            :recipe="r"
            :parent-name="parentName(r)"
            :start-editing="renamingId === r.id"
            @open="openRecipe"
            @contextmenu="handleCardContextMenu"
            @rename="handleInlineRename"
            @rename-cancelled="renamingId = null"
          />
        </div>
      </template>
    </div>

    <EntityContextMenu
      @open="handleContextMenuOpen"
      @delete="handleContextMenuDelete"
      @rename="handleContextMenuRename"
      @move-to-project="handleContextMenuMoveToProject"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import RecipeCard from '../components/recipe/RecipeCard.vue'
import ConnectionError from '../components/ConnectionError.vue'
import EntityContextMenu from '../components/EntityContextMenu.vue'
import { useRecipesApi, type Recipe } from '../composables/useRecipesApi'
import { useRecipeCounts } from '../composables/useRecipeCounts'
import { deriveRecipeStatusLabel, type RecipeStatusLabel } from '../composables/useRecipeStatus'
import { useWebSocket } from '../composables/useWebSocket'
import { useEntityContextMenu } from '../composables/useEntityContextMenu'
import { useToasts } from '../composables/useToasts'

type SortKey = 'updated' | 'name' | 'status'

const router = useRouter()
const api = useRecipesApi()
const { stateFor: recipeState, summaryFor: recipeSummary, hasLoadErrorFor: recipeHasLoadError } = useRecipeCounts()
const { on } = useWebSocket()
const entityContextMenu = useEntityContextMenu()
const { addToast } = useToasts()

const props = defineProps<{ projectId?: number | null }>()

const recipes = ref<Recipe[]>([])
const loading = ref(false)
const loadError = ref<string | null>(null)
const searchQuery = ref('')
const renamingId = ref<number | null>(null)
const sortKey = ref<SortKey>('updated')
const unsubs: Array<() => void> = []

async function load() {
  loading.value = true
  loadError.value = null
  try {
    const params = props.projectId ? { project_id: props.projectId } : {}
    recipes.value = await api.listRecipes(params)
  } catch (err: any) {
    loadError.value = err?.message || 'Failed to load recipes'
  } finally {
    loading.value = false
  }
}

function statusLabelFor(r: Recipe): RecipeStatusLabel {
  return deriveRecipeStatusLabel(recipeState(r.id), recipeSummary(r.id), recipeHasLoadError(r.id))
}

// Sort priority mirrors the RecipeStatusPill workflow order so a "Status"
// sort surfaces what needs attention first: your turn > error > running >
// paused > idle > done. Lower = earlier in the list.
const STATUS_ORDER: Record<RecipeStatusLabel, number> = {
  'Your Turn': 0,
  'Error':     1,
  'Running':   2,
  'Paused':    3,
  'Idle':      4,
  'Done':      5,
}

const displayed = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  let list = recipes.value.filter(r => {
    if (q) {
      const hay = ((r.name || '') + ' ' + (r.description || '')).toLowerCase()
      if (!hay.includes(q)) return false
    }
    return true
  })
  list = [...list]
  switch (sortKey.value) {
    case 'name':
      list.sort((a, b) => (a.name || '').localeCompare(b.name || '') || a.id - b.id)
      break
    case 'status':
      list.sort((a, b) => {
        const sa = STATUS_ORDER[statusLabelFor(a)]
        const sb = STATUS_ORDER[statusLabelFor(b)]
        if (sa !== sb) return sa - sb
        return (b.updated_at || '').localeCompare(a.updated_at || '')
      })
      break
    case 'updated':
    default:
      list.sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''))
      break
  }
  return list
})

function parentName(r: Recipe): string | null {
  if (!r.parent_id) return null
  const parent = recipes.value.find(x => x.id === r.parent_id)
  return parent?.name || `Recipe #${r.parent_id}`
}

function openRecipe(r: Recipe) {
  router.push({ name: 'recipe', params: { id: String(r.id) } })
}

function handleCardContextMenu(event: MouseEvent, recipe: Recipe) {
  entityContextMenu.show({
    event,
    entityType: 'recipe',
    entityId: recipe.id,
    entityName: recipe.name || 'Untitled',
    projectId: recipe.project_id ?? null,
    isSelected: false,
    selectedCount: 0,
  })
}

function handleContextMenuOpen(_entityType: string, entityId: number) {
  const r = recipes.value.find(x => x.id === entityId)
  if (r) openRecipe(r)
}

function handleContextMenuDelete(_entityType: string, entityId: number) {
  performDelete(entityId)
}

function handleContextMenuRename(_entityType: string, entityId: number) {
  renamingId.value = entityId
}

async function handleContextMenuMoveToProject(_entityType: string, entityId: number, projectId: number | null) {
  try {
    const updated = await api.updateRecipe(entityId, { project_id: projectId })
    const idx = recipes.value.findIndex(r => r.id === entityId)
    if (idx >= 0) recipes.value[idx] = updated
    // If list is scoped to a project and recipe moved out, drop it.
    if (props.projectId && updated.project_id !== props.projectId) {
      recipes.value = recipes.value.filter(r => r.id !== entityId)
    }
  } catch (err) {
    console.error('Failed to move recipe to project:', err)
  }
}

async function handleInlineRename(recipe: Recipe, newName: string) {
  renamingId.value = null
  try {
    const updated = await api.updateRecipe(recipe.id, { name: newName })
    const idx = recipes.value.findIndex(r => r.id === recipe.id)
    if (idx >= 0) recipes.value[idx] = updated
  } catch (err) {
    console.error('Failed to rename recipe:', err)
  }
}

async function performDelete(id: number) {
  const removed = recipes.value.find(r => r.id === id)
  if (!removed) return
  recipes.value = recipes.value.filter(r => r.id !== id)

  try {
    await api.deleteRecipe(id)
  } catch (err) {
    console.error('Failed to delete recipe:', err)
    recipes.value = [removed, ...recipes.value]
    addToast('Failed to delete recipe', 'error', 5000)
    return
  }

  addToast('Deleted 1 recipe', 'info', 5000, {
    label: 'Undo',
    onClick: async () => {
      if (!recipes.value.find(r => r.id === id)) {
        recipes.value = [removed, ...recipes.value]
      }
      try {
        await api.restoreRecipe(id)
      } catch (err) {
        console.error('Failed to restore recipe:', err)
        recipes.value = recipes.value.filter(r => r.id !== id)
        addToast('Failed to restore recipe', 'error', 5000)
      }
    }
  })
}

function matchesScope(recipe: any): boolean {
  if (!props.projectId) return true
  return recipe?.project_id === props.projectId
}

async function createRecipe() {
  try {
    const body: any = {}
    if (props.projectId) body.project_id = props.projectId
    const r = await api.createRecipe(body)
    router.push({ name: 'recipe', params: { id: String(r.id) } })
  } catch (err) {
    console.error('Failed to create recipe:', err)
  }
}

onMounted(() => {
  load()
  unsubs.push(on('recipe_created', (data: any) => {
    const r = data?.recipe
    if (!r || !matchesScope(r)) return
    if (!recipes.value.find(x => x.id === r.id)) recipes.value = [r, ...recipes.value]
  }))
  unsubs.push(on('recipe_updated', (data: any) => {
    const r = data?.recipe
    if (!r) return
    const idx = recipes.value.findIndex(x => x.id === r.id)
    if (!matchesScope(r)) {
      if (idx >= 0) recipes.value.splice(idx, 1)
      return
    }
    if (idx >= 0) recipes.value[idx] = r
    else recipes.value = [r, ...recipes.value]
  }))
  unsubs.push(on('recipe_deleted', (data: any) => {
    const rid = data?.recipe_id
    if (rid != null) recipes.value = recipes.value.filter(r => r.id !== rid)
  }))
  unsubs.push(on('recipe_restored', (data: any) => {
    const r = data?.recipe
    if (!r || !matchesScope(r)) return
    if (!recipes.value.find(x => x.id === r.id)) recipes.value = [r, ...recipes.value]
  }))
  unsubs.push(on('websocket_reconnected', () => load()))
})

onUnmounted(() => {
  for (const u of unsubs) { try { u() } catch {} }
  unsubs.length = 0
})
</script>
