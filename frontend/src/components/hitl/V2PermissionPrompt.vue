<template>
  <!-- Compact completed state -->
  <div v-if="completed" class="flex items-start gap-2 py-0.5 min-w-0">
    <svg v-if="response?.approved" class="w-4 h-4 text-green-500 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
      <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
    <svg v-else class="w-4 h-4 text-red-500/70 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
      <path stroke-linecap="round" stroke-linejoin="round" d="m9.75 9.75 4.5 4.5m0-4.5-4.5 4.5M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
    </svg>
    <div class="min-w-0">
      <div class="text-sm leading-snug truncate">
        <span class="text-content-muted">{{ response?.approved ? 'Allowed' : 'Denied' }}</span>
        <span class="text-content ml-1.5">{{ displayName }}</span>
      </div>
      <div
        v-if="providerName"
        class="text-[11px] leading-tight truncate mt-0.5"
        :class="isStimmaCloud ? 'stimma-cloud-text' : 'text-content-muted'"
      >via {{ providerName }}</div>
    </div>
  </div>

  <!-- Active interactive state -->
  <div v-else class="space-y-3">
    <!-- Header -->
    <div class="flex items-center gap-2">
      <svg class="w-4 h-4 text-amber-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m0-10.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285zm0 13.036h.008v.008H12v-.008z" />
      </svg>
      <span class="text-sm font-medium text-amber-500">Approval Required</span>
    </div>

    <!-- Tool name + provider + task chip -->
    <div class="min-w-0 space-y-1">
      <div class="flex items-center gap-2">
        <div class="text-sm text-content leading-snug">{{ displayName }}</div>
        <div v-if="taskTypeLabel" class="inline-flex items-center rounded-full border border-edge-subtle bg-surface-raised px-2 py-0.5 text-[11px] leading-none text-content-muted">
          <span>{{ taskTypeLabel }}</span>
        </div>
        <button v-if="hasCodeReview" @click="reviewModalOpen = true" class="text-[11px] text-blue-400 hover:text-blue-300 transition-colors">
          Review
        </button>
      </div>
      <div
        v-if="providerName"
        class="text-[11px] leading-tight"
        :class="isStimmaCloud ? 'stimma-cloud-text' : 'text-content-muted'"
      >
        {{ providerName }}
      </div>
    </div>

    <!-- Content: call_tool gets rich display -->
    <div v-if="isCallTool" class="space-y-2">
      <!-- Input image thumbnails -->
      <div v-if="inputMediaIds.length" class="space-y-2">
        <div class="text-[11px] uppercase tracking-[0.12em] text-content-muted">Input Images</div>
        <div class="flex flex-wrap gap-2">
        <MediaImage
          v-for="mediaId in inputMediaIds"
          :key="mediaId"
          :media-id="mediaId"
          :thumbnail="true"
          :thumbnail-size="128"
          :draggable="false"
          :enable-context-menu="false"
          container-class="w-16 h-16 rounded-lg overflow-hidden border border-edge-subtle"
          img-class="w-full h-full object-cover"
        />
        </div>
      </div>
      <!-- Prompt text -->
      <div v-if="promptText" class="text-sm text-content-muted leading-relaxed">{{ promptText }}</div>
    </div>

    <div v-else-if="!hasCodeReview && toolArgsPreview" class="bg-surface rounded-lg px-3 py-2 text-xs font-mono text-content-muted overflow-x-auto whitespace-pre-wrap break-all">{{ toolArgsPreview }}</div>

    <!-- Actions -->
    <div class="flex justify-end gap-3">
      <button
        @click="handleDeny"
        class="px-4 py-2 text-sm text-content-tertiary hover:text-content transition-colors"
      >
        Deny
      </button>
      <div class="relative flex" ref="allowMenuRef">
        <button
          @click="handleAllow(defaultScope)"
          class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-l-lg transition-colors"
        >
          Allow
        </button>
        <button
          @click.stop="allowMenuOpen = !allowMenuOpen"
          class="px-2 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-r-lg border-l border-blue-500 transition-colors"
        >
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
          </svg>
        </button>
        <div
          v-if="allowMenuOpen"
          class="absolute right-0 top-full mt-1 w-44 bg-surface border border-edge-subtle rounded-lg shadow-lg overflow-hidden z-50"
        >
          <button
            @click="handleAllow('once')"
            class="w-full px-3 py-2 text-left text-sm text-content hover:bg-overlay-light transition-colors"
          >
            Allow Once
          </button>
          <button
            @click="handleAllow('chat')"
            class="w-full px-3 py-2 text-left text-sm text-content transition-colors flex items-center justify-between"
            :class="defaultScope === 'chat' ? 'bg-blue-600/20 hover:bg-blue-600/30' : 'hover:bg-overlay-light'"
          >
            For this Chat
            <span v-if="defaultScope === 'chat'" class="text-[10px] text-blue-500">Default</span>
          </button>
          <button
            v-if="allowGlobal"
            @click="handleAllow('always')"
            class="w-full px-3 py-2 text-left text-sm text-content bg-blue-600/20 hover:bg-blue-600/30 transition-colors flex items-center justify-between"
          >
            Always Allow
            <span class="text-[10px] text-blue-500">Default</span>
          </button>
        </div>
      </div>
    </div>
  </div>

  <Teleport to="body">
    <Transition
      enter-active-class="transition duration-150 ease-out"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition duration-100 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="reviewModalOpen"
        class="fixed inset-0 z-[10020] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
        @click.self="reviewModalOpen = false"
      >
        <div class="flex max-h-[85vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl shadow-2xl" :class="modalPanelClass">
          <div class="flex items-center justify-between px-5 py-3" :class="modalHeaderClass">
            <h3 class="truncate text-sm font-medium" :class="modalTitleClass">{{ displayName }}</h3>
            <button
              @click="reviewModalOpen = false"
              class="rounded-lg p-2 transition-colors"
              :class="modalCloseButtonClass"
            >
              <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <div class="overflow-auto px-5 py-4" :class="modalBodyClass">
            <pre class="min-w-max rounded-xl border p-4 text-sm leading-6 select-text" :class="codeBlockClass"><code v-html="highlightedCodeHtml" /></pre>
          </div>

          <div class="flex justify-end px-5 py-4" :class="modalFooterClass">
            <button
              @click="reviewModalOpen = false"
              class="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { formatTaskTypeLabel } from '../../utils/taskTypeIcons'
import { isStimmaCloudTool, toolProviderDisplayName } from '../../utils/stimmaCloud'
import { MediaImage } from '../media'
import { useTheme } from '../../composables/useTheme'

const props = defineProps<{
  action: {
    type: string
    prompt: string
    node_id: string
    tool_call_id?: string
    v2_tool_args?: Record<string, any>
  }
  completed?: boolean
  response?: { approved: boolean; scope?: string } | null
}>()

type PermissionScope = 'once' | 'chat' | 'always'

const emit = defineEmits<{
  (e: 'respond', response: { approved: boolean; scope?: PermissionScope }): void
}>()

const allowMenuOpen = ref(false)
const allowMenuRef = ref<HTMLElement | null>(null)
const reviewModalOpen = ref(false)
const { resolvedTheme } = useTheme()
const isLight = computed(() => resolvedTheme.value === 'light')

const args = computed(() => props.action.v2_tool_args || {})

const isCallTool = computed(() => !!args.value.tool_id)

// "Always Allow" (a global/profile grant) only applies to per-tool trust for call_tool.
// Shell (bash) tops out at chat scope — there is no persistent global shell grant — so its
// default and broadest option is "For this Chat".
const allowGlobal = computed(() => isCallTool.value)
const defaultScope = computed<PermissionScope>(() => (isCallTool.value ? 'always' : 'chat'))

const v2ToolLabels: Record<string, string> = {
  bash: 'Running Command',
  run_code: 'Running Script',
  browse_web: 'Browsing Web',
  call_tool: 'Tool Call',
}

const displayName = computed(() => {
  if (args.value._display_name) return args.value._display_name
  if (args.value.tool_id) return args.value.tool_id
  const toolName = args.value._v2_tool_name
  // Shell: the agent-supplied purpose is the subject ("Download the reference image"),
  // replacing the generic "Running Command". The raw command stays visible below.
  if (toolName === 'bash' && typeof args.value.purpose === 'string' && args.value.purpose.trim()) {
    return args.value.purpose.trim()
  }
  if (toolName && v2ToolLabels[toolName]) return v2ToolLabels[toolName]
  if (toolName) return toolName
  return 'Tool'
})

const rawProviderName = computed(() => args.value._provider_name || '')
const isStimmaCloud = computed(() => isStimmaCloudTool({ provider_name: rawProviderName.value }))
const providerName = computed(() => toolProviderDisplayName({ provider_name: rawProviderName.value }, ''))
const modalPanelClass = computed(() => isLight.value
  ? 'border-edge bg-surface'
  : 'border-white/10 bg-zinc-950'
)
const modalHeaderClass = computed(() => isLight.value
  ? 'border-b border-edge'
  : 'border-b border-white/10'
)
const modalTitleClass = computed(() => isLight.value ? 'text-content' : 'text-white')
const modalCloseButtonClass = computed(() => isLight.value
  ? 'text-content-muted hover:bg-overlay-light hover:text-content'
  : 'text-zinc-400 hover:bg-white/[0.06] hover:text-white'
)
const modalBodyClass = computed(() => isLight.value ? 'bg-surface' : 'bg-zinc-950')
const modalFooterClass = computed(() => isLight.value
  ? 'border-t border-edge'
  : 'border-t border-white/10'
)
const codeBlockClass = computed(() => isLight.value
  ? 'border-edge bg-surface-raised text-content'
  : 'border-white/10 bg-black/30 text-zinc-100'
)

function formatTaskType(taskType: string) {
  return formatTaskTypeLabel(taskType)
}

const taskTypeLabel = computed(() => {
  if (typeof args.value._task_type === 'string' && args.value._task_type) {
    return formatTaskType(args.value._task_type)
  }

  const inputs = args.value.inputs || {}
  const hasInputImages = Array.isArray(inputs.input_images) && inputs.input_images.some(val => typeof val === 'number')
  if (hasInputImages) {
    return 'Image to Image'
  }

  return null
})

const inputMediaIds = computed(() => {
  const inputs = args.value.inputs
  if (!inputs) return []
  const ids = new Set<number>()

  const addId = (value: unknown) => {
    if (typeof value === 'number') {
      ids.add(value)
    }
  }

  const addIds = (value: unknown) => {
    if (!Array.isArray(value)) return
    for (const item of value) {
      addId(item)
    }
  }

  for (const [key, val] of Object.entries(inputs)) {
    if (key === 'media_id' || key.endsWith('_media_id') || key === 'image_id' || key.endsWith('_image_id')) {
      addId(val)
      continue
    }

    if (
      key === 'media_ids' ||
      key.endsWith('_media_ids') ||
      key === 'image_ids' ||
      key.endsWith('_image_ids') ||
      key === 'input_images' ||
      key === 'input_media_ids' ||
      key === 'reference_media_ids'
    ) {
      addIds(val)
    }
  }
  return Array.from(ids)
})

const promptText = computed(() => {
  const inputs = args.value.inputs
  if (!inputs) return ''
  return inputs.prompt || inputs.positive_prompt || ''
})

const compactDetail = computed(() => {
  if (args.value.command) return args.value.command.slice(0, 80)
  if (args.value.code) return ''
  if (args.value.query) return args.value.query.slice(0, 80)
  if (args.value.url) return args.value.url.slice(0, 80)
  if (promptText.value) return promptText.value.slice(0, 80)
  return ''
})

const v2ToolName = computed(() => args.value._v2_tool_name || '')
const codeContent = computed(() => typeof args.value.code === 'string' ? args.value.code : '')
const isRunCode = computed(() => v2ToolName.value === 'run_code' && !!codeContent.value)
const isBash = computed(() => v2ToolName.value === 'bash' && !!codeContent.value)
const hasCodeReview = computed(() => isRunCode.value || isBash.value)

const toolArgsPreview = computed(() => {
  if (hasCodeReview.value) return null
  if (args.value.command) return args.value.command
  if (args.value.query) return args.value.query
  if (args.value.url) return args.value.url
  const text = JSON.stringify(args.value, null, 2)
  return text === '{}' ? null : text
})

function escapeHtml(text: string) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function tokenClass(kind: 'string' | 'keyword' | 'number' | 'comment' | 'variable' | 'lineNumber') {
  if (isLight.value) {
    switch (kind) {
      case 'string':
        return 'text-emerald-700'
      case 'keyword':
        return 'text-blue-700'
      case 'number':
        return 'text-amber-700'
      case 'comment':
        return 'text-zinc-500'
      case 'variable':
        return 'text-fuchsia-700'
      case 'lineNumber':
        return 'text-zinc-400'
    }
  }

  switch (kind) {
    case 'string':
      return 'text-emerald-300'
    case 'keyword':
      return 'text-blue-300'
    case 'number':
      return 'text-amber-300'
    case 'comment':
      return 'text-zinc-500'
    case 'variable':
      return 'text-fuchsia-300'
    case 'lineNumber':
      return 'text-zinc-600'
  }
}

function highlightPython(code: string) {
  return code
    .replace(/(&quot;&quot;&quot;[\s\S]*?&quot;&quot;&quot;|&#39;&#39;&#39;[\s\S]*?&#39;&#39;&#39;|&quot;(?:\\.|[^&])*?&quot;|&#39;(?:\\.|[^&])*?&#39;)/g, `<span class="${tokenClass('string')}">$1</span>`)
    .replace(/(^|\s)(from|import|def|class|return|if|elif|else|for|while|try|except|finally|with|as|await|async|yield|lambda|pass|break|continue|in|is|not|and|or|True|False|None)(?=\s|:|\(|$)/gm, `$1<span class="${tokenClass('keyword')}">$2</span>`)
    .replace(/(^|\s)(\d+(?:\.\d+)?)(?=\s|,|\)|\]|$)/gm, `$1<span class="${tokenClass('number')}">$2</span>`)
    .replace(/(#.*)$/gm, `<span class="${tokenClass('comment')}">$1</span>`)
}

function highlightShell(code: string) {
  return code
    .replace(/(&quot;(?:\\.|[^&])*?&quot;|&#39;(?:\\.|[^&])*?&#39;)/g, `<span class="${tokenClass('string')}">$1</span>`)
    .replace(/(^|\s)(if|then|else|fi|for|do|done|while|case|esac|function|export|local|sudo)(?=\s|$)/gm, `$1<span class="${tokenClass('keyword')}">$2</span>`)
    .replace(/(\$\w+|\$\{[^}]+\})/g, `<span class="${tokenClass('variable')}">$1</span>`)
    .replace(/(#.*)$/gm, `<span class="${tokenClass('comment')}">$1</span>`)
}

const highlightedCodeHtml = computed(() => {
  const lines = escapeHtml(codeContent.value)
    .split('\n')
    .map((line) => {
      const highlighted = isRunCode.value ? highlightPython(line) : highlightShell(line)
      return `<div class="grid grid-cols-[auto_1fr] gap-4"><span class="select-none text-right text-xs leading-6 min-w-6 ${tokenClass('lineNumber')}"></span><span class="whitespace-pre">${highlighted || '&nbsp;'}</span></div>`
    })

  return lines
    .map((line, index) => line.replace('text-right text-xs text-zinc-600">', `text-right text-xs text-zinc-600">${index + 1}`))
    .join('')
})

function handleClickOutside(e: MouseEvent) {
  if (allowMenuRef.value && !allowMenuRef.value.contains(e.target as Node)) {
    allowMenuOpen.value = false
  }
}

function handleAllow(scope: PermissionScope) {
  allowMenuOpen.value = false
  emit('respond', { approved: true, scope })
}

function handleDeny() {
  emit('respond', { approved: false, scope: 'once' })
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>
