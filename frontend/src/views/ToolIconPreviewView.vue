<template>
  <!-- Standalone dev preview for the shared ToolIcon component. Eyeball against
       plans/icon-branding/mocks/tool-icons.html. Not linked from app chrome. -->
  <div class="min-h-screen w-full overflow-auto px-10 py-8" style="background:#0a0a0c;color:#e7e7ea">
    <div class="max-w-[1180px] mx-auto">
      <h1 class="text-2xl font-semibold mb-1">ToolIcon — dev preview</h1>
      <p class="text-sm text-zinc-400 mb-8 max-w-3xl">
        Live render of the shared <code class="text-cyan-300">ToolIcon.vue</code> component across a
        representative set. Mark = model identity (vendor mark, else task-generic glyph). Tile =
        source (Stimma Cloud gradient hairline ring vs neutral). Compare against the signed-off mock.
      </p>

      <!-- Size row -->
      <h2 class="seg mb-3">SIZES (lg · sm · xs)</h2>
      <div class="flex items-end gap-6 mb-10">
        <div v-for="sz in (['lg', 'sm', 'xs'] as const)" :key="sz" class="text-center">
          <div class="flex items-center justify-center mb-2" style="min-height:48px">
            <ToolIcon :tool="{ provider_id: 'stimma-cloud', model_vendor: 'krea' }" :size="sz" />
          </div>
          <div class="text-[11px] text-zinc-500">{{ sz }}</div>
        </div>
        <div v-for="sz in (['lg', 'sm', 'xs'] as const)" :key="'n-' + sz" class="text-center">
          <div class="flex items-center justify-center mb-2" style="min-height:48px">
            <ToolIcon :tool="{ provider_id: 'comfyui', model_vendor: 'black-forest-labs' }" :size="sz" />
          </div>
          <div class="text-[11px] text-zinc-500">{{ sz }} · neutral</div>
        </div>
      </div>

      <!-- Stimma Cloud grid (ring) -->
      <h2 class="seg mb-3">STIMMA CLOUD — gradient hairline ring</h2>
      <div class="grid grid-cols-3 gap-3 mb-8">
        <ToolCard v-for="t in cloudTools" :key="t.name" :tool="t" />
      </div>

      <!-- ComfyUI / other (neutral) -->
      <h2 class="seg mb-3">COMFYUI &amp; OTHER — neutral tile (mark = model identity)</h2>
      <div class="grid grid-cols-3 gap-3 mb-8">
        <ToolCard v-for="t in comfyTools" :key="t.name" :tool="t" />
      </div>

      <!-- Built-in (task-generic) -->
      <h2 class="seg mb-3">BUILT-IN — task-generic</h2>
      <div class="grid grid-cols-3 gap-3 mb-10">
        <ToolCard v-for="t in builtinTools" :key="t.name" :tool="t" />
      </div>

      <!-- All task generics -->
      <h2 class="seg mb-3">TASK-GENERIC GLYPHS — the fallback floor</h2>
      <div class="grid grid-cols-3 gap-3 mb-10">
        <div
          v-for="g in taskGenerics"
          :key="g.task_type"
          class="rounded-lg p-3 flex items-center gap-3"
          style="background:#0e0e12;border:1px solid #1e1e24"
        >
          <ToolIcon :tool="{ task_type: g.task_type }" />
          <div class="text-[13px] text-zinc-300">{{ g.label }}</div>
        </div>
      </div>

      <!-- xs sidebar-style rows -->
      <h2 class="seg mb-3">SIDEBAR ROWS (xs)</h2>
      <div class="rounded-xl p-2 max-w-[300px]" style="background:#0c0c10;border:1px solid #1c1c22">
        <div
          v-for="r in sidebarRows"
          :key="r.name"
          class="flex items-center gap-2.5 px-2 py-1.5 rounded-lg"
        >
          <ToolIcon :tool="r.tool" size="xs" />
          <div class="min-w-0">
            <div class="text-[13px] truncate">{{ r.name }}</div>
            <div
              class="text-[11px]"
              :style="{ color: isStimmaCloudTool(r.tool) ? '#67e8f9' : '#71717a' }"
            >
              {{ r.src }}
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { h } from 'vue'
import ToolIcon from '../components/tools/ToolIcon.vue'
import { isStimmaCloudTool } from '../utils/stimmaCloud'
import { TASK_TYPE_LABELS } from '../utils/taskTypeIcons'

// Mock tool objects passed directly (backend does not emit model_vendor yet).
type MockTool = {
  name: string
  desc?: string
  src: string
  provider_id?: string
  model_vendor?: string | null
  task_type?: string | null
}

const cloudTools: MockTool[] = [
  { name: 'Krea 2 Large', desc: 'Higher-capacity Krea 2 variant', src: 'Stimma Cloud', provider_id: 'stimma-cloud', model_vendor: 'krea' },
  { name: 'Nano Banana', desc: 'Google → nano-banana mark', src: 'Stimma Cloud', provider_id: 'stimma-cloud', model_vendor: 'google' },
  { name: 'GPT Image 2', desc: "OpenAI's latest image model", src: 'Stimma Cloud', provider_id: 'stimma-cloud', model_vendor: 'openai' },
  { name: 'Ideogram 4.0', desc: 'Strong text rendering', src: 'Stimma Cloud', provider_id: 'stimma-cloud', model_vendor: 'ideogram' },
  { name: 'Flux.2 Pro', desc: 'BFL flagship', src: 'Stimma Cloud', provider_id: 'stimma-cloud', model_vendor: 'black-forest-labs' },
  { name: 'RMBG-2.0', desc: 'Orphan (Bria) → task-generic on the Cloud ring', src: 'Stimma Cloud', provider_id: 'stimma-cloud', model_vendor: 'bria-ai', task_type: 'remove-background' },
]

const comfyTools: MockTool[] = [
  { name: 'Flux.2 Dev', desc: 'Local Flux.2 dev (BFL mark)', src: 'ComfyUI', provider_id: 'comfyui', model_vendor: 'black-forest-labs' },
  { name: 'Qwen Image 2512', desc: 'Alibaba → Qwen mark', src: 'ComfyUI', provider_id: 'comfyui', model_vendor: 'alibaba' },
  { name: 'Wan 2.2', desc: 'Alibaba → Qwen mark', src: 'ComfyUI', provider_id: 'comfyui', model_vendor: 'alibaba' },
  { name: 'SDXL', desc: 'Stability vendor mark', src: 'ComfyUI', provider_id: 'comfyui', model_vendor: 'stability-ai' },
  { name: 'Grok Imagine', desc: 'xAI → Grok mark', src: 'Provider', provider_id: 'other', model_vendor: 'xai' },
  { name: 'Chroma HD', desc: 'Orphan (no vendor) → task-generic', src: 'ComfyUI', provider_id: 'comfyui', task_type: 'text-to-image' },
]

const builtinTools: MockTool[] = [
  { name: 'Blur', src: 'Built-in Tools', provider_id: 'builtin', task_type: 'filter' },
  { name: 'Chromatic', src: 'Built-in Tools', provider_id: 'builtin', task_type: 'filter' },
  { name: 'Clarity', src: 'Built-in Tools', provider_id: 'builtin', task_type: 'filter' },
]

const taskGenerics = [
  'text-to-image', 'image-to-image', 'inpaint-image', 'outpaint-image',
  'text-to-video', 'image-to-video', 'video-stitch', 'video-extend',
  'upscale-image', 'upscale-video', 'remove-background', 'filter',
].map((task_type) => ({ task_type, label: TASK_TYPE_LABELS[task_type] || task_type }))

const sidebarRows = [
  { name: 'Krea 2 Turbo', src: 'Stimma Cloud', tool: { provider_id: 'stimma-cloud', model_vendor: 'krea' } },
  { name: 'Flux.2 Klein 9B', src: 'ComfyUI', tool: { provider_id: 'comfyui', model_vendor: 'black-forest-labs' } },
  { name: 'Qwen Image Edit', src: 'ComfyUI', tool: { provider_id: 'comfyui', model_vendor: 'alibaba' } },
  { name: 'Ideogram 4.0', src: 'Stimma Cloud', tool: { provider_id: 'stimma-cloud', model_vendor: 'ideogram' } },
  { name: 'Blur', src: 'Built-in', tool: { provider_id: 'builtin', task_type: 'filter' } },
]

// Small inline card wrapper (kept local to the preview; not a shared component).
const ToolCard = (props: { tool: MockTool }) => {
  const t = props.tool
  const cloud = isStimmaCloudTool(t)
  const badge = cloud
    ? h('span', {
        class: 'text-[11px] px-2 py-0.5 rounded-full font-medium',
        style: 'background:linear-gradient(135deg,rgba(13,148,136,.18),rgba(99,102,241,.18));border:1px solid rgba(6,182,212,.45);color:#67e8f9',
      }, 'Stimma Cloud')
    : h('span', {
        class: 'text-[11px] px-2 py-0.5 rounded-full text-zinc-400',
        style: 'background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1)',
      }, t.src)
  return h('div', { class: 'rounded-xl p-4', style: 'background:#0e0e12;border:1px solid #1e1e24' }, [
    h('div', { class: 'flex gap-3' }, [
      h(ToolIcon, { tool: t }),
      h('div', { class: 'min-w-0 flex-1' }, [
        h('div', { class: 'font-medium text-[15px] truncate' }, t.name),
        h('div', { class: 'text-[12px] text-zinc-500 mt-0.5 line-clamp-2' }, t.desc || ''),
      ]),
    ]),
    h('div', { class: 'flex flex-wrap gap-1.5 mt-3' }, [badge]),
  ])
}
</script>

<style scoped>
.seg {
  color: #6b6b73;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
}
</style>
