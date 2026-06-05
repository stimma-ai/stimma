<template>
  <div
    class="flex items-center gap-4 px-6 py-3.5 mx-2 rounded-lg transition-colors cursor-pointer hover:bg-overlay-subtle"
    @click="handleClick"
    @contextmenu="$emit('contextmenu', $event, recipe)"
  >
    <!-- Thumbnail / status -->
    <div
      v-if="heroMediaId != null"
      class="flex-shrink-0 w-10 h-10 rounded-xl overflow-hidden ring-1 ring-edge-subtle bg-surface-raised"
    >
      <MediaImage
        :media-id="heroMediaId"
        :thumbnail="true"
        :thumbnail-size="128"
        :draggable="false"
        :enable-context-menu="false"
        container-class="w-full h-full"
        img-class="w-full h-full object-cover"
      />
    </div>
    <div
      v-else
      class="flex-shrink-0 w-10 h-10 rounded-xl overflow-hidden flex items-center justify-center bg-gradient-to-br from-violet-500 to-blue-600"
    >
      <svg class="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
      </svg>
    </div>

    <!-- Name + parent -->
    <div class="flex-1 min-w-0">
      <div class="flex items-center gap-2">
        <template v-if="editing">
          <input
            v-no-autocorrect
            ref="editInputRef"
            v-model="editingName"
            @blur="saveName"
            @keydown.enter="saveName"
            @keydown.esc.prevent="cancelEdit"
            @click.stop
            class="text-sm text-content font-medium bg-surface-raised border border-edge rounded px-2 py-0.5 outline-none focus:border-blue-500 flex-1 min-w-0"
            placeholder="Name this recipe..."
          />
        </template>
        <template v-else>
          <span
            v-if="recipe.name"
            class="text-[14px] text-content font-medium truncate"
          >
            {{ recipe.name }}
          </span>
          <span
            v-else
            @click.stop="beginEdit"
            class="text-[14px] text-content-muted italic truncate cursor-pointer hover:text-content-secondary"
          >
            Name this recipe...
          </span>
          <RecipeStatusPill
            :recipe-id="recipe.id"
            show-pending
            text-class="text-[11.5px] text-content-muted whitespace-nowrap"
          />
        </template>
      </div>
      <div v-if="!editing && parentName" class="text-[12px] text-content-muted truncate mt-0.5">
        based on {{ parentName }}
      </div>
      <div v-else-if="!editing && recipe.description" class="text-[12px] text-content-muted truncate mt-0.5">
        {{ recipe.description }}
      </div>
    </div>

    <!-- Output asset strip: up to 3 tiles overlap stacked-avatar style,
         mirrors the collapsed-header treatment in EquationTraceRow /
         IterationGroup so a recipe row reads as a live preview of its
         surfaced outputs, not just a generic bolt glyph. -->
    <div
      v-if="stripMediaIds.length > 0"
      class="hidden sm:flex flex-shrink-0 items-center justify-end"
    >
      <div
        v-for="(mid, i) in stripMediaIds"
        :key="mid"
        class="w-7 h-7 rounded-md border border-surface overflow-hidden ring-1 ring-edge-subtle bg-surface-raised"
        :class="i > 0 ? '-ml-2' : ''"
        :style="{ zIndex: stripMediaIds.length - i }"
      >
        <MediaImage
          :media-id="mid"
          :thumbnail="true"
          :thumbnail-size="128"
          :draggable="false"
          :enable-context-menu="false"
          container-class="w-full h-full"
          img-class="w-full h-full object-cover"
        />
      </div>
      <span
        v-if="extraCount > 0"
        class="ml-1.5 text-[10.5px] text-content-muted tabular-nums"
      >+{{ extraCount }}</span>
    </div>

    <!-- Right side: time -->
    <div class="flex-shrink-0 flex flex-col items-end gap-1.5">
      <span v-if="recipe.updated_at" class="text-[13px] text-content-muted whitespace-nowrap">
        {{ formatRelative(recipe.updated_at) }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRecipesApi, type Recipe, type RecipeEquation } from '../../composables/useRecipesApi'
import { computeRecipeOutputs } from '../../composables/useRecipeOutputs'
import { useWebSocket } from '../../composables/useWebSocket'
import RecipeStatusPill from './RecipeStatusPill.vue'
import { MediaImage } from '../media'

interface Props {
  recipe: Recipe
  parentName?: string | null
  startEditing?: boolean
}
const props = withDefaults(defineProps<Props>(), { parentName: null, startEditing: false })
const emit = defineEmits<{
  (e: 'open', recipe: Recipe): void
  (e: 'contextmenu', event: MouseEvent, recipe: Recipe): void
  (e: 'rename', recipe: Recipe, newName: string): void
  (e: 'rename-cancelled'): void
}>()

const api = useRecipesApi()
const { on } = useWebSocket()

const editing = ref(false)
const editingName = ref('')
const editInputRef = ref<HTMLInputElement | null>(null)

// Output media for the hero avatar + strip. Populated by a lazy listEquations
// fetch per row — the recipe list endpoint doesn't aggregate output media, so
// each card pulls its own equations and derives outputs via the same
// computeRecipeOutputs helper the recipe detail view uses.
const outputMediaIds = ref<number[]>([])

const heroMediaId = computed<number | null>(() => outputMediaIds.value[0] ?? null)
const stripMediaIds = computed<number[]>(() => outputMediaIds.value.slice(1, 4))
const extraCount = computed<number>(() =>
  Math.max(0, outputMediaIds.value.length - 1 - stripMediaIds.value.length)
)

let loadSeq = 0
let reloadTimer: ReturnType<typeof setTimeout> | null = null

async function loadOutputs() {
  const id = props.recipe.id
  const seq = ++loadSeq
  try {
    const eqs: RecipeEquation[] = await api.listEquations(id)
    if (seq !== loadSeq) return
    const byKey = new Map<string, RecipeEquation>()
    for (const eq of eqs) byKey.set(eq.equation_key, eq)
    outputMediaIds.value = computeRecipeOutputs(byKey).map((o) => o.mediaId)
  } catch {
    if (seq !== loadSeq) return
    outputMediaIds.value = []
  }
}

function scheduleReload() {
  if (reloadTimer) clearTimeout(reloadTimer)
  reloadTimer = setTimeout(() => {
    reloadTimer = null
    loadOutputs()
  }, 250)
}

const unsubs: Array<() => void> = []

watch(
  () => props.startEditing,
  (should) => {
    if (should) beginEdit()
  },
  { immediate: true }
)

// Re-fetch when switching to a different recipe instance within the same card.
watch(() => props.recipe.id, () => { loadOutputs() })

onMounted(() => {
  loadOutputs()
  // Live updates: each persisted equation status transition fires
  // recipe_equation_updated with a recipe_id payload. Debounced so a cascade
  // of events from one invalidation coalesces into a single refetch.
  unsubs.push(on('recipe_equation_updated', (data: any) => {
    if (data?.recipe_id === props.recipe.id) scheduleReload()
  }))
})

onUnmounted(() => {
  if (reloadTimer) { clearTimeout(reloadTimer); reloadTimer = null }
  for (const u of unsubs) { try { u() } catch {} }
  unsubs.length = 0
})

function handleClick() {
  if (editing.value) return
  emit('open', props.recipe)
}

function beginEdit() {
  editingName.value = props.recipe.name || ''
  editing.value = true
  nextTick(() => {
    editInputRef.value?.focus()
    editInputRef.value?.select()
  })
}

function saveName() {
  if (!editing.value) return
  const newName = editingName.value.trim()
  editing.value = false
  if (newName !== (props.recipe.name || '')) {
    emit('rename', props.recipe, newName)
  } else {
    emit('rename-cancelled')
  }
}

function cancelEdit() {
  editing.value = false
  editingName.value = ''
  emit('rename-cancelled')
}

function formatRelative(ts: string): string {
  const d = new Date(ts)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)}d ago`
  return d.toLocaleDateString()
}
</script>
