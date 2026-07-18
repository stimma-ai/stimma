<template>
  <div v-if="completed" class="min-w-0">
    <div v-if="isInterrupted" class="flex items-center gap-2">
      <svg class="w-4 h-4 flex-shrink-0 text-red-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 9.75L8.25 17.25M8.25 9.75l7.5 7.5" />
      </svg>
      <span class="text-sm text-red-500">Interrupted</span>
    </div>
    <template v-else>
      <div class="space-y-2">
        <div
          v-for="(entry, index) in resolvedAnswerEntries"
          :key="index"
          class="text-sm"
        >
          <div v-if="entry.label" class="text-content-muted text-xs mb-0.5">{{ entry.label }}</div>
          <div class="text-content">{{ entry.value }}</div>
        </div>
      </div>
    </template>
  </div>

  <div v-else class="space-y-3">
    <div class="text-sm font-medium text-content">{{ action.prompt }}</div>

    <div v-if="groupedQuestions.length > 0" class="space-y-4">
      <div class="rounded-lg bg-overlay-subtle overflow-hidden">
        <div class="flex gap-1.5 p-2 overflow-x-auto scrollbar-hide">
          <button
            v-for="(question, index) in groupedQuestions"
            :key="`${index}-${question.question}`"
            @click="goToTab(index)"
            class="shrink-0 flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium transition-colors rounded-md border"
            :class="tabClass(index)"
          >
            <svg v-if="isTabAnswered(index)" class="w-3 h-3 text-green-400" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
            </svg>
            {{ getTabTitle(question, index) }}
          </button>
        </div>

        <div class="p-4 space-y-3">
          <div class="text-sm font-medium text-content leading-tight">
            {{ activeQuestion.question }}
          </div>

          <div class="space-y-1">
            <button
              v-for="(opt, optionIndex) in activeQuestion.options"
              :key="`${activeQuestion.question}-${optionIndex}`"
              @click="selectGroupedOption(activeQuestion.question, opt.label)"
              class="w-full text-left px-3 py-2 rounded-lg transition-colors"
              :class="currentAnswer === opt.label
                ? 'bg-accent-selection/15 border border-accent-selection/40'
                : 'hover:bg-overlay-light border border-transparent'"
            >
              <div class="flex items-start gap-2">
                <span class="text-sm text-content-muted font-mono w-5 flex-shrink-0 mt-px">{{ optionIndex + 1 }}.</span>
                <div class="min-w-0">
                  <span class="text-sm font-medium text-content">{{ opt.label }}</span>
                  <div v-if="opt.description" class="text-xs text-content-muted leading-snug mt-0.5">{{ opt.description }}</div>
                </div>
              </div>
            </button>
          </div>

          <div class="flex items-center gap-2 px-3 py-1.5 border-t border-edge-subtle">
            <input
              ref="groupedInputRef"
              v-model="groupedCustomAnswers[activeQuestion.question]"
              placeholder="Or type your own…"
              class="flex-1 bg-transparent text-sm text-content placeholder-content-muted focus:outline-none"
              @keydown.enter.prevent="submitCurrentTab"
            />
            <button
              v-if="groupedCustomAnswers[activeQuestion.question]?.trim()"
              @click="submitCurrentTab"
              :disabled="!currentAnswer"
              class="text-xs text-accent hover:text-accent/80 disabled:opacity-40 disabled:cursor-not-allowed font-medium transition-colors"
            >
              Next
            </button>
          </div>

          <div v-if="allAnswered" class="px-4 pb-3">
            <button
              @click="submitAllGroupedAnswers"
              class="w-full rounded-lg bg-accent-selection/15 border border-accent-selection/40 px-3 py-2 text-xs font-medium text-accent-selection hover:bg-accent-selection/20 transition-colors"
            >
              Submit answers
            </button>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="space-y-0.5">
      <button
        v-for="(opt, index) in options"
        :key="index"
        @click="selectOption(index)"
        class="w-full text-left px-3 py-2 rounded-lg transition-colors group"
        :class="selectedIndex === index
          ? 'bg-accent-selection/15 border border-accent-selection/40'
          : 'hover:bg-overlay-light border border-transparent'"
      >
        <div class="flex items-start gap-2">
          <span class="text-sm text-content-muted font-mono w-5 flex-shrink-0 mt-px">{{ index + 1 }}.</span>
          <div class="min-w-0">
            <span class="text-sm font-medium text-content">{{ opt.label }}</span>
            <div v-if="opt.description" class="text-xs text-content-muted leading-snug mt-0.5">{{ opt.description }}</div>
          </div>
        </div>
      </button>

      <div class="border-t border-edge-subtle my-1"></div>

      <button
        v-if="!typing"
        @click="startTyping"
        class="w-full text-left px-3 py-2 rounded-lg transition-colors hover:bg-overlay-light border border-transparent"
      >
        <div class="flex items-start gap-2">
          <span class="text-sm text-content-muted font-mono w-5 flex-shrink-0 mt-px">{{ options.length + 1 }}.</span>
          <span class="text-sm text-content-muted">Type something...</span>
        </div>
      </button>

      <div v-else class="flex items-center gap-2 px-3 py-1.5">
        <span class="text-sm text-content-muted font-mono w-5 flex-shrink-0">{{ options.length + 1 }}.</span>
        <input
          ref="inputRef"
          v-model="inputText"
          placeholder="Type your answer…"
          class="flex-1 bg-transparent text-sm text-content placeholder-content-muted focus:outline-none"
          @keydown.enter="submitText"
          @keydown.escape="cancelTyping"
        />
        <button
          @click="submitText"
          :disabled="!inputText.trim()"
          class="text-xs text-accent hover:text-accent/80 disabled:opacity-40 disabled:cursor-not-allowed font-medium transition-colors"
        >
          Submit
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'

interface AskOption {
  label: string
  description?: string
}

interface AskQuestion {
  title?: string
  question: string
  options: AskOption[]
}

const props = defineProps<{
  action: {
    type: string
    prompt: string
    node_id: string
    tool_call_id?: string
    ask_options?: AskOption[]
    ask_questions?: AskQuestion[]
  }
  completed?: boolean
  response?: { answer: string; interrupted?: boolean } | null
}>()

const emit = defineEmits<{
  (e: 'respond', response: { answer: string }): void
}>()

const selectedIndex = ref<number | null>(null)
const typing = ref(false)
const inputText = ref('')
const inputRef = ref<HTMLInputElement | null>(null)
const groupedInputRef = ref<HTMLInputElement | null>(null)
const activeTabIndex = ref(0)
const groupedSelections = reactive<Record<string, string>>({})
const groupedCustomAnswers = reactive<Record<string, string>>({})

const options = computed<AskOption[]>(() => props.action.ask_options || [])
const groupedQuestions = computed<AskQuestion[]>(() => props.action.ask_questions || [])
const isInterrupted = computed(() => !!props.response?.interrupted)
const resolvedAnswerEntries = computed(() => {
  const answer = props.response?.answer || ''
  const lines = answer.split('\n').filter(Boolean)
  const questions = props.action.ask_questions || []

  // Grouped answers: "question: answer" per line
  if (questions.length > 0 || lines.some((l) => l.includes(':'))) {
    return lines.map((line, i) => {
      const colonIndex = line.indexOf(':')
      if (colonIndex > 0 && colonIndex < line.length - 1) {
        const label = questions[i]
          ? (questions[i].title?.trim() || deriveTitle(questions[i].question))
          : line.slice(0, colonIndex).trim()
        const value = line.slice(colonIndex + 1).trim()
        return { label, value }
      }
      return { label: '', value: line.trim() }
    })
  }

  // Single answer: use action.prompt as the question
  return [{ label: props.action.prompt, value: answer }]
})
const activeQuestion = computed(() => groupedQuestions.value[activeTabIndex.value] || { question: '', options: [] })
const currentAnswer = computed(() => groupedAnswer(activeQuestion.value.question))

watch(groupedQuestions, () => {
  activeTabIndex.value = 0
}, { immediate: true })

watch(activeTabIndex, async () => {
  await nextTick()
  groupedInputRef.value?.focus()
})

function groupedAnswer(question: string) {
  return groupedCustomAnswers[question]?.trim() || groupedSelections[question] || ''
}

function deriveTitle(question: string) {
  const cleaned = question
    .replace(/[?.,!]/g, ' ')
    .trim()
    .split(/\s+/)
    .filter(Boolean)
  return cleaned.slice(0, 2).join(' ') || 'Question'
}

function getTabTitle(question: AskQuestion, index: number) {
  return question.title?.trim() || deriveTitle(question.question) || `Q${index + 1}`
}

function isTabAnswered(index: number) {
  return !!groupedAnswer(groupedQuestions.value[index]?.question || '')
}

function goToTab(index: number) {
  if (index < 0 || index >= groupedQuestions.value.length) return
  activeTabIndex.value = index
}

function tabClass(index: number) {
  if (index === activeTabIndex.value) return 'bg-accent-selection/15 border-accent-selection/40 text-accent-selection'
  if (isTabAnswered(index)) return 'bg-overlay-subtle border-edge-subtle text-content hover:bg-overlay-light'
  return 'bg-overlay-faint border-edge-subtle text-content-muted hover:bg-overlay-subtle hover:text-content'
}

function selectOption(index: number) {
  selectedIndex.value = index
  const opt = options.value[index]
  emit('respond', { answer: opt.label })
}

function selectGroupedOption(question: string, label: string) {
  groupedSelections[question] = label
  groupedCustomAnswers[question] = ''
  submitCurrentTab()
}

function submitAllGroupedAnswers() {
  const lines = groupedQuestions.value.map((question) => `${question.question}: ${groupedAnswer(question.question)}`)
  emit('respond', { answer: lines.join('\n') })
}

const allAnswered = computed(() => groupedQuestions.value.every((q) => !!groupedAnswer(q.question)))

function submitCurrentTab() {
  const question = activeQuestion.value.question
  if (!question || !groupedAnswer(question)) return
  // Advance to next unanswered tab
  for (let i = 1; i <= groupedQuestions.value.length; i++) {
    const next = (activeTabIndex.value + i) % groupedQuestions.value.length
    if (!groupedAnswer(groupedQuestions.value[next]?.question || '')) {
      activeTabIndex.value = next
      return
    }
  }
}

async function startTyping() {
  typing.value = true
  selectedIndex.value = null
  await nextTick()
  inputRef.value?.focus()
}

function cancelTyping() {
  typing.value = false
  inputText.value = ''
}

function submitText() {
  const text = inputText.value.trim()
  if (!text) return
  emit('respond', { answer: text })
}
</script>
