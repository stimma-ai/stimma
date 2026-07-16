<template>
  <div>
    <!-- Wildcards -->
    <div class="mb-3">
      <h3 class="text-base font-medium text-content">Wildcards</h3>
      <p class="mt-1 max-w-xl text-xs text-content-tertiary">
        Each time you generate, a random value from the list is picked — great for adding variety across batches.
      </p>
    </div>

    <div class="space-y-1">
      <div
        v-for="(wildcard, wIndex) in localWildcards"
        :key="wildcard._id"
        class="group px-1 py-3 hover:bg-white/[0.015]"
      >
        <div class="flex items-center justify-between gap-3">
          <!-- Editable name (double-click to edit) -->
          <div v-if="editingNameIndex === wIndex && editingNameType === 'wildcard'" class="flex items-center gap-2 flex-1">
            <input
              ref="nameInputRefs"
              v-model="editingNameValue"
              @keydown.enter="saveWildcardName(wIndex)"
              @keydown.escape="cancelEditName"
              @blur="saveWildcardName(wIndex)"
              class="bg-surface border rounded px-2 py-0.5 text-sm text-content focus:outline-none w-40"
              :class="nameError ? 'border-red-500' : 'border-edge focus:border-blue-500'"
              placeholder="Wildcard name"
            />
            <span v-if="nameError" class="text-xs text-red-500 whitespace-nowrap">{{ nameError }}</span>
          </div>
          <span
            v-else
            @dblclick="startEditName(wIndex, 'wildcard')"
            class="text-sm font-medium cursor-default select-none"
            :class="wildcard.name ? 'text-content' : 'text-content-muted italic'"
            title="Double-click to rename"
          >{{ wildcard.name || 'Name this wildcard...' }}</span>

          <!-- Delete button -->
          <button
            @click="confirmDeleteWildcard(wIndex)"
            class="p-1 text-content-muted opacity-0 transition-all hover:text-red-500 focus:opacity-100 group-hover:opacity-100"
            title="Delete wildcard"
          >
            <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
              <path fill-rule="evenodd" d="M16.5 4.478v.227a48.816 48.816 0 0 1 3.878.512.75.75 0 1 1-.256 1.478l-.209-.035-1.005 13.07a3 3 0 0 1-2.991 2.77H8.084a3 3 0 0 1-2.991-2.77L4.087 6.66l-.209.035a.75.75 0 0 1-.256-1.478A48.567 48.567 0 0 1 7.5 4.705v-.227c0-1.564 1.213-2.9 2.816-2.951a52.662 52.662 0 0 1 3.369 0c1.603.051 2.815 1.387 2.815 2.951Zm-6.136-1.452a51.196 51.196 0 0 1 3.273 0C14.39 3.05 15 3.684 15 4.478v.113a49.488 49.488 0 0 0-6 0v-.113c0-.794.609-1.428 1.364-1.452Zm-.355 5.945a.75.75 0 1 0-1.5.058l.347 9a.75.75 0 1 0 1.499-.058l-.346-9Zm5.48.058a.75.75 0 1 0-1.498-.058l-.347 9a.75.75 0 0 0 1.5.058l.345-9Z" clip-rule="evenodd" />
            </svg>
          </button>
        </div>

        <!-- Tag input area -->
        <div class="mt-2 flex flex-wrap gap-1.5 items-center">
          <span
            v-for="(value, vIndex) in wildcard.values"
            :key="vIndex"
            class="inline-flex items-center gap-1 px-2.5 py-1 bg-surface-raised rounded-full text-xs text-content-secondary"
          >
            {{ value }}
            <button
              @click="removeValue(wIndex, vIndex)"
              class="text-content-muted hover:text-red-500 transition-colors ml-0.5"
            >
              <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </span>

          <!-- Always-visible tag input -->
          <input
            v-model="tagInputs[wIndex]"
            @keydown.enter.prevent="commitTagInput(wIndex)"
            @keydown.tab.prevent="commitTagInput(wIndex)"
            @keydown.delete="handleBackspace(wIndex, $event)"
            @input="handleTagInputChange(wIndex)"
            @blur="commitTagInput(wIndex)"
            class="flex-1 min-w-[80px] bg-transparent text-xs text-content py-1 px-1 focus:outline-none placeholder:text-content-muted"
            placeholder="Type and press Enter..."
          />
        </div>
      </div>

      <!-- Add wildcard row -->
      <button
        type="button"
        @click="addWildcard"
        class="flex w-full items-center gap-4 px-1 py-3 text-left hover:bg-blue-500/[0.04]"
      >
        <div class="flex h-9 w-9 shrink-0 items-center justify-center text-blue-400">
          <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path stroke-linecap="round" d="M12 5v14M5 12h14" /></svg>
        </div>
        <div class="min-w-0 flex-1">
          <div class="text-sm font-medium text-blue-400">Add Wildcard</div>
        </div>
      </button>
    </div>

    <!-- Segments -->
    <div class="mt-12 mb-3">
      <h3 class="text-base font-medium text-content">Segments</h3>
      <p class="mt-1 max-w-xl text-xs text-content-tertiary">
        Fixed text blocks that expand in place. Content can include <code class="text-xs">[verbatim]</code>, <code class="text-xs"># comments</code>, and <code class="text-xs">{a|b|c}</code> wildcards.
      </p>
    </div>

    <div class="space-y-1">
      <div
        v-for="(segment, sIndex) in localSegments"
        :key="segment._id"
        class="group px-1 py-3 hover:bg-white/[0.015]"
      >
        <div class="flex items-center justify-between gap-3">
          <div v-if="editingNameIndex === sIndex && editingNameType === 'segment'" class="flex items-center gap-2 flex-1">
            <input
              ref="nameInputRefs"
              v-model="editingNameValue"
              @keydown.enter="saveSegmentName(sIndex)"
              @keydown.escape="cancelEditName"
              @blur="saveSegmentName(sIndex)"
              class="bg-surface border rounded px-2 py-0.5 text-sm text-content focus:outline-none w-40"
              :class="nameError ? 'border-red-500' : 'border-edge focus:border-blue-500'"
              placeholder="Segment name"
            />
            <span v-if="nameError" class="text-xs text-red-500 whitespace-nowrap">{{ nameError }}</span>
          </div>
          <span
            v-else
            @dblclick="startEditName(sIndex, 'segment')"
            class="text-sm font-medium cursor-default select-none"
            :class="segment.name ? 'text-content' : 'text-content-muted italic'"
            title="Double-click to rename"
          >{{ segment.name || 'Name this segment...' }}</span>

          <!-- Delete button -->
          <button
            @click="confirmDeleteSegment(sIndex)"
            class="p-1 text-content-muted opacity-0 transition-all hover:text-red-500 focus:opacity-100 group-hover:opacity-100"
            title="Delete segment"
          >
            <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
              <path fill-rule="evenodd" d="M16.5 4.478v.227a48.816 48.816 0 0 1 3.878.512.75.75 0 1 1-.256 1.478l-.209-.035-1.005 13.07a3 3 0 0 1-2.991 2.77H8.084a3 3 0 0 1-2.991-2.77L4.087 6.66l-.209.035a.75.75 0 0 1-.256-1.478A48.567 48.567 0 0 1 7.5 4.705v-.227c0-1.564 1.213-2.9 2.816-2.951a52.662 52.662 0 0 1 3.369 0c1.603.051 2.815 1.387 2.815 2.951Zm-6.136-1.452a51.196 51.196 0 0 1 3.273 0C14.39 3.05 15 3.684 15 4.478v.113a49.488 49.488 0 0 0-6 0v-.113c0-.794.609-1.428 1.364-1.452Zm-.355 5.945a.75.75 0 1 0-1.5.058l.347 9a.75.75 0 1 0 1.499-.058l-.346-9Zm5.48.058a.75.75 0 1 0-1.498-.058l-.347 9a.75.75 0 0 0 1.5.058l.345-9Z" clip-rule="evenodd" />
            </svg>
          </button>
        </div>

        <!-- CodeMirror editor for segment content -->
        <div class="mt-2">
          <SegmentEditor
            :model-value="segment.content"
            @update:model-value="(val) => { segment.content = val; emitSegmentsUpdate() }"
          />
        </div>
      </div>

      <!-- Add segment row -->
      <button
        type="button"
        @click="addSegment"
        class="flex w-full items-center gap-4 px-1 py-3 text-left hover:bg-blue-500/[0.04]"
      >
        <div class="flex h-9 w-9 shrink-0 items-center justify-center text-blue-400">
          <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path stroke-linecap="round" d="M12 5v14M5 12h14" /></svg>
        </div>
        <div class="min-w-0 flex-1">
          <div class="text-sm font-medium text-blue-400">Add Segment</div>
        </div>
      </button>
    </div>

    <!-- Delete confirmation -->
    <ConfirmModal
      :show="showDeleteConfirm"
      :title="deleteConfirmTitle"
      :message="deleteConfirmMessage"
      confirm-text="Delete"
      @confirm="executeDelete"
      @cancel="cancelDelete"
    />
  </div>
</template>

<script setup>
import { ref, reactive, watch, nextTick } from 'vue'
import ConfirmModal from '../../ConfirmModal.vue'
import SegmentEditor from './SegmentEditor.vue'

const props = defineProps({
  wildcards: {
    type: Array,
    default: () => []
  },
  promptSegments: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['update', 'update-segments'])

let idCounter = 0

function withId(item) {
  return { ...item, _id: idCounter++ }
}

// --- Wildcards state ---
const localWildcards = ref(props.wildcards.map(withId))
const tagInputs = reactive({})

watch(() => props.wildcards, (newVal) => {
  const propsData = JSON.stringify(newVal.map(({ name, values }) => ({ name, values })))
  const localData = JSON.stringify(localWildcards.value.map(({ name, values }) => ({ name, values })))
  if (propsData !== localData) {
    localWildcards.value = newVal.map(withId)
  }
})

// --- Segments state ---
const localSegments = ref(props.promptSegments.map(withId))

watch(() => props.promptSegments, (newVal) => {
  const propsData = JSON.stringify(newVal.map(({ name, content }) => ({ name, content })))
  const localData = JSON.stringify(localSegments.value.map(({ name, content }) => ({ name, content })))
  if (propsData !== localData) {
    localSegments.value = newVal.map(withId)
  }
})

// --- Shared name editing ---
const editingNameIndex = ref(null)
const editingNameType = ref(null) // 'wildcard' or 'segment'
const editingNameValue = ref('')
const nameInputRefs = ref([])
const nameError = ref('')

// --- Delete confirmation ---
const showDeleteConfirm = ref(false)
const deleteTargetIndex = ref(null)
const deleteTargetType = ref(null) // 'wildcard' or 'segment'
const deleteTargetName = ref('')

const deleteConfirmTitle = ref('Delete?')
const deleteConfirmMessage = ref('')

// --- Cross-list name validation ---
function isNameTaken(name, excludeType, excludeIndex) {
  if (!name) return false
  const lower = name.toLowerCase()
  const wildcardDup = localWildcards.value.some((w, i) =>
    !(excludeType === 'wildcard' && i === excludeIndex) && w.name.toLowerCase() === lower
  )
  if (wildcardDup) return true
  const segmentDup = localSegments.value.some((s, i) =>
    !(excludeType === 'segment' && i === excludeIndex) && s.name.toLowerCase() === lower
  )
  return segmentDup
}

// --- Emit helpers ---
function emitWildcardsUpdate() {
  const data = localWildcards.value.map(({ name, values }) => ({ name, values }))
  emit('update', data)
}

function emitSegmentsUpdate() {
  const data = localSegments.value.map(({ name, content }) => ({ name, content }))
  emit('update-segments', data)
}

// --- Wildcards methods ---
function addWildcard() {
  localWildcards.value.push(withId({ name: '', values: [] }))
  emitWildcardsUpdate()
  nextTick(() => startEditName(localWildcards.value.length - 1, 'wildcard'))
}

function startEditName(index, type) {
  nameError.value = ''
  editingNameIndex.value = index
  editingNameType.value = type
  const list = type === 'wildcard' ? localWildcards.value : localSegments.value
  editingNameValue.value = list[index].name
  nextTick(() => {
    const inputs = nameInputRefs.value
    if (inputs && inputs.length > 0) {
      const input = Array.isArray(inputs) ? inputs[0] : inputs
      input?.focus()
      input?.select()
    }
  })
}

function saveWildcardName(index) {
  const trimmed = editingNameValue.value.trim().toLowerCase().replace(/[^a-z0-9_-]/g, '_')
  if (!trimmed) {
    if (localWildcards.value[index].name !== '') {
      localWildcards.value[index].name = ''
      emitWildcardsUpdate()
    }
    editingNameIndex.value = null
    editingNameType.value = null
    nameError.value = ''
    return
  }
  if (isNameTaken(trimmed, 'wildcard', index)) {
    nameError.value = `"${trimmed}" already exists`
    return
  }
  nameError.value = ''
  if (trimmed !== localWildcards.value[index].name) {
    localWildcards.value[index].name = trimmed
    emitWildcardsUpdate()
  }
  editingNameIndex.value = null
  editingNameType.value = null
}

function cancelEditName() {
  editingNameIndex.value = null
  editingNameType.value = null
  nameError.value = ''
}

function confirmDeleteWildcard(index) {
  deleteTargetIndex.value = index
  deleteTargetType.value = 'wildcard'
  deleteTargetName.value = localWildcards.value[index].name
  deleteConfirmTitle.value = 'Delete Wildcard?'
  deleteConfirmMessage.value = `Delete "${deleteTargetName.value || 'unnamed'}" and all its values? This cannot be undone.`
  showDeleteConfirm.value = true
}

function commitTagInput(wIndex) {
  const raw = tagInputs[wIndex] || ''
  const trimmed = raw.trim()
  if (!trimmed) {
    tagInputs[wIndex] = ''
    return
  }
  const newValues = trimmed.split(',').map(v => v.trim()).filter(v => v)
  const existing = new Set(localWildcards.value[wIndex].values)
  const unique = newValues.filter(v => !existing.has(v))
  if (unique.length > 0) {
    localWildcards.value[wIndex].values.push(...unique)
    emitWildcardsUpdate()
  }
  tagInputs[wIndex] = ''
}

function handleTagInputChange(wIndex) {
  const raw = tagInputs[wIndex] || ''
  if (raw.includes(',')) {
    commitTagInput(wIndex)
  }
}

function handleBackspace(wIndex, event) {
  const raw = tagInputs[wIndex] || ''
  if (raw === '' && localWildcards.value[wIndex].values.length > 0) {
    localWildcards.value[wIndex].values.pop()
    emitWildcardsUpdate()
  }
}

function removeValue(wIndex, vIndex) {
  localWildcards.value[wIndex].values.splice(vIndex, 1)
  emitWildcardsUpdate()
}

// --- Segments methods ---
function addSegment() {
  localSegments.value.push(withId({ name: '', content: '' }))
  emitSegmentsUpdate()
  nextTick(() => startEditName(localSegments.value.length - 1, 'segment'))
}

function saveSegmentName(index) {
  const trimmed = editingNameValue.value.trim().toLowerCase().replace(/[^a-z0-9_-]/g, '_')
  if (!trimmed) {
    if (localSegments.value[index].name !== '') {
      localSegments.value[index].name = ''
      emitSegmentsUpdate()
    }
    editingNameIndex.value = null
    editingNameType.value = null
    nameError.value = ''
    return
  }
  if (isNameTaken(trimmed, 'segment', index)) {
    nameError.value = `"${trimmed}" already exists`
    return
  }
  nameError.value = ''
  if (trimmed !== localSegments.value[index].name) {
    localSegments.value[index].name = trimmed
    emitSegmentsUpdate()
  }
  editingNameIndex.value = null
  editingNameType.value = null
}

function confirmDeleteSegment(index) {
  deleteTargetIndex.value = index
  deleteTargetType.value = 'segment'
  deleteTargetName.value = localSegments.value[index].name
  deleteConfirmTitle.value = 'Delete Segment?'
  deleteConfirmMessage.value = `Delete "${deleteTargetName.value || 'unnamed'}" and its content? This cannot be undone.`
  showDeleteConfirm.value = true
}

// --- Shared delete execution ---
function executeDelete() {
  if (deleteTargetIndex.value !== null) {
    if (deleteTargetType.value === 'wildcard') {
      localWildcards.value.splice(deleteTargetIndex.value, 1)
      emitWildcardsUpdate()
    } else if (deleteTargetType.value === 'segment') {
      localSegments.value.splice(deleteTargetIndex.value, 1)
      emitSegmentsUpdate()
    }
  }
  showDeleteConfirm.value = false
  deleteTargetIndex.value = null
  deleteTargetType.value = null
}

function cancelDelete() {
  showDeleteConfirm.value = false
  deleteTargetIndex.value = null
  deleteTargetType.value = null
}
</script>
