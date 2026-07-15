import { getModelMarkSvg } from '../components/tools/modelMarks'

export type ModelVendorId =
  | 'anthropic'
  | 'openai'
  | 'xai'
  | 'minimax'
  | 'kimi'
  | 'alibaba'
  | 'google'
  | 'stepfun'
  | 'zai'

export type ModelLike = {
  name?: string | null
  slug?: string | null
  model_id?: string | null
  canonical_model_id?: string | null
  model_vendor?: string | null
  provider_kind?: string | null
  source?: string | null
}

export type ModelVendorInfo = {
  id: ModelVendorId
  label: string
  svg: string
}

// Manufacturer marks from https://github.com/glincker/thesvg. Existing
// ToolIcon marks are reused for OpenAI, xAI/Grok, and Alibaba/Qwen; the rest
// are theSVG mono/default variants added for the LLM catalog.
const ANTHROPIC_SVG = `<svg role="img" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="currentColor"><title>Anthropic</title><path d="M17.3041 3.541h-3.6718l6.696 16.918H24Zm-10.6082 0L0 20.459h3.7442l1.3693-3.5527h7.0052l1.3693 3.5528h3.7442L10.5363 3.5409Zm-.3712 10.2232 2.2914-5.9456 2.2914 5.9456Z"/></svg>`
const MINIMAX_SVG = `<svg role="img" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="currentColor"><title>MiniMax</title><path d="M11.43 3.92a.86.86 0 1 0-1.718 0v14.236a1.999 1.999 0 0 1-3.997 0V9.022a.86.86 0 1 0-1.718 0v3.87a1.999 1.999 0 0 1-3.997 0V11.49a.57.57 0 0 1 1.139 0v1.404a.86.86 0 0 0 1.719 0V9.022a1.999 1.999 0 0 1 3.997 0v9.134a.86.86 0 0 0 1.719 0V3.92a1.998 1.998 0 1 1 3.996 0v11.788a.57.57 0 1 1-1.139 0zm10.572 3.105a2 2 0 0 0-1.999 1.997v7.63a.86.86 0 0 1-1.718 0V3.923a1.999 1.999 0 0 0-3.997 0v16.16a.86.86 0 0 1-1.719 0V18.08a.57.57 0 1 0-1.138 0v2a1.998 1.998 0 0 0 3.996 0V3.92a.86.86 0 0 1 1.719 0v12.73a1.999 1.999 0 0 0 3.996 0V9.023a.86.86 0 1 1 1.72 0v6.686a.57.57 0 0 0 1.138 0V9.022a2 2 0 0 0-1.998-1.997"/></svg>`
const KIMI_SVG = `<svg viewBox="0 0 512 512" xmlns="http://www.w3.org/2000/svg" fill-rule="evenodd" clip-rule="evenodd" stroke-linejoin="round" stroke-miterlimit="2"><path d="M503 114.333v280c0 60.711-49.29 110-110 110H113c-60.711 0-110-49.289-110-110v-280c0-60.71 49.289-110 110-110h280c60.71 0 110 49.29 110 110z"/><path d="M342.065 189.759c1.886-2.42 3.541-4.63 5.289-6.77.81-1.007.74-1.771-.046-2.824-7.58-9.965-8.298-21.028-3.935-32.254 3.275-8.448 10.52-12.406 19.373-13.25 5.52-.521 10.936.046 15.959 2.73 6.596 3.53 10.438 8.912 11.688 16.341.995 5.926.81 11.712-.868 17.452-2.974 10.161-10.277 15.427-20.287 16.758-8.31 1.11-16.734 1.25-25.113 1.817-.648.046-1.308 0-2.06 0z" fill="#027aff"/><path d="M321.512 144.254h-50.064l-39.637 90.384h-56.036v-89.99H131v232.868h44.787v-98.103h78.973c13.598 0 26.015-7.927 31.744-20.252v118.355h44.787v-98.103c0-23.342-18.239-42.97-41.523-44.671v-.116h-24.593a45.577 45.577 0 0026.884-24.534l29.453-65.838z" fill="#fff"/></svg>`
const GOOGLE_GEMMA_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" fill-rule="evenodd"><title>Gemma (Google)</title><path d="M12.34 5.953a8.233 8.233 0 01-.247-1.125V3.72a8.25 8.25 0 015.562 2.232H12.34zm-.69 0c.113-.373.199-.755.257-1.145V3.72a8.25 8.25 0 00-5.562 2.232h5.304zm-5.433.187h5.373a7.98 7.98 0 01-.267.696 8.41 8.41 0 01-1.76 2.65L6.216 6.14zm-.264-.187H2.977v.187h2.915a8.436 8.436 0 00-2.357 5.767H0v.186h3.535a8.436 8.436 0 002.357 5.767H2.977v.186h2.976v2.977h.187v-2.915a8.436 8.436 0 005.767 2.357V24h.186v-3.535a8.436 8.436 0 005.767-2.357v2.915h.186v-2.977h2.977v-.186h-2.915a8.436 8.436 0 002.357-5.767H24v-.186h-3.535a8.436 8.436 0 00-2.357-5.767h2.915v-.187h-2.977V2.977h-.186v2.915a8.436 8.436 0 00-5.767-2.357V0h-.186v3.535A8.436 8.436 0 006.14 5.892V2.977h-.187v2.976zm6.14 14.326a8.25 8.25 0 005.562-2.233H12.34c-.108.367-.19.743-.247 1.126v1.107zm-.186-1.087a8.015 8.015 0 00-.258-1.146H6.345a8.25 8.25 0 005.562 2.233v-1.087zm-8.186-7.285h1.107a8.23 8.23 0 001.125-.247V6.345a8.25 8.25 0 00-2.232 5.562zm1.087.186H3.72a8.25 8.25 0 002.232 5.562v-5.304a8.012 8.012 0 00-1.145-.258zm15.47-.186a8.25 8.25 0 00-2.232-5.562v5.315c.367.108.743.19 1.126.247h1.107zm-1.086.186c-.39.058-.772.144-1.146.258v5.304a8.25 8.25 0 002.233-5.562h-1.087zm-1.332 5.69V12.41a7.97 7.97 0 00-.696.267 8.409 8.409 0 00-2.65 1.76l3.346 3.346zm0-6.18v-5.45l-.012-.013h-5.451c.076.235.162.468.26.696a8.698 8.698 0 001.819 2.688 8.698 8.698 0 002.688 1.82c.228.097.46.183.696.259zM6.14 17.848V12.41c.235.078.468.167.696.267a8.403 8.403 0 012.688 1.799 8.404 8.404 0 011.799 2.688c.1.228.19.46.267.696H6.152l-.012-.012zm0-6.245V6.326l3.29 3.29a8.716 8.716 0 01-2.594 1.728 8.14 8.14 0 01-.696.259zm6.257 6.257h5.277l-3.29-3.29a8.716 8.716 0 00-1.728 2.594 8.135 8.135 0 00-.259.696zm-2.347-7.81a9.435 9.435 0 01-2.88 1.96 9.14 9.14 0 012.88 1.94 9.14 9.14 0 011.94 2.88 9.435 9.435 0 011.96-2.88 9.14 9.14 0 012.88-1.94 9.435 9.435 0 01-2.88-1.96 9.434 9.434 0 01-1.96-2.88 9.14 9.14 0 01-1.94 2.88z"/></svg>`
const STEPFUN_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" fill-rule="evenodd"><title>StepFun</title><path d="M22.012 0h1.032v.927H24v.968h-.956V3.78h-1.032V1.896h-1.878v-.97h1.878V0zM2.6 12.371V1.87h.969v10.502h-.97zm10.423.66h10.95v.918h-6.208v9.579h-4.742V13.03zM5.629 3.333v12.356H0v4.51h10.386V8L20.859 8l-.003-4.668-15.227.001z"/></svg>`
const ZAI_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" fill-rule="evenodd"><title>Z.ai</title><path d="M12.105 2L9.927 4.953H.653L2.83 2h9.276zM23.254 19.048L21.078 22h-9.242l2.174-2.952h9.244zM24 2L9.264 22H0L14.736 2H24z"/></svg>`

export const MODEL_VENDORS: Record<ModelVendorId, ModelVendorInfo> = {
  anthropic: { id: 'anthropic', label: 'Anthropic', svg: ANTHROPIC_SVG },
  openai: { id: 'openai', label: 'OpenAI', svg: getModelMarkSvg('openai')! },
  xai: { id: 'xai', label: 'xAI', svg: getModelMarkSvg('xai')! },
  minimax: { id: 'minimax', label: 'MiniMax', svg: MINIMAX_SVG },
  kimi: { id: 'kimi', label: 'Kimi', svg: KIMI_SVG },
  alibaba: { id: 'alibaba', label: 'Alibaba', svg: getModelMarkSvg('alibaba')! },
  google: { id: 'google', label: 'Google', svg: GOOGLE_GEMMA_SVG },
  stepfun: { id: 'stepfun', label: 'StepFun', svg: STEPFUN_SVG },
  zai: { id: 'zai', label: 'Z.ai', svg: ZAI_SVG },
}

const VENDOR_ALIASES: Record<string, ModelVendorId> = {
  anthropic: 'anthropic', claude: 'anthropic',
  openai: 'openai', gpt: 'openai',
  xai: 'xai', 'x-ai': 'xai', grok: 'xai',
  minimax: 'minimax',
  kimi: 'kimi', moonshot: 'kimi', moonshotai: 'kimi',
  alibaba: 'alibaba', qwen: 'alibaba',
  google: 'google', gemma: 'google',
  stepfun: 'stepfun',
  zai: 'zai', 'z.ai': 'zai', 'z-ai': 'zai', zhipu: 'zai', glm: 'zai',
}

export function resolveModelVendorId(model: ModelLike | string | null | undefined): ModelVendorId | null {
  if (!model) return null
  if (typeof model === 'string') {
    const normalized = model.toLowerCase()
    return VENDOR_ALIASES[normalized] || resolveModelVendorId({ name: normalized })
  }
  const explicit = model.model_vendor?.toLowerCase()
  if (explicit && VENDOR_ALIASES[explicit]) return VENDOR_ALIASES[explicit]
  const haystack = [model.canonical_model_id, model.slug, model.model_id, model.name]
    .filter(Boolean).join(' ').toLowerCase()
  if (haystack.includes('anthropic') || haystack.includes('claude')) return 'anthropic'
  if (haystack.includes('openai') || haystack.includes('gpt-')) return 'openai'
  if (haystack.includes('xai') || haystack.includes('x-ai') || haystack.includes('grok')) return 'xai'
  if (haystack.includes('minimax')) return 'minimax'
  if (haystack.includes('kimi') || haystack.includes('moonshot')) return 'kimi'
  if (haystack.includes('qwen') || haystack.includes('alibaba')) return 'alibaba'
  if (haystack.includes('gemma') || haystack.includes('google/')) return 'google'
  if (haystack.includes('stepfun') || haystack.includes('step-')) return 'stepfun'
  if (haystack.includes('z.ai') || haystack.includes('zhipu') || haystack.includes('glm')) return 'zai'
  return null
}

export function getModelVendorInfo(model: ModelLike | string | null | undefined): ModelVendorInfo | null {
  const id = resolveModelVendorId(model)
  return id ? MODEL_VENDORS[id] : null
}

function modelOrder(model: ModelLike): number {
  if (model.source === 'auto') return -100
  const name = `${model.slug || ''} ${model.model_id || ''} ${model.name || ''}`.toLowerCase()
  if (name.includes('claude-opus') || name.includes('claude opus')) return 0
  if (name.includes('claude-fable') || name.includes('claude fable')) return 1
  if (name.includes('claude-sonnet') || name.includes('claude sonnet')) return 2
  if (name.includes('claude-haiku') || name.includes('claude haiku')) return 3
  if (name.includes('gpt-5.6-sol')) return 10
  if (name.includes('gpt-5.6-terra')) return 11
  if (name.includes('gpt-5.6-luna')) return 12
  const vendor = resolveModelVendorId(model)
  if (!vendor) return 90
  return { anthropic: 9, openai: 19, xai: 20, minimax: 30, kimi: 40, alibaba: 50, stepfun: 60, zai: 70, google: 80 }[vendor]
}

export function sortModelsByBrand<T extends ModelLike>(models: readonly T[]): T[] {
  return models
    .map((model, index) => ({ model, index }))
    .sort((left, right) => modelOrder(left.model) - modelOrder(right.model) || left.index - right.index)
    .map(({ model }) => model)
}
