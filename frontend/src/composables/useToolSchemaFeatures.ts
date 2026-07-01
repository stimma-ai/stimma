import { computed, type Ref, type ComputedRef } from 'vue'
import { detectResolutionControls } from '../utils/resolutionControls'
import { AUDIO_TASK_TYPES } from '../utils/taskTypeIcons'
import type { ParamConstraint, ConstraintExpr } from '../utils/paramConstraints'

// Special param names that have dedicated UI components
const SPECIAL_PARAM_NAMES = new Set([
  // Inputs with dedicated components
  'prompt',
  'input_images', 'input_videos', 'input_audios',
  'mask',
  'loras',
  // Resolution-related (handled by pickers)
  'width', 'height', 'megapixels', 'aspect_ratio', 'image_size',
  // Video params (handled by dedicated video controls)
  'frame_count', 'fps', 'duration',
  // Audio: lyrics is prompt-like — rendered right under the main prompt, not as a generic setting
  'lyrics',
  // Deprecated/removed features
  'supersede_source',
])

export interface MediaInputConfig {
  accept: 'image' | 'video' | 'audio'
  min: number
  max: number
  reorderable: boolean
  label: string
  description?: string
  control?: string  // x-control value: 'image_picker' | 'video_frame_picker' | 'audio_picker'
  allowPrep: boolean  // x-allow-prep: show Scale / Extend Canvas / Paint controls. Implicit true if x-controlnet present.
}

export interface GenericParam {
  name: string
  type: string
  label: string
  description?: string
  default?: any
  enum?: string[]
  enumLabels?: Record<string, string>
  minimum?: number
  maximum?: number
  step?: number
  format?: string
  control?: string
  visibleWhen?: { param: string; value: any }
  fullWidth?: boolean
  constraints?: ParamConstraint[]
}

export interface GenericParamGroup {
  group: string | null
  label: string | null
  cols: number
  params: GenericParam[]
  singleItem: boolean
  collapsible: boolean
  hiddenWhen?: ConstraintExpr
}

export interface UseToolSchemaFeaturesOptions {
  tool: Ref<any>
  availableLoras: ComputedRef<any[]>
}

// Mask format types for x-mask-format hint
export type MaskFormat = 'alpha' | 'white-black' | 'black-white'

export interface UseToolSchemaFeaturesReturn {
  // Schema feature detection
  hasWidthHeight: ComputedRef<boolean>
  hasAspectRatio: ComputedRef<boolean>
  hasMegapixels: ComputedRef<boolean>
  hasPrompt: ComputedRef<boolean>
  hasMask: ComputedRef<boolean>
  maskFormat: ComputedRef<MaskFormat>
  hasLoras: ComputedRef<boolean>
  hasScaleFactor: ComputedRef<boolean>
  hasUpscaleResolution: ComputedRef<boolean>
  showUpscalePicker: ComputedRef<boolean>
  hasResolution: ComputedRef<boolean>
  hasFrameCount: ComputedRef<boolean>
  hasDuration: ComputedRef<boolean>
  hasLyrics: ComputedRef<boolean>
  allowedDurations: ComputedRef<number[] | null>
  hasVideoFrames: ComputedRef<boolean>
  hasEndFrame: ComputedRef<boolean>
  frameMinItems: ComputedRef<number>
  frameConstraints: ComputedRef<ParamConstraint[] | undefined>

  // Output type detection
  outputsVideo: ComputedRef<boolean>
  outputsAudio: ComputedRef<boolean>
  isFromScratch: ComputedRef<boolean>

  // Media input configuration
  mediaInputConfig: ComputedRef<MediaInputConfig | null>
  // Audio input configuration (separate section, audio-conditioned tools)
  audioInputConfig: ComputedRef<MediaInputConfig | null>

  // Schema-derived choices
  aspectRatioChoices: ComputedRef<string[]>
  imageSizeChoices: ComputedRef<string[]>

  // Parameter schema
  parameterSchema: ComputedRef<any>

  // Generic parameters
  genericParams: ComputedRef<GenericParam[]>
  groupedGenericParams: ComputedRef<GenericParamGroup[]>

  // Prompt placeholder
  promptPlaceholder: ComputedRef<string>

  // Allowed dimension pairs (for constrained tools like Grok)
  allowedDimensions: ComputedRef<[number, number][] | null>

  // ControlNet preprocessor options
  controlnetOptions: ComputedRef<string[]>
}

export function useToolSchemaFeatures(options: UseToolSchemaFeaturesOptions): UseToolSchemaFeaturesReturn {
  const { tool, availableLoras } = options

  // Parameter schema (from tool)
  const parameterSchema = computed(() => {
    return tool.value?.parameter_schema || null
  })

  // Resolution-family picker detection — shared with the flow input form so the
  // two surfaces stay identical (utils/resolutionControls.ts).
  const resControls = computed(() =>
    detectResolutionControls(tool.value?.parameter_schema?.properties)
  )

  const hasWidthHeight = computed(() => resControls.value.hasWidthHeight)
  const hasAspectRatio = computed(() => resControls.value.hasAspectRatio)
  const hasMegapixels = computed(() => resControls.value.hasMegapixels)

  const hasPrompt = computed(() => {
    const props = tool.value?.parameter_schema?.properties || {}
    return 'prompt' in props
  })

  const hasMask = computed(() => {
    const props = tool.value?.parameter_schema?.properties || {}
    return 'mask' in props
  })

  // Mask format from x-mask-format hint (defaults to 'alpha' for backward compatibility)
  const maskFormat = computed((): MaskFormat => {
    const props = tool.value?.parameter_schema?.properties || {}
    const maskSchema = props.mask
    const format = maskSchema?.['x-mask-format']
    if (format === 'white-black' || format === 'black-white') {
      return format
    }
    return 'alpha' // default
  })

  const hasLoras = computed(() => {
    const props = tool.value?.parameter_schema?.properties || {}
    return 'loras' in props
  })

  // Upscale picker detection (shared — see resControls above).
  const hasScaleFactor = computed(() => resControls.value.hasScaleFactor)
  const hasUpscaleResolution = computed(() => resControls.value.hasUpscaleResolution)
  const showUpscalePicker = computed(() => resControls.value.showUpscalePicker)

  // Check if tool has a 'resolution' param (for config transfer purposes - any resolution param)
  const hasResolution = computed(() => {
    const props = tool.value?.parameter_schema?.properties || {}
    return 'resolution' in props
  })

  const hasFrameCount = computed(() => {
    const props = tool.value?.parameter_schema?.properties || {}
    return 'frame_count' in props
  })

  const hasDuration = computed(() => {
    const props = tool.value?.parameter_schema?.properties || {}
    return 'duration' in props
  })

  const hasLyrics = computed(() => {
    const props = tool.value?.parameter_schema?.properties || {}
    return 'lyrics' in props
  })

  const allowedDurations = computed((): number[] | null => {
    const props = tool.value?.parameter_schema?.properties || {}
    const schema = props.duration
    const allowed = schema?.['x-allowed-values'] || schema?.['x-allowed-durations']
    return Array.isArray(allowed) && allowed.length > 0 ? allowed : null
  })

  const hasVideoFrames = computed(() => {
    const props = tool.value?.parameter_schema?.properties || {}
    const imagesSchema = props.input_images
    return imagesSchema?.['x-control'] === 'video_frame_picker'
  })

  const hasEndFrame = computed(() => {
    const props = tool.value?.parameter_schema?.properties || {}
    const imagesSchema = props.input_images
    if (imagesSchema?.['x-control'] !== 'video_frame_picker') return false
    const max = imagesSchema?.maxItems ?? imagesSchema?.['x-max-items'] ?? 1
    return max >= 2
  })

  // How many frames the tool actually requires (0 for T2V/I2V-dual-mode tools
  // like Kling, which support running with zero reference frames).
  const frameMinItems = computed(() => {
    const props = tool.value?.parameter_schema?.properties || {}
    const imagesSchema = props.input_images
    if (imagesSchema?.['x-control'] !== 'video_frame_picker') return 1
    return imagesSchema?.['x-min-items'] ?? imagesSchema?.minItems ?? 1
  })

  // x-constraints on input_images itself (e.g. Kling: frames disabled while
  // native audio is on). Consumed directly by ToolView rather than routed
  // through GenericParam, since input_images has dedicated picker UI.
  const frameConstraints = computed(() => {
    const props = tool.value?.parameter_schema?.properties || {}
    return props.input_images?.['x-constraints']
  })

  // Output type detection
  const outputsVideo = computed(() => {
    const taskType = tool.value?.task_type || ''
    return taskType.includes('video')
  })

  const outputsAudio = computed(() => {
    const taskType = tool.value?.task_type || ''
    return (AUDIO_TASK_TYPES as readonly string[]).includes(taskType)
  })

  // Unified media input configuration
  const mediaInputConfig = computed((): MediaInputConfig | null => {
    const props = tool.value?.parameter_schema?.properties || {}

    // Images (input_images) — skip if using videoFramePicker. Frame tools render
    // their own MediaPicker instance (named Start/End slots) wired to videoImages
    // state, so the generic mediaInputItems picker must not also mount.
    if ('input_images' in props) {
      const schema = props.input_images
      const control = schema?.['x-control']
      if (control === 'video_frame_picker') {
        return null
      }
      const max = schema?.['x-max-items'] || schema?.maxItems || 3
      const hasControlnetHint = Array.isArray(schema?.['x-controlnet']) && schema['x-controlnet'].length > 0
      return {
        accept: 'image',
        min: schema?.['x-min-items'] ?? schema?.minItems ?? 1,
        max,
        reorderable: max > 1,
        label: schema?.['x-label'] || (max > 1 ? 'Reference Images' : 'Input Image'),
        description: schema?.description,
        control,
        allowPrep: schema?.['x-allow-prep'] === true || hasControlnetHint,
      }
    }

    // Videos (input_videos)
    if ('input_videos' in props) {
      const schema = props.input_videos
      const control = schema?.['x-control']
      return {
        accept: 'video',
        min: schema?.['x-min-items'] ?? schema?.minItems ?? 2,
        max: schema?.['x-max-items'] || schema?.maxItems || 999,
        reorderable: true,
        label: schema?.['x-label'] || 'Input Videos',
        description: schema?.description,
        control,
        allowPrep: false,
      }
    }

    return null
  })

  // Audio input — its OWN section, independent of the visual media input above.
  // Audio-conditioned tools (lip-sync, avatar) take a visual input (image/video)
  // AND an audio track, so this renders as a separate "reference audio" picker
  // alongside the primary visual picker.
  const audioInputConfig = computed((): MediaInputConfig | null => {
    const props = tool.value?.parameter_schema?.properties || {}
    if (!('input_audios' in props)) return null
    const schema = props.input_audios
    return {
      accept: 'audio',
      min: schema?.['x-min-items'] ?? schema?.minItems ?? 1,
      max: schema?.['x-max-items'] || schema?.maxItems || 1,
      reorderable: false,
      label: schema?.['x-label'] || 'Audio',
      description: schema?.description,
      control: schema?.['x-control'],
      allowPrep: false,
    }
  })

  // Whether this tool generates "from scratch" (no required input media)
  const isFromScratch = computed(() => {
    return !mediaInputConfig.value && !audioInputConfig.value && !hasVideoFrames.value
  })

  // Schema-derived choices
  const aspectRatioChoices = computed(() => {
    return parameterSchema.value?.properties?.aspect_ratio?.enum || []
  })

  const imageSizeChoices = computed(() => {
    return parameterSchema.value?.properties?.image_size?.enum || []
  })

  // Prompt placeholder
  const promptPlaceholder = computed(() => {
    const props = tool.value?.parameter_schema?.properties || {}
    const promptSchema = props.prompt
    return promptSchema?.description || 'Enter your prompt...'
  })

  // Allowed dimension pairs (shared — see resControls above).
  const allowedDimensions = computed(() => resControls.value.allowedDimensions)

  // ControlNet preprocessor options from x-controlnet hint on input_image/input_images
  // If "lineart" is listed, expand to all lineart variants automatically
  const controlnetOptions = computed((): string[] => {
    const props = tool.value?.parameter_schema?.properties || {}
    const imageSchema = props.input_images
    if (!imageSchema) return []
    const options = imageSchema['x-controlnet']
    if (!Array.isArray(options) || options.length === 0) return []
    const result: string[] = []
    for (const opt of options) {
      if (opt === 'lineart') {
        result.push('lineart', 'lineart_realistic', 'lineart_anime')
      } else {
        result.push(opt)
      }
    }
    return result
  })

  // Generic params: all params from parameter_schema except those with dedicated UI
  const genericParams = computed((): GenericParam[] => {
    const allProps = tool.value?.parameter_schema?.properties || {}

    const params: GenericParam[] = []

    for (const [name, schema] of Object.entries(allProps)) {
      const s = schema as any

      // Skip special params with dedicated UI
      if (SPECIAL_PARAM_NAMES.has(name)) continue

      // Skip params with upscale_resolution control (handled by UpscaleResolutionPicker)
      if (s['x-control'] === 'upscale_resolution') continue

      params.push({
        name,
        type: s.type,
        label: s['x-label'] || name.split('_').map((w: string) => w.charAt(0).toUpperCase() + w.slice(1)).join(' '),
        description: s.description,
        default: s.default,
        enum: s.enum,
        enumLabels: s['x-enum-labels'],
        minimum: s.minimum,
        maximum: s.maximum,
        step: s['x-step'],
        format: s['x-format'],
        control: s['x-control'],
        visibleWhen: s['x-visible-when'],
        constraints: s['x-constraints'],
      })
    }

    return params
  })

  // Group generic params for rendering with headers
  const groupedGenericParams = computed((): GenericParamGroup[] => {
    const params = genericParams.value
    if (params.length === 0) return []

    const layout = tool.value?.layout ?? tool.value?.metadata?.layout

    // Build a map of param name -> param for quick lookup
    const paramMap = new Map(params.map(p => [p.name, p]))

    const result: GenericParamGroup[] = []
    const usedParams = new Set<string>()

    // If we have a layout, use it to organize params into groups
    if (layout && Array.isArray(layout)) {
      for (const group of layout) {
        const groupParams: GenericParam[] = []

        for (const layoutParam of group.params || []) {
          const paramName = layoutParam.name
          const param = paramMap.get(paramName)
          if (!param) continue

          usedParams.add(paramName)

          // Apply layout overrides
          groupParams.push({
            ...param,
            label: layoutParam.label || param.label,
            fullWidth: layoutParam.full_width || false,
            visibleWhen: layoutParam.visible_when || param.visibleWhen,
          })
        }

        if (groupParams.length === 0) continue

        const singleItem = groupParams.length === 1
        result.push({
          group: group.label,
          label: group.label,
          cols: 2,
          params: groupParams,
          singleItem,
          collapsible: group.collapsed || false,
          hiddenWhen: group.hidden_when,
        })
      }
    }

    // Add any params not in layout as ungrouped
    const ungroupedParams = params.filter(p => !usedParams.has(p.name))

    // For upscale tasks without explicit layout, auto-group advanced params
    const isUpscaleTask = tool.value?.task_type?.startsWith('upscale')
    const advancedParamNames = new Set(['seed', 'color_correction'])

    if (isUpscaleTask && ungroupedParams.length > 0) {
      const primaryParams = ungroupedParams.filter(p => !advancedParamNames.has(p.name))
      const advancedParams = ungroupedParams.filter(p => advancedParamNames.has(p.name))

      if (primaryParams.length > 0) {
        result.push({
          group: null,
          label: null,
          cols: 2,
          params: primaryParams,
          singleItem: primaryParams.length === 1,
          collapsible: false,
        })
      }

      if (advancedParams.length > 0) {
        result.push({
          group: 'Advanced',
          label: 'Advanced',
          cols: 2,
          params: advancedParams,
          singleItem: advancedParams.length === 1,
          collapsible: true,
        })
      }
    } else if (ungroupedParams.length > 0) {
      result.push({
        group: null,
        label: null,
        cols: 2,
        params: ungroupedParams,
        singleItem: ungroupedParams.length === 1,
        collapsible: false,
      })
    }

    return result
  })

  return {
    // Schema feature detection
    hasWidthHeight,
    hasAspectRatio,
    hasMegapixels,
    hasPrompt,
    hasMask,
    maskFormat,
    hasLoras,
    hasScaleFactor,
    hasUpscaleResolution,
    showUpscalePicker,
    hasResolution,
    hasFrameCount,
    hasDuration,
    hasLyrics,
    allowedDurations,
    hasVideoFrames,
    hasEndFrame,
    frameMinItems,
    frameConstraints,

    // Output type detection
    outputsVideo,
    outputsAudio,
    isFromScratch,

    // Media input configuration
    mediaInputConfig,
    audioInputConfig,

    // Schema-derived choices
    aspectRatioChoices,
    imageSizeChoices,

    // Parameter schema
    parameterSchema,

    // Generic parameters
    genericParams,
    groupedGenericParams,

    // Prompt placeholder
    promptPlaceholder,

    // Constrained dimensions
    allowedDimensions,

    // ControlNet
    controlnetOptions,
  }
}
