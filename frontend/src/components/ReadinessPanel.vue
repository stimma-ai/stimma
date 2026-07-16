<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition-opacity duration-150"
      leave-active-class="transition-opacity duration-150"
      enter-from-class="opacity-0"
      leave-to-class="opacity-0"
    >
      <div
        v-if="panelVisible"
        data-testid="readiness-panel"
        class="fixed inset-0 z-[10005] flex items-center justify-center bg-black/65 p-6 backdrop-blur-sm"
        @click.self="dismissWizard"
      >
        <section class="relative flex h-[820px] max-h-[94vh] w-[1180px] max-w-[96vw] flex-col overflow-hidden rounded-2xl border border-edge bg-surface shadow-2xl">
          <button
            type="button"
            data-testid="readiness-dismiss"
            aria-label="Close"
            class="absolute right-4 top-4 z-10 flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-white/[0.05] hover:text-content"
            @click="dismissWizard"
          >
            <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.75">
              <path stroke-linecap="round" d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>

          <div v-if="loading" class="flex flex-1 items-center justify-center">
            <div class="h-6 w-6 animate-spin rounded-full border-2 border-edge border-t-content-secondary"></div>
          </div>

          <div v-else-if="loadError" class="flex flex-1 items-center justify-center p-8 text-center">
            <div>
              <p class="text-sm text-red-400">{{ loadError }}</p>
              <button type="button" class="mt-4 rounded-md bg-surface-raised px-4 py-2 text-sm font-medium text-content hover:bg-surface-hover" @click="loadWizardSettings">
                Retry
              </button>
            </div>
          </div>

          <template v-else>
            <!-- WELCOME -->
            <div v-if="step === 'welcome'" class="relative flex min-h-0 flex-1 flex-col justify-center overflow-y-auto px-11 py-9">
              <GlowCanvas class="absolute inset-0" :blobs="WELCOME_GLOW" />
              <div class="relative mx-auto max-w-2xl text-center">
                <h1 class="text-[28px] font-semibold tracking-tight text-content">Stimma needs AI to work</h1>
                <p class="mt-2.5 text-sm leading-relaxed text-content-secondary">
                  Connect Stimma to your favorite services, use local models, or add credits to your Stimma account to power AI features.
                </p>
              </div>

              <div class="relative mt-9 grid grid-cols-[1fr_auto_1fr] items-start gap-8">
                <!-- Chat models -->
                <div class="min-w-0 w-full max-w-[350px] justify-self-end text-right">
                  <h3 class="text-xs font-bold uppercase tracking-[0.13em] text-content">Chat Models</h3>
                  <p class="mt-1.5 text-xs leading-relaxed text-content-secondary">Run chat, the agent, and prompt enhancement.</p>
                  <div class="mt-3 flex flex-wrap justify-end gap-1.5">
                    <WizardBrandChip v-for="chip in chatChips" :key="chip.label" :chip="chip" side="chat" />
                  </div>
                </div>

                <!-- Stimma hub -->
                <div class="relative w-[196px] self-center px-3 pb-3 pt-6 text-center">
                  <img src="/logo.png" class="relative mx-auto h-16 w-16" alt="" />
                  <div class="relative mt-3 font-brand text-[17px] font-medium lowercase tracking-[0.12em] text-content">stimma</div>
                </div>

                <!-- Generation tools -->
                <div class="min-w-0 w-full max-w-[350px] justify-self-start">
                  <h3 class="text-xs font-bold uppercase tracking-[0.13em] text-content">Generation Tools</h3>
                  <p class="mt-1.5 text-xs leading-relaxed text-content-secondary">Create and edit images, video, and audio.</p>
                  <div class="mt-3 flex flex-wrap gap-1.5">
                    <WizardBrandChip v-for="chip in genChips" :key="chip.label" :chip="chip" side="gen" />
                  </div>
                </div>
              </div>

              <p class="relative mt-8 text-center text-xs text-content-tertiary">Mix and match services freely. You can change them at any time.</p>

            </div>

            <!-- STEP 1 · chat models -->
            <div v-else-if="step === 'llm'" class="min-h-0 flex-1 overflow-y-auto px-10 py-9">
              <div class="max-w-3xl">
                <div class="text-[11px] font-semibold uppercase tracking-[0.14em] text-content-tertiary">Step 1 of 3 · Chat models</div>
                <h1 class="mt-2 text-2xl font-semibold tracking-tight text-content">Connect a chat model</h1>
                <p class="mt-2 text-sm text-content-secondary">Chat models power chat, the agent, and AI-assisted features.</p>
                <div class="mt-6">
                  <AIServicesSection
                    :llm-settings="settings?.llm_settings || []"
                    :setup-required="!llmReady"
                    wizard
                  />
                </div>
              </div>
            </div>

            <!-- STEP 2 · generation tools -->
            <div v-else-if="step === 'generation'" class="min-h-0 flex-1 overflow-y-auto px-10 py-9">
              <div class="max-w-3xl">
                <div class="text-[11px] font-semibold uppercase tracking-[0.14em] text-content-tertiary">Step 2 of 3 · Generation tools</div>
                <h1 class="mt-2 text-2xl font-semibold tracking-tight text-content">Connect generation tools</h1>
                <p class="mt-2 text-sm text-content-secondary">Generation tools create and edit images, video, and audio.</p>
                <div class="mt-6">
                  <ToolProvidersSection
                    :providers="settings?.tool_providers || []"
                    :setup-required="!generationReady"
                    wizard
                    @update="handleToolProviderUpdate"
                    @create="handleToolProviderCreate"
                    @delete="handleToolProviderDelete"
                  />
                </div>
              </div>
            </div>

            <!-- STEP 3 · folders -->
            <div v-else-if="step === 'folders'" class="min-h-0 flex-1 overflow-y-auto px-10 py-9">
              <div class="max-w-3xl">
                <div class="text-[11px] font-semibold uppercase tracking-[0.14em] text-content-tertiary">Step 3 of 3 · Your library</div>
                <h1 class="mt-2 text-2xl font-semibold tracking-tight text-content">Add your existing artwork</h1>
                <p class="mt-2 text-sm text-content-secondary">
                  Add folders of AI artwork you've made — ComfyUI outputs, Midjourney downloads — plus photos,
                  renders, and other reference imagery. Everything becomes part of your library to browse,
                  search, and remix.
                </p>
                <div class="mt-6">
                  <FoldersSection
                    :folders="settings?.folders || []"
                    @update="handleFoldersUpdate"
                    @rescan="handleFolderRescan"
                  />
                </div>
              </div>
            </div>

            <!-- END · state-dependent -->
            <div v-else class="relative flex min-h-0 flex-1 flex-col justify-center overflow-y-auto px-10 py-9">
              <GlowCanvas class="absolute inset-0" :blobs="END_GLOW" />

              <!-- Both connected: welcome -->
              <div v-if="allReady" class="relative flex flex-col items-center text-center">
                <div class="relative">
                  <div
                    class="relative mx-auto flex h-[76px] w-[76px] items-center justify-center rounded-[19px] border border-transparent p-2 shadow-[0_0_42px_rgba(6,182,212,.18),0_14px_34px_rgba(0,0,0,.5)]"
                    :style="{ background: 'linear-gradient(#12151d,#12151d) padding-box, linear-gradient(135deg, rgba(13,148,136,.9), rgba(6,182,212,.8) 50%, rgba(99,102,241,.9)) border-box' }"
                  >
                    <img src="/logo.png" class="h-full w-full" alt="" />
                  </div>
                </div>
                <div class="relative mt-4 font-brand text-xl font-medium lowercase tracking-[0.12em] text-content">stimma</div>
                <h1 class="relative mt-5 text-3xl font-semibold tracking-tight text-content">Welcome to Stimma</h1>
                <p class="relative mt-2 text-sm text-content-secondary">Your workshop is ready.</p>
              </div>

              <!-- Something missing -->
              <div v-else class="relative flex flex-col items-center text-center">
                <h1 class="text-3xl font-semibold tracking-tight text-content">Setup isn’t finished</h1>
                <p class="mt-2 max-w-xl text-sm text-content-secondary">
                  Your workshop isn’t fully equipped. Creation will be limited until setup is finished.
                </p>
                <button
                  type="button"
                  class="mt-7 rounded-lg bg-blue-500 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-blue-500/15 hover:bg-blue-400"
                  @click="goToStep(llmReady ? 'generation' : 'llm')"
                >
                  Go back
                </button>
              </div>

            </div>

            <footer class="flex h-[78px] shrink-0 items-center justify-end gap-3 border-t border-edge px-7">
              <button
                v-if="step !== 'welcome'"
                type="button"
                class="rounded-lg px-4 py-2.5 text-sm font-medium text-content-tertiary hover:bg-white/[0.05] hover:text-content"
                @click="goBack"
              >
                Back
              </button>
              <button
                type="button"
                class="rounded-lg px-5 py-2.5 text-sm font-semibold text-white"
                :class="step === 'complete' && allReady
                  ? 'bg-gradient-to-r from-teal-600 via-cyan-500 to-indigo-500 shadow-lg shadow-cyan-500/15 hover:from-teal-500 hover:via-cyan-400 hover:to-indigo-400'
                  : 'bg-blue-500 shadow-lg shadow-blue-500/15 hover:bg-blue-400'"
                @click="handlePrimaryAction"
              >
                {{ primaryActionLabel }}
              </button>
            </footer>
          </template>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, onUnmounted, ref, watch } from 'vue'
import { useReadiness } from '../composables/useReadiness'
import { useSettingsApi } from '../composables/useSettingsApi'
import { useWebSocket } from '../composables/useWebSocket'
import { addToast } from '../composables/useToasts'
import AIServicesSection from './settings/sections/AIServicesSection.vue'
import ToolProvidersSection from './settings/sections/ToolProvidersSection.vue'
import FoldersSection from './settings/sections/FoldersSection.vue'
import { preserveConnectingToolProviderStatuses, toolProviderUpdateStartsConnection } from '../utils/toolProviderBrands'
import { sanitizeSvg } from '../utils/sanitizeHtml'
import { MODEL_MARK_SVGS } from './tools/modelMarks'
import { MODEL_VENDORS } from '../utils/modelVendors'
import {
  DEEPSEEK_SVG,
  FIREWORKS_SVG,
  GOOGLE_GEMINI_SVG,
  META_SVG,
  MISTRAL_SVG,
  OPENROUTER_SVG,
  TOGETHER_AI_SVG,
} from '../utils/modelVendorSvgs'

const { readiness, shouldShowPanel, dismissPanel, markWizardSeen, refreshReadiness } = useReadiness()
const { fetchSettings, updateToolProvider, createToolProvider, deleteToolProvider, updateFolders, rescanFolders } = useSettingsApi()
const { on, off } = useWebSocket()

// ── Dithered glow renderer ───────────────────────────────────────────────
// These soft glows span only ~10 8-bit levels over the dark surface, so ANY
// smooth CSS falloff (gradient or blur) quantizes into visible rings. Drawing
// the falloff into a canvas with noise added BEFORE quantization (true
// dithering) is the only artifact-free way to render them.
const GlowCanvas = defineComponent({
  props: { blobs: { type: Array, required: true } },
  setup(props) {
    const el = ref(null)
    onMounted(() => {
      const canvas = el.value
      const rect = canvas.getBoundingClientRect()
      const scale = Math.min(window.devicePixelRatio || 1, 1.5)
      const w = Math.max(1, Math.round(rect.width * scale))
      const hgt = Math.max(1, Math.round(rect.height * scale))
      canvas.width = w
      canvas.height = hgt
      const ctx = canvas.getContext('2d')
      const img = ctx.createImageData(w, hgt)
      const data = img.data
      const blobs = props.blobs.map(b => ({
        cx: b.x * w, cy: b.y * hgt, rx: b.rx * w, ry: b.ry * hgt,
        r: b.color[0], g: b.color[1], b: b.color[2], a: b.alpha,
      }))
      let i = 0
      for (let y = 0; y < hgt; y++) {
        for (let x = 0; x < w; x++) {
          let r = 0, g = 0, bl = 0, a = 0
          for (const blob of blobs) {
            const dx = (x - blob.cx) / blob.rx
            const dy = (y - blob.cy) / blob.ry
            const wgt = Math.exp(-(dx * dx + dy * dy) * 2.2) * blob.a
            r += blob.r * wgt; g += blob.g * wgt; bl += blob.b * wgt; a += wgt
          }
          if (a > 0.001) {
            const n = (Math.random() - 0.5) * 2
            data[i] = Math.max(0, Math.min(255, r / a + n))
            data[i + 1] = Math.max(0, Math.min(255, g / a + n))
            data[i + 2] = Math.max(0, Math.min(255, bl / a + n))
            data[i + 3] = Math.max(0, Math.min(255, a * 255 + (Math.random() - 0.5) * 2.5))
          }
          i += 4
        }
      }
      ctx.putImageData(img, 0, 0)
    })
    return () => h('canvas', { ref: el, class: 'pointer-events-none h-full w-full', 'aria-hidden': 'true' })
  },
})

const TEAL = [13, 148, 136]
const INDIGO = [99, 102, 241]
const WELCOME_GLOW = [
  { x: 0.23, y: 0.6, rx: 0.26, ry: 0.4, color: TEAL, alpha: 0.16 },
  { x: 0.77, y: 0.6, rx: 0.26, ry: 0.4, color: INDIGO, alpha: 0.16 },
]
const END_GLOW = [
  { x: 0.23, y: 0.6, rx: 0.26, ry: 0.4, color: TEAL, alpha: 0.12 },
  { x: 0.77, y: 0.6, rx: 0.26, ry: 0.4, color: INDIGO, alpha: 0.12 },
]

// ── Welcome infographic chips ────────────────────────────────────────────
// Brand marks come from the same registries the rest of the app renders
// (modelMarks / modelVendors / modelVendorSvgs); labels are display-only.
const chatChips = [
  { label: 'OpenAI', svg: MODEL_MARK_SVGS.openai },
  { label: 'Anthropic', svg: MODEL_VENDORS.anthropic.svg, color: '#D97757' },
  { label: 'Google', svg: GOOGLE_GEMINI_SVG, color: '#8ab4f8' },
  { label: 'Grok', svg: MODEL_MARK_SVGS.grok },
  { label: 'Llama', svg: META_SVG },
  { label: 'Mistral', svg: MISTRAL_SVG, color: '#fa500f' },
  { label: 'DeepSeek', svg: DEEPSEEK_SVG, color: '#4d6bfe' },
  { label: 'OpenRouter', svg: OPENROUTER_SVG },
  { label: 'Together AI', svg: TOGETHER_AI_SVG, color: '#0f6fff' },
  { label: 'Fireworks', svg: FIREWORKS_SVG, color: '#c084fc' },
  { label: 'Ollama', text: '🦙', tileClass: 'bg-white text-xs' },
  { label: 'LM Studio', text: 'LM', tileClass: 'bg-[#6C4EE6] text-[9px] font-extrabold text-white' },
  { label: 'vLLM', text: 'vLLM', tileClass: 'bg-[#2a3140] text-[7px] font-extrabold text-[#fcbf49]' },
  { label: '+ more', more: true },
]
const genChips = [
  { label: 'FLUX', svg: MODEL_MARK_SVGS.bfl },
  { label: 'Nano Banana', svg: MODEL_MARK_SVGS['nano-banana'], color: '#f9d13a' },
  { label: 'Kling', text: 'K', tileClass: 'border border-white/20 bg-black text-[10px] font-extrabold text-[#00e676]' },
  { label: 'Veo', svg: GOOGLE_GEMINI_SVG, color: '#8ab4f8' },
  { label: 'Seedream', svg: MODEL_MARK_SVGS.bytedance, color: '#4b64f4' },
  { label: 'Qwen-Image', svg: MODEL_MARK_SVGS.qwen, color: '#8b5cf6' },
  { label: 'GPT Image', svg: MODEL_MARK_SVGS.openai },
  { label: 'Ideogram', svg: MODEL_MARK_SVGS.ideogram },
  { label: 'Wan', svg: MODEL_MARK_SVGS.qwen, color: '#22c55e' },
  { label: 'Krea', svg: MODEL_MARK_SVGS.krea },
  { label: 'LTX', svg: MODEL_MARK_SVGS.lightricks },
  { label: 'Stable Diffusion', svg: MODEL_MARK_SVGS.stability },
  { label: 'Grok Imagine', svg: MODEL_MARK_SVGS.grok },
  { label: '+ dozens more', more: true },
]

const WizardBrandChip = defineComponent({
  props: { chip: { type: Object, required: true }, side: { type: String, default: 'chat' } },
  setup(props) {
    return () => {
      if (props.chip.more) {
        return h('span', { class: 'rounded-lg border border-dashed border-edge px-2.5 py-1 text-[11px] text-content-tertiary' }, props.chip.label)
      }
      const tile = props.chip.svg
        ? h('span', {
            class: 'flex h-5 w-5 shrink-0 items-center justify-center overflow-hidden rounded-[5px] bg-white/[0.06] [&_svg]:h-[13px] [&_svg]:w-[13px]',
            style: props.chip.color ? { color: props.chip.color } : { color: '#e8eaf0' },
            innerHTML: sanitizeSvg(props.chip.svg),
          })
        : h('span', {
            class: ['flex h-5 w-5 shrink-0 items-center justify-center overflow-hidden rounded-[5px]', props.chip.tileClass],
          }, props.chip.text)
      return h('span', {
        class: [
          'inline-flex items-center gap-1.5 rounded-lg border py-1 pl-1 pr-2 backdrop-blur-[3px]',
          props.side === 'chat' ? 'border-cyan-500/15 bg-[#171b24]/60' : 'border-indigo-500/20 bg-[#171b24]/60',
        ],
      }, [tile, h('span', { class: 'whitespace-nowrap text-[11px] font-medium text-content-secondary' }, props.chip.label)])
    }
  },
})

// ── Wizard state ─────────────────────────────────────────────────────────
const STEPS = ['welcome', 'llm', 'generation', 'folders', 'complete']

const step = ref('welcome')
const settings = ref(null)
const loading = ref(false)
const loadError = ref('')
const panelVisible = ref(false)
const llmReady = computed(() => Boolean(readiness.value?.has_agent_llm))
const generationReady = computed(() => Boolean(readiness.value?.has_generation))
const allReady = computed(() => llmReady.value && generationReady.value)
const primaryActionLabel = computed(() => {
  if (step.value === 'welcome') return 'Get started'
  if (step.value === 'llm' || step.value === 'generation') return 'Continue'
  if (step.value === 'folders') return 'Continue'
  return allReady.value ? 'Start creating' : 'Start anyway'
})

async function loadWizardSettings() {
  loading.value = true
  loadError.value = ''
  try {
    settings.value = await fetchSettings()
  } catch (error) {
    console.error('Failed to load AI setup:', error)
    loadError.value = 'Could not load AI setup.'
  } finally {
    loading.value = false
  }
}

async function refreshWizardState() {
  const [freshSettings] = await Promise.all([
    fetchSettings().catch(() => null),
    refreshReadiness(),
  ])
  if (freshSettings) {
    if (settings.value) {
      freshSettings.tool_providers = preserveConnectingToolProviderStatuses(
        settings.value.tool_providers,
        freshSettings.tool_providers,
      )
    }
    settings.value = freshSettings
  }
}

async function goToStep(nextStep) {
  step.value = nextStep
  await refreshWizardState()
}

function goBack() {
  const index = STEPS.indexOf(step.value)
  if (index > 0) goToStep(STEPS[index - 1])
}

async function handlePrimaryAction() {
  if (step.value === 'welcome') return goToStep('llm')
  if (step.value === 'llm') return goToStep('generation')
  if (step.value === 'generation') return goToStep('folders')
  if (step.value === 'folders') return goToStep('complete')
  dismissWizard()
}

function dismissWizard() {
  // Any exit marks the current wizard version seen (backend-persisted);
  // the wizard returns only when SETUP_WIZARD_VERSION is bumped, or via
  // Settings → Developer → Run Setup Wizard.
  markWizardSeen()
  panelVisible.value = false
  dismissPanel()
}

async function handleFoldersUpdate(folders) {
  if (settings.value) {
    settings.value = { ...settings.value, folders }
  }
  try {
    await updateFolders(folders)
  } catch (error) {
    console.error('Failed to persist folders:', error)
    addToast(error.message || 'Could not save folders', 'error')
  }
}

async function handleFolderRescan() {
  try {
    await rescanFolders()
  } catch (error) {
    console.error('Failed to trigger rescan:', error)
  }
}

async function handleToolProviderUpdate({ providerId, data }) {
  const originalProvider = settings.value?.tool_providers.find(provider => provider.id === providerId)
  const startsConnection = toolProviderUpdateStartsConnection(data)
  if (settings.value) {
    settings.value = {
      ...settings.value,
      tool_providers: settings.value.tool_providers.map(provider => provider.id === providerId
        ? { ...provider, ...data, ...(startsConnection ? { status: 'connecting', error_message: null } : {}) }
        : provider),
    }
  }
  try {
    await updateToolProvider(providerId, data)
    await refreshReadiness()
  } catch (error) {
    console.error('Failed to persist tool provider:', error)
    if (settings.value && originalProvider) {
      settings.value = {
        ...settings.value,
        tool_providers: settings.value.tool_providers.map(provider => provider.id === providerId ? originalProvider : provider),
      }
    }
  }
}

async function handleToolProviderCreate(providerConfig) {
  const temporaryProvider = {
    id: providerConfig.id,
    name: providerConfig.name || providerConfig.id,
    type: providerConfig.type,
    enabled: true,
    status: 'connecting',
    command: providerConfig.command,
    args: providerConfig.args,
    url: providerConfig.url,
  }
  if (settings.value) {
    settings.value = { ...settings.value, tool_providers: [...settings.value.tool_providers, temporaryProvider] }
  }
  try {
    await createToolProvider(providerConfig)
    await refreshWizardState()
  } catch (error) {
    if (settings.value) {
      settings.value = { ...settings.value, tool_providers: settings.value.tool_providers.filter(provider => provider.id !== providerConfig.id) }
    }
    addToast(error.message || 'Could not add provider', 'error')
  }
}

async function handleToolProviderDelete(providerId) {
  const originalProviders = settings.value?.tool_providers || []
  if (settings.value) {
    settings.value = { ...settings.value, tool_providers: originalProviders.filter(provider => provider.id !== providerId) }
  }
  try {
    await deleteToolProvider(providerId)
    await refreshReadiness()
  } catch (error) {
    if (settings.value) settings.value = { ...settings.value, tool_providers: originalProviders }
    addToast(error.message || 'Could not remove provider', 'error')
  }
}

function handleProviderStatusChanged(data) {
  if (!settings.value || !data?.provider_id || !data?.status) return
  const freshProviders = settings.value.tool_providers.map(provider =>
    provider.id === data.provider_id ? { ...provider, status: data.status } : provider
  )
  settings.value = {
    ...settings.value,
    tool_providers: preserveConnectingToolProviderStatuses(settings.value.tool_providers, freshProviders),
  }
}

async function handleToolsUpdated() {
  if (!panelVisible.value) return
  await refreshWizardState()
}

watch(shouldShowPanel, async visible => {
  if (!visible || panelVisible.value) return
  panelVisible.value = true
  step.value = 'welcome'
  await loadWizardSettings()
}, { immediate: true })

onMounted(() => {
  on('provider_status_changed', handleProviderStatusChanged)
  on('tools_updated', handleToolsUpdated)
})

onUnmounted(() => {
  off('provider_status_changed', handleProviderStatusChanged)
  off('tools_updated', handleToolsUpdated)
})
</script>
