/**
 * TEMPORARY eval/resilience bridge.
 *
 * The deployed Cloudflare cloud (and cached/disconnected providers) do not yet
 * emit the STP `model_vendor` field, so `ToolIcon` would fall back to a generic
 * glyph for every Stimma Cloud tool. This map infers the vendor from the tool id
 * so brand marks render now. Once providers emit `model_vendor` end-to-end (WS4
 * cloud deploy + WS5 comfy + a CachedProviderTool migration), the descriptor's
 * `model_vendor` always takes precedence and this map can be deleted.
 *
 * Source of truth for the mapping: plans/icon-branding/SLUGS.md §5.
 */
export const TOOL_ID_VENDOR_FALLBACK: Record<string, string> = {
  // Black Forest Labs
  'flux1-dev-t2i': 'black-forest-labs',
  'flux2-dev': 'black-forest-labs',
  'flux-klein-9b': 'black-forest-labs',
  'flux2-klein-4b': 'black-forest-labs',
  'flux2-klein-9b': 'black-forest-labs',
  'flux2-pro': 'black-forest-labs',
  'flux2-flex': 'black-forest-labs',
  'flux2-max': 'black-forest-labs',
  // Alibaba (Qwen / Wan / Tongyi → Qwen mark)
  'qwen-image-t2i': 'alibaba',
  'qwen-image-2512-t2i': 'alibaba',
  'qwen-image-20': 'alibaba',
  'qwen-image-20-pro': 'alibaba',
  'qwen-edit-2509': 'alibaba',
  'qwen-edit-2511': 'alibaba',
  'wan-22': 'alibaba',
  'wan-26': 'alibaba',
  'wan-26-flash': 'alibaba',
  'wan-26-image': 'alibaba',
  'z-image-turbo': 'alibaba',
  // OpenAI
  'gpt-image-15': 'openai',
  'gpt-image-2': 'openai',
  // ByteDance
  'seedream-45': 'bytedance',
  'seedance-15-pro': 'bytedance',
  'seedvr2-image-upscale': 'bytedance',
  'seedvr2-video-upscale': 'bytedance',
  // xAI
  'grok-imagine-image': 'xai',
  'grok-imagine-image-pro': 'xai',
  'grok-imagine-video': 'xai',
  // Ideogram
  'ideogram-4': 'ideogram',
  // Krea
  'krea-2-turbo': 'krea',
  'krea-2-medium': 'krea',
  'krea-2-large': 'krea',
  // Lightricks
  'ltx-23': 'lightricks',
  'ltx-23-fast': 'lightricks',
  // Google (nano-banana mark)
  'veo-31': 'google',
  'veo-31-fast': 'google',
  'gemini-2.5-flash-image': 'google',
  'gemini-2.5-flash-image-edit': 'google',
  'gemini-3-pro-image-preview': 'google',
  'gemini-3-pro-image-preview-edit': 'google',
  // Skywork
  'skyreels-v4': 'skywork',
  'skyreels-v4-extend': 'skywork',
  // Bria (no mark → task-generic, but record the vendor)
  'rmbg-2.0': 'bria-ai',
  // Stability (comfy)
  'sdxl-t2i': 'stability-ai',
}

/** model_vendor from the descriptor wins; else infer from the tool id. */
export function resolveVendor(tool: {
  model_vendor?: string | null
  id?: string
  full_tool_id?: string
}): string | null {
  if (tool.model_vendor) return tool.model_vendor
  const bare = tool.id || (tool.full_tool_id ? tool.full_tool_id.split(':').pop() : undefined)
  if (bare && TOOL_ID_VENDOR_FALLBACK[bare]) return TOOL_ID_VENDOR_FALLBACK[bare]
  return null
}
