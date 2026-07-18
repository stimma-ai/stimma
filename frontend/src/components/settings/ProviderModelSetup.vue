<template>
  <div class="space-y-6">
    <section class="py-2">
      <div class="flex flex-wrap items-start gap-3">
        <div class="min-w-[220px] flex-1">
          <h5 class="text-sm font-medium text-content">Test Model</h5>
          <div v-if="!requiredFailed" class="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
            <span v-if="testing" class="text-blue-400">Testing…</span>
            <span v-else-if="canAdd" class="text-green-500">Ready</span>
            <span v-else class="text-content-muted">Not tested</span>
          </div>
        </div>
        <button type="button" @click="$emit('test')" :disabled="testing" class="shrink-0 rounded-md border border-blue-500/50 bg-blue-500/15 px-3 py-1.5 text-xs font-medium text-blue-400 hover:bg-blue-500/20 disabled:opacity-50">
          {{ testing ? 'Testing…' : tested ? 'Re-test' : 'Run tests' }}
        </button>
      </div>

      <div v-if="tested || testing" class="mt-4 flex flex-wrap gap-1.5">
        <span
          v-for="check in checks"
          :key="check.key"
          class="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px]"
          :class="check.classes"
          :title="check.title"
        >
          <span v-if="testing && !check.result" class="h-2.5 w-2.5 animate-spin rounded-full border border-blue-300/30 border-t-blue-300" />
          <span v-else>{{ check.passed ? '✓' : '×' }}</span>
          <span>{{ check.label }}</span>
          <span v-if="check.detail" class="text-content-muted">· {{ check.detail }}</span>
        </span>
      </div>

      <p v-if="visibleError" class="mt-3 text-xs text-red-400">{{ visibleError }}</p>
    </section>

    <section class="py-2">
      <h5 class="text-sm font-medium text-content">System prompt</h5>
      <label class="mt-3 flex cursor-pointer items-start gap-2.5">
        <input type="radio" :name="`policy-${model.id}`" :checked="model.content_policy_enabled !== false" @change="setPolicy(true)" class="mt-0.5" />
        <span>
          <span class="block text-xs text-content">Include Stimma's Content Policy</span>
          <span class="mt-0.5 block text-[11px] leading-relaxed text-content-muted">With aligned models, stating the policy typically increases permissiveness and creative control while making refusals clearer.</span>
        </span>
      </label>
      <label class="mt-3 flex cursor-pointer items-start gap-2.5">
        <input type="radio" :name="`policy-${model.id}`" :checked="model.content_policy_enabled === false" @change="setPolicy(false)" class="mt-0.5" />
        <span>
          <span class="block text-xs text-content">Use the model default</span>
          <span class="mt-0.5 block text-[11px] leading-relaxed text-content-muted">Stimma does not add its policy. The model's built-in policy remains in effect.</span>
        </span>
      </label>
      <label class="mt-4 block">
        <span class="mb-1 block text-[11px] text-content-tertiary">Additional instructions</span>
        <textarea v-model="model.extra_system_prompt" rows="3" @blur="changed" class="w-full rounded-md border border-edge bg-surface-raised px-3 py-2 text-xs text-content focus:border-accent focus:outline-none" placeholder="Appended to this model's system prompt." />
      </label>
    </section>

    <section>
      <button type="button" @click="advancedOpen = !advancedOpen" class="flex w-full items-center justify-between py-3 text-left hover:text-content">
        <span class="text-sm font-medium text-content">Advanced</span>
        <svg class="h-4 w-4 text-content-muted transition-transform" :class="advancedOpen ? 'rotate-90' : ''" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="m9 5 7 7-7 7" /></svg>
      </button>
      <div v-if="advancedOpen" class="space-y-6 pt-2">
        <div class="py-2">
          <div class="flex items-start justify-between gap-4">
            <div>
              <div class="text-xs font-medium text-content">Reasoning control</div>
              <div class="mt-0.5 text-[11px] text-content-muted">How thinking is toggled per request.</div>
            </div>
            <div class="inline-flex overflow-hidden rounded-md border border-edge text-[11px]">
              <button type="button" @click="setReasoningSource('auto')" class="px-2 py-1" :class="model.reasoning_control_source !== 'manual' ? 'bg-blue-500/15 text-blue-400' : 'text-content-tertiary'">Auto</button>
              <button type="button" @click="setReasoningSource('manual')" class="px-2 py-1" :class="model.reasoning_control_source === 'manual' ? 'bg-blue-500/15 text-blue-400' : 'text-content-tertiary'">Manual</button>
            </div>
          </div>
          <div v-if="model.reasoning_control_source !== 'manual'" class="mt-2 text-[11px] text-content-tertiary">
            Detected: {{ model.reasoning?.control || 'none' }}<span v-if="model.detected_runtime"> · {{ model.detected_runtime }}</span>
          </div>
          <SettingsDropdown v-else control class="mt-3" :model-value="model.reasoning?.control || 'none'" :options="controlOptions" @update:model-value="setReasoningControl" />
        </div>

        <div class="py-2">
          <div class="mb-1 flex items-baseline justify-between gap-4">
            <label class="text-xs font-medium text-content">Context window</label>
            <span class="text-xs tabular-nums text-content-secondary">{{ contextLabel }}</span>
          </div>
          <input v-model.number="model.max_context_tokens" type="range" min="32768" max="1048576" step="32768" @change="changed" class="w-full accent-blue-500" />
          <p class="mt-1 text-[11px] text-content-muted">Match the model's configured context length. Stimma compacts history at about 80% of this.</p>
        </div>

        <label class="block py-2">
          <span class="text-xs font-medium text-content">Extra request body</span>
          <span class="mb-2 mt-0.5 block text-[11px] text-content-muted">Merged into every request for this model.</span>
          <textarea v-model="extraBodyText" rows="3" @blur="commitExtraBody" class="w-full rounded-md border border-edge bg-surface-raised px-3 py-2 font-mono text-xs text-content focus:border-accent focus:outline-none" placeholder="{}" />
          <span v-if="extraBodyError" class="mt-1 block text-[11px] text-red-400">Enter a JSON object.</span>
        </label>
      </div>
    </section>

    <div class="flex items-center gap-3 pt-2">
      <button v-if="!isNew" type="button" @click="$emit('remove')" :disabled="saving" class="ml-auto inline-flex items-center gap-1.5 text-xs text-red-400 hover:text-red-300 disabled:opacity-50">
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166M4.772 5.79l1.068 13.133A2.25 2.25 0 0 0 8.084 21h7.832a2.25 2.25 0 0 0 2.244-2.077L19.228 5.79M9.75 5.393V4.477c0-1.18.91-2.164 2.09-2.201a51.964 51.964 0 0 1 3.32 0c1.18.037 2.09 1.022 2.09 2.201v.916" /></svg>
        Remove model
      </button>
      <button v-if="isNew" type="button" @click="$emit('commit')" :disabled="saving || !canAdd || extraBodyError" class="ml-auto shrink-0 rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed">{{ saving ? 'Adding…' : 'Add model' }}</button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import SettingsDropdown from '../ui/SettingsDropdown.vue'

const props = defineProps({
  model: { type: Object, required: true },
  isNew: Boolean,
  testing: Boolean,
  saving: Boolean,
  error: { type: String, default: '' },
})
const emit = defineEmits(['test', 'commit', 'save', 'remove'])

const advancedOpen = ref(false)
const extraBodyText = ref(JSON.stringify(props.model.extra_body || {}, null, 2))
const extraBodyError = ref(false)
watch(() => props.model.id, () => {
  extraBodyText.value = JSON.stringify(props.model.extra_body || {}, null, 2)
  extraBodyError.value = false
  advancedOpen.value = false
})

const controlOptions = [
  { value: 'none', label: 'Always on / no control' },
  { value: 'openai_effort', label: 'reasoning_effort' },
  { value: 'openrouter_effort', label: 'OpenRouter reasoning' },
  { value: 'enable_thinking', label: 'enable_thinking' },
  { value: 'think', label: 'think (Ollama)' },
  { value: 'reasoning_budget', label: 'reasoning_budget (llama.cpp)' },
]

const results = computed(() => props.model.last_test_results || {})
const tested = computed(() => Boolean(props.model.last_tested_at || Object.keys(results.value).length))
const requiredChecks = ['text', 'tools', 'vision', 'thinking', 'context']
const canAdd = computed(() => props.model.last_test_passed === true && requiredChecks.every(key => results.value[key]?.passed === true))
const requiredFailed = computed(() => tested.value && !props.testing && !canAdd.value)
const visibleError = computed(() => {
  const message = props.model.last_error || props.error || ''
  return /images? (?:are|is) required/i.test(message) ? 'Vision is required.' : message
})
const contextLabel = computed(() => {
  const tokens = Number(props.model.max_context_tokens || 0)
  return tokens >= 1_000_000 ? `${(tokens / 1_000_000).toFixed(2)}M tokens` : `${Math.round(tokens / 1024)}K tokens`
})

function detailFor(key, result) {
  if (!result) return ''
  if (result.elapsed_ms) return result.elapsed_ms > 999 ? `${(result.elapsed_ms / 1000).toFixed(1)}s` : `${result.elapsed_ms}ms`
  if (key === 'thinking' && result.passed) return props.model.reasoning?.control || 'none'
  return ''
}
const checks = computed(() => [
  ['text', 'Text'], ['tools', 'Tools'], ['vision', 'Vision'], ['thinking', 'Thinking'], ['context', 'Context'],
].map(([key, label]) => {
  const result = results.value[key]
  const passed = result?.passed === true
  return {
    key,
    label,
    result,
    passed,
    detail: detailFor(key, result),
    title: result?.detail || result?.error || '',
    classes: !result && props.testing
      ? 'border-blue-500/30 bg-blue-500/10 text-blue-400'
      : passed
        ? 'border-green-500/30 bg-green-500/5 text-green-500'
        : 'border-red-500/30 bg-red-500/5 text-red-400',
  }
}))

function changed() { if (!props.isNew) emit('save') }
function setPolicy(value) { props.model.content_policy_enabled = value; changed() }
function setReasoningSource(value) {
  props.model.reasoning_control_source = value
  if (value === 'manual' && !props.model.reasoning?.control) props.model.reasoning.control = 'openai_effort'
  changed()
}
function setReasoningControl(value) {
  props.model.reasoning.control = value
  changed()
}
function commitExtraBody() {
  try {
    const parsed = extraBodyText.value.trim() ? JSON.parse(extraBodyText.value) : {}
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error()
    props.model.extra_body = parsed
    extraBodyError.value = false
    changed()
  } catch { extraBodyError.value = true }
}
</script>
