<script setup lang="ts">
/**
 * The image editor.
 *
 * The document is an ordered stack of ops over a base AssetRevision. Generative
 * steps submit through the existing job pipeline as context-owned candidates;
 * picking one composites client-side, taking only the pixels inside its mask.
 * Save materializes the composite as a new Revision — until then, nothing
 * outside this screen sees the stack (the rasterized-head invariant).
 *
 * Every step in the stack is a live parameter: reorderable, toggleable,
 * re-editable, with nothing pinning its position. There are no checkpoints and
 * no whole-image steps — a step that replaced the composite would occlude the
 * stack below it, which makes it a new base rather than a step, and new bases
 * belong to the version chain. The one operation that legitimately produces one
 * is the output stage's upscale, which runs at save.
 */
import { ref, computed, onMounted, onBeforeUnmount, onActivated, onDeactivated, onUpdated, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import {
  ArrowUturnLeftIcon,
  ArrowUturnRightIcon,
  ArrowsPointingInIcon,
  ChevronUpIcon,
  MinusIcon,
  PlusIcon,
} from '@heroicons/vue/24/outline'
import Button from '../components/ui/Button.vue'
import IconButton from '../components/ui/IconButton.vue'
import Tooltip from '../components/ui/Tooltip.vue'
import ConfirmDialog from '../components/ui/ConfirmDialog.vue'
import Spinner from '../components/ui/Spinner.vue'
import StatusDot from '../components/ui/StatusDot.vue'
import ImageCompareSlider from '../components/ImageCompareSlider.vue'
import SlideshowInfoPanel from '../components/SlideshowInfoPanel.vue'
import ExportModal from '../components/ExportModal.vue'
import ShareDialog from '../components/ShareDialog.vue'
import { MediaContextMenu } from '../components/media'
import { AutoMarkPicker } from '../components/generation'
import BaseRow from '../imageEditor/components/BaseRow.vue'
import { DROP_LINE } from '../imageEditor/components/rowLayout'
import EditRow from '../imageEditor/components/EditRow.vue'
import EditorToolbar from '../imageEditor/components/EditorToolbar.vue'
import EditorSubbar from '../imageEditor/components/EditorSubbar.vue'
import CursorPopover from '../imageEditor/components/CursorPopover.vue'
import BrushPicker from '../imageEditor/ported/BrushPicker.vue'
import StackPaintCanvas from '../imageEditor/components/StackPaintCanvas.vue'
import StackRetouchFeedback from '../imageEditor/components/StackRetouchFeedback.vue'
import StackSelectCanvas from '../imageEditor/components/StackSelectCanvas.vue'
import StackAnnotateCanvas from '../imageEditor/components/StackAnnotateCanvas.vue'
import OutputPanel from '../imageEditor/components/OutputPanel.vue'
import AdjustInspector from '../imageEditor/components/AdjustInspector.vue'
import AnnotationInspector from '../imageEditor/components/AnnotationInspector.vue'
import RetouchInspector from '../imageEditor/components/RetouchInspector.vue'
import ModelEditInspector from '../imageEditor/components/ModelEditInspector.vue'
import AnnotationIsland from '../imageEditor/components/AnnotationIsland.vue'
import SelectIsland from '../imageEditor/components/SelectIsland.vue'
import StackCropCanvas from '../imageEditor/components/StackCropCanvas.vue'
import ToolPicker from '../imageEditor/components/ToolPicker.vue'
import { useStackDocument, newOpId } from '../imageEditor/stack/useStackDocument'
import { useStackCandidates } from '../imageEditor/stack/useStackCandidates'
import { StackCompositor, stackHashes, canvasToBlob } from '../imageEditor/stack/useStackCompositor'
import {
  LiveAdjustPreview,
  maskedAdjustmentNeedsCompositorPreview,
} from '../imageEditor/stack/liveAdjustPreview'
import type { AdjustmentValues } from '../imageEditor/stack/liveAdjustPreview'
import {
  headCacheHash,
  headCacheImageRef,
} from '../imageEditor/stack/headCache'
import { applyAdjust, applyAnnotations } from '../imageEditor/stack/opExecutors'
import { useProvidersApi } from '../composables/useProvidersApi'
import { useMediaApi } from '../composables/useMediaApi'
import { useAssetApi } from '../composables/useAssetApi'
import { useMarkers } from '../composables/useMarkers'
import {
  nameStepFromCrop,
  regionCropBase64,
} from '../imageEditor/stack/nameStepFromRegion'
import { apiErrorMessage } from '../imageEditor/stack/errors'
import { setEditorDirty } from '../imageEditor/stack/editorDirtyState'
import {
  readToolPrefs, writeToolPrefs, rememberSubTool,
  rememberedSubTool, rememberedIfValid,
} from '../imageEditor/stack/toolPrefs'
import { addRecentPrompt } from '../imageEditor/stack/promptHistory'
import {
  paintEngineSettings,
} from '../imageEditor/stack/paintEngineSettings'
import { retouchBrushAdjustmentParams } from '../imageEditor/stack/retouchBrushAdjustment'
import type {
  PaintEngineSettings, PaintGradientType, PaintRange,
} from '../imageEditor/stack/paintEngineSettings'
import { flattenWholeOps, hasWholeOps } from '../imageEditor/stack/flattenWholeOps'
import { blastRadius, deriveStackState, moveTargetForGap } from '../imageEditor/stack/stackState'
import {
  reusableRepaintOp,
  type RepaintSession,
} from '../imageEditor/stack/repaintSession'
import {
  directEditRowId,
  editRowKeyboardCommand,
  rowCandidateIndex,
} from '../imageEditor/stack/editListKeyboard'
import { annotationBlockOrder } from '../imageEditor/stack/annotationBlockOrder'
import { implicitPaintLayer } from '../imageEditor/stack/paintLayerTarget'
import {
  finalResolutionFor, outputDimensions, outputLabel, outputOf, resampleLanczos,
} from '../imageEditor/stack/outputStage'
import {
  geometryBelow, coTransform, isIdentity, intersectsFrame, rewritePayload,
  transformShapes, multiply, applyToPoint, invert as invertMatrix,
  payloadToDocument as payloadToDocumentTransform,
} from '../imageEditor/stack/geometryTransform'
import type { Affine } from '../imageEditor/stack/geometryTransform'
import {
  expandBorderMask, expandEdgesFromParams, expandParamsFromEdges, expandedFrame,
} from '../imageEditor/stack/expandGeometry'
import type { ExpandEdges } from '../imageEditor/stack/expandGeometry'
import { validateTaskType } from '../utils/taskTypeValidation'
import {
  DEFAULT_LINEAR_SOFTNESS,
  DEFAULT_RADIAL_FEATHER,
  gradientMaskCanvas,
  isGradientMask,
  transformGradientMask,
  withGradientSlider,
} from '../imageEditor/stack/regionMask'
import {
  combineAfterSelectionChange,
  combineFromModifiers,
  editorEscapeAction,
  selectionMatteAction,
} from '../imageEditor/stack/selectionLifecycle'
import {
  captureAdjustmentScope,
} from '../imageEditor/stack/adjustmentScope'
import type {
  AdjustmentScopeSemantic,
  AdjustmentScopeSnapshot,
} from '../imageEditor/stack/adjustmentScope'
import {
  composeMaskCanvases,
  generativeOpHasEditableMask,
  hasMaskComponents,
  luminanceToAlphaCanvas,
  opMaskComponents,
  regionMaskComponents,
  regionWithMaskComponents,
} from '../imageEditor/stack/maskComponents'
import {
  GESTURE_TOOL_LABELS,
  appendWorkspaceMaskGesture,
} from '../imageEditor/stack/workspaceMaskRecipe'
import type { WorkspaceMaskGesture } from '../imageEditor/stack/workspaceMaskRecipe'
import { FragileEntryTracker } from '../imageEditor/stack/fragileEntries'
import {
  CROP_ASPECTS, cropRectForAspect, adjustLabel,
} from '../imageEditor/stack/adjustSections'
import { toneCurveHistogramFromCanvas } from '../imageEditor/stack/toneCurve'
import {
  familyById, TOOL_FAMILIES, SELECT_TOOLS, PAINT_ENGINES,
} from '../imageEditor/stack/toolFamilies'
import type { FamilyId, SelectionMode, SelectToolId } from '../imageEditor/stack/toolFamilies'
import { useSelection } from '../imageEditor/ported/useSelection'
import type {
  GenerativeOp,
  GradientMask,
  MaskComponent,
  ModelReferenceImage,
  RetouchRegion,
  RetouchRegionKind,
  RetouchRegionSettings,
} from '../imageEditor/stack/types'
import { generateShapeId } from '../imageEditor/ported/shapes'
import type { AnnotateTool, GradientPaint, Paint, Shape } from '../imageEditor/ported/shapeTypes'
import { textStyleOfShape, textStylePatch } from '../imageEditor/stack/textStyles'
import type { TextStyleId } from '../imageEditor/stack/textStyles'
import type { CropRect } from '../imageEditor/ported/useCropInteraction'
import {
  clampViewportPan,
  isZoomWheelGesture,
  panForDragDelta,
  panForWheelDelta,
  panForZoomAtPoint,
  stabilizeWacomWheelDelta,
  wheelPanDelta,
} from '../imageEditor/ported/viewportNavigation'
import { autoLevels, autoContrast, autoBalance } from '../imageEditor/ported/autoLevels'
import {
  LOOKS, AUTO_EDITS, levelEditById, lookById, effectLookStepOf,
  photoAdjustmentRenderParams, photoAdjustmentGroup, PHOTO_ADJUSTMENT_CONTROLS,
} from '../imageEditor/stack/adjustSections'
import type { LevelEdit, Look } from '../imageEditor/stack/adjustSections'
import { rgbToHslColor } from '../imageEditor/stack/pointColorMatch'
import type { BrushSettings } from '../imageEditor/ported/geometry'
import {
  subscribeTabletPan,
  tabletInputFor,
  tabletWheelPanActive,
} from '../composables/useTabletInput'
import type { NativeTabletPanSample } from '../composables/useTabletInput'
import {
  copyModelReferenceImages,
  modelReferenceLimits,
  modelToolDefaults,
  sanitizeModelToolParams,
} from '../imageEditor/stack/modelToolParams'
import {
  REMOVE_COMPATIBLE_TASK_TYPES,
  removeCapableTools,
  removeRouteForTool,
} from '../imageEditor/stack/modelToolRouting'
import { isRunnableTool } from '../utils/toolHandoff'
import { useLoraPool } from '../composables/useLoraPool'
import {
  clearEditorLivePreview,
  publishEditorLivePreview,
} from '../imageEditor/liveEditorPreview'
import { openImageEditor } from '../imageEditor/stack/openImageEditor'
import { editorBarrelAction, heldButtonMask } from '../imageEditor/stack/tabletButtons'

const props = defineProps<{ assetId: string; revisionId?: string }>()
const router = useRouter()

const stack = useStackDocument()
const {
  listAllTools,
  getProviderTool,
  refreshProviderTools,
  uploadToTool,
} = useProvidersApi()
const loraPool = useLoraPool()
const { availableMarkers, init: initMarkers } = useMarkers()
// <img> cannot send the X-Profile-ID header the profile middleware requires,
// which is why media URLs carry their database in the path.
const { getMediaFileUrl, getMediaFaces } = useMediaApi()
const {
  getAssetBrowserItem,
  getProjects: getAssetProjects,
  getBoards: getAssetBoards,
  addMarker: addAssetMarker,
  removeMarker: removeAssetMarker,
} = useAssetApi()

const loading = ref(true)
/** KeepAlive preserves the document, but hidden editors must do no background UI work. */
const editorActive = ref(true)
let editorReady = false
let toolCatalogListenerAttached = false
const error = ref<string | null>(null)
const baseInfo = ref<any>(null)
const infoItem = ref<any>(null)
const infoLoading = ref(false)
const infoProjects = ref<any[]>([])
const infoBoards = ref<any[]>([])
const infoFaces = ref<any[]>([])
const infoDescendants = ref<any[]>([])
const infoInspiredDescendants = ref<any[]>([])
const infoChat = ref<any>(null)
const infoMarkerUpdateTrigger = ref(0)
const infoExportOpen = ref(false)
const infoShareOpen = ref(false)
let infoLoadToken = 0
const initialToolPrefs = readToolPrefs()
const newAssetMarkerIds = ref<number[]>(
  Array.isArray(initialToolPrefs.newAssetMarkerIds)
    ? initialToolPrefs.newAssetMarkerIds.filter(Number.isInteger)
    : [],
)

watch(newAssetMarkerIds, markerIds => {
  writeToolPrefs({ newAssetMarkerIds: [...markerIds] })
})

const candidateCount = ref(4)
const selectedOpId = ref<string | null>(null)

const tools = ref<any[]>([])
const repaintToolId = ref<string | null>(null)
const removeToolId = ref<string | null>(null)
const cutoutToolId = ref<string | null>(null)
const expandToolId = ref<string | null>(null)
/**
 * Expand's four edge percents. Zero all around, matching the contract's own
 * default: an expansion is a deliberate ask, and Run stays disabled until an
 * edge changes.
 */
const expandEdges = ref<ExpandEdges>({ top: 0, bottom: 0, left: 0, right: 0 })
/** Session-owned defaults and edits, keyed by provider-scoped tool id. */
const modelToolParams = ref<Record<string, Record<string, any>>>({})
/** The open family and its active sub-tool. */
const family = ref<FamilyId | null>(null)
const sub = ref<string | null>(null)
const repaintPrompt = ref(initialToolPrefs.repaintPrompt ?? '')
/** Content-specific drafts; references never leak into Remove or across verbs. */
const repaintReferenceImages = ref<ModelReferenceImage[]>([])
const recentRepaintPrompts = ref([
  ...(initialToolPrefs.recentRepaintPrompts ?? []),
])
const prompt = computed({
  get: () => repaintPrompt.value,
  set: value => {
    repaintPrompt.value = value
    writeToolPrefs({ repaintPrompt: value })
  },
})
const referenceImages = computed<ModelReferenceImage[]>({
  get: () => family.value === 'generate' && sub.value === 'repaint'
    ? repaintReferenceImages.value
    : [],
  set: value => {
    if (family.value === 'generate' && sub.value === 'repaint') {
      repaintReferenceImages.value = value
    }
  },
})
/**
 * Catalog tool picker for the active Generate sub-tool.
 *
 * The button set this and nothing rendered it, so clicking did nothing at all.
 * It uses the shared TaskTypeToolList, which is the same tool-and-provider row
 * that Send to tool and the rest of the app use — a second treatment for the
 * same list would be a second thing to keep in step.
 */
const toolPickerOpen = ref(false)
/** Where the trigger sits, so the menu opens under it rather than at the edge. */
const toolPickerLeft = ref(16)

/** Repaint uses STP inpaint; Remove may use erase or inpaint. */
const activeTaskType = computed(() =>
  family.value === 'generate' && sub.value === 'cutout'
    ? 'remove-background'
    : family.value === 'generate' && sub.value === 'expand'
      ? 'outpaint-image'
      : family.value === 'generate' && sub.value === 'remove'
        ? 'erase-image'
        : 'inpaint-image'
)
const activeCompatibleTaskTypes = computed(() =>
  family.value === 'generate' && sub.value === 'remove'
    ? [...REMOVE_COMPATIBLE_TASK_TYPES]
    : [activeTaskType.value]
)
const activeToolId = computed(() => {
  if (family.value === 'generate' && sub.value === 'remove') return removeToolId.value
  if (family.value === 'generate' && sub.value === 'repaint') return repaintToolId.value
  if (family.value === 'generate' && sub.value === 'cutout') return cutoutToolId.value
  if (family.value === 'generate' && sub.value === 'expand') return expandToolId.value
  return null
})
const activeTool = computed(() =>
  tools.value.find(tool => tool.full_tool_id === activeToolId.value) ?? null
)
const activeToolLabel = computed(() => activeTool.value?.name ?? null)
const activeToolParamValues = computed(() =>
  activeToolId.value ? modelToolParams.value[activeToolId.value] ?? {} : {}
)
const activeLoraToolId = computed(() => activeToolId.value
  ? `${activeToolId.value}__i_image-stack-${stack.documentId.value ?? 'new'}`
  : null)
const isRefreshingLoras = ref(false)
const isUploadingLora = ref(false)
const loraUploadProgress = ref<number | null>(null)
const loraUploadFileName = ref<string | null>(null)
const activeReferenceLimits = computed(() =>
  family.value === 'generate'
  && (sub.value === 'remove' || sub.value === 'cutout' || sub.value === 'expand')
    ? { totalMin: 1, totalMax: 1, min: 0, max: 0 }
    : modelReferenceLimits(activeTool.value)
)

function ensureModelToolParams(tool: any) {
  if (!tool?.full_tool_id || modelToolParams.value[tool.full_tool_id]) return
  modelToolParams.value = {
    ...modelToolParams.value,
    [tool.full_tool_id]: modelToolDefaults(tool),
  }
}

function onOpenToolPicker(event: MouseEvent) {
  const button = event?.currentTarget as HTMLElement | undefined
  const host = (button?.closest('.flex-1') as HTMLElement) ?? null
  if (button && host) {
    toolPickerLeft.value =
      button.getBoundingClientRect().left - host.getBoundingClientRect().left
  }
  toolPickerOpen.value = !toolPickerOpen.value
}

function chooseTool(tool: any) {
  ensureModelToolParams(tool)
  if (family.value === 'generate' && sub.value === 'remove') {
    removeToolId.value = tool.full_tool_id
    writeToolPrefs({ removeToolId: tool.full_tool_id })
  } else if (family.value === 'generate' && sub.value === 'repaint') {
    repaintToolId.value = tool.full_tool_id
    writeToolPrefs({ repaintToolId: tool.full_tool_id })
  } else if (family.value === 'generate' && sub.value === 'cutout') {
    cutoutToolId.value = tool.full_tool_id
    writeToolPrefs({ cutoutToolId: tool.full_tool_id })
  } else if (family.value === 'generate' && sub.value === 'expand') {
    expandToolId.value = tool.full_tool_id
    writeToolPrefs({ expandToolId: tool.full_tool_id })
  }
  toolPickerOpen.value = false
}

async function refreshEditorLoras(fullToolId: string) {
  if (!fullToolId) return
  isRefreshingLoras.value = true
  try {
    await refreshProviderTools(fullToolId.split(':')[0] || undefined)
    const refreshed = await getProviderTool(fullToolId)
    tools.value = tools.value.map(tool =>
      tool.full_tool_id === fullToolId ? { ...tool, ...refreshed } : tool
    )
  } catch (err: any) {
    error.value = apiErrorMessage(err, 'Could not refresh LoRAs.')
  } finally {
    isRefreshingLoras.value = false
  }
}

async function uploadEditorLoras(
  fullToolId: string,
  scopedLoraToolId: string,
  files: File[],
) {
  if (!files.length) return
  isUploadingLora.value = true
  isRefreshingLoras.value = true
  const failures: string[] = []
  let added = 0
  try {
    for (let index = 0; index < files.length; index++) {
      const file = files[index]
      loraUploadFileName.value = files.length > 1
        ? `${file.name} (${index + 1}/${files.length})`
        : file.name
      loraUploadProgress.value = 0
      try {
        const result = await uploadToTool(
          fullToolId,
          'loras',
          file,
          percent => { loraUploadProgress.value = percent },
        )
        const path = (result as any).lora_id ?? result.installed_path
        if (!result.success || !path) {
          failures.push(`${file.name}: ${result.error || 'upload failed'}`)
          continue
        }
        const displayName = (result as any).lora_id
          ? file.name
          : String(path).split('/').pop()?.replace(/\.[^.]+$/i, '').replace(/_/g, ' ') || String(path)
        loraPool.addToPool(
          scopedLoraToolId,
          { path, name: displayName },
          1,
          added === 0,
        )
        added++
      } catch (err: any) {
        failures.push(`${file.name}: ${apiErrorMessage(err, 'Upload failed.')}`)
      }
    }
    await refreshEditorLoras(fullToolId)
    if (failures.length) error.value = failures.join('; ')
  } finally {
    isUploadingLora.value = false
    isRefreshingLoras.value = false
    loraUploadProgress.value = null
    loraUploadFileName.value = null
  }
}

// -- selection --------------------------------------------------------------
//
// Selection is WORKSPACE state, not a mode. The model lives here — not in the
// overlay component — so it survives everything that unmounts the overlay
// (crop replaces the display box entirely). The rail on the left arms a tool;
// arming suspends the open family's pointer without ending its session.
const selModel = useSelection()
const selectRef = ref<InstanceType<typeof StackSelectCanvas> | null>(null)
/** The published mask: what consumers scope to. Kept in step with selModel. */
const selection = ref<HTMLCanvasElement | null>(null)
/**
 * Identity for the live select-then-Regenerate loop.
 *
 * This advances only when the user publishes a different selection (including
 * clear), not when render geometry merely reprojects the same master mask.
 * That makes clearing the explicit boundary even if the same pixels are later
 * selected again.
 */
let selectionRevision = 0
let repaintSession: RepaintSession | null = null
const armedSelectTool = ref<SelectToolId | null>(null)
const lastSelectTool = ref<SelectToolId>(
  (rememberedIfValid(
    readToolPrefs().selectTool,
    id => SELECT_TOOLS.some(tool => tool.id === id),
  ) as SelectToolId | undefined) ?? 'rect',
)
const selectCombine = ref<SelectionMode>('new')
const selectFeather = ref(0)
/** Magic wand extent and refinement settings. */
const selectTolerance = ref(8)
const selectSpread = ref(100)
const selectGrow = ref(0)
const selectAntialias = ref(true)
const selectBrushSize = ref(80)
/**
 * Falloff a NEW gradient starts with. Once one exists, the island slider edits
 * that gradient rather than this default — the ramp on the canvas is the thing
 * being tuned, and a slider that silently stopped affecting it would be a lie.
 */
const selectGradientSoftness = ref(DEFAULT_LINEAR_SOFTNESS)
const selectGradientFeather = ref(DEFAULT_RADIAL_FEATHER)
/** True only for the live gesture on a gradient falloff slider. */
const gradientAdjustmentPreview = ref(false)
/**
 * The selection as created, anchored directly into permanent document space.
 * Its bitmap may be compact/current-frame storage, but every pixel has one
 * complete local → document affine. Crop and viewport geometry are projections
 * of that master, never part of its identity.
 */
let selectionMaster: HTMLCanvasElement | null = null
let selectionToDocument: Affine | null = null
/** What the live selection currently reflects, so sync is a no-op at rest. */
let selectionAppliedKey: string | null = null
/** Loading a saved mask into the palette must not immediately rewrite it. */
let suppressMaskedAdjustmentSync = false
/**
 * One-shot: a gradient gesture has just landed, so the raster mask the same
 * gesture publishes came from that ramp. Consumed by `onSelectionChange`,
 * which then keeps the geometry in `workspaceGradient` instead of treating
 * the selection as drawn pixels.
 */
let gradientGestureLanding = false
/** Whether the visible workspace selection is still the one gradient gesture. */
const selectionIsGradient = ref(false)
/**
 * The live selection's PARAMETRIC identity, when it has one: the whole
 * selection is a single un-combined gradient gesture. An Adjust click scopes
 * with this geometry — keeping the ramp's handles live on the step — instead
 * of freezing the rasterised copy. Any other gesture, combine, or geometry
 * change underneath falls back to the raster (`workspaceGradientKey` pins the
 * frame it was drawn in).
 */
const workspaceGradient = ref<GradientMask | null>(null)
const workspaceGradientKey = ref<string | null>(null)
/**
 * The live selection's SEMANTIC identity, when it has one: the whole
 * selection is a single recomputable AI gesture ("sky", the subject). An
 * Adjust click scopes with the name attached, so the step's base component
 * keeps what it was a selection OF next to the cached raster. Follows the
 * same key discipline as `workspaceGradient`.
 */
const workspaceSemantic = ref<AdjustmentScopeSemantic | null>(null)
const workspaceSemanticKey = ref<string | null>(null)
/** One-shot: the AI gesture landing right now, consumed by onSelectionChange. */
let aiGestureLanding: {
  semantic: AdjustmentScopeSemantic | null
  replaces: boolean
  /** The gesture's own coverage at source size. */
  coverage: HTMLCanvasElement | null
  /** Combine mode the mask was applied with (captured at request time). */
  mode: SelectionMode
  /** Object-pick granularity cycling: re-lands over the pre-click selection. */
  cycling?: boolean
} | null = null
/** One-shot: the geometry of the gradient gesture landing right now. */
let lastGestureGradient: GradientMask | null = null
/** The combine mode that gradient gesture actually used (modifier override). */
let lastGestureGradientCombine: SelectionMode | null = null
/** One-shot: a drawn gesture's own coverage, from the selection canvas. */
let pendingGestureCapture: {
  coverage: HTMLCanvasElement
  tool: SelectToolId
  combine: SelectionMode
} | null = null
/**
 * The combine mode the HELD modifiers would give the next gesture, for the
 * island to preview (Shift add, Option subtract, both intersect). Display
 * only — each gesture samples its own modifiers at the press.
 */
const heldCombineOverride = ref<SelectionMode | null>(null)
/**
 * The workspace selection as a RECIPE of tracked gestures, so a scoped
 * adjustment can keep every ingredient editable. Best-effort bookkeeping:
 * anything it cannot describe (invert, morph, a gesture over an untracked
 * selection, a frame change) nulls it, and consumers fall back to the
 * flattened raster. Key discipline matches `workspaceGradient`.
 */
let workspaceMaskRecipe: WorkspaceMaskGesture<HTMLCanvasElement>[] | null = null
let workspaceMaskRecipeKey: string | null = null

// Retouch
const retouchRef = ref<InstanceType<typeof StackPaintCanvas> | null>(null)
const retouchOpId = ref<string | null>(null)
const retouchInput = ref<HTMLCanvasElement | null>(null)
const selectedRetouchRegionId = ref<string | null>(null)
const hoveredRetouchRegionId = ref<string | null>(null)
/** The selected/hovered mask COMPONENT inside the selected region, if any. */
const selectedMaskComponentId = ref<string | null>(null)
const hoveredMaskComponentId = ref<string | null>(null)
/** A semantic base being re-segmented; blocks a second overlapping run. */
const recomputingMaskComponentId = ref<string | null>(null)
/**
 * A GENERATIVE op whose mask is selected/armed for component editing. The op
 * plays the role a region plays for scoped adjustments; component selection
 * state (`selectedMaskComponentId`) is shared.
 */
const selectedGenerativeMaskOpId = ref<string | null>(null)
/**
 * The workspace selection IS the session step's composed mask right now.
 *
 * While bound, the marching ants are the mask's honest display, every
 * selection tool edits it (gestures land as components and the ants resync
 * to the composed result), and Deselect/Escape end the session leaving the
 * step's mask intact. The blue wash returns to what it was meant to be:
 * hover and component preview, never a phantom editing surface.
 */
const maskSessionBound = ref(false)
/** Programmatic loads of the bound selection must not re-capture themselves. */
let syncingBoundSelection = false
const hoveredGenerativeMaskOpId = ref<string | null>(null)
/** Coverage debt by op id, published after each render (0..1). */
const maskDebtByOp = ref<Record<string, number>>({})
/** Debt below this share is feather noise, not missing pixels. */
const MASK_DEBT_ADVISORY_THRESHOLD = 0.01
const selectedRetouchMask = ref<HTMLCanvasElement | null>(null)
const hoveredRetouchMask = ref<HTMLCanvasElement | null>(null)
const selectedRetouchSource = ref<{ x: number; y: number } | null>(null)
const selectedRetouchTarget = ref<{ x: number; y: number } | null>(null)
const hoveredRetouchSource = ref<{ x: number; y: number } | null>(null)
const hoveredRetouchTarget = ref<{ x: number; y: number } | null>(null)
const selectedRetouchIsPatch = ref(false)
const hoveredRetouchIsPatch = ref(false)
const hoveredRetouchOpId = ref<string | null>(null)
const allRetouchFeedback = ref<Array<{
  mask: HTMLCanvasElement
  source?: { x: number; y: number } | null
  target?: { x: number; y: number } | null
  isPatch?: boolean
}>>([])
/**
 * Sticky per-brush settings for the Retouch family, one complete record per
 * sub-tool — a soft, low-exposure Dodge brush must not become the Heal brush
 * when the chips change. The legacy shared `retouchBrush` pref seeds the
 * repair brushes it used to describe.
 */
const RETOUCH_BRUSH_SUBS = [
  'heal', 'clone', 'patch', 'dodge', 'burn', 'sponge', 'blur', 'sharpen',
] as const
const retouchSettingsBySub = ref<Record<string, PaintEngineSettings>>(
  Object.fromEntries(RETOUCH_BRUSH_SUBS.map(id => [
    id,
    paintEngineSettings(id, initialToolPrefs.retouchEngines?.[id]
      ?? (id === 'heal' || id === 'clone' || id === 'patch'
        ? { brush: initialToolPrefs.retouchBrush }
        : undefined)),
  ])),
)

let retouchPrefsTimer: ReturnType<typeof setTimeout> | null = null

function persistRetouchSettings() {
  if (retouchPrefsTimer) clearTimeout(retouchPrefsTimer)
  retouchPrefsTimer = null
  writeToolPrefs({ retouchEngines: retouchSettingsBySub.value })
}

const activeRetouchSub = computed(() =>
  family.value === 'retouch' && sub.value && sub.value in retouchSettingsBySub.value
    ? sub.value
    : 'heal',
)
const activeRetouchSettings = computed(() =>
  retouchSettingsBySub.value[activeRetouchSub.value]
  ?? paintEngineSettings(activeRetouchSub.value),
)

function updateActiveRetouchSettings(patch: Partial<PaintEngineSettings>) {
  const subId = activeRetouchSub.value
  retouchSettingsBySub.value = {
    ...retouchSettingsBySub.value,
    [subId]: paintEngineSettings(subId, {
      ...activeRetouchSettings.value,
      ...patch,
    }),
  }
  if (retouchPrefsTimer) clearTimeout(retouchPrefsTimer)
  retouchPrefsTimer = setTimeout(persistRetouchSettings, 150)
}

const retouchBrush = computed<BrushSettings>({
  get: () => activeRetouchSettings.value.brush,
  set: value => updateActiveRetouchSettings({ brush: value }),
})
const retouchExposure = computed({
  get: () => activeRetouchSettings.value.exposure,
  set: value => updateActiveRetouchSettings({ exposure: value }),
})
const retouchRange = computed<PaintRange>({
  get: () => activeRetouchSettings.value.range,
  set: value => updateActiveRetouchSettings({ range: value }),
})
const retouchStrength = computed({
  get: () => activeRetouchSettings.value.strength,
  set: value => updateActiveRetouchSettings({ strength: value }),
})
const retouchSaturate = computed({
  get: () => activeRetouchSettings.value.saturate,
  set: value => updateActiveRetouchSettings({ saturate: value }),
})

/** Retouch location feedback may be dismissed; a live selection may not. */
const selectedRetouchFeedbackVisible = ref(false)
function dismissCanvasFeedback() {
  selectedRetouchFeedbackVisible.value = false
  disarmSelect()
}

function onViewportMatteClick(event: MouseEvent) {
  if (event.button !== 0) return
  if (annotateRef.value?.consumeCompletedGestureClick()) return
  // Empty matte means "nothing here". Give the click to the most visible
  // thing first: an existing pixel selection is deselected, without also
  // changing the selection tool the person deliberately chose. A second
  // empty-matte click, once there is no selection, releases that tool.
  selectedRetouchFeedbackVisible.value = false
  const action = selectionMatteAction(!!selection.value, !!armedSelectTool.value)
  if (action === 'clear-selection') clearSelection()
  else if (action === 'disarm-tool') disarmSelect()
  annotateRef.value?.clearSelection()
}

/**
 * Object Select owns the whole workspace, not only the image rectangle.
 *
 * Starting on the matte hands the same normalized (possibly out-of-bounds)
 * point to the annotation gesture. The overlay clips the marquee visually to
 * the image, while hit-testing counts every in-image shape the drag crosses.
 */
function onViewportMatteMouseDown(event: MouseEvent) {
  if (event.button !== 0 || spacePanHeld.value || annotateTool.value !== 'select') return
  annotateRef.value?.startMarqueeSelection(event)
}

// Paint
const paintRef = ref<InstanceType<typeof StackPaintCanvas> | null>(null)
const paintOpId = ref<string | null>(null)
/** Existing pixels must be loaded before this layer can accept another stroke. */
const paintLayerReady = ref(true)
/** Invalidates a layer decode when selection, mode, or document changes first. */
let paintLayerLoadRevision = 0
const paintEngineId = ref(
  rememberedIfValid(
    initialToolPrefs.paintEngineId,
    id => PAINT_ENGINES.some(engine => engine.id === id && !engine.pending),
  ) ?? 'paint',
)
const paintFillEngineId = ref<'fill' | 'gradient'>(
  paintEngineId.value === 'gradient'
    ? 'gradient'
    : initialToolPrefs.paintFillEngineId === 'gradient'
      ? 'gradient'
      : 'fill',
)
const paintSettingsByEngine = ref<Record<string, PaintEngineSettings>>(
  Object.fromEntries(PAINT_ENGINES.map(engine => [
    engine.id,
    paintEngineSettings(engine.id, initialToolPrefs.paintEngines?.[engine.id]),
  ])),
)

const activePaintSettings = computed(() =>
  paintSettingsByEngine.value[paintEngineId.value]
  ?? paintEngineSettings(paintEngineId.value),
)

let paintPrefsTimer: ReturnType<typeof setTimeout> | null = null

function persistPaintSettings() {
  if (paintPrefsTimer) clearTimeout(paintPrefsTimer)
  paintPrefsTimer = null
  writeToolPrefs({ paintEngines: paintSettingsByEngine.value })
}

function updateActivePaintSettings(patch: Partial<PaintEngineSettings>) {
  const engineId = paintEngineId.value
  paintSettingsByEngine.value = {
    ...paintSettingsByEngine.value,
    [engineId]: paintEngineSettings(engineId, {
      ...activePaintSettings.value,
      ...patch,
    }),
  }
  if (paintPrefsTimer) clearTimeout(paintPrefsTimer)
  paintPrefsTimer = setTimeout(persistPaintSettings, 150)
}

// Writable aliases keep the subbar and gesture surface simple while the actual
// values live in an independent, persisted record for every engine.
const paintBrush = computed<BrushSettings>({
  get: () => activePaintSettings.value.brush,
  set: value => updateActivePaintSettings({ brush: value }),
})
const paintColorRgb = computed({
  get: () => activePaintSettings.value.color,
  set: value => updateActivePaintSettings({ color: value }),
})
const paintGradient = computed<GradientPaint>({
  get: () => activePaintSettings.value.gradient,
  set: value => updateActivePaintSettings({ gradient: value }),
})
const paintGradientType = computed<PaintGradientType>({
  get: () => activePaintSettings.value.gradientType,
  set: value => updateActivePaintSettings({ gradientType: value }),
})
const paintGradientReverse = computed<boolean>({
  get: () => activePaintSettings.value.gradientReverse,
  set: value => updateActivePaintSettings({ gradientReverse: value }),
})

// Annotate
const annotateRef = ref<InstanceType<typeof StackAnnotateCanvas> | null>(null)
const textStyle = ref<TextStyleId>('pill')
/**
 * The paint the next annotation starts with — a flat color or a gradient,
 * since a gradient is a color here and not a mode the shape is put into.
 */
const annotatePaint = ref<Paint>({ r: 255, g: 255, b: 255, a: 1 })
const selectedShapeId = ref<string | null>(null)
// The rest of the latent shape's initial conditions, sticky across shapes:
// stroke weight, fill, the universal effect and opacity all live in the
// sub-toolbar so a neon circle is one gesture, not draw-then-fix-three-knobs.
const annotateStrokeWidth = ref(8)
const annotateFillColor = ref<Paint | null>(null)
const annotateShapeEffect = ref<'none' | 'neon'>('none')
const annotateOpacity = ref(1)

/**
 * The sub-bar names a family of tools; the ported gesture code wants the
 * specific one. Shape and Text carry a second choice, so the mapping is not
 * one-to-one.
 */
const annotateTool = computed<AnnotateTool>(() => {
  // Outside the Annotate family the canvas only ever object-selects (the idle
  // state / island pointer); inside it, `sub = null` is select — where every
  // drawing tool lands after its one-shot creation.
  if (family.value !== 'annotate' || !sub.value) return 'select'
  if (sub.value === 'redact') return 'redact'
  if (sub.value === 'text') return 'text'
  if (sub.value === 'draw') return 'sharpie'
  if (sub.value === 'arrow') return 'arrow'
  if (sub.value === 'rectangle' || sub.value === 'ellipse' || sub.value === 'line') {
    return sub.value as AnnotateTool
  }
  return 'arrow'
})

/**
 * Object select is the workspace's IDLE state: with no family open and no
 * selection tool armed, the things you can click ARE the annotations, so
 * clicking one should just select it — no Annotate → Select → thing dance.
 * The island's pointer lights up to say so.
 */
const objectSelectActive = computed(() =>
  family.value === null && !armedSelectTool.value
)

/** The vector overlay currently owns annotation pixels and interactions. */
const annotationOverlayActive = computed(() =>
  family.value === 'annotate' || objectSelectActive.value
)

/** The island's pointer: leave whatever mode is open. Idle IS object select. */
function activatePointer() {
  disarmSelect()
  leaveMode()
}

/** The active Annotate step's shapes, or nothing until one exists. */
/**
 * One annotation, one step.
 *
 * An arrow and a text box are two things a user made and will want to reach
 * separately — to hide one, reorder it, or delete it without touching the
 * other. Accumulating them into a single 'Annotate' row made the stack lie
 * about how many edits there were and left no way to address any of them.
 * The rows are named for what they are: Rectangle, Text, Arrow.
 */
const annotateOps = computed(() =>
  (stack.doc.value?.edits || []).filter(op => (op as any).exec?.kind === 'annotate')
)

/**
 * The annotate ops the overlay is responsible for: the ENABLED ones.
 *
 * A hidden annotation is hidden everywhere. The overlay drawing it anyway left
 * a hidden shape on screen at full strength while the composite correctly
 * dropped it — so hiding a shape appeared to only weaken it (one of the two
 * copies went away) instead of removing it.
 */
const visibleAnnotateOps = computed(() => annotateOps.value.filter(op => op.enabled))

/** Permanent document shapes projected into the current head for interaction. */
const annotateShapes = computed<Shape[]>(() => {
  const doc = stack.doc.value
  if (!doc) return []
  const head = geometryBelow(doc, doc.edits.length)
  return visibleAnnotateOps.value.flatMap(op => {
    const anyOp = op as any
    const shapes = (anyOp.params?.shapes ?? []) as Shape[]
    if (!anyOp.shapes_in_document) return shapes
    return transformShapes(
      shapes,
      head.matrix,
      doc.canvas.width,
      doc.canvas.height,
      head.width,
      head.height,
    ) as Shape[]
  })
})

function opIdForShape(shapeId: string): string | null {
  const op = annotateOps.value.find(
    o => ((o as any).params?.shapes ?? []).some((s: Shape) => s.id === shapeId)
  )
  return op?.id ?? null
}

/** Rows read as what the user drew, not as the family they drew it in. */
function shapeLabel(shape: Shape): string {
  const type = shape.type === 'curved-arrow' ? 'arrow'
    : shape.type === 'path' ? 'drawing'
    : shape.type
  return type.charAt(0).toUpperCase() + type.slice(1)
}

// -- compositing -----------------------------------------------------------

const displayCanvas = ref<HTMLCanvasElement | null>(null)
const composite = ref<HTMLCanvasElement | null>(null)
const toneCurveHistogram = computed(() =>
  composite.value ? toneCurveHistogramFromCanvas(composite.value) : undefined,
)
const rendering = ref(false)
const viewportSize = ref({ width: 0, height: 0 })
const viewport = ref<HTMLElement | null>(null)

/** The image as of each step, keyed by op id — the Edits list's row previews. */
const stepPreviews = ref<Record<string, string>>({})

// Canvas snapshots can live here too. Paint rewrites a stable raster filename,
// and the immutable in-memory snapshot is a stronger source for the revision
// that just landed than asking WebKit to re-read an overwritten PNG.
const payloadCache = new Map<string, CanvasImageSource>()

function invalidatePayload(ref: string) {
  for (const key of payloadCache.keys()) {
    if (key.startsWith(`${ref}@`)) payloadCache.delete(key)
  }
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error(`failed to load ${url}`))
    img.src = url
  })
}

async function loadStackPayload(ref: string, revision = 0) {
  const key = `${ref}@${revision}`
  const cached = payloadCache.get(key)
  if (cached) return cached
  const img = await loadImage(stack.payloadUrl(ref, revision))
  payloadCache.set(key, img)
  return img
}

async function loadStackBase() {
  // A flattened document supplies its own base pixels; everything else reads
  // the revision recorded by the recipe. The Asset's current revision may be
  // a flattened Save of this same stack and must never be substituted here.
  const ref = stack.doc.value?.base.payload_ref
  if (ref) return loadImage(stack.payloadUrl(ref))
  const mediaId = stack.doc.value?.base.media_id
  if (!mediaId) throw new Error('The image stack has no base media.')
  return loadImage(getMediaFileUrl(Number(mediaId)))
}

const compositor = new StackCompositor({
  loadPayload: loadStackPayload,
  loadBase: loadStackBase,
  onStepPreview: (opId, preview) => {
    // Only a render of the WHOLE document describes the steps truthfully; a
    // stage render with the annotate overlay's shapes held out would file
    // previews that are missing them.
    if (!emitPreviews) return
    if (bufferedStepPreviews) {
      bufferedStepPreviews[opId] = preview
      return
    }
    stepPreviews.value = { ...stepPreviews.value, [opId]: preview }
  },
})

/** Small, throwaway composites used only while a Retouch property is dragged. */
const retouchPreviewCompositor = new StackCompositor({
  loadPayload: loadStackPayload,
  loadBase: loadStackBase,
})

/**
 * Slider drags never replay the document. The pixels already on screen become
 * the preview baseline and a viewport-sized shader applies only the parameter
 * delta. Pointer-up performs the one authoritative source-resolution render.
 */
const liveAdjustPreview = new LiveAdjustPreview()
let liveAdjustOwner: string | null = null
let liveAdjustBase: AdjustmentValues = {}
let liveAdjustCurrent: AdjustmentValues = {}
let liveAdjustMask: HTMLCanvasElement | null = null
let liveAdjustFrame: number | null = null
let liveAdjustSetupRevision = 0
let liveAdjustReady = false

function cancelLiveAdjustPreview() {
  liveAdjustSetupRevision++
  if (liveAdjustFrame !== null) {
    cancelAnimationFrame(liveAdjustFrame)
    liveAdjustFrame = null
  }
  liveAdjustOwner = null
  liveAdjustBase = {}
  liveAdjustCurrent = {}
  liveAdjustMask = null
  liveAdjustReady = false
}

function drawLiveAdjustPreview() {
  liveAdjustFrame = null
  if (!liveAdjustReady) return
  const preview = liveAdjustPreview.render(liveAdjustCurrent)
  const target = displayCanvas.value
  if (!preview || !target) return
  target.width = preview.width
  target.height = preview.height
  const context = target.getContext('2d')!
  context.clearRect(0, 0, target.width, target.height)
  context.drawImage(preview, 0, 0)
}

function queueLiveAdjustFrame() {
  if (liveAdjustFrame !== null || !liveAdjustReady) return
  liveAdjustFrame = requestAnimationFrame(drawLiveAdjustPreview)
}

async function previewAdjustment(
  owner: string,
  base: AdjustmentValues,
  current: AdjustmentValues,
  options: {
    mask?: HTMLCanvasElement | null | Promise<HTMLCanvasElement | null>
    maskStrength?: number
  } = {},
) {
  liveAdjustCurrent = { ...current }
  if (liveAdjustOwner === owner && liveAdjustReady) {
    queueLiveAdjustFrame()
    return
  }
  if (liveAdjustOwner === owner) return

  cancelLiveAdjustPreview()
  liveAdjustOwner = owner
  liveAdjustBase = { ...base }
  liveAdjustCurrent = { ...current }
  const source = composite.value
  if (!source) return
  const revision = ++liveAdjustSetupRevision
  liveAdjustMask = options.mask ? await options.mask : null
  if (revision !== liveAdjustSetupRevision || liveAdjustOwner !== owner) return
  liveAdjustReady = liveAdjustPreview.begin(source, liveAdjustBase, {
    mask: liveAdjustMask,
    width: displayBox.value.width,
    height: displayBox.value.height,
    maskStrength: options.maskStrength,
  })
  queueLiveAdjustFrame()
}

/**
 * Restore the exact materialized head on a cold open. The recipe remains
 * authoritative; a missing hash-addressed PNG is simply a cache miss.
 */
async function restoreCachedHead(): Promise<boolean> {
  const doc = stack.doc.value
  if (!doc) return false
  // "Original image" is a trust boundary. When no edit contributes pixels,
  // always decode the immutable base; never let a persisted projection speak
  // for it, even if a cache file happens to have the same historical key.
  if (!doc.edits.some(op => op.enabled)) return false
  const hash = headCacheHash(doc)
  try {
    const image = await loadImage(stack.payloadUrl(headCacheImageRef(doc), hash))
    const restored = document.createElement('canvas')
    restored.width = image.naturalWidth
    restored.height = image.naturalHeight
    restored.getContext('2d')!.drawImage(image, 0, 0)
    compositor.prime(hash, restored, doc.edits.map(op => op.id))
    composite.value = restored
    publishEditorLivePreview(props.assetId, restored)
    return true
  } catch {
    return false
  }
}

let headCacheTimer: ReturnType<typeof setTimeout> | null = null
let headCacheRevision = 0
let headCacheWrite = Promise.resolve()

/**
 * Persist only after the person pauses. Lossless PNG encoding is deliberately
 * kept out of live slider and brush frames.
 */
function scheduleHeadCache(documentSnapshot: any, canvas: HTMLCanvasElement) {
  const revision = ++headCacheRevision
  const hash = headCacheHash(documentSnapshot)
  const name = `head-${hash}.png`
  if (headCacheTimer) clearTimeout(headCacheTimer)
  headCacheTimer = setTimeout(() => {
    headCacheTimer = null
    headCacheWrite = headCacheWrite.then(async () => {
      if (revision !== headCacheRevision || !stack.doc.value) return
      if (headCacheHash(stack.doc.value) !== hash) return
      await stack.uploadPayload(name, await canvasToBlob(canvas), 'cache')
    }).catch(cacheError => {
      // Cache loss changes only the next open's speed, never the document.
      console.warn('[imageStack] could not persist head cache', cacheError)
    })
  }, 1500)
}

/** Set only while rendering the full document — see onStepPreview. */
let emitPreviews = true
/** One reactive update per replay, not one per recomputed stack stage. */
let bufferedStepPreviews: Record<string, string> | null = null

type RenderOptions = {
  /**
   * Debounce destructive bursts while the rows update optimistically. Normal
   * renders use the next animation frame.
   */
  settleMs?: number
}

const RENDER_BURST_SETTLE_MS = 140
let renderRequested = false
let renderRunning = false
let renderRequestRevision = 0
let renderFrame: number | null = null
let renderTimer: ReturnType<typeof setTimeout> | null = null
let renderCycle: Promise<void> | null = null
let resolveRenderCycle: (() => void) | null = null

function ensureRenderCycle(): Promise<void> {
  if (!renderCycle) {
    renderCycle = new Promise(resolve => {
      resolveRenderCycle = resolve
    })
  }
  return renderCycle
}

function clearRenderSchedule() {
  if (renderFrame !== null) {
    cancelAnimationFrame(renderFrame)
    renderFrame = null
  }
  if (renderTimer) {
    clearTimeout(renderTimer)
    renderTimer = null
  }
}

function abandonScheduledRender() {
  clearRenderSchedule()
  renderRequested = false
  if (renderRunning) return
  const resolve = resolveRenderCycle
  resolveRenderCycle = null
  renderCycle = null
  resolve?.()
}

function scheduleRenderDrain(settleMs: number) {
  if (renderRunning) return

  if (settleMs > 0) {
    // An already scheduled animation-frame render is more urgent; do not turn
    // it into a delayed one. Repeated settled requests reset only each other.
    if (renderFrame !== null) return
    if (renderTimer) clearTimeout(renderTimer)
    renderTimer = setTimeout(() => {
      renderTimer = null
      void drainRenderQueue()
    }, settleMs)
    return
  }

  if (renderTimer) {
    clearTimeout(renderTimer)
    renderTimer = null
  }
  if (renderFrame !== null) return
  renderFrame = requestAnimationFrame(() => {
    renderFrame = null
    void drainRenderQueue()
  })
}

/**
 * The one doorway into full document rendering.
 *
 * Requests are coalesced, compositor work is serialized, and a render that
 * became stale while awaiting payloads may warm caches but cannot repaint the
 * UI over a newer document. Callers awaiting render wait until the queue has
 * reached the latest requested state.
 */
function render(options: RenderOptions = {}): Promise<void> {
  renderRequested = true
  renderRequestRevision++
  const cycle = ensureRenderCycle()
  scheduleRenderDrain(options.settleMs ?? 0)
  return cycle
}

/**
 * What the STAGE composites: the document, minus whatever a live overlay is
 * already drawing.
 *
 * While the annotation overlay is mounted, its canvas draws the enabled
 * annotations itself so they can be dragged, selected and restyled. This
 * includes the workspace's idle object-select state. Compositing them as
 * well drew every annotation twice — invisible for an opaque stroke, but a
 * neon glow compounds, so what you saw while editing was stronger than what
 * Save would write. The tool owns the layer it is editing; the stack renders
 * everything else. Save always flattens the real document (see save()).
 */
const displayDoc = computed(() => {
  const doc = stack.doc.value
  if (!doc || !annotationOverlayActive.value) return doc
  const drawnByOverlay = new Set(visibleAnnotateOps.value.map(op => op.id))
  if (!drawnByOverlay.size) return doc
  return { ...doc, edits: doc.edits.filter(op => !drawnByOverlay.has(op.id)) }
})

/** Drop previews for steps that no longer exist, so removals don't accumulate. */
function prunePreviews() {
  const live = new Set((stack.doc.value?.edits || []).map(op => op.id))
  const kept: Record<string, string> = {}
  for (const [opId, preview] of Object.entries(stepPreviews.value)) {
    if (live.has(opId)) kept[opId] = preview
  }
  stepPreviews.value = kept
}

async function renderSnapshot(requestRevision: number) {
  // Mutations can request a render before open() has assigned the base. The
  // later open path requests again once both halves are ready.
  if (!stack.doc.value || !baseInfo.value) return
  const liveDoc = displayDoc.value!
  const whole = liveDoc === stack.doc.value
  // The compositor awaits payloads. Snapshot the plain recipe so a mutation
  // arriving during that await cannot change the array underneath its loop.
  const doc = JSON.parse(JSON.stringify(liveDoc))
  bufferedStepPreviews = whole ? {} : null
  try {
    emitPreviews = whole
    const rendered = await compositor.render(doc)
    if (requestRevision !== renderRequestRevision) return
    composite.value = rendered
    if (whole) publishEditorLivePreview(props.assetId, rendered)
    if (whole && bufferedStepPreviews) {
      stepPreviews.value = { ...stepPreviews.value, ...bufferedStepPreviews }
    }
    if (whole) prunePreviews()
    if (
      whole
      && doc.edits.some((op: any) => op.enabled)
      && !compositor.failedOpIds.size
    ) {
      scheduleHeadCache(doc, rendered)
    }
    // Coverage debt is measured while the compositor recomputes generative
    // ops; publish the fresh readings for the rows' amber advisories.
    maskDebtByOp.value = Object.fromEntries(compositor.maskDebt)
    // The selection lives at the head, so whatever this render did to the
    // geometry under it (crop edits, toggles, an expand's new frame) is
    // carried into it here — the one funnel every such change passes through.
    syncSelectionGeometry()
    paint()
    samplePalette()
    if (family.value === 'levels' && looksOpen.value) void renderLookThumbs()
  } catch (err: any) {
    error.value = err?.message || 'Could not render the composite.'
  } finally {
    bufferedStepPreviews = null
    emitPreviews = true
  }
}

async function drainRenderQueue() {
  if (renderRunning) return
  clearRenderSchedule()
  renderRunning = true
  rendering.value = true
  try {
    while (renderRequested) {
      renderRequested = false
      const requestRevision = renderRequestRevision
      await renderSnapshot(requestRevision)
    }
  } finally {
    renderRunning = false
    rendering.value = false
    const resolve = resolveRenderCycle
    resolveRenderCycle = null
    renderCycle = null
    resolve?.()
    // A request cannot normally interleave with the synchronous cleanup above,
    // but keep the invariant explicit for future awaited teardown work.
    if (renderRequested) {
      ensureRenderCycle()
      scheduleRenderDrain(0)
    }
  }
}

/** Fit the composite into the viewport; the mask overlay uses the same box. */
/**
 * Fit the COMPOSITE into the viewport — not the document's base canvas.
 *
 * Geometry ops change the frame: a 16:9 base cropped square composites to a
 * square canvas. Fitting the base instead stretched that square back out to
 * 16:9, and because every overlay takes its size from this box, Select, Paint
 * and Annotate all drew into the same wrong aspect and their coordinates were
 * skewed with it.
 */
const displayBox = computed(() => {
  const doc = stack.doc.value
  const vp = viewportSize.value
  if (!doc || !vp.width || !vp.height) return { width: 0, height: 0 }
  const frame = composite.value ?? doc.canvas
  const scale = Math.min(vp.width / frame.width, vp.height / frame.height, 1)
  return {
    width: Math.round(frame.width * scale),
    height: Math.round(frame.height * scale),
  }
})

// -- viewport navigation ---------------------------------------------------

/**
 * Zoom is relative to the fitted view: 100% means "fit/actual size, whichever
 * is smaller" and the user can zoom farther out to make working room around
 * floating controls. The image and every interactive overlay share the zoomed
 * display box, so their coordinate systems stay locked; pan is the one CSS
 * transform shared by the whole stage.
 */
const FIT_VIEW_ZOOM = 1
const MIN_VIEW_ZOOM = 0.5
const MAX_VIEW_ZOOM = 10
const viewZoom = ref(1)
const viewPan = ref({ x: 0, y: 0 })
const viewPanning = ref(false)
const spacePanHeld = ref(false)
let viewPanStart = { pointerX: 0, pointerY: 0 }

/**
 * The stage element a pan moves, so a drag can write its transform directly.
 *
 * `viewPan` is a ref on a view this large: changing it re-runs this component's
 * whole render and diff. At pointer rates that saturates the main thread, and
 * the moves that pile up behind it land together — the drag reads as dead, then
 * as a jump. A pan touches nothing but one transform, so during the gesture it
 * bypasses reactivity entirely and the ref is written once, at the end.
 */
const stageTransform = ref<HTMLElement | null>(null)
/** Authoritative pan while a gesture owns it; `viewPan` is stale until commit. */
let livePan = { x: 0, y: 0 }
let panFrame = 0

function panTransform(pan: { x: number; y: number }): string {
  // A static -50% plus a 3D translate: the offset stays on the compositor
  // instead of resolving a calc() against the stage's size on every frame.
  return `translate(-50%, -50%) translate3d(${pan.x}px, ${pan.y}px, 0)`
}

function scheduleLivePan() {
  if (panFrame) return
  panFrame = requestAnimationFrame(() => {
    panFrame = 0
    const element = stageTransform.value
    if (element) element.style.transform = panTransform(livePan)
  })
}

function beginLivePan() {
  livePan = { ...viewPan.value }
  const element = stageTransform.value
  if (element) element.style.willChange = 'transform'
}

/**
 * Pan by the movement since the LAST event, re-anchoring on every one.
 *
 * Panning from the gesture's origin instead lets the raw offset run away past
 * whatever the clamp allows, while the applied pan sits pinned at the edge.
 * Reversing then does nothing until the drag has retraced the whole overshoot
 * — a dead zone as long as however far past the edge you pushed, ended by an
 * abrupt jump when the raw value finally re-enters range. It bites on the axis
 * with the least room: on a wide viewport the vertical range is only the
 * overscroll slack, so vertical pans stick while horizontal ones feel fine.
 */
function applyViewPanDeltaValue(delta: { x: number; y: number }) {
  livePan = panForDragDelta(
    livePan,
    delta,
    viewZoom.value,
    viewContentSize.value,
    viewportSize.value,
  )
  scheduleLivePan()
}

function applyViewPanDelta(event: PointerEvent) {
  applyViewPanDeltaValue({
    x: event.clientX - viewPanStart.pointerX,
    y: event.clientY - viewPanStart.pointerY,
  })
  viewPanStart.pointerX = event.clientX
  viewPanStart.pointerY = event.clientY
}

/**
 * A render triggered by anything else mid-drag would write the pre-drag pan
 * back over the stage's transform, snapping it and undoing the gesture until
 * the next pointer move. The live pan is authoritative while it owns the stage.
 */
onUpdated(() => {
  // Both pan gestures raise `viewPanning` for the duration of the drag.
  if (!viewPanning.value) return
  const element = stageTransform.value
  if (element) element.style.transform = panTransform(livePan)
})

/** Hand the gesture's result back to reactive state in a single write. */
function commitLivePan() {
  if (panFrame) {
    cancelAnimationFrame(panFrame)
    panFrame = 0
  }
  const element = stageTransform.value
  if (element) element.style.willChange = ''
  viewPan.value = { ...livePan }
}

const viewZoomLabel = computed(() => `${Math.round(viewZoom.value * 100)}%`)
const viewTransformStyle = computed(() => ({ transform: panTransform(viewPan.value) }))
const zoomedDisplayBox = computed(() => ({
  width: Math.round(displayBox.value.width * viewZoom.value),
  height: Math.round(displayBox.value.height * viewZoom.value),
}))

/** Crop owns a viewport-sized stage; every other family owns the fitted box. */
const viewContentSize = computed(() =>
  family.value === 'crop' ? viewportSize.value : displayBox.value
)

function clampViewPan() {
  viewPan.value = clampViewportPan(
    viewPan.value,
    viewZoom.value,
    viewContentSize.value,
    viewportSize.value,
  )
}

function resetView() {
  viewZoom.value = FIT_VIEW_ZOOM
  viewPan.value = { x: 0, y: 0 }
}

function setViewZoom(nextZoom: number, anchor?: { x: number; y: number }) {
  const clamped = Math.max(MIN_VIEW_ZOOM, Math.min(MAX_VIEW_ZOOM, nextZoom))
  if (clamped === viewZoom.value) return
  if (anchor) {
    viewPan.value = panForZoomAtPoint(viewPan.value, viewZoom.value, clamped, anchor)
  }
  viewZoom.value = clamped
  clampViewPan()
}

function zoomViewBy(direction: 1 | -1) {
  const factor = direction > 0 ? 1.25 : 1 / 1.25
  setViewZoom(viewZoom.value * factor)
}

function onViewportWheel(event: WheelEvent) {
  if (nativeTabletPanActive) return
  const element = viewport.value
  if (!element) return

  // Lightroom's contract is explicit rather than device-detected: plain
  // wheel/two-finger input pans, while pinch or modifier+wheel zooms.
  if (!isZoomWheelGesture(event)) {
    let delta = wheelPanDelta(
      { x: event.deltaX, y: event.deltaY },
      event.deltaMode,
      { width: element.clientWidth, height: element.clientHeight },
      event.shiftKey,
    )
    if (tabletWheelPanActive()) delta = stabilizeWacomWheelDelta(delta)
    viewPan.value = panForWheelDelta(viewPan.value, delta)
    clampViewPan()
    return
  }

  if (event.deltaY === 0) return
  const rect = element.getBoundingClientRect()
  const anchor = {
    x: event.clientX - rect.left - rect.width / 2,
    y: event.clientY - rect.top - rect.height / 2,
  }
  const factor = event.deltaY > 0 ? 0.9 : 1.1
  setViewZoom(viewZoom.value * factor, anchor)
}

/**
 * Left drag belongs to the active image tool. Space+left-drag is handled as a
 * pointer gesture here; middle mouse uses window-level pointer events below so
 * no child canvas or its pointer capture can steal it.
 */
function startViewPan(event: PointerEvent) {
  const isSpaceDrag = event.button === 0 && spacePanHeld.value
  if (!isSpaceDrag) return

  viewPanning.value = true
  viewPanStart = { pointerX: event.clientX, pointerY: event.clientY }
  beginLivePan()
  viewport.value?.setPointerCapture(event.pointerId)
  event.preventDefault()
  event.stopPropagation()
}

let middleMousePointerId: number | null = null
let viewportPanButtonMask = 4
let nativeTabletPanActive = false
let stopTabletPan: (() => void) | null = null

function onNativeTabletPan(sample: NativeTabletPanSample) {
  if (sample.phase === 'down') {
    if (nativeTabletPanActive) return
    const element = viewport.value
    if (!element?.matches(':hover')) return
    nativeTabletPanActive = true
    paintRef.value?.commitStroke()
    retouchRef.value?.commitStroke()
    if (middleMousePointerId === null) {
      viewPanning.value = true
      beginLivePan()
    }
    return
  }
  if (!nativeTabletPanActive) return
  if (sample.phase === 'up') {
    nativeTabletPanActive = false
    if (middleMousePointerId !== null) {
      endMiddleMousePan()
    } else {
      viewPanning.value = false
      commitLivePan()
    }
    return
  }
  applyViewPanDeltaValue({
    x: sample.deltaX,
    y: sample.deltaY,
  })
}

function startMiddleMousePan(event: PointerEvent) {
  const element = viewport.value
  const action = editorBarrelAction(event, /Linux/i.test(navigator.userAgent))
  if (
    action !== 'pan'
    || !element?.contains(event.target as Node)
  ) return
  // Real middle mouse always pans. Linux pen buttons are normalized by their
  // physical assignment here; macOS native tablet points retain their own pan.
  paintRef.value?.commitStroke()
  retouchRef.value?.commitStroke()

  middleMousePointerId = event.pointerId
  viewportPanButtonMask = heldButtonMask(event.button)
  viewPanning.value = true
  viewPanStart = { pointerX: event.clientX, pointerY: event.clientY }
  beginLivePan()
  event.preventDefault()
  event.stopPropagation()
}

function moveMiddleMousePan(event: PointerEvent) {
  if (event.pointerId !== middleMousePointerId) return
  if (nativeTabletPanActive) {
    // The native AppKit stream is complete; consuming both it and WebKit's
    // synthetic movement would double-count whichever sparse DOM samples land.
    event.preventDefault()
    event.stopPropagation()
    return
  }
  // Mouseup can be lost when the window itself loses capture. `buttons` is the
  // authoritative held-state on every later move.
  if ((event.buttons & viewportPanButtonMask) === 0) {
    endMiddleMousePan(event)
    return
  }
  applyViewPanDelta(event)
  event.preventDefault()
  event.stopPropagation()
}

function endMiddleMousePan(event?: PointerEvent) {
  if (event && event.pointerId !== middleMousePointerId) return
  if (middleMousePointerId === null) return
  middleMousePointerId = null
  nativeTabletPanActive = false
  viewPanning.value = false
  commitLivePan()
  event?.preventDefault()
  event?.stopPropagation()
}

function moveViewPan(event: PointerEvent) {
  if (!viewPanning.value) return
  applyViewPanDelta(event)
  event.preventDefault()
  event.stopPropagation()
}

function endViewPan(event: PointerEvent) {
  if (!viewPanning.value) return
  if (viewport.value?.hasPointerCapture(event.pointerId)) {
    viewport.value.releasePointerCapture(event.pointerId)
  }
  viewPanning.value = false
  commitLivePan()
  event.preventDefault()
  event.stopPropagation()
}

// -- pen quick brush picker ------------------------------------------------

/**
 * A stylus side button mapped to Back/Forward arrives as a pointer event with
 * button 3/4 — macOS synthesizes a plain mouse press at the hover position,
 * so it works without the pen touching down. It toggles the same brush picker
 * the toolbar chip opens, popped beside the cursor.
 */
const brushHud = ref<{ x: number; y: number } | null>(null)

/** Which brush the picker edits — null when the active family has none. */
const brushHudTarget = computed(() => {
  if (
    family.value === 'paint'
    && (paintEngineId.value === 'paint' || paintEngineId.value === 'erase')
  ) return 'paint' as const
  if (family.value === 'retouch' && sub.value && sub.value !== 'patch') return 'retouch' as const
  return null
})

// Tool changes invalidate the popup's subject; close instead of retargeting.
watch(brushHudTarget, target => {
  if (!target) brushHud.value = null
})

function onBrushHudPointerDown(event: PointerEvent) {
  const action = editorBarrelAction(event, /Linux/i.test(navigator.userAgent))
  if (action !== 'brush-popup') return
  event.preventDefault()
  event.stopPropagation()
  if (brushHud.value) {
    brushHud.value = null
    return
  }
  if (!brushHudTarget.value) return
  if (!viewport.value?.contains(event.target as Node)) return
  brushHud.value = { x: event.clientX, y: event.clientY }
}

/** Never let a claimed popup button fall through to browser navigation/scroll. */
function swallowBrushHudButton(event: PointerEvent) {
  const action = editorBarrelAction(event, /Linux/i.test(navigator.userAgent))
  if (action === 'brush-popup') {
    event.preventDefault()
    event.stopPropagation()
  }
}

function addBrushHudListeners() {
  window.addEventListener('pointerdown', onBrushHudPointerDown, true)
  window.addEventListener('pointerup', swallowBrushHudButton, true)
  window.addEventListener('auxclick', swallowBrushHudButton, true)
}

function removeBrushHudListeners() {
  window.removeEventListener('pointerdown', onBrushHudPointerDown, true)
  window.removeEventListener('pointerup', swallowBrushHudButton, true)
  window.removeEventListener('auxclick', swallowBrushHudButton, true)
}

function paint() {
  const target = displayCanvas.value
  const source = composite.value
  if (!target || !source) return
  // Assigning either canvas dimension reallocates and clears its full backing
  // store. Most renders keep the same geometry, so only resize when a crop or
  // expand actually changed it.
  if (target.width !== source.width || target.height !== source.height) {
    target.width = source.width
    target.height = source.height
  }
  const ctx = target.getContext('2d')!
  ctx.clearRect(0, 0, target.width, target.height)
  ctx.drawImage(source, 0, 0, target.width, target.height)
}

// -- candidates ------------------------------------------------------------

const candidates = useStackCandidates({
  documentId: () => stack.documentId.value,
  uploadPayload: stack.uploadPayload,
  attachCandidates: stack.attachCandidates,
  mediaFileUrl: (mediaId: number) => getMediaFileUrl(mediaId),
  onFirstCandidate: (opId, candidate) => {
    // A staged op with no pick contributes nothing, so the first arrival
    // auto-applies. Switching to another candidate afterwards is free.
    //
    // A RESAMPLED op always has a pick — that is what makes it a resample — so
    // the arrival replaces it. Without this the run completes, the candidate is
    // attached, and the canvas never changes: a paid click with no effect.
    const op = stack.opById(opId) as GenerativeOp | undefined
    const resampled = resampledOpIds.value.has(opId)
    if (op && (!op.picked || resampled)) stack.pickCandidate(opId, candidate.id)
    if (resampled) {
      const next = new Set(resampledOpIds.value)
      next.delete(opId)
      resampledOpIds.value = next
    }
    void render()
  },
})

const pendingByOp = computed(() => {
  const counts: Record<string, number> = {}
  for (const job of candidates.pending.value) {
    if (job.status === 'failed') continue
    counts[job.opId] = (counts[job.opId] || 0) + 1
  }
  return counts
})

const pendingBatchesByOp = computed(() => {
  const grouped: Record<string, Array<{ batchId: string; count: number }>> = {}
  const indexes = new Map<string, number>()
  for (const job of candidates.pending.value) {
    if (job.status === 'failed') continue
    const rows = grouped[job.opId] ?? (grouped[job.opId] = [])
    const key = `${job.opId}:${job.batchId}`
    const existingIndex = indexes.get(key)
    if (existingIndex === undefined) {
      indexes.set(key, rows.length)
      rows.push({ batchId: job.batchId, count: 1 })
    } else {
      rows[existingIndex].count += 1
    }
  }
  return grouped
})

const candidateThumbs = computed(() => {
  const thumbs: Record<string, Array<{ id: string; url: string; batchId?: string }>> = {}
  for (const op of stack.ops.value) {
    const anyOp = op as any
    if (!anyOp.candidates?.length) continue
    thumbs[op.id] = anyOp.candidates
      .filter((c: any) => c.patch_ref)
      .map((c: any) => ({
        id: c.id,
        url: stack.payloadUrl(c.patch_ref),
        batchId: c.batch_id,
      }))
  }
  return thumbs
})

// -- derived stack state ----------------------------------------------------

/** Staleness is DERIVED, never stored. */
const stackState = computed(() => deriveStackState(stack.doc.value))

/** Which rows the currently hovered gesture would disturb. */
const intentOpId = ref<string | null>(null)
const preview = computed(() =>
  intentOpId.value ? blastRadius(stack.doc.value, intentOpId.value) : null
)
function previewStalenessOf(opId: string) {
  if (!preview.value) return null
  return preview.value.advisory.has(opId) ? ('advisory' as const) : null
}

/**
 * Rows the list shows, top-first. Every step is visible: nothing folds anything
 * any more, because nothing consumes anything.
 */
const visibleRows = computed(() => [...stackState.value.ops].reverse())

/** A payload whose geometry has moved it entirely off the frame. */
const outOfFrame = computed(() => {
  const doc = stack.doc.value
  const result: Record<string, boolean> = {}
  if (!doc) return result
  for (let index = 0; index < doc.edits.length; index++) {
    const op = doc.edits[index] as any
    if (!op.mask_ref && !op.raster_ref) continue
    const geometry = geometryBelow(doc, index)
    const canonical = (op.payload_to_document as Affine | undefined)
      ?? (op.payload_frame
        ? payloadToDocumentTransform(op.payload_frame) ?? undefined
        : undefined)
    const matrix = canonical
      ? multiply(geometry.matrix, canonical)
      : geometry.matrix
    result[op.id] = !intersectsFrame(
      matrix,
      op.payload_frame?.width ?? doc.canvas.width,
      op.payload_frame?.height ?? doc.canvas.height,
      geometry.width, geometry.height
    )
  }
  return result
})

// -- reorder ----------------------------------------------------------------

/**
 * Reorder is drag, and a drag must never be a guess.
 *
 * The whole gesture is expressed in GAPS, not rows: a gap `g` is the boundary
 * below edits[g] — the place the row would land. Hovering the top half of a
 * row targets the gap above it, the bottom half the gap below it, so every
 * pixel of the list belongs to exactly one landing place and the indicator
 * says which. Dropping ON a row (the old behaviour) could not express "above
 * or below", which is what made the drop feel like a coin flip.
 *
 * The list is drawn top-of-stack-first, so the gap ABOVE visible row i is
 * doc index i + 1.
 */
const dragOpId = ref<string | null>(null)
/** Gap the drop would land in, or null when there is no legal target. */
const dropGap = ref<number | null>(null)

/** The lowest visible row, whose bottom edge is the list's last gap. */
const lastVisibleIndex = computed(() =>
  visibleRows.value.length ? visibleRows.value[visibleRows.value.length - 1].index : null
)

function onDragStart(opId: string, event: DragEvent) {
  dragOpId.value = opId
  intentOpId.value = opId
  event.dataTransfer?.setData('text/plain', opId)
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}

function onListDragOver(event: DragEvent) {
  const doc = stack.doc.value
  const source = dragOpId.value
  if (!doc || !source) return

  const row = (event.target as HTMLElement | null)?.closest?.('[data-op-id]') as HTMLElement | null
  const targetOpId = row?.dataset.opId
  const index = targetOpId ? doc.edits.findIndex(op => op.id === targetOpId) : -1
  if (!row || index < 0) {
    // Over the list's padding: no landing place, so no line. A line left
    // behind from the last row would be a lie.
    dropGap.value = null
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'none'
    return
  }

  const box = row.getBoundingClientRect()
  const gap = event.clientY < box.top + box.height / 2 ? index + 1 : index

  const legal = moveTargetForGap(doc, source, gap) !== null
  dropGap.value = legal ? gap : null
  // Say so on the cursor too: a line that simply isn't there reads as "not
  // hovering anything", not as "this move is blocked".
  if (event.dataTransfer) event.dataTransfer.dropEffect = legal ? 'move' : 'none'
}

/** Leaving the list entirely clears the line; moving between rows does not. */
function onListDragLeave(event: DragEvent) {
  const to = event.relatedTarget as Node | null
  const list = event.currentTarget as HTMLElement
  if (!to || !list.contains(to)) dropGap.value = null
}

function onDragEnd() {
  dragOpId.value = null
  dropGap.value = null
  intentOpId.value = null
}

async function onDrop() {
  const doc = stack.doc.value
  const source = dragOpId.value
  const gap = dropGap.value
  onDragEnd()
  if (!doc || !source || gap === null) return

  const toIndex = moveTargetForGap(doc, source, gap)
  if (toIndex === null) return

  const before = JSON.parse(JSON.stringify(doc))
  stack.moveOp(source, toIndex)
  await afterGeometryChange(before)
  void render()
}

// -- geometry co-transform ---------------------------------------------------

/**
 * Geometry changes never rewrite spatial payloads. Their permanent document
 * anchors make the compositor's projection authoritative.
 *
 * The only work left here is a one-time conversion of legacy annotation
 * vectors, which predate document-space storage.
 */
async function afterGeometryChange(before: any) {
  const doc = stack.doc.value
  if (!doc) return
  const bearsGeometry = (op: any) =>
    (op.class === 'parametric' && op.exec?.kind === 'crop')
    || (op.class === 'patch' && op.operation === 'expand')
  const hasGeometry =
    doc.edits.some(bearsGeometry) || before.edits.some(bearsGeometry)
  if (!hasGeometry) return

  for (let index = 0; index < doc.edits.length; index++) {
    const op = doc.edits[index] as any
    const shapes = op.exec?.kind === 'annotate' && !op.shapes_in_document
      ? op.params?.shapes ?? []
      : []
    if (!shapes.length) continue

    const previousIndex = before.edits.findIndex((candidate: any) => candidate.id === op.id)
    if (previousIndex < 0) continue

    const oldGeometry = geometryBelow(before, previousIndex)
    const documentFromOld = invertMatrix(oldGeometry.matrix)
    if (!documentFromOld) continue
    op.shapes_in_document = true
    op.params = {
      ...(op.params || {}),
      shapes: transformShapes(
        shapes,
        documentFromOld,
        oldGeometry.width,
        oldGeometry.height,
        doc.canvas.width,
        doc.canvas.height,
      ),
    }
    // Compatibility normalization is not a user gesture and must not add a
    // second Undo entry beside the crop move that exposed it.
    stack.touchOp(op.id)
  }
}

/**
 * The geometry a payload is being created in — its anchor.
 *
 * Stored on the op so the payload's pixels stay addressable in the ORIGINAL
 * image's coordinates no matter what happens to the crops below it. The
 * compositor carries it forward with `M_now ∘ M_created⁻¹`; without it there
 * is nothing to translate through, and a crop removed after the fact leaves
 * the payload at coordinates that meant something in a frame that is gone.
 *
 * `index` is where the op sits, or the top of the stack for one about to be
 * appended.
 */
function payloadFrame(index?: number) {
  const doc = stack.doc.value
  if (!doc) return undefined
  const at = index ?? doc.edits.length
  const geometry = geometryBelow(doc, at)
  return { matrix: geometry.matrix, width: geometry.width, height: geometry.height }
}

/**
 * Complete local-payload → permanent-document transform.
 *
 * Compact origins are folded in here at creation. No renderer is allowed to
 * recover position later from an authored frame plus a separate offset.
 */
function payloadTransform(
  index?: number,
  origin: [number, number] = [0, 0],
): Affine | undefined {
  const frame = payloadFrame(index)
  if (!frame) return undefined
  return payloadToDocumentTransform(frame, origin) ?? undefined
}

/**
 * Remove or disable a step, co-transforming anything above it.
 *
 * Dropping a crop is a geometry change exactly like adding one: every mask,
 * raster layer and annotation above it was authored in the cropped frame and
 * has to be carried back into the uncropped one, or it lands somewhere the
 * user never put it. Toggling a crop's eye is the same change, reversibly.
 */
async function removeOpWithGeometry(opId: string) {
  const removed = stack.opById(opId) as any
  const removedRegionIds = new Set<string>(
    removed?.exec?.kind === 'retouch-regions'
      ? (removed.regions ?? []).map((region: RetouchRegion) => region.id)
      : [],
  )
  if (
    (selectedRetouchRegionId.value && removedRegionIds.has(selectedRetouchRegionId.value))
    || (hoveredRetouchRegionId.value && removedRegionIds.has(hoveredRetouchRegionId.value))
  ) {
    selectedRetouchRegionId.value = null
    hoveredRetouchRegionId.value = null
    selectedRetouchFeedbackVisible.value = false
    void refreshRetouchFeedback()
  }
  if (hoveredRetouchOpId.value === opId) {
    hoveredRetouchOpId.value = null
    allRetouchFeedback.value = []
    allRetouchFeedbackRevision++
  }
  if (retouchOpId.value === opId) resetRetouchSession()
  const before = JSON.parse(JSON.stringify(stack.doc.value))
  stack.removeOp(opId)
  if (opId === cropOpId.value) cropOpId.value = null
  await afterGeometryChange(before)
  // The row disappears synchronously. Let a quick run of trash clicks settle
  // before touching full-resolution pixels so the burst becomes one replay.
  void render({ settleMs: RENDER_BURST_SETTLE_MS })
}

async function setEnabledWithGeometry(opId: string, enabled: boolean) {
  const before = JSON.parse(JSON.stringify(stack.doc.value))
  stack.setEnabled(opId, enabled)
  await afterGeometryChange(before)
  void render()
}

// -- running a generative step ---------------------------------------------

/**
 * The generative op the top bar is ITERATING on: the sticky session's op,
 * while no workspace selection exists and the open sub-tool matches its verb.
 * Run then re-rolls THIS step — same base (the composite below it), current
 * prompt, current composed mask — appending a candidate batch, instead of
 * stacking a new step on a shifted base. A live workspace selection always
 * means a NEW operation and outranks the session.
 */
const iterationOp = computed<GenerativeOp | null>(() => {
  // A BOUND selection is the session's own mask, not a new operation's scope.
  if (selection.value && !maskSessionBound.value) return null
  if (family.value !== 'generate') return null
  const id = selectedGenerativeMaskOpId.value
  const op = id ? stack.opById(id) as any : null
  if (!generativeOpHasEditableMask(op)) return null
  if (sub.value === 'repaint' && op.operation === 'repaint') return op as GenerativeOp
  if (sub.value === 'remove' && op.operation === 'remove') return op as GenerativeOp
  return null
})

// Entering an iteration session shows the step's OWN prompt in the bar — the
// text about to be re-rolled, not whatever the last unrelated run typed.
watch(iterationOp, (op, previous) => {
  if (!op || op === previous || (op as any).operation !== 'repaint') return
  const opPrompt = ((op as any).params?.prompt ?? '') as string
  if (opPrompt && opPrompt !== prompt.value) prompt.value = opPrompt
})

const canRun = computed(() => {
  if (!composite.value || busy.value) return false
  const referencesValid =
    referenceImages.value.length >= activeReferenceLimits.value.min
    && referenceImages.value.length <= activeReferenceLimits.value.max
  if (
    family.value === 'generate'
    && (sub.value === 'remove' || sub.value === 'repaint')
  ) {
    return (!!selection.value || !!iterationOp.value)
      && !!activeToolId.value && referencesValid
  }
  // Remove background is whole-image: the model finds the subject itself.
  if (family.value === 'generate' && sub.value === 'cutout') {
    return !!activeToolId.value
  }
  // Expand is whole-frame too; the task-type rule is the real gate — asking
  // for zero growth on every edge is asking for nothing.
  if (family.value === 'generate' && sub.value === 'expand') {
    return !!activeToolId.value
      && validateTaskType('outpaint-image', expandParamsFromEdges(expandEdges.value)).ok
  }
  return false
})

const busy = ref(false)

/**
 * Whether the composite can carry real transparency — an applied cutout step.
 * The stage then shows the standard checkerboard, because transparent pixels
 * rendered straight onto the matte read as "the image turned grey".
 */
const compositeHasCutout = computed(() =>
  (stack.doc.value?.edits ?? []).some(op =>
    op.enabled && (op as any).operation === 'cutout' && (op as any).picked,
  ),
)

/**
 * Tool families. Clicking one enters a MODE and opens its sub-toolbar; the step
 * is created on the first real gesture — a slider move, an aspect choice, an
 * explicit Run. Empty steps cannot exist, and Esc leaves a mode with nothing to
 * undo.
 */
function selectFamily(id: FamilyId) {
  // Changing modes takes the pointer back from the selection; the selection
  // itself survives — it is workspace state, and the chips in each family's
  // sub-bar say when it is scoping them.
  disarmSelect()
  toolPickerOpen.value = false
  // Looks is a transient chooser, never the Adjust family's landing page.
  // Closing it on every family transition means returning to Adjust cannot
  // surface presets unless the user explicitly opens them in that visit.
  looksOpen.value = false
  // Clicking the active family leaves it — entering and leaving are the same
  // gesture, and leaving with nothing drawn leaves nothing to undo.
  if (family.value === id) { leaveMode(); return }
  leaveMode()
  family.value = id
  writeToolPrefs({ family: id })
  // Entering a family lands on the tool it was last left holding — the pick is
  // this person's way of working, not a property of the image. It only stands
  // while it still names one of the family's tools; the family's own default
  // covers a renamed or removed one.
  const spec = familyById(id)
  sub.value =
    rememberedIfValid(
      rememberedSubTool(id),
      subId => spec.subTools.some(tool => tool.id === subId && !tool.pending),
    ) ?? spec.defaultSub
  // Entering Annotate with a shape already selected means "work with that" —
  // land in select mode with its handles up, not with the arrow tool armed
  // (which hides the handles and turns the next click into a drawing).
  if (id === 'annotate' && selectedShapeId.value) sub.value = null
  // Changing families ends a scoped step's mask-editing session: the armed
  // step belongs to the family flow that armed it, and gestures made in the
  // next family are new selections, not silent rewrites of that step's mask.
  disarmMaskedAdjustmentEditing()
  if (id === 'retouch') {
    retouchInput.value = composite.value
    discardFragileMaskedAdjustment()
  }
  if (id === 'retouch' && sub.value === 'patch' && !selection.value) {
    armSelectTool('lasso', true)
  } else if (
    id === 'generate'
    && (sub.value === 'remove' || sub.value === 'repaint')
  ) {
    if (!selection.value) armSelectTool('brush', true)
  }
  // Entering an adjustment family starts fresh. Without this the panel kept
  // editing whatever was selected before, and a subbar click would judge the
  // wrong step for try-then-replace.
  if (id === 'levels') {
    selectedOpId.value = null
    selectedShapeId.value = null
    if (looksOpen.value) void renderLookThumbs()
  }
  if (id === 'crop') {
    // Each visit to Crop is its own step. Cropping twice is a real thing to
    // want — frame roughly, work, then tighten — and it stays non-destructive
    // because the earlier crop is still a row you can widen or delete. The
    // only time an existing crop is resumed is when its row is selected,
    // which enterParametricOp handles.
    cropOpId.value = null
    void renderCropInput()
  }
  if (id === 'paint') syncImplicitPaintLayer()
}

function selectSub(id: string) {
  // Switching sub-tools is reaching for the canvas: the selection tool lets go.
  disarmSelect()
  toolPickerOpen.value = false
  if (family.value === 'retouch') discardFragileMaskedAdjustment()
  sub.value = id
  if (family.value) rememberSubTool(family.value, id)
  if (family.value === 'retouch' && id === 'patch' && !selection.value) {
    armSelectTool('lasso', true)
  } else if (
    family.value === 'generate'
    && (id === 'remove' || id === 'repaint')
  ) {
    selectedRetouchRegionId.value = null
    if (!selection.value) armSelectTool('brush', true)
  }
}

/** Sub-toolbar state, flattened so the sub-bar stays a dumb renderer. */
const subbarState = computed(() => ({
  prompt: prompt.value,
  candidateCount: candidateCount.value,
  cropAspect: cropAspect.value,
  rotation: cropParamsOf().cropRotation ?? 0,
  flipX: !!cropParamsOf().flipX,
  flipY: !!cropParamsOf().flipY,
  engineId: paintEngineId.value,
  paintFillEngineId: paintFillEngineId.value,
  paintBrush: paintBrush.value,
  paintColor: paintColorRgb.value,
  paintGradient: paintGradient.value,
  paintGradientType: paintGradientType.value,
  paintGradientReverse: paintGradientReverse.value,
  retouchBrush: retouchBrush.value,
  retouchExposure: retouchExposure.value,
  retouchRange: retouchRange.value,
  retouchStrength: retouchStrength.value,
  retouchSaturate: retouchSaturate.value,
  activeTool: activeTool.value,
  toolParams: activeToolParamValues.value,
  loraToolId: activeLoraToolId.value,
  isRefreshingLoras: isRefreshingLoras.value,
  isUploadingLora: isUploadingLora.value,
  loraUploadProgress: loraUploadProgress.value,
  loraUploadFileName: loraUploadFileName.value,
  expandEdges: expandEdges.value,
  frameWidth: composite.value?.width ?? 0,
  frameHeight: composite.value?.height ?? 0,
  recentRepaintPrompts: recentRepaintPrompts.value,
  referenceImages: referenceImages.value,
  referenceMin: activeReferenceLimits.value.min,
  referenceMax: activeReferenceLimits.value.max,
  textStyle: textStyle.value,
  annotatePaint: annotatePaint.value,
  annotateStrokeWidth: annotateStrokeWidth.value,
  annotateFillColor: annotateFillColor.value,
  annotateShapeEffect: annotateShapeEffect.value,
  annotateOpacity: annotateOpacity.value,
  selectedShapeId: selectedShapeId.value,
  // With a shape selected, the sub-bar shows THAT shape's control set — the
  // selection's status overrides the latent tool's initial conditions.
  selectedShapeKind: selectedShape.value?.type ?? null,
  imagePalette: imagePalette.value,
  appliedLookIds: appliedLookIds.value,
  lookThumbs: lookThumbs.value,
  looksOpen: looksOpen.value,
  // Adjust's scope chip: a live selection means the next added edit is scoped.
  hasSelection: !!selection.value,
}))

/**
 * Sub-bar keys that do NOT reach for the canvas: typing a prompt or setting a
 * factor keeps an armed selection tool armed (Repaint arms the brush and then
 * asks for a sentence). Everything else — engines, brushes, colors, annotate
 * styles, adjust actions — is the user picking family work up again, and the
 * selection tool must let go.
 */
const SUBBAR_KEEPS_SELECT = new Set([
  'prompt', 'candidateCount', 'toolParamPatch',
  'removeRecentPrompt', 'referenceImages', 'expandEdges',
  // Showing or hiding the Looks strip is chrome, not canvas work.
  'looksOpen',
])

function onSubbarSet(patch: Record<string, any>, continuous = false) {
  if (Object.keys(patch).some(key => !SUBBAR_KEEPS_SELECT.has(key))) disarmSelect()
  if ('prompt' in patch) prompt.value = patch.prompt
  if ('candidateCount' in patch) candidateCount.value = patch.candidateCount
  if ('referenceImages' in patch) referenceImages.value = patch.referenceImages
  // Deliberately not persisted: how much to grow is a property of THIS
  // image's composition, not a way of working — a new document starts at
  // zero, not at the last image's answer.
  if ('expandEdges' in patch) {
    expandEdges.value = { ...patch.expandEdges }
  }
  if ('removeRecentPrompt' in patch) {
    recentRepaintPrompts.value = recentRepaintPrompts.value.filter(
      entry => entry !== patch.removeRecentPrompt,
    )
    writeToolPrefs({ recentRepaintPrompts: recentRepaintPrompts.value })
  }
  if ('toolParamPatch' in patch && activeToolId.value) {
    modelToolParams.value = {
      ...modelToolParams.value,
      [activeToolId.value]: {
        ...activeToolParamValues.value,
        ...sanitizeModelToolParams(activeTool.value, patch.toolParamPatch),
      },
    }
  }
  if ('engineId' in patch) {
    paintEngineId.value = patch.engineId
    if (patch.engineId === 'fill' || patch.engineId === 'gradient') {
      paintFillEngineId.value = patch.engineId
      writeToolPrefs({
        paintEngineId: patch.engineId,
        paintFillEngineId: patch.engineId,
      })
    } else {
      writeToolPrefs({ paintEngineId: patch.engineId })
    }
  }
  if ('paintBrush' in patch) paintBrush.value = patch.paintBrush
  if ('paintColor' in patch) paintColorRgb.value = patch.paintColor
  if ('paintGradient' in patch) paintGradient.value = patch.paintGradient
  if ('paintGradientType' in patch) paintGradientType.value = patch.paintGradientType
  if ('paintGradientReverse' in patch) paintGradientReverse.value = patch.paintGradientReverse
  if ('retouchBrush' in patch) retouchBrush.value = patch.retouchBrush
  if ('retouchExposure' in patch) retouchExposure.value = patch.retouchExposure
  if ('retouchRange' in patch) retouchRange.value = patch.retouchRange
  if ('retouchStrength' in patch) retouchStrength.value = patch.retouchStrength
  if ('retouchSaturate' in patch) retouchSaturate.value = patch.retouchSaturate
  if ('textStyle' in patch) {
    textStyle.value = patch.textStyle
    // Same act before or after: the strip arms the next text and, with one
    // selected, restyles it — the inspector's preset row writes the same patch.
    if (selectedShape.value?.type === 'text') {
      onShapeChange(textStylePatch(patch.textStyle, {
        glowIntensity: (selectedShape.value as any).glowIntensity,
      }))
    }
  }
  if ('annotatePaint' in patch) {
    annotatePaint.value = patch.annotatePaint
    if (selectedShape.value) {
      onShapeChange(selectedShape.value.type === 'text'
        ? { textColor: patch.annotatePaint }
        : { strokeColor: patch.annotatePaint })
    }
  }
  // The annotate strip is the latent shape's initial conditions, and — with a
  // shape selected — a compact remote for that shape: both views bind to the
  // same values, so setting neon before or after drawing is the same act.
  if ('annotateStrokeWidth' in patch) {
    annotateStrokeWidth.value = patch.annotateStrokeWidth
    if (selectedShape.value) onShapeChange({ strokeWidth: patch.annotateStrokeWidth })
  }
  if ('annotateFillColor' in patch) {
    annotateFillColor.value = patch.annotateFillColor
    if (selectedShape.value && 'backgroundColor' in (selectedShape.value as any)) {
      onShapeChange({ backgroundColor: patch.annotateFillColor ?? undefined })
    }
  }
  if ('annotateShapeEffect' in patch) {
    annotateShapeEffect.value = patch.annotateShapeEffect
    if (selectedShape.value && selectedShape.value.type !== 'text') {
      onShapeChange({
        style: patch.annotateShapeEffect === 'none'
          ? undefined
          : { effect: patch.annotateShapeEffect, glowIntensity: 70 },
      })
    }
  }
  if ('annotateOpacity' in patch) {
    annotateOpacity.value = patch.annotateOpacity
    if (selectedShape.value) {
      onShapeChange({ opacity: patch.annotateOpacity }, continuous)
    }
  }
  if ('deleteShape' in patch) annotateRef.value?.deleteSelected()
  // Picking a group edit or an Auto is moving on from browsing looks, so the
  // strip puts itself away. Picking a LOOK does not: trying several against
  // the picture is the whole point of a strip.
  if ('auto' in patch || 'addLevel' in patch) looksOpen.value = false
  if ('auto' in patch) runAuto(patch.auto)
  if ('applyLook' in patch) applyLook(patch.applyLook)
  if ('looksOpen' in patch) {
    looksOpen.value = patch.looksOpen
    if (looksOpen.value) void renderLookThumbs()
  }
  if ('addLevel' in patch) void addLevelEdit(patch.addLevel)
  if ('cropAspect' in patch) chooseAspect(patch.cropAspect)
  // Straighten and the lollipop are the same control: the crop window's tilt.
  if ('rotation' in patch) {
    void applyCropChange(
      { cropRotation: patch.rotation },
      cropGestureKey.value,
      continuous,
    )
  }
  if ('rotateQuarter' in patch) rotateQuarter()
  if ('flipX' in patch) void applyCropChange({ flipX: patch.flipX })
  if ('flipY' in patch) void applyCropChange({ flipY: patch.flipY })
  if ('newLayer' in patch) startNewPaintLayer()
}

async function run() {
  if (!canRun.value || !stack.doc.value || !composite.value) return

  // The sticky iteration: no workspace selection and a session op whose verb
  // matches the bar. Run means "re-roll THIS step" — same base, the current
  // prompt, the current composed mask — appending a batch. Never a new step
  // on a shifted base; that mistake costs real money.
  const iterating = iterationOp.value
  if (iterating && (sub.value === 'repaint' || sub.value === 'remove')) {
    busy.value = true
    error.value = null
    try {
      if (
        sub.value === 'repaint'
        && prompt.value !== ((iterating.params as any)?.prompt ?? '')
      ) {
        stack.setParams(
          iterating.id,
          { prompt: prompt.value },
          `iterate-prompt:${iterating.id}`,
        )
      }
      await resample(iterating.id)
    } finally {
      busy.value = false
    }
    return
  }

  busy.value = true
  error.value = null
  let reusedRepaintOpId: string | null = null
  try {
    const action = sub.value === 'remove'
      ? 'remove'
      : sub.value === 'repaint'
        ? 'repaint'
        : sub.value === 'expand'
          ? 'expand'
          : 'cutout'
    const toolId = activeToolId.value!
    const tool = activeTool.value
    if (!tool) throw new Error('That tool is no longer in the catalog.')
    const toolParams = sanitizeModelToolParams(tool, {
      ...activeToolParamValues.value,
      ...(tool.parameter_schema?.properties?.loras && activeLoraToolId.value
        ? { loras: loraPool.getEnabledLoras(activeLoraToolId.value) }
        : {}),
    })
    const removeRoute = action === 'remove' ? removeRouteForTool(tool) : null
    if (action === 'remove' && !removeRoute) {
      throw new Error('That tool cannot remove or inpaint an image.')
    }
    const taskType = action === 'cutout'
      ? 'remove-background'
      : action === 'expand'
        ? 'outpaint-image'
        : removeRoute?.taskType ?? 'inpaint-image'
    const submittedPrompt = action === 'cutout' || action === 'expand'
      ? ''
      : removeRoute?.prompt ?? prompt.value
    const submittedReferences = action === 'repaint'
      ? copyModelReferenceImages(referenceImages.value)
      : []
    const submittedSelectionRevision = selectionRevision
    let submitMask = selectionAsMask()

    // Regenerate is an iterative session while its original selection remains
    // live and its step remains the head. Another Run appends a candidate batch
    // to that step and samples the same composite BELOW it — never the rejected
    // candidate currently picked by the step itself.
    const reusableOp = action === 'repaint'
      ? reusableRepaintOp(
          stack.doc.value,
          repaintSession,
          submittedSelectionRevision,
          toolId,
          taskType,
        )
      : null
    const reusableIndex = reusableOp
      ? stack.doc.value.edits.length - 1
      : -1
    const opId = reusableOp?.id ?? newOpId()
    reusedRepaintOpId = reusableOp?.id ?? null
    const sampledInputHash = reusableOp
      ? stackHashes(stack.doc.value).inputs[reusableIndex]
      : stackHashes(stack.doc.value).head

    // What a tool is given is the real head composite, not the stage: the
    // stage can be holding a layer out while an overlay draws it (see
    // displayDoc), and a model must never be handed pixels the document does
    // not have. A continued Regenerate session instead renders only the ops
    // below its existing step, keeping every candidate batch on one base.
    const submitInput = reusableOp
      ? await compositor.renderUpTo(stack.doc.value, reusableIndex)
      : await compositor.render(stack.doc.value)
    // A cutout has no drawn region — its "mask" is the whole frame. It exists
    // for the patch machinery (crop bounds, resample), not the wire:
    // remove-background tools declare no mask input, so none is uploaded.
    if (action === 'cutout') {
      submitMask = fullFrameMask(submitInput.width, submitInput.height)
    }
    // Expand's mask is the border ring at the GROWN size. Also never uploaded
    // (outpaint tools declare no mask input; the tool grows the canvas itself
    // from the percent params) — its dimensions tell the candidate machinery
    // what size a correct result comes back at, and its bounds crop nothing,
    // because a ring touches every edge.
    let expandParams: Record<string, number> | null = null
    if (action === 'expand') {
      expandParams = expandParamsFromEdges(expandEdges.value)
      const frame = expandedFrame(
        expandEdges.value, submitInput.width, submitInput.height,
      )
      submitMask = expandBorderMask(submitInput.width, submitInput.height, frame)
    }
    if (!submitMask) throw new Error('There is nothing selected to work on.')

    const label = action === 'remove'
      ? 'Remove object'
      : action === 'repaint'
        ? 'Repaint'
        : action === 'expand'
          ? 'Expand'
          : 'Remove background'

    let authoredToDocument = payloadTransform()
    if (reusableOp) {
      authoredToDocument = payloadTransform(reusableIndex)
      // The step's inspector and future explicit Resample use the latest
      // settings. Existing candidates remain intact and independently
      // selectable; only the recipe for the next batch moves forward.
      stack.setParams(opId, {
        ...toolParams,
        prompt: submittedPrompt,
      })
      stack.setReferenceImages(opId, submittedReferences)
      selectedOpId.value = opId
      // The first result from the new row replaces the disliked current pick;
      // every older pick stays available in its original candidate row.
      resampledOpIds.value = new Set(resampledOpIds.value).add(opId)
    } else {
      const maskPayloadRef = await stack.uploadPayload(
        `${opId}-mask.png`, await canvasToBlob(submitMask)
      )
      const authoredFrame = payloadFrame()
      const op: GenerativeOp = {
        id: opId,
        class: 'patch',
        enabled: true,
        label,
        exec: { kind: 'tool', tool_id: toolId, task_type: taskType },
        operation: action,
        params: {
          ...toolParams,
          ...(expandParams ?? {}),
          ...(submittedPrompt ? { prompt: submittedPrompt } : {}),
        },
        reference_images: submittedReferences,
        mask_ref: maskPayloadRef,
        // The mask, and the candidates generated for it, are anchored to the
        // frame they were made in.
        payload_to_document: authoredToDocument,
        payload_frame: authoredFrame,
        // A cutout matte is already soft where the model made it soft; a default
        // feather would eat the subject's edge. Expand's overdraw of the
        // original fades into the candidate over this feather (expanded edges
        // only) — model border content is often softer than the source, and a
        // hard crisp-against-soft boundary reads as a seam. Tunable in Blend.
        blend: {
          feather_px: action === 'cutout' ? 0 : action === 'expand' ? 24 : 6,
          opacity: 1,
        },
        picked: null,
        candidates: [],
      }
      stack.addOp(op)
      selectedOpId.value = opId
      if (
        action === 'repaint'
        && selectionRevision === submittedSelectionRevision
      ) {
        repaintSession = { opId, selectionRevision: submittedSelectionRevision }
      }
    }

    // Cut the naming crop HERE, while the mask and the composite it was sampled
    // against are still this step's. The request itself is fire-and-forget: a
    // name is a nicety and must never sit in front of the job.
    if (action === 'remove' || action === 'repaint') {
      const crop = regionCropBase64(submitInput, submitMask)
      if (crop) {
        void nameStepFromCrop(action, crop, submittedPrompt).then(label => {
          if (label) stack.annotateLabel(opId, label)
        })
      }
    }

    await candidates.submit({
      opId,
      tool,
      taskType,
      inputCanvas: submitInput,
      maskCanvas: submitMask,
      prompt: submittedPrompt,
      // Background removal is deterministic — N runs are N identical mattes.
      count: action === 'cutout' ? 1 : candidateCount.value,
      params: { ...toolParams, ...(expandParams ?? {}) },
      referenceImages: submittedReferences,
      sampledInputHash,
      // Expand's candidate is the whole grown frame; the compositor's expand
      // branch places it by the percent math, not by an anchored transform.
      payloadToDocument: action === 'expand' ? undefined : authoredToDocument,
      // The outpaint tool computes its own output size from the percents; a
      // locked resolution would ask it to return the input unchanged.
      lockResolution: action !== 'expand',
    })
    if (action === 'repaint') {
      recentRepaintPrompts.value = addRecentPrompt(
        recentRepaintPrompts.value,
        submittedPrompt,
      )
      writeToolPrefs({
        repaintPrompt: submittedPrompt,
        recentRepaintPrompts: recentRepaintPrompts.value,
      })
    }

    // The selection lives on as the step's editable mask, and the step
    // becomes the sticky iteration session: the ants you selected with ARE
    // the mask now (bound), the tools keep editing it, and Run re-rolls THIS
    // step on the same base. Deselect/Escape or a New selection walk away.
    if (action === 'remove' || action === 'repaint') {
      selectedOpId.value = opId
      selectedGenerativeMaskOpId.value = opId
      maskedGenerativeOpId = opId
      maskSessionBound.value = selModel.hasSelection()
      workspaceMaskRecipe = null
      workspaceMaskRecipeKey = null
      selectedRetouchFeedbackVisible.value = false
    }
  } catch (err: any) {
    if (reusedRepaintOpId) {
      const next = new Set(resampledOpIds.value)
      next.delete(reusedRepaintOpId)
      resampledOpIds.value = next
    }
    error.value = apiErrorMessage(err, 'Could not start the edit.')
  } finally {
    busy.value = false
  }
}

/**
 * Re-run a generative step against its CURRENT input.
 *
 * Old candidates are kept: switching back to one is free and restores the prior
 * look, which is what makes a resample safe to try.
 *
 * Two things this must NOT do, both of which it once did. It must not report
 * itself finished when the job is merely submitted — the work is the job, and a
 * spinner that stops at submission says "done, and nothing happened". And its
 * result must not be discarded because the step already has a pick: a resample
 * by definition targets a picked step, so the arriving candidate has to replace
 * that pick or the run cost money and changed nothing.
 */
const resampledOpIds = ref<Set<string>>(new Set())

/** Steps with a live job, whichever way it was started. */
const runningOpIds = computed(() => new Set(Object.keys(pendingByOp.value)))

async function resample(opId: string) {
  const doc = stack.doc.value
  const op = stack.opById(opId) as GenerativeOp | undefined
  if (!doc || !op || !composite.value) return

  const index = doc.edits.findIndex(o => o.id === opId)
  const inputHash = stackHashes(doc).inputs[index]
  const tool = tools.value.find(t => t.full_tool_id === op.exec.tool_id)
  if (!tool) {
    error.value = 'That tool is no longer in the catalog.'
    return
  }
  const referenceLimits = modelReferenceLimits(tool)
  const referenceCount = op.reference_images?.length ?? 0
  if (
    referenceCount < referenceLimits.min
    || referenceCount > referenceLimits.max
  ) {
    error.value = `That tool accepts ${referenceLimits.min}–${referenceLimits.max} reference images.`
    return
  }
  // Expand re-derives everything from its percent params against the CURRENT
  // input frame — the ring mask is arithmetic, not a stored payload, so a
  // resample after edits below (or after tweaking the percents in Advanced)
  // grows the right frame from the right pixels.
  if (op.operation === 'expand') {
    error.value = null
    try {
      const inputCanvas = await compositor.renderUpTo(doc, index)
      const frame = expandedFrame(
        expandEdgesFromParams(op.params), inputCanvas.width, inputCanvas.height,
      )
      const mask = expandBorderMask(inputCanvas.width, inputCanvas.height, frame)
      resampledOpIds.value = new Set(resampledOpIds.value).add(opId)
      await candidates.submit({
        opId,
        tool,
        taskType: op.exec.task_type,
        inputCanvas,
        maskCanvas: mask,
        prompt: '',
        count: candidateCount.value,
        params: sanitizeModelToolParams(tool, op.params),
        sampledInputHash: inputHash,
        lockResolution: false,
      })
    } catch (err: any) {
      const next = new Set(resampledOpIds.value)
      next.delete(opId)
      resampledOpIds.value = next
      error.value = apiErrorMessage(err, 'Could not resample.')
    }
    return
  }

  const maskRef = (op as any).mask_ref
  const maskComponents = (op as any).mask_components as MaskComponent[] | undefined
  if (!maskRef && !maskComponents?.length) {
    error.value = 'That step has no mask to resample through.'
    return
  }

  error.value = null
  try {
    // The op's input composite, not the head: a step re-samples against what it
    // actually sits on.
    const inputCanvas = await compositor.renderUpTo(doc, index)
    let mask: HTMLCanvasElement
    if (maskComponents?.length) {
      // The composed effective mask IS the submission: regenerating is what
      // settles the coverage debt the edited recipe created. Rendered as the
      // white-on-black luminance shape every mask consumer expects.
      const composed = await generativeMaskFeedback(opId)
      if (!composed) {
        error.value = 'The mask is empty — nothing to resample through.'
        return
      }
      const flattened = document.createElement('canvas')
      flattened.width = inputCanvas.width
      flattened.height = inputCanvas.height
      const ctx = flattened.getContext('2d')!
      ctx.fillStyle = '#000'
      ctx.fillRect(0, 0, flattened.width, flattened.height)
      ctx.drawImage(composed, 0, 0, flattened.width, flattened.height)
      mask = flattened
    } else {
      const image = await loadImage(stack.payloadUrl(maskRef))
      const canonical = (op.payload_to_document as Affine | undefined)
        ?? (op.payload_frame
          ? payloadToDocumentTransform(op.payload_frame) ?? undefined
          : undefined)
      const now = geometryBelow(doc, index)
      mask = canonical
        ? rewritePayload(
            image,
            multiply(now.matrix, canonical),
            inputCanvas.width,
            inputCanvas.height,
          )
        : (() => {
            const canvas = document.createElement('canvas')
            canvas.width = inputCanvas.width
            canvas.height = inputCanvas.height
            canvas.getContext('2d')!.drawImage(image, 0, 0, canvas.width, canvas.height)
            return canvas
          })()
    }
    const resampledToDocument = payloadTransform(index)

    // Marked BEFORE the submit: the first candidate back auto-applies, which is
    // the only way the click has a visible result.
    resampledOpIds.value = new Set(resampledOpIds.value).add(opId)
    await candidates.submit({
      opId,
      tool,
      taskType: op.exec.task_type,
      inputCanvas,
      maskCanvas: mask,
      prompt: (op.params as any)?.prompt || '',
      count: candidateCount.value,
      params: sanitizeModelToolParams(tool, op.params),
      referenceImages: op.reference_images ?? [],
      sampledInputHash: inputHash,
      payloadToDocument: resampledToDocument,
    })
    if (
      op.operation === 'repaint'
      || (!op.operation && op.label === 'Repaint')
    ) {
      const submittedPrompt = (op.params as any)?.prompt || ''
      recentRepaintPrompts.value = addRecentPrompt(
        recentRepaintPrompts.value,
        submittedPrompt,
      )
      writeToolPrefs({
        repaintPrompt: submittedPrompt,
        recentRepaintPrompts: recentRepaintPrompts.value,
      })
    }
  } catch (err: any) {
    const next = new Set(resampledOpIds.value)
    next.delete(opId)
    resampledOpIds.value = next
    error.value = apiErrorMessage(err, 'Could not resample.')
  }
}

/** A white-everywhere mask: the whole frame is the region. */
function fullFrameMask(width: number, height: number): HTMLCanvasElement {
  const mask = document.createElement('canvas')
  mask.width = width
  mask.height = height
  const ctx = mask.getContext('2d')!
  ctx.fillStyle = '#fff'
  ctx.fillRect(0, 0, width, height)
  return mask
}

// -- adjust ----------------------------------------------------------------

/**
 * Fine-grained adjust steps, one rule for both doorways: every entry in the
 * Adjust and Filters sub-toolbars is an ADD. Clicking it creates its own
 * focused step — a Light, a Color, a Portra 400, a VHS — and the step's
 * controls live in its Properties. There is no session step and no latent
 * state: the click IS the creating gesture.
 *
 * Try-then-replace: a step that is still exactly as the click created it is
 * replaced when another entry is clicked, so paging through looks does not
 * leave a trail. Touch any of its properties and it sticks.
 */
const pristineSnapshots = new Map<string, string>()

function snapshotPristine(opId: string) {
  const op = stack.opById(opId) as any
  pristineSnapshots.set(opId, JSON.stringify(op?.params ?? {}))
}

async function replaceIfPristine() {
  const id = selectedOpId.value
  if (!id) return
  const snap = pristineSnapshots.get(id)
  if (snap === undefined) return
  const op = stack.opById(id) as any
  pristineSnapshots.delete(id)
  if (!op || JSON.stringify(op.params ?? {}) !== snap) return
  await removeOpWithGeometry(id)
}

function addAdjustOp(
  label: string,
  params: Record<string, any>,
  options: { pristine?: boolean } = {},
) {
  // A whole-image step takes over from any scoped step still armed for mask
  // edits; leaving it armed would route the next selection gesture into the
  // OLD step's mask.
  disarmMaskedAdjustmentEditing()
  const opId = newOpId()
  stack.addOp({
    id: opId, class: 'parametric', enabled: true,
    label, exec: { kind: 'adjust' }, params,
  } as any)
  selectedOpId.value = opId
  // pristine: false is for steps born DONE (the Autos): their values arrive
  // finished rather than as a doorway's defaults, so an untouched one is a
  // real edit, not a provisional landing place for the next click to replace.
  if (options.pristine !== false) snapshotPristine(opId)
  void render()
}

/**
 * Light, Color or Detail, from the Adjust bar. Scope comes from the workspace:
 * a live selection makes the step a scoped one (its own single-region
 * container); otherwise it is a whole-image parametric step. Either way the
 * click yields the edit's controls, never a brush.
 */
async function addLevelEdit(id: string) {
  const edit = levelEditById(id)
  if (!edit) return
  // Scope belongs to the CLICK, not to whatever workspace state survives the
  // async replacement below. Snapshot now so an active selection can never
  // silently degrade into a whole-image adjustment during the handoff.
  const scope = activeAdjustmentScope()
  // Try-then-replace, both shapes: an untouched whole-image step and an
  // untouched scoped step are equally provisional landing places.
  await replaceIfPristine()
  discardFragileMaskedAdjustment()
  if (scope) {
    addScopedLevelEdit(edit, scope)
    return
  }
  addAdjustOp(edit.label, { section: edit.id, ...(edit.seed ?? {}) })
}

function activeAdjustmentScope(): AdjustmentScopeSnapshot<HTMLCanvasElement> | null {
  return captureAdjustmentScope(
    selection.value,
    copyCanvas,
    workspaceGradient.value,
    workspaceGradientKey.value,
    selectionAppliedKey,
    workspaceSemantic.value,
    workspaceSemanticKey.value,
    workspaceMaskRecipe,
    workspaceMaskRecipeKey,
  )
}

/** The region kind the masked pipeline stores for a level edit's section. */
function maskedKindOf(edit: LevelEdit): Exclude<MaskedAdjustmentKind, 'adjust'> {
  const group = photoAdjustmentGroup(edit.id)
  return (group?.id ?? 'light') as Exclude<MaskedAdjustmentKind, 'adjust'>
}

/**
 * One scoped Adjust step from the live selection.
 *
 * A selection that IS a single gradient gesture scopes parametrically — the
 * step keeps the ramp's geometry and its handles stay live. Anything else
 * freezes the rasterised mask, consumed by copy like every region consumer.
 */
function addScopedLevelEdit(
  edit: LevelEdit,
  scope: AdjustmentScopeSnapshot<HTMLCanvasElement>,
) {
  disarmMaskedAdjustmentEditing()
  selectedRetouchRegionId.value = null
  hoveredRetouchRegionId.value = null
  void refreshRetouchFeedback()
  const opId = newOpId()
  const regionId = newOpId()
  maskedAdjustOpId = opId
  maskedAdjustRegionId = regionId
  maskedAdjustSpec = {
    kind: maskedKindOf(edit),
    label: edit.label,
    seed: edit.seed,
  }
  fragileRetouchRegions.mark(regionId)
  if (scope.kind === 'gradient') {
    createScopedGradientStep(opId, regionId, scope.gradient)
    return
  }
  if (scope.kind === 'recipe') {
    queueMaskedAdjustmentMask(null, null, scope.entries)
  } else {
    queueMaskedAdjustmentMask(scope.mask, scope.semantic ?? null)
  }
  // The selection moved INTO the step's mask; leaving it live would make the
  // next gesture flatten on top of coverage the mask already owns.
  consumeWorkspaceSelection()
}

/**
 * The gradient-scoped step, created synchronously: geometry, not pixels, so
 * there is no payload upload to wait for.
 */
function createScopedGradientStep(
  opId: string,
  regionId: string,
  gradient: GradientMask,
) {
  const spec = maskedAdjustSpec
  const frame = payloadFrame()
  const canonical = frame
    ? payloadToDocumentTransform(frame) ?? undefined
    : undefined
  const authored = authoredGradient(gradient, frame, canonical, -1)
  if (!authored) return
  const region: RetouchRegion = {
    id: regionId,
    kind: spec?.kind ?? 'light',
    enabled: true,
    mask: authored,
    payload_to_document: canonical,
    payload_frame: frame,
    sampled_input_hash: null,
    settings: { ...DEFAULT_RETOUCH_REGION_SETTINGS, ...(spec?.seed ?? {}) },
  }
  stack.addOp({
    id: opId,
    class: 'container',
    enabled: true,
    label: spec?.label ?? 'Adjust',
    exec: { kind: 'retouch-regions', version: 1 },
    defaults: { ...DEFAULT_RETOUCH_REGION_SETTINGS },
    regions: [region],
  } as any)
  selectedOpId.value = opId
  selectedRetouchRegionId.value = regionId
  selectedMaskComponentId.value = null
  // Ownership moves from the transient workspace selection to this region:
  // the region's own geometry now drives the handles, and the compatibility
  // bitmap is consumed so the next gesture starts clean.
  consumeWorkspaceSelection()
  // The ramp's guides say where it is; a second wash would double up.
  selectedRetouchFeedbackVisible.value = false
  void render().then(refreshRetouchInput)
}

/**
 * Selecting a Adjust row makes the inspector edit THAT row, which is how an
 * earlier session's step is re-entered rather than a new one being stacked.
 */
const selectedAdjustOp = computed(() => {
  const op = selectedOpId.value ? stack.opById(selectedOpId.value) : null
  return op && op.class === 'parametric' && (op as any).exec?.kind === 'adjust' ? op : null
})
const selectedModelOp = computed<GenerativeOp | null>(() => {
  const op = selectedOpId.value ? stack.opById(selectedOpId.value) : null
  return op?.class === 'patch' ? op as GenerativeOp : null
})
const selectedModelTool = computed(() => {
  const id = selectedModelOp.value?.exec.tool_id
  return id ? tools.value.find(tool => tool.full_tool_id === id) ?? null : null
})

function setSelectedModelParams(patch: Record<string, any>) {
  if (!selectedModelOp.value) return
  stack.setParams(selectedModelOp.value.id, patch)
}

function setSelectedModelReferences(images: ModelReferenceImage[]) {
  if (!selectedModelOp.value) return
  stack.setReferenceImages(selectedModelOp.value.id, images)
}

function setSelectedModelBlend(blend: Record<string, number>) {
  if (!selectedModelOp.value) return
  stack.setBlend(
    selectedModelOp.value.id,
    blend,
    `model-blend:${selectedModelOp.value.id}:${Object.keys(blend)[0] ?? 'value'}`,
  )
  scheduleRetouchSettingsPreview()
}

function commitSelectedModelBlend() {
  void commitRetouchSettingsRender()
}

/**
 * What the properties panel is showing: the selected step decides, and with
 * nothing selected there is nothing to show — the sub-toolbars are the door
 * to a first step now, not the inspector.
 */
const inspectorKind = computed<'annotation' | 'adjust' | 'retouch' | 'model' | null>(() => {
  // Properties belongs to a selected STEP, so it follows the Edits panel. The
  // Output panel carries its own controls and would otherwise be sharing the
  // sidebar with a second, unrelated control surface.
  if (sidebarTab.value !== 'edits') return null
  const op = selectedOpId.value ? (stack.opById(selectedOpId.value) as any) : null
  if (
    op?.exec?.kind === 'retouch-regions'
    && (op.regions ?? []).some(
      (region: RetouchRegion) => region.id === selectedRetouchRegionId.value,
    )
  ) return 'retouch'
  if (op?.exec?.kind === 'annotate') return 'annotation'
  if (op?.exec?.kind === 'adjust') return 'adjust'
  if (op?.class === 'patch' && op?.exec?.kind === 'tool') return 'model'
  return null
})

const showsAdjustInspector = computed(() => inspectorKind.value === 'adjust')

/**
 * A thumbnail per look, off the real picture, for the strip.
 *
 * Naming a look tells you nothing — Kodachrome and Portra 400 are only
 * distinguishable by looking.
 */
const lookThumbs = ref<Record<string, string>>({})
const LOOK_THUMB = 128

/**
 * Whether the Looks strip is showing under the Adjust bar.
 *
 * Closed unless asked for. The strip is two rows of thumbnails; leaving it up
 * means every visit to Adjust opens with it in the way, and it stayed up while
 * you worked on a Light step that has nothing to do with it. Opening it is one
 * click, and any OTHER Adjust action puts it away again — reaching for a group
 * edit or an Auto says you are done browsing starting points.
 */
const looksOpen = ref(false)

async function renderLookThumbs() {
  // The strip previews what a click DOES. With a still-pristine step selected
  // a click replaces it, so the tiles render off the composite WITHOUT that
  // step — otherwise every preview shows a stack that will never happen.
  // Cheap: the composite below the top op is already in the compositor cache.
  let source = composite.value
  const selected = selectedOpId.value
  if (selected && pristineSnapshots.has(selected) && stack.doc.value) {
    const op = stack.opById(selected) as any
    if (
      op?.exec?.kind === 'adjust' &&
      JSON.stringify(op.params ?? {}) === pristineSnapshots.get(selected)
    ) {
      source = await compositor.render({
        ...stack.doc.value,
        edits: stack.doc.value.edits.filter(edit => edit.id !== selected),
      })
    }
  }
  if (!source?.width) return

  const base = document.createElement('canvas')
  base.width = LOOK_THUMB
  base.height = LOOK_THUMB
  const ctx = base.getContext('2d', { willReadFrequently: true })
  if (!ctx) return
  const side = Math.min(source.width, source.height)
  ctx.drawImage(
    source,
    (source.width - side) / 2, (source.height - side) / 2, side, side,
    0, 0, LOOK_THUMB, LOOK_THUMB
  )

  const out: Record<string, string> = {}
  for (const look of LOOKS) {
    // Through the real executor, at the exact params a click would write, so
    // the tile cannot drift from the step it promises.
    out[look.id] = applyAdjust(base, LOOK_THUMB, LOOK_THUMB, look.params).toDataURL()
  }
  lookThumbs.value = out
}

/**
 * The step a look created, if one is on — whole-image or scoped to a
 * selection. Only steps the strip itself wrote match: a hand-edited blob that
 * happens to carry the same params must never be matched, or clicking the tile
 * would delete somebody's whole adjustment.
 */
function lookOpFor(look: Look): any | null {
  return (stack.doc.value?.edits || []).find(op => {
    const anyOp = op as any
    if (anyOp.exec?.kind === 'adjust') return anyOp.params?.look === look.id
    if (anyOp.exec?.kind === 'retouch-regions') {
      // Only the single-region container the strip itself made. Clicking the
      // tile REMOVES what it matches, and a container that grew siblings would
      // take them with it.
      const regions = anyOp.regions ?? []
      return regions.length === 1
        && regions[0].kind === 'look'
        && regions[0].settings?.look === look.id
    }
    return false
  }) ?? null
}

/** What the strip highlights: looks whose step is on. */
const appliedLookIds = computed(() =>
  LOOKS.filter(look => lookOpFor(look)?.enabled).map(look => look.id)
)

/**
 * Picking from the strip IS applying it. The look's params land as a step —
 * scoped to the workspace selection when there is one, exactly like a Light or
 * Color click, because a look is the same kind of thing. Clicking the applied
 * tile takes it off again, which is the only sensible meaning for pressing a
 * pressed button.
 */
function applyLook(id: string) {
  const look = lookById(id)
  if (!look) return
  const existing = lookOpFor(look)
  if (existing) {
    pristineSnapshots.delete(existing.id)
    void removeOpWithGeometry(existing.id)
    return
  }
  const scope = activeAdjustmentScope()
  void (async () => {
    await replaceIfPristine()
    discardFragileMaskedAdjustment()
    if (scope) {
      addScopedLook(look, scope)
      return
    }
    addAdjustOp(look.label, { look: look.id, ...look.params })
  })()
}

/**
 * One scoped Looks step from the live selection: a single-region container of
 * kind `look`, on the same path a scoped Light edit takes. Gradient selections
 * stay parametric so the ramp's handles remain live.
 */
function addScopedLook(
  look: Look,
  scope: AdjustmentScopeSnapshot<HTMLCanvasElement>,
) {
  disarmMaskedAdjustmentEditing()
  selectedRetouchRegionId.value = null
  hoveredRetouchRegionId.value = null
  void refreshRetouchFeedback()
  const opId = newOpId()
  const regionId = newOpId()
  maskedAdjustOpId = opId
  maskedAdjustRegionId = regionId
  maskedAdjustSpec = {
    kind: 'look',
    label: look.label,
    seed: { ...look.params, look: look.id },
  }
  fragileRetouchRegions.mark(regionId)
  if (scope.kind === 'gradient') {
    createScopedGradientStep(opId, regionId, scope.gradient)
    return
  }
  if (scope.kind === 'recipe') {
    queueMaskedAdjustmentMask(null, null, scope.entries)
  } else {
    queueMaskedAdjustmentMask(scope.mask, scope.semantic ?? null)
  }
  consumeWorkspaceSelection()
}

/**
 * The Autos: each reads the histogram of the composite and lands as a normal
 * Light step seeded with the values it chose — inspectable, adjustable and
 * deletable like anything else.
 */
function runAuto(kind: 'levels' | 'contrast' | 'balance') {
  const source = composite.value
  const patch = kind === 'levels' ? autoLevels(source)
    : kind === 'contrast' ? autoContrast(source)
    : autoBalance(source)
  // An auto that computes no change makes no step. The histogram is already
  // where it wants it, and a row that does nothing is worse than no row.
  if (!patch || Object.values(patch).every(value => value === 0)) return
  const label = AUTO_EDITS.find(auto => auto.id === kind)?.label ?? 'Auto'
  // Autos ALWAYS append. Try-then-replace exists for doorway clicks whose
  // step starts at identity; an Auto lands complete, with nothing for the
  // person to touch first — replacing anything on its way in (or being
  // replaced later for never having been touched) reads as steps vanishing.
  addAdjustOp(label, { section: 'tone', ...patch }, { pristine: false })
}

const adjustInspectorParams = computed<Record<string, any>>(
  () => (selectedAdjustOp.value as any)?.params || {}
)

function onAdjustInspectorChange(patch: Record<string, any>, coalesceKey: string) {
  const op = selectedAdjustOp.value as any
  if (!op) return
  const before = { ...(op.params || {}) }
  dismissCanvasFeedback()
  // Touching a step's properties is the substantive change that makes it
  // stick: the next strip or Adjust click stacks rather than replaces.
  pristineSnapshots.delete(op.id)
  stack.setParams(op.id, patch, coalesceKey)
  // Migrated blob steps rename by content; fine-grained steps keep the name
  // they were born with.
  const updated = (stack.opById(op.id) as any)?.params || {}
  if (isLegacyAdjustBlob(updated)) stack.setLabel(op.id, adjustLabel(updated))
  void previewAdjustment(`adjust:${op.id}`, before, updated)
}

async function commitAdjustInspectorChange() {
  cancelLiveAdjustPreview()
  await render()
  await stack.flush()
}

// -- scope conversions: whole-image step ⇄ scoped step -----------------------

/**
 * A scoped step's settings back into whole-image params: only the values that
 * differ from the projection's defaults, so the step reads as what it does.
 */
function scopedSettingsToParams(
  settings: Record<string, any> | undefined,
): Record<string, any> {
  const params: Record<string, any> = {}
  for (const control of PHOTO_ADJUSTMENT_CONTROLS) {
    const value = settings?.[control.key]
    if (value === undefined) continue
    if (control.kind === 'curve') {
      if (JSON.stringify(value) !== JSON.stringify(control.default)) {
        params[control.key] = value
      }
    } else if (
      typeof value === 'number' && Number.isFinite(value)
      && value !== control.default
    ) {
      params[control.key] = value
    }
  }
  return params
}

/**
 * Whether the selected whole-image step can carry a mask.
 *
 * Every step the current build writes can: a group edit names its group, and a
 * Looks step scopes as one `look` region. Only legacy steps — a migrated blob,
 * or a `filter` preset from before looks were parameter bundles — stay
 * whole-image, because there is no single region kind to convert them into.
 */
const selectedAdjustScopeKind = computed<
  Exclude<MaskedAdjustmentKind, 'adjust'> | null
>(() => {
  const op = selectedAdjustOp.value as any
  if (op?.params?.look) return 'look'
  const group = op?.params?.section ? photoAdjustmentGroup(op.params.section) : null
  return group ? group.id as Exclude<MaskedAdjustmentKind, 'adjust'> : null
})

/**
 * Convert the selected whole-image step into a scoped one, keeping its
 * values. One undo step. The mask is authored at the head of the stack, so
 * the step stays in place only while the geometry there matches its own;
 * otherwise it moves to the end, the one frame those pixels are true in.
 */
async function limitSelectedAdjustToSelection() {
  const op = selectedAdjustOp.value as any
  const mask = selection.value
  const kind = selectedAdjustScopeKind.value
  const doc = stack.doc.value
  if (!op || !mask || !kind || !doc) return
  const index = doc.edits.findIndex(edit => edit.id === op.id)
  if (index < 0) return
  pristineSnapshots.delete(op.id)

  const headFrame = payloadFrame()
  const stepFrame = payloadFrame(index)
  const inPlace = JSON.stringify(headFrame) === JSON.stringify(stepFrame)
  const frame = inPlace ? stepFrame : headFrame
  const opId = newOpId()
  const regionId = newOpId()
  // `section` is the whole-image marker; the region carries the same meaning
  // as its `kind`. `look` survives, because it names WHICH look either way.
  const { section: _section, ...values } = op.params ?? {}
  const settings: RetouchRegionSettings = {
    ...DEFAULT_RETOUCH_REGION_SETTINGS,
    ...values,
  }

  // The full scope snapshot: a matching gradient stays parametric, a tracked
  // multi-gesture selection keeps its ingredients, a semantic single gesture
  // keeps its name — the same contract creating a scoped step has.
  const scope = activeAdjustmentScope()
  if (!scope) return
  let region: RetouchRegion
  if (scope.kind === 'gradient') {
    const canonical = frame
      ? payloadToDocumentTransform(frame) ?? undefined
      : undefined
    const authored = authoredGradient(
      scope.gradient, frame, canonical as Affine | undefined, inPlace ? index : -1,
    )
    if (!authored) return
    region = {
      id: regionId,
      kind,
      enabled: true,
      mask: authored,
      payload_to_document: canonical as number[] | undefined,
      payload_frame: frame,
      sampled_input_hash: null,
      settings,
    }
  } else if (
    scope.kind === 'recipe'
    || (scope.kind === 'raster' && scope.semantic)
  ) {
    const entries = scope.kind === 'recipe'
      ? scope.entries
      : [{ mode: 'add' as const, mask: scope.mask, semantic: scope.semantic }]
    const components = await buildRecipeComponents(
      entries, opId, regionId, inPlace ? index : undefined,
    )
    if (!components) return
    region = regionWithMaskComponents({
      id: regionId,
      kind,
      enabled: true,
      payload_frame: frame,
      sampled_input_hash: null,
      settings,
    } as RetouchRegion, components)
  } else {
    const compact = compactSelectionMask(mask)
    if (!compact) return
    const maskRef = await stack.uploadPayload(
      `${opId}-${regionId}-mask-${newOpId()}.png`,
      await canvasToBlob(compact.mask),
    )
    payloadCache.set(`${maskRef}@0`, compact.mask)
    region = {
      id: regionId,
      kind,
      enabled: true,
      mask_ref: maskRef,
      payload_origin: compact.origin,
      payload_to_document: payloadTransform(
        inPlace ? index : undefined,
        compact.origin,
      ),
      payload_frame: frame,
      sampled_input_hash: null,
      settings,
    }
  }

  // Re-resolve after the await: the step may have been removed meanwhile.
  const current = stack.doc.value
  if (!current || !current.edits.some((edit: any) => edit.id === op.id)) return
  const container: any = {
    id: opId,
    class: 'container',
    enabled: op.enabled,
    label: op.label,
    exec: { kind: 'retouch-regions', version: 1 },
    defaults: { ...DEFAULT_RETOUCH_REGION_SETTINGS },
    regions: [region],
  }
  const edits = current.edits.flatMap((edit: any) =>
    edit.id === op.id ? (inPlace ? [container] : []) : [edit],
  )
  if (!inPlace) edits.push(container)
  stack.replaceEdits(edits)

  // Refining the selection keeps editing this step's mask.
  maskedAdjustOpId = opId
  maskedAdjustRegionId = regionId
  maskedAdjustSpec = null
  selectedOpId.value = opId
  selectedRetouchRegionId.value = regionId
  selectedMaskComponentId.value = null
  // The selection moved into the step's mask. Consuming it keeps the next
  // gesture a clean single component instead of a flatten on top of coverage
  // the mask already owns.
  consumeWorkspaceSelection()
  // A ramp's guides say where it is; every other mask gets the wash.
  selectedRetouchFeedbackVisible.value = scope.kind !== 'gradient'
  await render()
  await refreshRetouchInput()
  await refreshRetouchFeedback()
}

/**
 * Convert the selected scoped step back to a whole-image one, keeping its
 * values and its place in the stack. The mask (and its blend dials) is what
 * is given up. One undo step.
 */
async function unscopeSelectedRegion() {
  await unscopeRegion(selectedRetouchRegionId.value)
}

/**
 * Removing a step's Mask MEANS Whole image — explicitly, never as a silent
 * reinterpretation of whatever components were left. The values survive; the
 * mask, its components and its blend dials are what is given up.
 */
async function unscopeRegion(regionId: string | null) {
  const location = retouchRegionLocation(regionId)
  const doc = stack.doc.value
  if (!location || !doc) return
  const { op, region } = location
  if (!isMaskedAdjustmentKind(region.kind)) return
  const look = region.kind === 'look' ? lookById(region.settings?.look ?? '') : null
  const group = region.kind === 'look'
    ? null
    : photoAdjustmentGroup(region.kind === 'adjust' ? 'light' : region.kind)
  const opId = newOpId()
  const step: any = {
    id: opId,
    class: 'parametric',
    enabled: op.enabled && region.enabled,
    label: op.regions.length === 1
      ? op.label
      : look?.label ?? group?.label ?? 'Adjust',
    exec: { kind: 'adjust' },
    // A look step is marked by WHICH look it is; every other kind by its
    // group's section. The values themselves are the same either way.
    params: look
      ? { look: look.id, ...scopedSettingsToParams(region.settings) }
      : { section: group?.section ?? 'tone', ...scopedSettingsToParams(region.settings) },
  }
  const edits = doc.edits.flatMap((edit: any) => {
    if (edit.id !== op.id) return [edit]
    const regions = (edit.regions ?? []).filter(
      (candidate: RetouchRegion) => candidate.id !== region.id,
    )
    return regions.length ? [{ ...edit, regions }, step] : [step]
  })
  disarmMaskedAdjustmentEditing()
  fragileRetouchRegions.forget(region.id)
  selectedRetouchRegionId.value = null
  selectedRetouchFeedbackVisible.value = false
  stack.replaceEdits(edits)
  selectedOpId.value = opId
  await render()
  await refreshRetouchInput()
  await refreshRetouchFeedback()
}

/**
 * Route the next selection gestures into the selected scoped step's mask.
 * Every completed gesture republishes the whole mask; combine modes apply
 * as the island says.
 */
function armScopedMaskEditing() {
  const location = retouchRegionLocation(selectedRetouchRegionId.value)
  if (!location || !isMaskedAdjustmentKind(location.region.kind)) return
  maskedAdjustOpId = location.op.id
  maskedAdjustRegionId = location.region.id
  maskedAdjustSpec = null
  // The session edits the STEP's mask: bind it as the live selection so the
  // tools start from what the step actually covers.
  if (!maskSessionBound.value) void bindMaskSessionSelection()
  armSelectTool(lastSelectTool.value ?? 'brush', true)
}

/**
 * Replace the base component: the NEXT gesture — and only it — lands with
 * combine New as the new base, keeping every modifier. One-shot and explicit,
 * because an ordinary New gesture means "fresh workspace selection", never a
 * silent base swap. Set after arming, because arming a brush deliberately
 * rewrites the combine to Add.
 */
function armMaskBaseReplace() {
  armScopedMaskEditing()
  selectCombine.value = 'new'
  maskBaseReplaceArmed = true
}

/**
 * A step from before the fine-grained split: no section marker, not a strip
 * step. Its inspector shows the full legacy surface, and its label tracks its
 * content because nothing else names it.
 */
function isLegacyAdjustBlob(params: Record<string, any>): boolean {
  if (!params || params.section || params.look) return false
  const keys = Object.keys(params)
  if (keys.length && keys.every(key => key === 'filter' || key === 'filterAmount')) return false
  if (keys.length && effectLookStepOf(params)) return false
  return true
}

// -- crop ---------------------------------------------------------------------

const cropOpId = ref<string | null>(null)
const cropAspect = ref<string>('free')

function cropParamsOf() {
  const op = cropOpId.value ? stack.opById(cropOpId.value) : null
  return (op as any)?.params || { rect: { x: 0.5, y: 0.5, width: 1, height: 1 } }
}

/**
 * @param live  A drag in progress. The crop itself updates every frame, but the
 *              co-transform — which reloads and rewrites every spatial payload
 *              above the crop — waits for the gesture to end. Running it per
 *              frame rewrote a dozen payloads per mouse move and made the drag
 *              lag far enough behind the pointer to land somewhere else.
 */
async function applyCropChange(
  patch: Record<string, any>,
  coalesceKey = 'crop',
  live = false
) {
  if (!stack.doc.value) return
  const before = liveCropBefore ?? JSON.parse(JSON.stringify(stack.doc.value))
  if (live && !liveCropBefore) liveCropBefore = before
  if (!cropOpId.value) {
    const opId = newOpId()
    stack.addOp({
      id: opId, class: 'parametric', enabled: true, label: 'Crop',
      exec: { kind: 'crop' },
      params: {
        rect: { x: 0.5, y: 0.5, width: 1, height: 1 },
        rotation: 0, cropRotation: 0, rotation90: 0,
        flipX: false, flipY: false, ...patch,
      },
    } as any)
    cropOpId.value = opId
    selectedOpId.value = opId
  } else {
    stack.setParams(cropOpId.value, patch, coalesceKey)
  }
  // StackCropCanvas already draws the moving crop directly from cropInput.
  // Replaying the document here is both invisible in Crop mode and expensive:
  // every pointer move invalidates the crop and everything above it.
  if (live) return
  // A geometry change moves every payload above it into a new space. `before`
  // is the document as it stood when the GESTURE started, so a drag rewrites
  // payloads once, from where they were, rather than in accumulating steps.
  liveCropBefore = null
  await afterGeometryChange(before)
  void render()
}

/** The document as it stood when the current crop drag began. */
let liveCropBefore: any = null

/**
 * The image the crop step sees. Rendering only the ops BELOW it is what lets
 * the region outside the crop be dimmed rather than gone — and what makes
 * widening the crop later reveal real pixels.
 */
const cropInput = ref<HTMLCanvasElement | null>(null)

async function renderCropInput() {
  const doc = stack.doc.value
  if (!doc || !baseInfo.value) return
  const index = cropOpId.value
    ? doc.edits.findIndex(op => op.id === cropOpId.value)
    : doc.edits.length
  try {
    cropInput.value = await compositor.renderUpTo(doc, index < 0 ? doc.edits.length : index)
  } catch {
    cropInput.value = composite.value
  }
}

/** The crop rectangle the overlay draws, defaulting to the whole frame. */
const cropRect = computed<CropRect>(() => {
  const params = cropParamsOf()
  const rect = params.rect ?? { x: 0.5, y: 0.5, width: 1, height: 1 }
  return {
    x: rect.x, y: rect.y, width: rect.width, height: rect.height,
    aspectRatio: cropAspectRatio.value,
    rotation: params.cropRotation ?? 0,
  }
})

/**
 * Locked ratio in PIXEL space, which is what the ported resize maths expects;
 * it divides through by the image's own ratio to work in normalized coords.
 */
const cropAspectRatio = computed<number | null>(() => {
  const preset = CROP_ASPECTS.find(a => a.id === cropAspect.value)
  if (!preset || preset.ratio == null) return null
  const frame = cropInput.value
  if (preset.ratio === -1) return frame ? frame.width / frame.height : null
  return preset.ratio
})

/** The selected annotation, whose properties the inspector edits. */
/**
 * The annotation whose properties the inspector edits.
 *
 * Not gated on being in Annotate: the row IS the annotation, so selecting it
 * anywhere should show what it is and let you change it. Entering the mode is
 * what makes it draggable on the canvas, which is a separate thing.
 */
const selectedShape = computed<Shape | null>(() => {
  if (!selectedShapeId.value) return null
  return annotateShapes.value.find(s => s.id === selectedShapeId.value) ?? null
})

/** The canvas owns marquee membership; the host still owns the primary shape. */
const selectedAnnotationShapes = computed<Shape[]>(() => {
  const canvasSelection = annotateRef.value?.selectedShapes
  if (canvasSelection?.length) return canvasSelection
  return selectedShape.value ? [selectedShape.value] : []
})

function onShapeChange(patch: Record<string, any>, continuous = false) {
  const id = selectedShapeId.value
  if (!id) return
  onAnnotationsChange(
    annotateShapes.value.map(s => (s.id === id ? { ...s, ...patch } as Shape : s))
  )
  if (!continuous) annotateGesture.value += 1
}

function onSelectedShapesChange(patch: Record<string, any>, continuous = false) {
  const selectedIds = new Set(selectedAnnotationShapes.value.map(shape => shape.id))
  if (!selectedIds.size) return
  onAnnotationsChange(
    annotateShapes.value.map(shape =>
      selectedIds.has(shape.id) ? { ...shape, ...patch } as Shape : shape
    )
  )
  if (!continuous) annotateGesture.value += 1
}

function commitSelectedShapesChange() {
  annotateGesture.value += 1
}

function onSubbarCommit(kind: 'crop' | 'annotation') {
  if (kind === 'crop') onCropCommit()
  else annotateGesture.value += 1
}

// -- the selected annotation AS an object ------------------------------------

/**
 * The floating strip carries the verbs that are about the annotation as an
 * object — where it sits in the pile, another one of it, no more of it — while
 * the inspector carries its properties. Both are needed: a strip that also
 * held settings would be a second inspector, and an inspector alone puts the
 * object's own verbs across the screen from the object.
 *
 * It hides while a text session owns the caret, along with the handles: during
 * editing the shape is a text field, and chrome sitting over it is in the way.
 * It hides during a gesture too — a move publishes nothing until the mouse
 * comes up, so a strip positioned from the document would sit where the shape
 * was grabbed and then jump to catch up.
 */
const annotationIslandVisible = computed(() =>
  selectedAnnotationShapes.value.length > 0 &&
  annotationOverlayActive.value &&
  !annotateRef.value?.editingText &&
  !annotateRef.value?.gestureActive
)

/** The frame the shapes are normalized against. */
const frameSize = computed(() => {
  const source = composite.value
  if (source) return { width: source.width, height: source.height }
  const canvas = stack.doc.value?.canvas
  return canvas ? { width: canvas.width, height: canvas.height } : null
})

/**
 * An annotation selection's z-order IS its block position in the stack.
 * Selected rows retain their internal order while the block crosses the
 * unselected annotation peers.
 */
function annotationOrder(direction: 'front' | 'back'): string[] | null {
  const doc = stack.doc.value
  if (!doc) return null
  const opIds = selectedAnnotationShapes.value.flatMap(shape => {
    const opId = opIdForShape(shape.id)
    return opId ? [opId] : []
  })
  return annotationBlockOrder(
    doc.edits.map(op => ({
      id: op.id,
      annotate: (op as any).exec?.kind === 'annotate',
    })),
    opIds,
    direction
  )
}

const canBringAnnotationToFront = computed(() => !!annotationOrder('front'))

const canSendAnnotationToBack = computed(() => !!annotationOrder('back'))

/**
 * Restack the annotation past its neighbours. Routed through the same
 * post-move path as a dragged row — the move cannot change geometry, but the
 * stack is the stack, and one path that co-transforms and re-renders is better
 * than a second that assumes it never has to.
 */
async function moveAnnotation(direction: 'front' | 'back') {
  const doc = stack.doc.value
  const order = annotationOrder(direction)
  if (!doc || !order) return

  const before = JSON.parse(JSON.stringify(doc))
  stack.reorderOps(order)
  await afterGeometryChange(before)
  void render()
}

/**
 * A copy of the selected annotation, offset so it reads as its own object.
 *
 * The offset goes through the geometry transformer rather than nudging x and
 * y: a brush path and a curved arrow keep their geometry in point arrays, and
 * moving a shape's anchor while its points stay put tears it in half.
 */
function duplicateAnnotation() {
  if (annotateRef.value) {
    annotateRef.value.duplicateSelected()
    return
  }
  const shape = selectedShape.value
  const frame = frameSize.value
  if (!shape || !frame) return

  const [clone] = transformShapes(
    // Shapes are pure JSON; a round trip both detaches the reactive proxy and
    // deep-copies the colors and style nested inside.
    [JSON.parse(JSON.stringify(shape))],
    [1, 0, 0, 1, 0.02 * frame.width, 0.02 * frame.height],
    frame.width, frame.height, frame.width, frame.height
  ) as Shape[]
  clone.id = generateShapeId()

  // One annotation, one step: handing the whole list back makes the copy a
  // step of its own at the top of the stack, exactly like drawing it would.
  onAnnotationsChange([...annotateShapes.value, clone])
  annotateGesture.value += 1
  selectedShapeId.value = clone.id
}

/** Put the caret in the selected text shape without hunting for a double-click. */
function editSelectedText() {
  const id = selectedShapeId.value
  if (id) annotateRef.value?.editText(id)
}

/**
 * Delete through the op, not the canvas: one shape is one step, so removing
 * the step IS the deletion — the same path the Delete key takes.
 */
function deleteSelectedAnnotation() {
  if (annotateRef.value) {
    annotateRef.value.deleteSelected()
    return
  }
  const id = selectedShapeId.value
  const opId = id ? opIdForShape(id) : null
  selectedShapeId.value = null
  if (opId) void removeOpWithGeometry(opId)
}

/**
 * Selecting a shape overrides the toolbar with THAT shape's status. The same
 * controls are a remote for the selection while one exists and initial
 * conditions when none does — showing next-shape defaults over a selected
 * shape made the toolbar lie about the thing with handles on it.
 */
watch(selectedShape, shape => {
  if (!shape) return
  const any = shape as any
  const stroke = any.strokeColor ?? any.textColor
  // Paint and all: the next shape inherits the selected one's gradient the
  // same way it inherits its color, because they are the same slot.
  if (stroke) annotatePaint.value = stroke
  if (typeof any.strokeWidth === 'number') annotateStrokeWidth.value = any.strokeWidth
  if ('backgroundColor' in any) annotateFillColor.value = any.backgroundColor ?? null
  annotateShapeEffect.value = any.style?.effect ?? 'none'
  if (shape.type === 'text') textStyle.value = textStyleOfShape(any)
  if (typeof any.opacity === 'number') annotateOpacity.value = any.opacity
})

/**
 * Colors sampled off the composite, so the pickers can offer the image's own
 * palette rather than only a fixed row of swatches.
 */
/**
 * The two splits in the right-hand column, both dragged and both remembered.
 *
 * How much room the stack deserves against the canvas is the user's call.
 * Properties starts larger because its control surfaces are usually the active
 * work, while the stack remains available above it.
 */
const sidebarWidth = ref(Number(localStorage.getItem('stimma_editor_sidebar')) || 320)
const propertiesHeight = ref(Number(localStorage.getItem('stimma_editor_properties')) || 0)
const sidebarEl = ref<HTMLElement | null>(null)

/**
 * Two thirds of the sidebar by default, measured rather than guessed — a pixel
 * constant is the wrong height on every window that is not the one it was
 * picked on. Only until the user drags it, after which their number wins.
 */
watch(sidebarEl, element => {
  if (!element || propertiesHeight.value) return
  propertiesHeight.value = Math.round(element.getBoundingClientRect().height * (2 / 3))
}, { flush: 'post' })

/** Drag along one axis, clamped, persisted on release. */
function startResize(
  event: PointerEvent,
  target: { value: number },
  key: string,
  axis: 'x' | 'y',
  min: number,
  max: number
) {
  event.preventDefault()
  const start = axis === 'x' ? event.clientX : event.clientY
  const startValue = target.value
  const onMove = (move: PointerEvent) => {
    const now = axis === 'x' ? move.clientX : move.clientY
    // Both handles sit on the leading edge of what they size, so the panel
    // grows as the pointer moves toward the origin.
    target.value = Math.max(min, Math.min(max, startValue + (start - now)))
  }
  const onUp = () => {
    localStorage.setItem(key, String(target.value))
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
  }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
}

const startSidebarResize = (event: PointerEvent) =>
  startResize(event, sidebarWidth, 'stimma_editor_sidebar', 'x', 260, 640)
const startPropertiesResize = (event: PointerEvent) =>
  startResize(
    event,
    propertiesHeight,
    'stimma_editor_properties',
    'y',
    140,
    Math.round((sidebarEl.value?.getBoundingClientRect().height ?? 1140) * (2 / 3)),
  )

const propertiesPanelStyle = computed(() => ({
  height: propertiesHeight.value + 'px',
  maxHeight: '66.6667%',
}))

const imagePalette = ref<Array<{ r: number; g: number; b: number; a?: number }>>([])

function samplePalette() {
  const source = composite.value
  if (!source) return
  const scratch = document.createElement('canvas')
  scratch.width = 48
  scratch.height = 48
  const ctx = scratch.getContext('2d', { willReadFrequently: true })
  if (!ctx) return
  ctx.drawImage(source, 0, 0, 48, 48)
  const data = ctx.getImageData(0, 0, 48, 48).data
  // Coarse quantisation, most-common first: enough to surface the picture's
  // actual colors without pretending to be a clustering algorithm.
  const buckets = new Map<string, { r: number; g: number; b: number; n: number }>()
  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] < 128) continue
    const key = `${data[i] >> 5}-${data[i + 1] >> 5}-${data[i + 2] >> 5}`
    const bucket = buckets.get(key)
    if (bucket) { bucket.r += data[i]; bucket.g += data[i + 1]; bucket.b += data[i + 2]; bucket.n++ }
    else buckets.set(key, { r: data[i], g: data[i + 1], b: data[i + 2], n: 1 })
  }
  imagePalette.value = [...buckets.values()]
    .sort((a, b) => b.n - a.n)
    .slice(0, 8)
    .map(c => ({ r: Math.round(c.r / c.n), g: Math.round(c.g / c.n), b: Math.round(c.b / c.n), a: 1 }))
}

/** A drag is many changes and one undo step. */
const cropGesture = ref(0)
const cropGestureKey = computed(() => `crop:${cropOpId.value}:${cropGesture.value}`)

function onCropRectChange(next: CropRect) {
  void applyCropChange(
    { rect: { x: next.x, y: next.y, width: next.width, height: next.height },
      cropRotation: next.rotation ?? 0 },
    cropGestureKey.value,
    true
  )
}

/** The drag ended: settle the geometry and start a new undo step. */
function onCropCommit() {
  cropGesture.value += 1
  void applyCropChange({}, cropGestureKey.value)
}

function chooseAspect(id: string) {
  cropAspect.value = id
  const preset = CROP_ASPECTS.find(a => a.id === id)
  const doc = stack.doc.value
  if (!doc) return
  const frame = cropInput.value ?? doc.canvas
  const ratio = preset?.ratio === -1
    ? frame.width / frame.height
    : preset?.ratio ?? null
  void applyCropChange({
    rect: cropRectForAspect(ratio, frame.width, frame.height),
  })
}

function rotateQuarter() {
  void applyCropChange({ rotation90: (((cropParamsOf().rotation90 ?? 0) + 1) % 4) as 0 | 1 | 2 | 3 })
}

function flip(axis: 'flipX' | 'flipY') {
  void applyCropChange({ [axis]: !cropParamsOf()[axis] })
}

// -- paint ---------------------------------------------------------------------

/**
 * The Paint layer this session is painting into. A layer IS a step, so
 * "New layer" simply forgets the current one and the next stroke creates the
 * next Paint row.
 */
let paintStrokeCommitQueue: Promise<void> = Promise.resolve()

/**
 * Op ids this view has put into the document. An id in here that is no longer
 * in the document was deleted, and no queued stroke commit may re-create it —
 * this set, not watcher timing, is what makes the drop race-free. Never
 * cleared: ids are ULIDs, so the set only ever holds this session's few.
 */
const committedPaintOps = new Set<string>()

async function commitPaintStroke(
  layer: HTMLCanvasElement,
  readsPixels: boolean,
  revision: number,
  opId: string,
) {
  if (!stack.doc.value) return
  const blob = await canvasToBlob(layer)
  const ref = await stack.uploadPayload(`${opId}-layer.png`, blob)
  let payloadRevision = 0

  if (!stack.opById(opId)) {
    // The op is created by the FIRST commit, so "not in the document" normally
    // means exactly that. But an id this session already added and cannot find
    // now names a DELETED layer — the row trashed or the add undone while this
    // commit waited in the queue — and re-adding it would resurrect the whole
    // accumulated layer. Same if the session itself ended while queued.
    if (paintOpId.value !== opId || committedPaintOps.has(opId)) return
    const { head } = stackHashes(stack.doc.value)
    committedPaintOps.add(opId)
    stack.addOp({
      id: opId,
      class: 'container',
      enabled: true,
      label: 'Paint',
      exec: { kind: 'paint' },
      raster_ref: ref,
      payload_to_document: payloadTransform(),
      payload_frame: payloadFrame(),
      blend: { feather_px: 0, opacity: 1 },
      // A pixel-reading engine baked what was underneath, so its layer carries
      // an advisory hash exactly like a generative patch.
      ...(readsPixels ? { sampled_input_hash: head } : {}),
    } as any)
    if (paintOpId.value === opId) selectedOpId.value = opId
  } else {
    const existing = stack.opById(opId) as any
    const opIndex = stack.doc.value.edits.findIndex(op => op.id === opId)
    // The uploaded layer is the current stage raster. Re-anchor that complete
    // payload into document space before replacing the old master pixels.
    existing.payload_to_document = payloadTransform(opIndex >= 0 ? opIndex : undefined)
    existing.payload_frame = payloadFrame(opIndex >= 0 ? opIndex : undefined)
    // The payload changed under the same ref; nudge the cache so the composite
    // picks it up.
    invalidatePayload(ref)
    stack.touchOp(opId)
    payloadRevision = (stack.opById(opId) as any)?._revision ?? 0
  }
  // The preview may only hand off after the compositor has rendered THIS
  // snapshot. Keeping it under the same ref@revision key loadAnchored requests
  // removes the stable-filename/browser-cache race entirely.
  payloadCache.set(`${ref}@${payloadRevision}`, layer)
  // The composite owns the stroke from here; the overlay handing off rather
  // than keeping a copy is what stops the halo and the paint that outlived
  // its own step being switched off.
  await render()
  if (paintOpId.value === opId) paintRef.value?.clearDisplay(revision)
}

/**
 * Pointer-up must stay cheap and synchronous: take the already-snapshotted
 * layer and queue its persistence. Serializing commits prevents two encodes
 * and uploads to the same raster_ref from finishing in reverse order.
 */
function onPaintStroke(
  layer: HTMLCanvasElement,
  readsPixels: boolean,
  revision: number,
) {
  // Reserve the step synchronously so another stroke emitted before the first
  // upload completes still targets this same layer.
  const opId = paintOpId.value || newOpId()
  paintOpId.value = opId
  paintStrokeCommitQueue = paintStrokeCommitQueue
    .then(() => commitPaintStroke(layer, readsPixels, revision, opId))
    .catch(err => {
      console.error('[imageStack] paint stroke commit failed', err)
      error.value = apiErrorMessage(err, 'Could not apply the paint stroke.')
    })
}

/**
 * Double-clicking a row re-enters THAT step rather than starting another: a
 * Paint layer keeps painting into itself, an Annotate step keeps accumulating
 * shapes, and a Crop reopens on its own input — which is what makes a second
 * crop a deliberate act rather than the only thing you can do.
 */
function enterContainerOp(op: any) {
  // Re-entering a step is canvas work: the selection tool lets the pointer go.
  disarmSelect()
  if (op.exec?.kind === 'crop') {
    family.value = 'crop'
    sub.value = null
    cropOpId.value = op.id
    cropAspect.value = 'free'
    void renderCropInput()
    return
  }
  if (op.class !== 'container') return
  if (op.exec?.kind === 'annotate') {
    // Re-entering an annotation means selecting it, since it is the step.
    family.value = 'annotate'
    sub.value = null
    selectedShapeId.value = (op.params?.shapes ?? [])[0]?.id ?? null
    return
  }
  if (op.exec?.kind === 'retouch-regions') {
    void enterRetouchOp(op.id)
    return
  }
  // Old documents used `retouch` (and, briefly, `sketch`) for raster Paint
  // layers. They remain re-enterable, but region-based Retouch will have its
  // own executor and must never be mistaken for a Paint layer.
  if (op.exec?.kind === 'paint' || op.exec?.kind === 'retouch' || op.exec?.kind === 'sketch') {
    void enterPaintOp(op.id)
  }
}

/**
 * Make the layer now, not on the next stroke.
 *
 * Clicking New layer and seeing nothing happen is the same as the button being
 * broken — and it made the first layer and every later one behave differently.
 * An empty layer composites as a no-op, so an unused one costs nothing but the
 * row that tells you it is there.
 */
async function startNewPaintLayer() {
  if (!stack.doc.value || !composite.value) return
  const opId = newOpId()
  const blank = document.createElement('canvas')
  blank.width = composite.value.width
  blank.height = composite.value.height
  const ref = await stack.uploadPayload(`${opId}-layer.png`, await canvasToBlob(blank))
  committedPaintOps.add(opId)
  stack.addOp({
    id: opId,
    class: 'container',
    enabled: true,
    label: 'Paint',
    exec: { kind: 'paint' },
    raster_ref: ref,
    payload_to_document: payloadTransform(),
    payload_frame: payloadFrame(),
    blend: { feather_px: 0, opacity: 1 },
  } as any)
  paintOpId.value = opId
  selectedOpId.value = opId
  paintInitialLayer.value = null
  paintRef.value?.reset()
  void render()
}

function resetPaintSession() {
  paintLayerLoadRevision += 1
  paintOpId.value = null
  paintLayerReady.value = true
  // Without this the next layer starts holding the previous one's pixels: the
  // canvas reloads `initialLayer` on any source change, so leaving it set
  // quietly copies the old strokes into the new step.
  paintInitialLayer.value = null
  paintRef.value?.reset()
}

/** Re-entering a Paint row paints into ITS layer rather than starting another. */
const paintInitialLayer = ref<HTMLCanvasElement | null>(null)

/**
 * The session's op leaving the document — row trashed, its add undone, the
 * document swapped — ends the session, whatever path removed it. Otherwise the
 * next stroke finds `paintOpId` naming a missing op and re-creates it from the
 * still-accumulated layer canvas: every "deleted" stroke rises from the dead
 * on mouse-up.
 *
 * Deliberately NOT flush: 'sync'. Reordering removes and re-inserts the op in
 * two splices, and a synchronous watcher fires between them, reading a move as
 * a deletion. The batched pre-flush pass only ever sees settled edit lists;
 * the commit queue's own `committedPaintOps` guard covers the removal-vs-
 * queued-commit race, so nothing here depends on firing first.
 *
 * The first stroke's not-yet-committed op is not a removal: it was never in
 * the previous edit list, so it cannot transition out of it.
 */
watch(
  () => (stack.doc.value?.edits ?? []).map(op => op.id),
  (ids, oldIds) => {
    const opId = paintOpId.value
    if (!opId || !oldIds) return
    if (oldIds.includes(opId) && !ids.includes(opId)) resetPaintSession()
  },
)

async function enterPaintOp(opId: string) {
  const op = stack.opById(opId) as any
  if (!op?.raster_ref || !stack.doc.value) return
  family.value = 'paint'
  if (paintOpId.value === opId && paintLayerReady.value) return
  // Re-entered ops are "committed" too: deleting the row while a stroke is
  // still uploading must drop that commit, not re-create the row.
  committedPaintOps.add(opId)
  const loadRevision = ++paintLayerLoadRevision
  paintOpId.value = opId
  paintLayerReady.value = false
  paintInitialLayer.value = null
  paintRef.value?.reset()
  try {
    const image = await loadImage(stack.payloadUrl(op.raster_ref, op._revision ?? 0))
    const doc = stack.doc.value
    const current = stack.opById(opId) as any
    if (
      loadRevision !== paintLayerLoadRevision
      || paintOpId.value !== opId
      || !doc
      || !current
    ) return
    const index = doc.edits.findIndex(candidate => candidate.id === opId)
    const now = geometryBelow(doc, index >= 0 ? index : doc.edits.length)
    const canonical = (current.payload_to_document as Affine | undefined)
      ?? (current.payload_frame
        ? payloadToDocumentTransform(current.payload_frame) ?? undefined
        : undefined)
    paintInitialLayer.value = canonical
      ? rewritePayload(image, multiply(now.matrix, canonical), now.width, now.height)
      : (() => {
          const unanchored = document.createElement('canvas')
          unanchored.width = image.naturalWidth
          unanchored.height = image.naturalHeight
          unanchored.getContext('2d')!.drawImage(image, 0, 0)
          return unanchored
        })()
    paintLayerReady.value = true
  } catch (paintLayerError) {
    if (loadRevision !== paintLayerLoadRevision || paintOpId.value !== opId) return
    resetPaintSession()
    console.error('[imageStack] could not load Paint layer', paintLayerError)
    error.value = 'Could not load that Paint layer.'
  }
}

/**
 * Reconcile Photoshop-style layer selection with the session-owned paint id.
 * A selected Paint row wins; otherwise an existing top Paint row is current.
 */
function syncImplicitPaintLayer() {
  if (family.value !== 'paint') return
  const target = implicitPaintLayer(stack.doc.value?.edits ?? [], selectedOpId.value)
  if (target) {
    if (paintOpId.value !== target.id) void enterPaintOp(target.id)
  } else if (paintOpId.value) {
    resetPaintSession()
  }
}

// Row selection can also move by keyboard or through another canvas surface;
// all selection paths carry the same Paint-layer meaning as a sidebar click.
watch(selectedOpId, syncImplicitPaintLayer)

// -- retouch --------------------------------------------------------------------

const DEFAULT_RETOUCH_REGION_SETTINGS: RetouchRegionSettings = {
  opacity: 1,
  feather_px: 0,
  // The current Heal kernel performs its own local matching. These explicit,
  // adjustable finishing passes remain off until their renderers land.
  match_color: 0,
  match_noise: 0,
  ...photoAdjustmentRenderParams({}),
}

type MaskedAdjustmentKind =
  | 'light' | 'color' | 'detail'
  | 'mixer' | 'point' | 'grade'
  | 'effects' | 'stylize'
  | 'look'
  | 'adjust'
const MASKED_ADJUSTMENT_SUBS = [
  'light', 'color', 'detail', 'mixer', 'point', 'grade', 'effects', 'stylize',
  'look',
] as const

function isMaskedAdjustmentSub(value: string | null): value is Exclude<MaskedAdjustmentKind, 'adjust'> {
  return MASKED_ADJUSTMENT_SUBS.includes(value as any)
}

function isMaskedAdjustmentKind(value: RetouchRegionKind): value is MaskedAdjustmentKind {
  return value === 'adjust' || isMaskedAdjustmentSub(value)
}

interface RetouchGestureMetadata {
  tool: string
  source?: { x: number; y: number }
  target?: { x: number; y: number }
}

let retouchCommitQueue: Promise<void> = Promise.resolve()
let maskedAdjustCommitQueue: Promise<void> = Promise.resolve()
/** The one scoped-Adjust child whose mask the selection palette is editing. */
let maskedAdjustRegionId: string | null = null
/** Its container op — one single-region container per scoped Adjust step. */
let maskedAdjustOpId: string | null = null
/** A generative op whose mask session is armed: gestures land as ITS components. */
let maskedGenerativeOpId: string | null = null
/** One-shot: the next New gesture replaces the armed step's base component. */
let maskBaseReplaceArmed = false
/**
 * Creation-time identity for the armed scoped step: what an Adjust click
 * chose. Consumed by the mask commit when the region does not exist yet;
 * mask re-edits of an existing region carry no spec.
 */
let maskedAdjustSpec: {
  kind: Exclude<MaskedAdjustmentKind, 'adjust'>
  label: string
  seed?: Record<string, any>
} | null = null
const fragileRetouchRegions = new FragileEntryTracker()

/** Stop routing selection gestures into a scoped step's mask. */
function disarmMaskedAdjustmentEditing() {
  maskedAdjustRegionId = null
  maskedAdjustOpId = null
  maskedAdjustSpec = null
  maskBaseReplaceArmed = false
}

/**
 * Remove the current identity child before another masked tool takes its
 * place. Cancellation is recorded even when its mask upload is still in
 * flight, so that completion cannot resurrect the discarded child.
 */
function discardFragileMaskedAdjustment() {
  const regionId = maskedAdjustRegionId ?? selectedRetouchRegionId.value
  if (!fragileRetouchRegions.cancel(regionId)) return
  // Keep the tombstone until every already-queued mask publication for this
  // id has observed it. Clearing it immediately after removing a visible row
  // lets a slower second upload add the child back.
  const pendingPublications = maskedAdjustCommitQueue
  void pendingPublications.finally(() => {
    fragileRetouchRegions.forget(regionId!)
  })

  const location = retouchRegionLocation(regionId)
  if (location) {
    const regions = location.op.regions.filter(
      (region: RetouchRegion) => region.id !== regionId,
    )
    if (regions.length) {
      stack.setRegions(location.op.id, regions)
    } else {
      stack.removeOp(location.op.id)
      if (retouchOpId.value === location.op.id) retouchOpId.value = null
      if (selectedOpId.value === location.op.id) selectedOpId.value = null
    }
    void render().then(refreshRetouchInput)
  }

  if (selectedRetouchRegionId.value === regionId) {
    selectedRetouchRegionId.value = null
    selectedRetouchFeedbackVisible.value = false
  }
  if (hoveredRetouchRegionId.value === regionId) {
    hoveredRetouchRegionId.value = null
    hoveredRetouchMask.value = null
  }
  if (maskedAdjustRegionId === regionId) disarmMaskedAdjustmentEditing()
}

/**
 * Crop a repair to its alpha bounds and derive its retained mask.
 *
 * A spot repair should cost roughly the size of the spot, not two full-frame
 * PNGs. `payload_origin` puts both compact payloads back in authored space.
 */
function compactRetouchPayload(layer: HTMLCanvasElement): {
  result: HTMLCanvasElement
  mask: HTMLCanvasElement
  origin: [number, number]
} | null {
  const source = layer.getContext('2d', { willReadFrequently: true })!
  const full = source.getImageData(0, 0, layer.width, layer.height)
  let minX = layer.width
  let minY = layer.height
  let maxX = -1
  let maxY = -1
  for (let y = 0; y < layer.height; y++) {
    for (let x = 0; x < layer.width; x++) {
      if (full.data[(y * layer.width + x) * 4 + 3] === 0) continue
      minX = Math.min(minX, x)
      minY = Math.min(minY, y)
      maxX = Math.max(maxX, x)
      maxY = Math.max(maxY, y)
    }
  }
  if (maxX < minX || maxY < minY) return null

  const width = maxX - minX + 1
  const height = maxY - minY + 1
  const result = document.createElement('canvas')
  result.width = width
  result.height = height
  result.getContext('2d')!.drawImage(layer, minX, minY, width, height, 0, 0, width, height)

  const mask = document.createElement('canvas')
  mask.width = width
  mask.height = height
  const target = mask.getContext('2d')!
  const pixels = result.getContext('2d', { willReadFrequently: true })!
    .getImageData(0, 0, width, height)
  for (let i = 0; i < pixels.data.length; i += 4) {
    pixels.data[i] = 255
    pixels.data[i + 1] = 255
    pixels.data[i + 2] = 255
  }
  target.putImageData(pixels, 0, 0)
  return { result, mask, origin: [minX, minY] }
}

/** Retain only the authored alpha bounds of a workspace selection. */
function compactSelectionMask(sourceMask: HTMLCanvasElement): {
  mask: HTMLCanvasElement
  origin: [number, number]
} | null {
  const source = sourceMask.getContext('2d', { willReadFrequently: true })!
  const pixels = source.getImageData(0, 0, sourceMask.width, sourceMask.height)
  let minX = sourceMask.width
  let minY = sourceMask.height
  let maxX = -1
  let maxY = -1
  for (let y = 0; y < sourceMask.height; y++) {
    for (let x = 0; x < sourceMask.width; x++) {
      if (pixels.data[(y * sourceMask.width + x) * 4 + 3] === 0) continue
      minX = Math.min(minX, x)
      minY = Math.min(minY, y)
      maxX = Math.max(maxX, x)
      maxY = Math.max(maxY, y)
    }
  }
  if (maxX < minX || maxY < minY) return null

  const mask = document.createElement('canvas')
  mask.width = maxX - minX + 1
  mask.height = maxY - minY + 1
  mask.getContext('2d')!.drawImage(
    sourceMask,
    minX,
    minY,
    mask.width,
    mask.height,
    0,
    0,
    mask.width,
    mask.height,
  )
  return { mask, origin: [minX, minY] }
}

function copyCanvas(source: HTMLCanvasElement): HTMLCanvasElement {
  const copy = document.createElement('canvas')
  copy.width = source.width
  copy.height = source.height
  copy.getContext('2d')!.drawImage(source, 0, 0)
  return copy
}

/**
 * Save the workspace selection as a scoped Adjust step's mask.
 *
 * Creates the step's single-region container on the first publication; every
 * later completed selection gesture republishes the whole mask, so refinement
 * strokes replace the payload instead of creating more rows.
 */
/**
 * Materialise tracked workspace gestures as mask components, each with its
 * own uploaded compact payload or authored gradient geometry, anchored at the
 * frame the target op sits in. Null when nothing usable survived.
 */
async function buildRecipeComponents(
  entries: WorkspaceMaskGesture<HTMLCanvasElement>[],
  opId: string,
  regionId: string,
  opIndex: number | undefined,
): Promise<MaskComponent[] | null> {
  const frame = payloadFrame(opIndex)
  const canonical = frame
    ? payloadToDocumentTransform(frame) ?? undefined
    : undefined
  const components: MaskComponent[] = []
  for (const entry of entries) {
    if (entry.gradient) {
      const authored = authoredGradient(
        entry.gradient, frame, canonical as Affine | undefined, opIndex ?? -1,
      )
      if (!authored) continue
      components.push({
        id: newOpId(),
        mode: entry.mode,
        enabled: true,
        mask: authored,
        ...(canonical ? { payload_to_document: canonical as number[] } : {}),
        ...(frame ? { payload_frame: frame } : {}),
        ...(entry.label ? { label: entry.label } : {}),
      })
      continue
    }
    if (!entry.mask) continue
    const compact = compactSelectionMask(entry.mask)
    if (!compact) continue
    const maskRef = await stack.uploadPayload(
      `${opId}-${regionId}-mask-${newOpId()}.png`,
      await canvasToBlob(compact.mask),
    )
    if (fragileRetouchRegions.isCancelled(regionId)) return null
    payloadCache.set(`${maskRef}@0`, compact.mask)
    components.push({
      id: newOpId(),
      mode: entry.mode,
      enabled: true,
      mask_ref: maskRef,
      payload_origin: compact.origin,
      payload_to_document: payloadTransform(opIndex, compact.origin),
      payload_frame: frame,
      ...(entry.semantic ? { semantic: { ...entry.semantic } } : {}),
      ...(entry.label ? { label: entry.label } : {}),
    })
  }
  return components.length ? components : null
}

async function commitMaskedAdjustmentMask(
  sourceMask: HTMLCanvasElement | null,
  opId: string,
  regionId: string,
  spec: typeof maskedAdjustSpec,
  semantic: AdjustmentScopeSemantic | null = null,
  recipe: WorkspaceMaskGesture<HTMLCanvasElement>[] | null = null,
) {
  const doc = stack.doc.value
  if (!doc) return
  if (fragileRetouchRegions.isCancelled(regionId)) return

  // A semantic single-gesture scope is a recipe of one: the name and the
  // cached raster belong together on a base component either way.
  const entries = recipe
    ?? (semantic && sourceMask
      ? [{ mode: 'add' as const, mask: sourceMask, semantic }]
      : null)

  const existingOp = stack.opById(opId) as any
  const opIndexBefore = doc.edits.findIndex(op => op.id === opId)
  const anchorIndex = opIndexBefore >= 0 ? opIndexBefore : undefined

  let withComponents: RetouchRegion
  if (entries) {
    const components = await buildRecipeComponents(entries, opId, regionId, anchorIndex)
    if (!components) return
    if (fragileRetouchRegions.isCancelled(regionId)) return
    const selected = ((stack.opById(opId) as any)?.regions ?? [] as RetouchRegion[])
      .find((region: RetouchRegion) =>
        region.id === regionId && isMaskedAdjustmentKind(region.kind))
    withComponents = regionWithMaskComponents({
      ...(selected ?? {}),
      id: regionId,
      kind: selected?.kind ?? spec?.kind ?? 'light',
      enabled: selected?.enabled ?? true,
      mask: undefined,
      mask_ref: undefined,
      result_ref: undefined,
      payload_origin: undefined,
      payload_to_document: undefined,
      payload_frame: payloadFrame(anchorIndex),
      sampled_input_hash: null,
      settings: selected?.settings
        ? { ...selected.settings }
        : { ...DEFAULT_RETOUCH_REGION_SETTINGS, ...(spec?.seed ?? {}) },
    } as RetouchRegion, components)
  } else {
    if (!sourceMask) return
    const compact = compactSelectionMask(sourceMask)
    if (!compact) return
    const maskRef = await stack.uploadPayload(
      `${opId}-${regionId}-mask-${newOpId()}.png`,
      await canvasToBlob(compact.mask),
    )
    if (fragileRetouchRegions.isCancelled(regionId)) return
    payloadCache.set(`${maskRef}@0`, compact.mask)
    const selected = ((stack.opById(opId) as any)?.regions ?? [] as RetouchRegion[])
      .find((region: RetouchRegion) =>
        region.id === regionId && isMaskedAdjustmentKind(region.kind))
    withComponents = {
      ...(selected ?? {}),
      id: regionId,
      kind: selected?.kind ?? spec?.kind ?? 'light',
      enabled: selected?.enabled ?? true,
      mask_ref: maskRef,
      // A republished raster replaces a parametric ramp outright — a region
      // holding both would render the stale gradient and ignore the pixels.
      mask: undefined,
      mask_components: undefined,
      result_ref: undefined,
      payload_origin: compact.origin,
      payload_to_document: payloadTransform(anchorIndex, compact.origin),
      payload_frame: payloadFrame(anchorIndex),
      sampled_input_hash: null,
      settings: selected?.settings
        ? { ...selected.settings }
        : { ...DEFAULT_RETOUCH_REGION_SETTINGS, ...(spec?.seed ?? {}) },
    }
  }
  const existingRegions = (existingOp?.regions ?? []) as RetouchRegion[]
  const selected = existingRegions.find(
    region => region.id === regionId && isMaskedAdjustmentKind(region.kind),
  )

  if (!existingOp) {
    stack.addOp({
      id: opId,
      class: 'container',
      enabled: true,
      label: spec?.label ?? 'Adjust',
      exec: { kind: 'retouch-regions', version: 1 },
      defaults: { ...DEFAULT_RETOUCH_REGION_SETTINGS },
      regions: [withComponents],
    } as any)
  } else if (selected) {
    stack.setRegions(
      opId,
      existingRegions.map(candidate => candidate.id === regionId ? withComponents : candidate),
    )
  } else {
    stack.setRegions(opId, [...existingRegions, withComponents])
  }

  selectedOpId.value = opId
  selectedRetouchRegionId.value = regionId
  selectedMaskComponentId.value = null
  // Bound ants carry the coverage display; the wash only stands in when the
  // selection is not bound to this step's mask.
  selectedRetouchFeedbackVisible.value = !maskSessionBound.value
  await render()
  await refreshRetouchInput()
  await refreshRetouchFeedback()
  // The step exists; its mask becomes the live selection, the same bound
  // state every other mask session lands in.
  if (!maskSessionBound.value && selectedRetouchRegionId.value === regionId) {
    await bindMaskSessionSelection()
    if (maskSessionBound.value) selectedRetouchFeedbackVisible.value = false
  }
}

/** Publish the captured scope to the ARMED scoped step (see the module vars). */
function queueMaskedAdjustmentMask(
  mask: HTMLCanvasElement | null,
  semantic: AdjustmentScopeSemantic | null = null,
  recipe: WorkspaceMaskGesture<HTMLCanvasElement>[] | null = null,
) {
  const opId = maskedAdjustOpId
  const regionId = maskedAdjustRegionId
  if (!opId || !regionId) return
  const spec = maskedAdjustSpec
  // Snapshot synchronously: the workspace canvas is mutable and the next
  // gesture may arrive before this payload upload finishes. Recipe coverages
  // were already captured by copy at scope time.
  const snapshot = mask ? copyCanvas(mask) : null
  maskedAdjustCommitQueue = maskedAdjustCommitQueue
    .then(() => commitMaskedAdjustmentMask(snapshot, opId, regionId, spec, semantic, recipe))
    .catch(err => {
      console.error('[imageStack] masked adjustment commit failed', err)
      error.value = apiErrorMessage(err, 'Could not save the adjustment mask.')
    })
}

/**
 * The workspace selection has been consumed — into a new step's mask, or into
 * a captured mask component. Clear it without letting the clear rewrite the
 * combine mode the person set: the mode belongs to their next gesture.
 */
function consumeWorkspaceSelection() {
  const combine = selectCombine.value
  clearSelection()
  selectCombine.value = combine
}

/** What a landed gesture becomes inside an armed step's mask. */
interface MaskComponentCapture {
  /** The island's combine mode at gesture time; `new` replaces the base. */
  mode: SelectionMode
  /** Parametric identity when the gesture was a gradient drag. */
  gradient: GradientMask | null
  /** Semantic identity when the gesture was a recomputable AI selection. */
  semantic: AdjustmentScopeSemantic | null
  /** Tool name for the component row (Rectangle, Brush…), when known. */
  label?: string | null
}

/**
 * Land one completed selection gesture as ONE mask component of the armed
 * scoped step. The workspace is empty between gestures while mask editing is
 * armed, so the published bitmap IS the gesture — nothing gets flattened, and
 * every ingredient of the mask stays individually editable.
 */
function queueMaskComponentCapture(
  mask: HTMLCanvasElement | null,
  capture: MaskComponentCapture,
) {
  const opId = maskedAdjustOpId
  const regionId = maskedAdjustRegionId
  if (!opId || !regionId) return
  const snapshot = mask ? copyCanvas(mask) : null
  maskedAdjustCommitQueue = maskedAdjustCommitQueue
    .then(() => commitMaskComponentCapture(snapshot, opId, regionId, capture))
    .catch(err => {
      console.error('[imageStack] mask component capture failed', err)
      error.value = apiErrorMessage(err, 'Could not save the mask component.')
    })
}

async function commitMaskComponentCapture(
  sourceMask: HTMLCanvasElement | null,
  opId: string,
  regionId: string,
  capture: MaskComponentCapture,
) {
  if (!stack.doc.value) return
  if (fragileRetouchRegions.isCancelled(regionId)) return
  const location = retouchRegionLocation(regionId)
  if (!location || location.op.id !== opId) return
  if (!isMaskedAdjustmentKind(location.region.kind)) return

  // Build the captured component with its own authoring anchor — components
  // added after a crop record the frame THEY were made in.
  let component: MaskComponent
  if (capture.gradient) {
    const frame = payloadFrame(location.index)
    const canonical = frame
      ? payloadToDocumentTransform(frame) ?? undefined
      : undefined
    const authored = authoredGradient(
      capture.gradient, frame, canonical, location.index,
    )
    if (!authored) return
    component = {
      id: newOpId(),
      mode: capture.mode === 'new' ? 'add' : capture.mode,
      enabled: true,
      mask: authored,
      ...(canonical ? { payload_to_document: canonical as number[] } : {}),
      ...(frame ? { payload_frame: frame } : {}),
    }
  } else {
    if (!sourceMask) return
    const compact = compactSelectionMask(sourceMask)
    if (!compact) return
    const maskRef = await stack.uploadPayload(
      `${opId}-${regionId}-mask-${newOpId()}.png`,
      await canvasToBlob(compact.mask),
    )
    if (fragileRetouchRegions.isCancelled(regionId)) return
    payloadCache.set(`${maskRef}@0`, compact.mask)
    // Re-resolve after the await: edits may have moved or removed the region.
    const current = retouchRegionLocation(regionId)
    if (!current || current.op.id !== opId) return
    component = {
      id: newOpId(),
      mode: capture.mode === 'new' ? 'add' : capture.mode,
      enabled: true,
      mask_ref: maskRef,
      payload_origin: compact.origin,
      payload_to_document: payloadTransform(current.index, compact.origin),
      payload_frame: payloadFrame(current.index),
      ...(capture.semantic ? { semantic: { ...capture.semantic } } : {}),
      ...(capture.label ? { label: capture.label } : {}),
    }
  }

  const current = retouchRegionLocation(regionId)
  if (!current || current.op.id !== opId) return
  // A mask refinement is a substantive edit: the step stops being a
  // provisional landing place the next Adjust click may replace.
  fragileRetouchRegions.commit(regionId)

  const existing = JSON.parse(
    JSON.stringify(regionMaskComponents(current.region)),
  ) as MaskComponent[]
  let next: RetouchRegion
  if (capture.mode === 'new') {
    const modifiers = existing.slice(1)
    if (!modifiers.length && !capture.gradient && !capture.semantic) {
      // Nothing to preserve and nothing to name: stay in the legacy single
      // mask shape, exactly what republishing has always written.
      next = {
        ...current.region,
        mask: undefined,
        mask_components: undefined,
        mask_ref: component.mask_ref,
        payload_origin: component.payload_origin,
        payload_to_document: component.payload_to_document,
        payload_frame: component.payload_frame,
      }
    } else if (!modifiers.length && capture.gradient) {
      // Replacing the whole mask with one ramp: the legacy parametric region
      // is the smallest honest shape, and its handles stay live.
      next = {
        ...current.region,
        mask: component.mask,
        mask_components: undefined,
        mask_ref: undefined,
        payload_origin: undefined,
        payload_to_document: component.payload_to_document,
        payload_frame: component.payload_frame,
      }
    } else {
      // Replace the base, keep the modifiers.
      next = regionWithMaskComponents(current.region, [component, ...modifiers])
    }
  } else {
    next = regionWithMaskComponents(current.region, [...existing, component])
  }

  stack.setRegions(
    current.op.id,
    current.op.regions.map((candidate: RetouchRegion) =>
      candidate.id === regionId ? next : candidate,
    ),
  )
  selectedOpId.value = opId
  selectedRetouchRegionId.value = regionId
  // A gradient capture selects its component so the handles come up; any
  // other capture selects the Mask PARENT, so the wash shows the COMPOSED
  // result — the union the person just built, not the lone new stroke.
  selectedMaskComponentId.value =
    capture.gradient && next.mask_components?.length ? component.id : null
  selectedRetouchFeedbackVisible.value = !maskSessionBound.value
  await render()
  await refreshRetouchInput()
  await refreshRetouchFeedback()
  if (!maskSessionBound.value && selectedRetouchRegionId.value === regionId) {
    await bindMaskSessionSelection()
    if (maskSessionBound.value && !capture.gradient) {
      selectedRetouchFeedbackVisible.value = false
    }
  }
}

/** Land one gesture as a mask component of the armed GENERATIVE op. */
function queueGenerativeMaskCapture(
  mask: HTMLCanvasElement | null,
  capture: MaskComponentCapture,
) {
  const opId = maskedGenerativeOpId
  if (!opId) return
  const snapshot = mask ? copyCanvas(mask) : null
  maskedAdjustCommitQueue = maskedAdjustCommitQueue
    .then(() => commitGenerativeMaskCapture(snapshot, opId, capture))
    .catch(err => {
      console.error('[imageStack] generative mask capture failed', err)
      error.value = apiErrorMessage(err, 'Could not save the mask component.')
    })
}

async function commitGenerativeMaskCapture(
  sourceMask: HTMLCanvasElement | null,
  opId: string,
  capture: MaskComponentCapture,
) {
  const doc = stack.doc.value
  if (!doc) return
  const index = doc.edits.findIndex(edit => edit.id === opId)
  if (index < 0) return
  const op = doc.edits[index] as any
  if (!generativeOpHasEditableMask(op)) return

  let component: MaskComponent
  if (capture.gradient) {
    const frame = payloadFrame(index)
    const canonical = frame
      ? payloadToDocumentTransform(frame) ?? undefined
      : undefined
    const authored = authoredGradient(
      capture.gradient, frame, canonical as Affine | undefined, index,
    )
    if (!authored) return
    component = {
      id: newOpId(),
      mode: capture.mode === 'new' ? 'add' : capture.mode,
      enabled: true,
      mask: authored,
      ...(canonical ? { payload_to_document: canonical as number[] } : {}),
      ...(frame ? { payload_frame: frame } : {}),
    }
  } else {
    if (!sourceMask) return
    const compact = compactSelectionMask(sourceMask)
    if (!compact) return
    const maskRef = await stack.uploadPayload(
      `${opId}-mask-${newOpId()}.png`,
      await canvasToBlob(compact.mask),
    )
    payloadCache.set(`${maskRef}@0`, compact.mask)
    component = {
      id: newOpId(),
      mode: capture.mode === 'new' ? 'add' : capture.mode,
      enabled: true,
      mask_ref: maskRef,
      payload_origin: compact.origin,
      payload_to_document: payloadTransform(index, compact.origin),
      payload_frame: payloadFrame(index),
      ...(capture.semantic ? { semantic: { ...capture.semantic } } : {}),
      ...(capture.label ? { label: capture.label } : {}),
    }
  }

  // Re-resolve after the awaits.
  const current = stack.doc.value
  const currentOp = current?.edits.find(edit => edit.id === opId) as any
  if (!current || !generativeOpHasEditableMask(currentOp)) return
  const existing = JSON.parse(
    JSON.stringify(opMaskComponents(currentOp)),
  ) as MaskComponent[]
  const next = capture.mode === 'new'
    // Replace the base, keep the modifiers. mask_ref survives regardless —
    // it stays the record of what the candidates were sampled through.
    ? [component, ...existing.slice(1)]
    : [...existing, component]
  stack.replaceEdits(current.edits.map((edit: any) =>
    edit.id === opId ? { ...edit, mask_components: next } : edit,
  ))
  selectedOpId.value = opId
  selectedGenerativeMaskOpId.value = opId
  // Same rule as region captures: gradients select their component for the
  // handles; everything else shows the composed union on the Mask parent.
  selectedMaskComponentId.value = capture.gradient ? component.id : null
  selectedRetouchFeedbackVisible.value = !maskSessionBound.value
  await render()
  await refreshRetouchFeedback()
  if (!maskSessionBound.value && selectedGenerativeMaskOpId.value === opId) {
    await bindMaskSessionSelection()
    if (maskSessionBound.value && !capture.gradient) {
      selectedRetouchFeedbackVisible.value = false
    }
  }
}

/**
 * The photographic Retouch brushes land as ADJUSTMENT regions: the stroke
 * authors a mask, the toolbar strength seeds the region's settings, and the
 * compositor re-renders it parametrically — so the amount stays adjustable in
 * the region's Properties after the stroke, and the region never goes stale.
 */
const ADJUSTMENT_BRUSHES: Record<string, { kind: RetouchRegionKind; label: string }> = {
  dodge: { kind: 'light', label: 'Dodge' },
  burn: { kind: 'light', label: 'Burn' },
  sponge: { kind: 'color', label: 'Sponge' },
  blur: { kind: 'detail', label: 'Blur' },
  sharpen: { kind: 'detail', label: 'Sharpen' },
}

/**
 * The Heal engine produces pixels immediately for a responsive preview, but
 * persistence keeps the gesture as a child region: its own mask, result,
 * settings, authored frame, and sampling identity.
 */
async function commitRetouchRegion(
  result: HTMLCanvasElement,
  revision: number,
  opId: string,
  metadata: RetouchGestureMetadata,
  seed: Record<string, number> | null = null,
) {
  const doc = stack.doc.value
  if (!doc) return

  const existing = stack.opById(opId) as any
  const regions = (existing?.regions ?? []) as RetouchRegion[]
  const compact = compactRetouchPayload(result)
  if (!compact) {
    retouchRef.value?.clearDisplay(revision)
    return
  }
  const adjustment = ADJUSTMENT_BRUSHES[metadata.tool] ?? null
  const regionId = newOpId()
  // An adjustment region stores only its mask: its pixels are re-derived from
  // the composite beneath on every render, so there is no result to retain.
  const maskRef = await stack.uploadPayload(
    `${opId}-${regionId}-mask.png`,
    await canvasToBlob(compact.mask),
  )
  const resultRef = adjustment
    ? null
    : await stack.uploadPayload(
        `${opId}-${regionId}-result.png`,
        await canvasToBlob(compact.result),
      )

  const opIndex = doc.edits.findIndex(op => op.id === opId)
  const hashes = stackHashes(doc)
  const sampledInputHash = opIndex >= 0 ? hashes.inputs[opIndex] : hashes.head
  const authoredToDocument = payloadTransform(opIndex >= 0 ? opIndex : undefined)
  const documentPoint = (point: { x: number; y: number } | undefined) => {
    if (!point || !authoredToDocument) return point
    const [x, y] = applyToPoint(authoredToDocument, point.x, point.y)
    return { x, y }
  }
  const region: RetouchRegion = {
    id: regionId,
    kind: adjustment
      ? adjustment.kind
      : metadata.tool === 'clone' || metadata.tool === 'patch' ? metadata.tool : 'heal',
    enabled: true,
    ...(adjustment ? { label: adjustment.label } : {}),
    mask_ref: maskRef,
    ...(resultRef ? { result_ref: resultRef } : {}),
    payload_origin: compact.origin,
    payload_to_document: payloadTransform(
      opIndex >= 0 ? opIndex : undefined,
      compact.origin,
    ),
    payload_frame: payloadFrame(opIndex >= 0 ? opIndex : undefined),
    // Parametric regions never go stale — they re-derive from whatever is
    // beneath them — so they carry no sampling identity.
    sampled_input_hash: adjustment ? null : sampledInputHash,
    ...(metadata.source ? { source: documentPoint(metadata.source) } : {}),
    ...(metadata.target ? { target: documentPoint(metadata.target) } : {}),
    points_in_document: !!authoredToDocument,
    settings: adjustment
      ? { ...DEFAULT_RETOUCH_REGION_SETTINGS, ...(seed ?? {}) }
      : { ...DEFAULT_RETOUCH_REGION_SETTINGS },
  }

  // The payloads have unique immutable refs, so revision zero is their
  // permanent cache key. This also lets the compositor take the overlay
  // hand-off without waiting for WebKit to fetch the PNG it just uploaded.
  if (resultRef) payloadCache.set(`${resultRef}@0`, compact.result)
  payloadCache.set(`${maskRef}@0`, compact.mask)

  if (!existing) {
    stack.addOp({
      id: opId,
      class: 'container',
      enabled: true,
      label: 'Retouch',
      exec: { kind: 'retouch-regions', version: 1 },
      defaults: { ...DEFAULT_RETOUCH_REGION_SETTINGS },
      regions: [region],
      sampled_input_hash: sampledInputHash,
    } as any)
  } else {
    stack.setRegions(opId, [...regions, region])
  }

  retouchOpId.value = opId
  selectedOpId.value = opId
  selectedRetouchRegionId.value = regionId
  selectedRetouchFeedbackVisible.value = false
  await render()
  await refreshRetouchInput()
  await refreshRetouchFeedback()
  if (retouchOpId.value === opId) retouchRef.value?.clearDisplay(revision)
}

function onRetouchStroke(
  result: HTMLCanvasElement,
  _readsPixels: boolean,
  revision: number,
  metadata: RetouchGestureMetadata,
) {
  const opId = retouchOpId.value || newOpId()
  retouchOpId.value = opId
  // Captured now, not in the queued commit: the seed is what the toolbar said
  // when the stroke was made, and the settings may change before it lands.
  const seed = retouchBrushAdjustmentParams(metadata.tool, activeRetouchSettings.value)
  retouchCommitQueue = retouchCommitQueue
    .then(() => commitRetouchRegion(result, revision, opId, metadata, seed))
    .catch(err => {
      console.error('[imageStack] retouch region commit failed', err)
      error.value = apiErrorMessage(err, 'Could not apply the retouch region.')
    })
}

async function refreshRetouchInput() {
  const doc = stack.doc.value
  const opId = retouchOpId.value
  if (!doc || !opId) {
    retouchInput.value = composite.value
    return
  }
  const index = doc.edits.findIndex(op => op.id === opId)
  retouchInput.value = index >= 0
    ? await compositor.renderUpTo(doc, index + 1)
    : composite.value
}

function retouchRegionLocation(regionId: string | null) {
  const doc = stack.doc.value
  if (!doc || !regionId) return null
  for (let index = 0; index < doc.edits.length; index++) {
    const op = doc.edits[index] as any
    if (op.exec?.kind !== 'retouch-regions') continue
    const region = (op.regions ?? []).find((candidate: RetouchRegion) => candidate.id === regionId)
    if (region) return { op, index, region }
  }
  return null
}

const selectedRetouchRegion = computed<RetouchRegion | null>(
  () => retouchRegionLocation(selectedRetouchRegionId.value)?.region ?? null,
)

/**
 * The gradient the canvas handles should edit, in the region's OWN terms: the
 * legacy single-gradient region, or the selected gradient component of a
 * composite mask. Carries the anchors the geometry was authored against.
 */
function selectedGradientSource(): {
  /** The mask owner's id: a region's, or the generative op's own. */
  ownerId: string
  region: RetouchRegion | null
  index: number
  componentId: string | null
  mask: GradientMask
  payload_to_document?: number[]
  payload_frame?: { matrix: number[]; width: number; height: number }
} | null {
  // A generative op's selected gradient component re-opens its handles the
  // same way a region's does.
  if (selectedGenerativeMaskOpId.value && selectedMaskComponentId.value) {
    const doc = stack.doc.value
    const index = doc?.edits.findIndex(
      edit => edit.id === selectedGenerativeMaskOpId.value,
    ) ?? -1
    const op = index >= 0 ? (doc!.edits[index] as any) : null
    const component = op?.mask_components?.find(
      (candidate: MaskComponent) => candidate.id === selectedMaskComponentId.value,
    )
    if (!component || !isGradientMask(component.mask)) return null
    return {
      ownerId: op.id,
      region: null,
      index,
      componentId: component.id,
      mask: component.mask,
      payload_to_document: component.payload_to_document,
      payload_frame: component.payload_frame,
    }
  }
  const location = retouchRegionLocation(selectedRetouchRegionId.value)
  if (!location) return null
  const region = location.region as RetouchRegion
  if (hasMaskComponents(region)) {
    const id = selectedMaskComponentId.value
    const component = id
      ? region.mask_components!.find(candidate => candidate.id === id)
      : null
    if (!component || !isGradientMask(component.mask)) return null
    return {
      ownerId: region.id,
      region,
      index: location.index,
      componentId: component.id,
      mask: component.mask,
      payload_to_document: component.payload_to_document,
      payload_frame: component.payload_frame,
    }
  }
  if (!isGradientMask(region.mask)) return null
  return {
    ownerId: region.id,
    region,
    index: location.index,
    componentId: null,
    mask: region.mask,
    payload_to_document: region.payload_to_document,
    payload_frame: region.payload_frame,
  }
}

/**
 * The selected gradient, mapped into the CURRENT composite frame so its
 * handles land on the pixels they describe. Geometry is authored in its own
 * frame, exactly like a payload, so a crop underneath moves the handles with
 * the image instead of leaving them behind.
 */
const selectedGradient = computed<GradientMask | null>(() => {
  // Touch the reactive dependencies the helper reads through non-reactive
  // paths, so a component selection change recomputes the handles.
  void selectedMaskComponentId.value
  const source = selectedGradientSource()
  if (!source) return null
  const doc = stack.doc.value
  if (!doc) return source.mask
  const now = geometryBelow(doc, source.index)
  const canonical = source.payload_to_document as Affine | undefined
  const created = source.payload_frame
  const carry = canonical
    ? multiply(now.matrix, canonical)
    : created
      ? coTransform(created.matrix as Affine, now.matrix as Affine)
      : null
  return carry ? transformGradientMask(source.mask, carry) : source.mask
})

/**
 * A raster workspace selection outranks a selected adjustment row's gradient.
 * This prevents old ramp guides from sitting on top of new rectangle/lasso
 * ants; clearing the workspace selection reveals the selected ramp again.
 */
const activeWorkspaceGradient = computed<GradientMask | null>(() =>
  selectionIsGradient.value
  && workspaceGradient.value
  && workspaceGradientKey.value === selectionAppliedKey
    ? workspaceGradient.value
    : null
)

const canvasGradient = computed<GradientMask | null>(() =>
  selection.value && !maskSessionBound.value
    ? selectionIsGradient.value
      ? activeWorkspaceGradient.value ?? selectedGradient.value
      : null
    : selectedGradient.value
)

/** A selected Adjust region owns the pixels it renders; a workspace selection
 * only scopes the next destructive operation. The canvas uses this distinction
 * to decide whether handles remain visible while no gradient tool is armed. */
const canvasGradientOwnsResult = computed(
  () => !!canvasGradient.value && !activeWorkspaceGradient.value,
)

/**
 * A gradient region keeps GEOMETRY, not pixels: nothing is uploaded, and the
 * compositor rasterises the ramp on every render. That is what keeps the
 * handles live for the life of the document.
 *
 * Called once per gesture, on release. The canvas owns the in-flight drag and
 * draws it locally, because a document write per pointer move re-renders the
 * composite at full resolution per mouse event — which buries the guides under
 * a second of pixel work and makes the tool feel broken.
 */
function onGradientChange(mask: GradientMask, combine?: SelectionMode) {
  // The ramp lands as a workspace selection like every other gesture; what is
  // remembered here is its parametric identity, so an Adjust click can scope
  // with live geometry instead of the frozen raster. The canvas emits the
  // geometry first and publishes the raster second, both synchronously —
  // `gradientGestureLanding` is armed here and consumed by the change handler.
  rememberGradientDefaults(mask)
  gradientGestureLanding = true
  // The gesture's own geometry, kept regardless of combine: an armed mask
  // component capture wants the ramp itself even when the workspace copy
  // would have to flatten.
  lastGestureGradient = { ...mask }
  // The mode the gesture ACTUALLY combined with — a held-modifier override
  // never shows up in the island's persistent control.
  lastGestureGradientCombine = combine ?? selectCombine.value
  // Combined onto an existing selection, the published raster is a composite
  // and the ramp alone no longer describes it — raster scoping is the honest
  // fallback there.
  workspaceGradient.value =
    !selection.value || lastGestureGradientCombine === 'new' ? mask : null
}

/** A handle drag re-aims either the live workspace ramp or the persisted
 * adjustment region the handles belong to — never both. */
function onGradientEdit(mask: GradientMask) {
  if (
    selectionIsGradient.value
    && workspaceGradient.value
    && workspaceGradientKey.value === selectionAppliedKey
  ) {
    rememberGradientDefaults(mask)
    workspaceGradient.value = mask
    // The selection bitmap is the compatibility copy used by model masks and
    // other non-parametric consumers. Keep it in lockstep with the handles.
    gradientGestureLanding = true
    selectRef.value?.replaceGradient(mask)
    return
  }
  const into = selectedGradientSource()
  if (!into) return
  persistGradientRegion(mask, { into: into.ownerId, componentId: into.componentId })
}

function rememberGradientDefaults(mask: GradientMask) {
  if (mask.kind === 'linear') selectGradientSoftness.value = mask.softness
  else selectGradientFeather.value = mask.feather
}

/**
 * The inspector edits the region's own stored geometry, so its values are
 * already in the authored frame. The canvas hands back composite-space handles.
 * Saying which avoids transforming twice — invisible until a crop exists, and
 * then badly wrong.
 */
function onInspectorGradient(mask: GradientMask) {
  const into = selectedGradientSource()
  if (!into) return
  persistGradientRegion(mask, {
    into: into.ownerId,
    componentId: into.componentId,
    space: 'authored',
    render: false,
    coalesceKey: `retouch-gradient:${into.componentId ?? into.ownerId}`,
  })
  scheduleRetouchSettingsPreview()
}

function commitInspectorGradient() {
  void commitRetouchSettingsRender()
}

/**
 * Re-aim an EXISTING gradient — a legacy gradient region, or one gradient
 * component of a composite mask. Creation goes through Adjust
 * (`addScopedLevelEdit`) or a captured gesture; this only rewrites geometry
 * that already exists.
 */
function persistGradientRegion(
  mask: GradientMask,
  options: {
    into: string
    componentId?: string | null
    space?: 'composite' | 'authored'
    render?: boolean
    coalesceKey?: string
  },
) {
  rememberGradientDefaults(mask)
  // A generative op's gradient component: same re-aim, op-level storage.
  const generativeOp = options.componentId
    ? generativeMaskOpFor(options.into, options.into)
    : null
  if (generativeOp) {
    const doc = stack.doc.value
    const index = doc?.edits.findIndex(edit => edit.id === generativeOp.id) ?? -1
    const component = (generativeOp.mask_components as MaskComponent[] | undefined)
      ?.find(candidate => candidate.id === options.componentId)
    if (!doc || index < 0 || !component || !isGradientMask(component.mask)) return
    const authored = options.space === 'authored'
      ? mask
      : authoredGradient(
          mask,
          component.payload_frame,
          component.payload_to_document as Affine | undefined,
          index,
        )
    if (!authored) return
    stack.replaceEdits(doc.edits.map((edit: any) =>
      edit.id === generativeOp.id
        ? {
            ...edit,
            mask_components: edit.mask_components.map((candidate: MaskComponent) =>
              candidate.id === component.id
                ? { ...candidate, mask: authored }
                : candidate,
            ),
          }
        : edit,
    ), options.coalesceKey)
    if (options.render !== false) {
      armedSelectTool.value = null
      void render().then(refreshRetouchInput)
    }
    return
  }
  const location = retouchRegionLocation(options.into)
  if (!location) return
  const existing = location.region as RetouchRegion
  const component = options.componentId
    ? existing.mask_components?.find(candidate => candidate.id === options.componentId)
    : null
  if (options.componentId && (!component || !isGradientMask(component.mask))) return

  // An edit maps back into the frame the GEOMETRY was authored in, which is
  // not necessarily the frame a new one would get: masks outlive crops.
  const frame = component ? component.payload_frame : existing.payload_frame
  const canonical = (component
    ? component.payload_to_document
    : existing.payload_to_document) as Affine | undefined

  // Handles are dragged in composite space; the geometry is stored in its own
  // authored frame, so the inverse of the carry goes back the way it came.
  const authored = options.space === 'authored'
    ? mask
    : authoredGradient(mask, frame, canonical, location.index)
  if (!authored) return

  const next: RetouchRegion = component
    ? {
        ...existing,
        mask_components: existing.mask_components!.map(candidate =>
          candidate.id === component.id ? { ...candidate, mask: authored } : candidate,
        ),
      }
    : { ...existing, mask: authored }
  stack.setRegions(location.op.id, location.op.regions.map((region: RetouchRegion) =>
    region.id === options.into ? next : region
  ), options.coalesceKey)

  if (options.render !== false) {
    armedSelectTool.value = null
    void render().then(refreshRetouchInput)
  }
}

/** Composite-space geometry back into the region's authored frame. */
function authoredGradient(
  mask: GradientMask,
  frame: { matrix: number[]; width: number; height: number } | undefined,
  canonical: Affine | undefined,
  opIndex: number,
): GradientMask | null {
  const doc = stack.doc.value
  if (!doc) return mask
  const now = geometryBelow(doc, opIndex >= 0 ? opIndex : doc.edits.length)
  const carry = canonical
    ? multiply(now.matrix, canonical)
    : frame
      ? coTransform(frame.matrix as Affine, now.matrix as Affine)
      : null
  if (!carry) return mask
  const back = invertMatrix(carry)
  return back ? transformGradientMask(mask, back) : mask
}

/**
 * One mask ingredient's coverage, carried into the current frame. A region's
 * legacy single mask and a mask component share this field shape, so both
 * feed through here.
 */
async function componentFeedbackCanvas(
  source: Pick<
    RetouchRegion,
    'mask' | 'mask_ref' | 'payload_origin' | 'payload_to_document' | 'payload_frame'
  >,
  now: { matrix: number[]; width: number; height: number },
): Promise<HTMLCanvasElement | null> {
  const created = source.payload_frame
  const canonical = source.payload_to_document as Affine | undefined
  const authored = document.createElement('canvas')
  authored.width = created?.width ?? now.width
  authored.height = created?.height ?? now.height
  // A gradient owns no payload; its coverage comes from the same rasteriser
  // the compositor uses, so feedback and render agree by construction.
  if (isGradientMask(source.mask)) {
    authored.getContext('2d')!.drawImage(
      gradientMaskCanvas(source.mask, authored.width, authored.height), 0, 0,
    )
  } else {
    if (!source.mask_ref) return null
    const key = `${source.mask_ref}@0`
    let payload = payloadCache.get(key)
    if (!payload) {
      try {
        payload = await loadImage(stack.payloadUrl(source.mask_ref, 0))
      } catch {
        return null
      }
    }
    if (canonical) {
      const matrix = multiply(now.matrix as Affine, canonical)
      return rewritePayload(payload, matrix, now.width, now.height)
    }
    const [x, y] = source.payload_origin ?? [0, 0]
    authored.getContext('2d')!.drawImage(payload, x, y)
  }
  if (canonical) {
    const matrix = multiply(now.matrix as Affine, canonical)
    return matrix && !isIdentity(matrix)
      ? rewritePayload(authored, matrix, now.width, now.height)
      : authored
  }
  if (!created) return authored
  const matrix = coTransform(created.matrix as Affine, now.matrix as Affine)
  return matrix && !isIdentity(matrix)
    ? rewritePayload(authored, matrix, now.width, now.height)
    : authored
}

/**
 * A region's coverage in its current frame — the whole effective mask, or one
 * component's when `componentId` names it (a component row's hover/selection
 * shows what THAT ingredient covers, not the composed result).
 */
async function retouchFeedbackMask(
  regionId: string | null,
  componentId: string | null = null,
): Promise<HTMLCanvasElement | null> {
  const location = retouchRegionLocation(regionId)
  if (!location) return null
  const { index, region } = location
  const doc = stack.doc.value!
  const now = geometryBelow(doc, index)
  const components = (region as RetouchRegion).mask_components
  if (components?.length) {
    if (componentId) {
      const component = components.find(candidate => candidate.id === componentId)
      return component ? componentFeedbackCanvas(component, now) : null
    }
    const layers = await Promise.all(components.map(async component => ({
      source: component.enabled !== false
        ? await componentFeedbackCanvas(component, now)
        : null,
      mode: component.mode,
      enabled: component.enabled !== false,
    })))
    if (!layers.some(layer => layer.enabled && layer.source)) return null
    return composeMaskCanvases(layers, now.width, now.height)
  }
  // Legacy single mask: the base component IS the region's mask, so a
  // component-addressed request answers with the same coverage.
  return componentFeedbackCanvas(region, now)
}

/**
 * A generative op's mask coverage in its current frame — the composed
 * effective mask, or one component's when `componentId` names it. Luminance
 * payloads translate to alpha before composing, so the wash reads coverage
 * rather than the opaque black around it.
 */
async function generativeMaskFeedback(
  opId: string,
  componentId: string | null = null,
): Promise<HTMLCanvasElement | null> {
  const doc = stack.doc.value
  if (!doc) return null
  const index = doc.edits.findIndex(op => op.id === opId)
  if (index < 0) return null
  const op = doc.edits[index] as any
  if (!generativeOpHasEditableMask(op)) return null
  const components = opMaskComponents(op)
  if (!components.length) return null
  const now = geometryBelow(doc, index)
  const load = async (component: MaskComponent) => {
    const canvas = await componentFeedbackCanvas(component, now)
    return canvas && component.luminance
      ? luminanceToAlphaCanvas(canvas, now.width, now.height)
      : canvas
  }
  if (componentId) {
    const component = components.find(candidate => candidate.id === componentId)
    return component ? load(component) : null
  }
  const layers = await Promise.all(components.map(async component => ({
    source: component.enabled !== false ? await load(component) : null,
    mode: component.mode,
    enabled: component.enabled !== false,
  })))
  if (!layers.some(layer => layer.enabled && layer.source)) return null
  return composeMaskCanvases(layers, now.width, now.height)
}

/** Carry a model patch's full-frame mask into its current stack geometry. */
async function modelFeedbackMask(opId: string): Promise<HTMLCanvasElement | null> {
  const doc = stack.doc.value
  if (!doc) return null
  const index = doc.edits.findIndex(op => op.id === opId)
  if (index < 0) return null
  const op = doc.edits[index] as any
  if (op.class !== 'patch' || !op.mask_ref) return null

  const now = geometryBelow(doc, index)
  const created = op.payload_frame
  const canonical = op.payload_to_document as Affine | undefined
  const authored = document.createElement('canvas')
  authored.width = created?.width ?? now.width
  authored.height = created?.height ?? now.height
  try {
    const payload = await loadImage(stack.payloadUrl(op.mask_ref, 0))
    const context = authored.getContext('2d', { willReadFrequently: true })!
    context.drawImage(payload, 0, 0, authored.width, authored.height)
    // Generative masks are opaque white-on-black because the STP tool needs
    // luminance. Canvas feedback consumes alpha, so translate the stored shape
    // instead of outlining the entire opaque frame.
    const pixels = context.getImageData(0, 0, authored.width, authored.height)
    for (let i = 0; i < pixels.data.length; i += 4) {
      const alpha = pixels.data[i]
      pixels.data[i] = 255
      pixels.data[i + 1] = 255
      pixels.data[i + 2] = 255
      pixels.data[i + 3] = alpha
    }
    context.putImageData(pixels, 0, 0)
  } catch {
    return null
  }
  if (canonical) {
    const matrix = multiply(now.matrix, canonical)
    return !isIdentity(matrix)
      ? rewritePayload(authored, matrix, now.width, now.height)
      : authored
  }
  if (!created) return authored
  const matrix = coTransform(created.matrix as Affine, now.matrix)
  return matrix && !isIdentity(matrix)
    ? rewritePayload(authored, matrix, now.width, now.height)
    : authored
}

function retouchFeedbackPoint(
  location: ReturnType<typeof retouchRegionLocation>,
  point: { x: number; y: number } | undefined,
) {
  if (!location || !point) return null
  if (location.region.points_in_document) {
    const now = geometryBelow(stack.doc.value!, location.index)
    const [x, y] = applyToPoint(now.matrix, point.x, point.y)
    return { x, y }
  }
  const created = location.region.payload_frame
  if (!created) return point
  const now = geometryBelow(stack.doc.value!, location.index)
  const matrix = coTransform(created.matrix as any, now.matrix)
  if (!matrix) return point
  const [x, y] = applyToPoint(matrix, point.x, point.y)
  return { x, y }
}

let retouchFeedbackRevision = 0
async function refreshRetouchFeedback() {
  const revision = ++retouchFeedbackRevision
  // Identity is the authority. Clear stale canvases synchronously so a
  // deleted/unhovered child cannot remain visible during async payload work.
  if (!selectedRetouchRegionId.value && !selectedGenerativeMaskOpId.value) {
    selectedRetouchMask.value = null
    selectedRetouchSource.value = null
    selectedRetouchTarget.value = null
    selectedRetouchIsPatch.value = false
  }
  if (!hoveredRetouchRegionId.value && !hoveredGenerativeMaskOpId.value) {
    hoveredRetouchMask.value = null
    hoveredRetouchSource.value = null
    hoveredRetouchTarget.value = null
    hoveredRetouchIsPatch.value = false
  }
  const [selected, hovered] = await Promise.all([
    selectedGenerativeMaskOpId.value
      ? generativeMaskFeedback(selectedGenerativeMaskOpId.value, selectedMaskComponentId.value)
      : retouchFeedbackMask(selectedRetouchRegionId.value, selectedMaskComponentId.value),
    hoveredGenerativeMaskOpId.value
      ? generativeMaskFeedback(hoveredGenerativeMaskOpId.value, hoveredMaskComponentId.value)
      : retouchFeedbackMask(hoveredRetouchRegionId.value, hoveredMaskComponentId.value),
  ])
  if (revision !== retouchFeedbackRevision) return
  selectedRetouchMask.value = selected
  hoveredRetouchMask.value = hovered
  const location = retouchRegionLocation(selectedRetouchRegionId.value)
  selectedRetouchSource.value = retouchFeedbackPoint(location, location?.region.source)
  selectedRetouchTarget.value = retouchFeedbackPoint(location, location?.region.target)
  selectedRetouchIsPatch.value = location?.region.kind === 'patch'
  // Hover owns the canvas while it is present, even when it is the currently
  // selected child. Do not suppress its source geometry in that case.
  const hoveredLocation = retouchRegionLocation(hoveredRetouchRegionId.value)
  hoveredRetouchSource.value = retouchFeedbackPoint(
    hoveredLocation,
    hoveredLocation?.region.source,
  )
  hoveredRetouchTarget.value = retouchFeedbackPoint(
    hoveredLocation,
    hoveredLocation?.region.target,
  )
  hoveredRetouchIsPatch.value = hoveredLocation?.region.kind === 'patch'
}

/**
 * A SELECTED scoped adjustment owns the selection gestures: while its region
 * (or one of its mask components) is selected, every landed gesture becomes a
 * component of ITS mask, through the island's combine mode. Deselecting —
 * Escape, the row toggle, picking anything else — releases the gestures back
 * to the workspace.
 */
function armMaskEditingForSelection(regionId: string | null) {
  const location = retouchRegionLocation(regionId)
  if (location && isMaskedAdjustmentKind(location.region.kind)) {
    maskedAdjustOpId = location.op.id
    maskedAdjustRegionId = location.region.id
    maskedAdjustSpec = null
  } else {
    disarmMaskedAdjustmentEditing()
  }
}

/** End a generative op's mask session and its selection state. */
function clearGenerativeMaskSelection() {
  selectedGenerativeMaskOpId.value = null
  maskedGenerativeOpId = null
  maskBaseReplaceArmed = false
}

/**
 * Load the session step's composed mask INTO the workspace selection: the
 * ants become the mask's display, the selection tools its editors, and
 * Deselect/Escape the way out. The wash returns to hover duty.
 */
async function bindMaskSessionSelection() {
  const opId = selectedGenerativeMaskOpId.value
  const regionId = selectedRetouchRegionId.value
  const composed = opId
    ? await generativeMaskFeedback(opId)
    : await retouchFeedbackMask(regionId)
  // Re-check after the compose: the session may have moved on.
  if (
    opId !== selectedGenerativeMaskOpId.value
    || regionId !== selectedRetouchRegionId.value
  ) return
  if (!composed || !selectRef.value) return
  syncingBoundSelection = true
  try {
    selectRef.value.applyMask(composed, 'new')
  } finally {
    syncingBoundSelection = false
  }
  // Feedback visibility stays the caller's decision: parent selections keep
  // the wash off (the ants are the mask), component selections keep it on
  // (the wash previews the component over the bound ants).
  maskSessionBound.value = selModel.hasSelection()
}

/**
 * Drop the bound selection without touching the step's mask — the projection
 * leaves with the session it belonged to. The flag flips FIRST so the clear's
 * change event reads as an ordinary empty workspace, not a session end.
 */
function releaseBoundSelection() {
  if (!maskSessionBound.value) return
  maskSessionBound.value = false
  clearSelection()
}

/** The selection was cleared WHILE bound: that gesture means "I'm done with
 *  this step's mask" — end the session; the mask itself stays. */
function endBoundMaskSession() {
  maskSessionBound.value = false
  disarmMaskedAdjustmentEditing()
  clearGenerativeMaskSelection()
  selectedRetouchRegionId.value = null
  selectedMaskComponentId.value = null
  selectedRetouchFeedbackVisible.value = false
  void refreshRetouchFeedback()
}

/** A `targetId` that names a patch op addresses the OP's mask. */
function generativeMaskOpFor(opId: string, targetId: string): any | null {
  if (opId !== targetId) return null
  const op = stack.opById(opId) as any
  return generativeOpHasEditableMask(op) ? op : null
}

function selectRetouchRegion(opId: string, regionId: string) {
  // Picking a region by hand ends any other step's mask-editing session.
  if (maskedAdjustRegionId && maskedAdjustRegionId !== regionId) {
    disarmMaskedAdjustmentEditing()
  }
  selectedOpId.value = opId
  selectedShapeId.value = null
  if (generativeMaskOpFor(opId, regionId)) {
    // The generative op's Mask parent: its composed mask binds as the live
    // selection, and the op's mask session arms.
    selectedRetouchRegionId.value = null
    const deselecting = selectedGenerativeMaskOpId.value === opId
      && !selectedMaskComponentId.value
    selectedMaskComponentId.value = null
    selectedGenerativeMaskOpId.value = deselecting ? null : opId
    maskedGenerativeOpId = deselecting ? null : opId
    selectedRetouchFeedbackVisible.value = false
    if (deselecting) releaseBoundSelection()
    else void bindMaskSessionSelection()
    void refreshRetouchFeedback()
    return
  }
  if (maskSessionBound.value && selectedGenerativeMaskOpId.value) {
    releaseBoundSelection()
  }
  clearGenerativeMaskSelection()
  const alreadySelected = selectedRetouchRegionId.value === regionId
    && !selectedMaskComponentId.value
  const deselecting = alreadySelected
  selectedRetouchRegionId.value = deselecting ? null : regionId
  // Region-level selection is the Mask parent: the composed result, no
  // individual component.
  selectedMaskComponentId.value = null
  selectedRetouchFeedbackVisible.value = false
  armMaskEditingForSelection(deselecting ? null : regionId)
  if (deselecting) releaseBoundSelection()
  else void bindMaskSessionSelection()
  void refreshRetouchFeedback()
}

/** Select one mask component: its coverage previews, its controls open. */
function selectMaskComponent(opId: string, targetId: string, componentId: string) {
  if (maskedAdjustRegionId && maskedAdjustRegionId !== targetId) {
    disarmMaskedAdjustmentEditing()
  }
  selectedOpId.value = opId
  selectedShapeId.value = null
  if (generativeMaskOpFor(opId, targetId)) {
    selectedRetouchRegionId.value = null
    selectedGenerativeMaskOpId.value = opId
    maskedGenerativeOpId = opId
    selectedMaskComponentId.value = componentId
    // The bound ants keep showing the WHOLE mask; the wash previews the
    // selected component over them.
    selectedRetouchFeedbackVisible.value = true
    if (!maskSessionBound.value) void bindMaskSessionSelection()
    void refreshRetouchFeedback()
    return
  }
  clearGenerativeMaskSelection()
  selectedRetouchRegionId.value = targetId
  selectedMaskComponentId.value = componentId
  selectedRetouchFeedbackVisible.value = true
  armMaskEditingForSelection(targetId)
  if (!maskSessionBound.value) void bindMaskSessionSelection()
  void refreshRetouchFeedback()
}

function hoverRetouchRegion(regionId: string | null) {
  // A generative op's Mask parent hovers by the op's own id.
  const generative = regionId ? generativeMaskOpFor(regionId, regionId) : null
  hoveredRetouchRegionId.value = generative ? null : regionId
  hoveredGenerativeMaskOpId.value = generative ? regionId : null
  hoveredMaskComponentId.value = null
  void refreshRetouchFeedback()
}

/** Hovering a component row washes that component's own coverage. */
function hoverMaskComponent(opId: string, targetId: string, componentId: string | null) {
  if (generativeMaskOpFor(opId, targetId)) {
    hoveredRetouchRegionId.value = null
    hoveredGenerativeMaskOpId.value = componentId ? opId : null
    hoveredMaskComponentId.value = componentId
  } else {
    hoveredGenerativeMaskOpId.value = null
    hoveredRetouchRegionId.value = componentId ? targetId : null
    hoveredMaskComponentId.value = componentId
  }
  void refreshRetouchFeedback()
}

/**
 * The component view of a mask target, upgraded for a structural edit. The
 * target is a retouch region — or, when `targetId` names the op itself, a
 * generative op's mask. Legacy single masks convert on first touch; the list
 * becomes the compositing authority (a generative op's `mask_ref` stays put
 * as the record of what its candidates were sampled through).
 */
function componentEditTargets(opId: string, targetId: string) {
  const op = stack.opById(opId) as any
  if (!op) return null
  if (targetId === opId && generativeOpHasEditableMask(op)) {
    const components = JSON.parse(
      JSON.stringify(opMaskComponents(op)),
    ) as MaskComponent[]
    if (!components.length) return null
    return { op, region: null as RetouchRegion | null, components, generative: true }
  }
  if (op?.exec?.kind !== 'retouch-regions') return null
  const region = (op.regions ?? []).find(
    (candidate: RetouchRegion) => candidate.id === targetId,
  ) as RetouchRegion | undefined
  if (!region) return null
  const components = JSON.parse(
    JSON.stringify(regionMaskComponents(region)),
  ) as MaskComponent[]
  if (!components.length) return null
  return { op, region, components, generative: false }
}

function commitRegionComponents(
  op: any,
  region: RetouchRegion | null,
  components: MaskComponent[],
) {
  if (!region) {
    // A generative op owns its components directly; the whole-list journal
    // entry keeps the structural edit one undo step.
    const doc = stack.doc.value
    if (!doc) return
    stack.replaceEdits(doc.edits.map((edit: any) =>
      edit.id === op.id ? { ...edit, mask_components: components } : edit,
    ))
  } else {
    const next = regionWithMaskComponents(region, components)
    stack.setRegions(op.id, op.regions.map((candidate: RetouchRegion) =>
      candidate.id === region.id ? next : candidate,
    ))
  }
  void refreshRetouchFeedback()
  void render().then(refreshRetouchInput)
}

function setMaskComponentEnabled(
  opId: string,
  regionId: string,
  componentId: string,
  enabled: boolean,
) {
  const targets = componentEditTargets(opId, regionId)
  if (!targets) return
  fragileRetouchRegions.commit(regionId)
  commitRegionComponents(
    targets.op,
    targets.region,
    targets.components.map(component =>
      component.id === componentId ? { ...component, enabled } : component,
    ),
  )
}

/**
 * Any component can go: coverage starts at nothing and every mode means what
 * it says, so a removal never reinterprets what remains. Removing the LAST
 * component removes the mask itself — explicitly Whole image, the same act
 * as trashing the Mask parent.
 */
function removeMaskComponent(opId: string, regionId: string, componentId: string) {
  const targets = componentEditTargets(opId, regionId)
  if (!targets) return
  if (!targets.components.some(component => component.id === componentId)) return
  fragileRetouchRegions.commit(regionId)
  if (selectedMaskComponentId.value === componentId) {
    selectedMaskComponentId.value = null
  }
  if (hoveredMaskComponentId.value === componentId) {
    hoveredMaskComponentId.value = null
  }
  const remaining = targets.components.filter(
    component => component.id !== componentId,
  )
  if (!remaining.length) {
    // A scoped adjustment without a mask IS Whole image. A generative op
    // without one is undefined; its sole component offers no trash.
    if (!targets.generative) void unscopeRegion(regionId)
    return
  }
  commitRegionComponents(targets.op, targets.region, remaining)
}

/**
 * Re-segment a semantic component against the composite its region actually
 * masks — the pixels below the op — and swap in the fresh cached raster.
 * The name, the mode, and every other component survive untouched.
 */
async function recomputeSemanticComponent(
  opId: string,
  regionId: string,
  componentId: string,
) {
  if (recomputingMaskComponentId.value) return
  const location = retouchRegionLocation(regionId)
  if (!location || location.op.id !== opId) return
  const component = (location.region as RetouchRegion).mask_components?.find(
    candidate => candidate.id === componentId,
  )
  const semantic = component?.semantic
  if (!semantic?.prompt && !semantic?.intent) return
  recomputingMaskComponentId.value = componentId
  try {
    const doc = stack.doc.value!
    const input = await compositor.renderUpTo(doc, location.index)
    const sent = aiSelectCanvas(input)
    const { data } = await axios.post('/api/mask/select', {
      request_id: globalThis.crypto?.randomUUID?.()
        ?? `select-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      image_data_url: sent.toDataURL('image/png'),
      ...(semantic.prompt ? { prompt: semantic.prompt } : {}),
      ...(semantic.intent ? { intent: semantic.intent } : {}),
    })
    if (!data.success || !data.detections?.length) {
      error.value = data.error || (semantic.prompt
        ? `No match for “${semantic.prompt}”`
        : 'Nothing to select')
      return
    }
    const masks = await Promise.all(
      data.detections.map((d: any) => loadMaskImage(d.mask_data_url)),
    )
    const union = document.createElement('canvas')
    union.width = input.width
    union.height = input.height
    const unionCtx = union.getContext('2d')!
    for (const mask of masks) unionCtx.drawImage(mask, 0, 0, union.width, union.height)
    const compact = compactSelectionMask(union)
    if (!compact) return
    const maskRef = await stack.uploadPayload(
      `${opId}-${regionId}-mask-${newOpId()}.png`,
      await canvasToBlob(compact.mask),
    )
    payloadCache.set(`${maskRef}@0`, compact.mask)

    // Re-resolve after the awaits; the segmentation ran against the pixels
    // below the op, so the anchor is the frame AT the op's index.
    const current = retouchRegionLocation(regionId)
    if (!current || current.op.id !== opId) return
    const targets = componentEditTargets(opId, regionId)
    if (!targets) return
    commitRegionComponents(
      targets.op,
      targets.region,
      targets.components.map(candidate =>
        candidate.id === componentId
          ? {
              ...candidate,
              mask_ref: maskRef,
              payload_origin: compact.origin,
              payload_to_document: payloadTransform(current.index, compact.origin),
              payload_frame: payloadFrame(current.index),
            }
          : candidate,
      ),
    )
  } catch (e) {
    error.value = apiErrorMessage(e, 'Could not recompute the selection.')
  } finally {
    recomputingMaskComponentId.value = null
  }
}

let allRetouchFeedbackRevision = 0
async function hoverRetouchOp(opId: string, hovering: boolean) {
  if (!hovering) {
    if (hoveredRetouchOpId.value === opId) hoveredRetouchOpId.value = null
    allRetouchFeedback.value = []
    allRetouchFeedbackRevision++
    return
  }

  hoveredRetouchOpId.value = opId
  const revision = ++allRetouchFeedbackRevision
  const op = stack.opById(opId) as any
  if (op?.class === 'patch') {
    // A composite mask hovers as its composed result; the legacy single
    // submission mask keeps its original path.
    const mask = op.mask_components?.length
      ? await generativeMaskFeedback(opId)
      : await modelFeedbackMask(opId)
    if (revision !== allRetouchFeedbackRevision || hoveredRetouchOpId.value !== opId) return
    allRetouchFeedback.value = mask ? [{ mask, isPatch: false }] : []
    return
  }
  if (op?.exec?.kind !== 'retouch-regions') {
    allRetouchFeedback.value = []
    return
  }
  const feedback = await Promise.all(
    (op.regions ?? []).map(async (region: RetouchRegion) => {
      const mask = await retouchFeedbackMask(region.id)
      if (!mask) return null
      const location = retouchRegionLocation(region.id)
      return {
        mask,
        source: retouchFeedbackPoint(location, region.source),
        target: retouchFeedbackPoint(location, region.target),
        isPatch: region.kind === 'patch',
      }
    }),
  )
  if (revision !== allRetouchFeedbackRevision || hoveredRetouchOpId.value !== opId) return
  allRetouchFeedback.value = feedback.filter(
    (item): item is NonNullable<typeof item> => item !== null,
  )
}

async function enterRetouchOp(opId: string) {
  const op = stack.opById(opId) as any
  if (op?.exec?.kind !== 'retouch-regions') return
  family.value = 'retouch'
  sub.value = 'heal'
  retouchOpId.value = opId
  selectedOpId.value = opId
  retouchRef.value?.reset()
  await refreshRetouchInput()
}

function resetRetouchSession() {
  retouchOpId.value = null
  retouchInput.value = null
  maskedAdjustRegionId = null
  retouchRef.value?.reset()
}

/**
 * Blend, mask, and spatial blur drags render the document at fitted display
 * resolution. Other masked photographic adjustments use the GPU delta preview
 * above; expensive source pixels are touched only once on pointer-up.
 */
let retouchPreviewFrame: number | null = null
let retouchPreviewInFlight = false
let retouchPreviewQueued = false
let retouchPreviewRevision = 0
let retouchPreviewSizeKey = ''

function scaledRetouchPreviewDocument(): any | null {
  const doc = displayDoc.value
  const source = composite.value
  if (!doc || !source || !displayBox.value.width || !displayBox.value.height) return null
  // Clarity/Blur/Sharpen are several full pixel passes. Half a
  // megapixel is enough for a faithful fitted preview and keeps those passes
  // interactive on the main thread.
  const pixelBudgetScale = Math.sqrt(500_000 / Math.max(1, source.width * source.height))
  const scale = Math.min(
    1,
    pixelBudgetScale,
    displayBox.value.width / Math.max(1, source.width),
    displayBox.value.height / Math.max(1, source.height),
  )
  const preview = JSON.parse(JSON.stringify(doc))
  preview.canvas = {
    width: Math.max(1, Math.round(doc.canvas.width * scale)),
    height: Math.max(1, Math.round(doc.canvas.height * scale)),
  }
  preview._preview_scale = scale
  for (const op of preview.edits ?? []) {
    if (op.class === 'patch' && op.blend?.feather_px) {
      op.blend.feather_px *= scale
    }
    if (op.exec?.kind !== 'retouch-regions') continue
    for (const region of op.regions ?? []) {
      if (!region.settings) continue
      region.settings.feather_px = (region.settings.feather_px ?? 0) * scale
      if (region.settings.blur) region.settings.blur *= scale
      if (region.settings.sharpenRadius) {
        region.settings.sharpenRadius = Math.max(
          0.5,
          region.settings.sharpenRadius * scale,
        )
      }
      if (region.settings.grainSize) {
        region.settings.grainSize = Math.max(
          0,
          (1 + region.settings.grainSize / 12) * scale * 12 - 12,
        )
      }
    }
  }
  return preview
}

function scheduleRetouchSettingsPreview() {
  retouchPreviewQueued = true
  retouchPreviewRevision++
  if (retouchPreviewInFlight || retouchPreviewFrame !== null) return
  retouchPreviewFrame = requestAnimationFrame(() => {
    retouchPreviewFrame = null
    void flushRetouchSettingsPreview()
  })
}

async function flushRetouchSettingsPreview() {
  if (retouchPreviewInFlight || !retouchPreviewQueued) return
  retouchPreviewQueued = false
  retouchPreviewInFlight = true
  const revision = retouchPreviewRevision
  try {
    const previewDoc = scaledRetouchPreviewDocument()
    if (!previewDoc) return
    const sizeKey = `${previewDoc.canvas.width}x${previewDoc.canvas.height}`
    if (sizeKey !== retouchPreviewSizeKey) {
      retouchPreviewSizeKey = sizeKey
      retouchPreviewCompositor.clear()
    }
    const preview = await retouchPreviewCompositor.render(previewDoc)
    if (revision !== retouchPreviewRevision) return
    const target = displayCanvas.value
    if (!target) return
    target.width = preview.width
    target.height = preview.height
    const ctx = target.getContext('2d')!
    ctx.clearRect(0, 0, target.width, target.height)
    ctx.drawImage(preview, 0, 0)
  } finally {
    retouchPreviewInFlight = false
    if (retouchPreviewQueued) scheduleRetouchSettingsPreview()
  }
}

async function commitRetouchSettingsRender() {
  cancelLiveAdjustPreview()
  retouchPreviewRevision++
  retouchPreviewQueued = false
  if (retouchPreviewFrame !== null) {
    cancelAnimationFrame(retouchPreviewFrame)
    retouchPreviewFrame = null
  }
  await render()
  await refreshRetouchInput()
}

function setRetouchRegionSettings(
  patch: Partial<RetouchRegionSettings>,
  coalesceKey: string,
) {
  const location = retouchRegionLocation(selectedRetouchRegionId.value)
  if (!location) return
  // The first substantive property gesture commits the child. It may still
  // be visually neutral if the slider lands back on its default, just like a
  // top-level Adjust step: the person's interaction, not value comparison,
  // is the durable boundary.
  fragileRetouchRegions.commit(location.region.id)
  // A slider move commits the step but does NOT end its mask-editing session:
  // while the region stays selected, gestures keep landing as components of
  // its mask. Deselecting is what hands the gestures back.
  const before = { ...location.region.settings }
  // Once a property moves, the person is judging the photograph rather than
  // constructing the region. Keep the mask intact but get its wash and ants
  // off the pixels immediately.
  dismissCanvasFeedback()
  stack.setRegions(
    location.op.id,
    location.op.regions.map((region: RetouchRegion) =>
      region.id === location.region.id
        ? { ...region, settings: { ...region.settings, ...patch } }
        : region
    ),
    coalesceKey,
  )
  const updated = retouchRegionLocation(location.region.id)?.region.settings
  const needsCompositorPreview = maskedAdjustmentNeedsCompositorPreview(patch)
  if (
    updated
    && isMaskedAdjustmentKind(location.region.kind)
    && !needsCompositorPreview
  ) {
    void previewAdjustment(
      `retouch:${location.region.id}`,
      before,
      updated,
      {
        // The delta previews the ADJUSTMENT, which renders through the whole
        // effective mask — a selected component's own coverage is a different
        // preview and must not stand in for it.
        mask: (!selectedMaskComponentId.value ? selectedRetouchMask.value : null)
          ?? retouchFeedbackMask(location.region.id),
        maskStrength: updated.opacity ?? 1,
      },
    )
  } else {
    scheduleRetouchSettingsPreview()
  }
}

function setRetouchRegionEnabled(opId: string, regionId: string, enabled: boolean) {
  const op = stack.opById(opId) as any
  if (op?.exec?.kind !== 'retouch-regions') return
  fragileRetouchRegions.commit(regionId)
  stack.setRegions(opId, op.regions.map((region: RetouchRegion) =>
    region.id === regionId ? { ...region, enabled } : region
  ))
  void refreshRetouchFeedback()
  void render().then(refreshRetouchInput)
}

function removeRetouchRegion(opId: string, regionId: string) {
  const op = stack.opById(opId) as any
  if (op?.exec?.kind !== 'retouch-regions') return
  fragileRetouchRegions.forget(regionId)
  // Removing a row can remove the DOM under the pointer, so mouseleave is not
  // guaranteed. End every hover path before mutating the stack.
  hoveredRetouchRegionId.value = null
  hoveredMaskComponentId.value = null
  hoveredRetouchMask.value = null
  hoveredRetouchOpId.value = null
  allRetouchFeedback.value = []
  allRetouchFeedbackRevision++
  const regions = op.regions.filter((region: RetouchRegion) => region.id !== regionId)
  if (regions.length) stack.setRegions(opId, regions)
  else {
    stack.removeOp(opId)
    if (retouchOpId.value === opId) resetRetouchSession()
    if (selectedOpId.value === opId) selectedOpId.value = null
  }
  if (selectedRetouchRegionId.value === regionId) {
    selectedRetouchRegionId.value = null
    selectedRetouchFeedbackVisible.value = false
  }
  if (maskedAdjustRegionId === regionId) maskedAdjustRegionId = null
  void refreshRetouchFeedback()
  // Region rows disappear immediately; coalesce a rapid trash run into one
  // full-resolution replay of the surviving regions.
  void render({ settleMs: RENDER_BURST_SETTLE_MS }).then(refreshRetouchInput)
}

/**
 * Selection is referential: if undo, row removal, or another edit path drops
 * its region, feedback and refinement must disappear in the same tick.
 */
watch(
  () => (stack.doc.value?.edits ?? []).flatMap((op: any) =>
    op.exec?.kind === 'retouch-regions'
      ? (op.regions ?? []).map((region: RetouchRegion) => region.id)
      : []
  ),
  liveIds => {
    const live = new Set(liveIds)
    let changed = false
    if (selectedRetouchRegionId.value && !live.has(selectedRetouchRegionId.value)) {
      selectedRetouchRegionId.value = null
      selectedMaskComponentId.value = null
      selectedRetouchFeedbackVisible.value = false
      changed = true
    }
    if (hoveredRetouchRegionId.value && !live.has(hoveredRetouchRegionId.value)) {
      hoveredRetouchRegionId.value = null
      hoveredMaskComponentId.value = null
      changed = true
    }
    if (maskedAdjustRegionId && !live.has(maskedAdjustRegionId)) {
      disarmMaskedAdjustmentEditing()
    }
    if (changed) void refreshRetouchFeedback()
  },
)

/**
 * Component selection is referential too: undo, a capture that rebuilt the
 * list, or a row removal must drop a selected component id that no longer
 * names anything. The legacy synthesized base id stays addressable.
 */
watch(
  () => {
    if (selectedGenerativeMaskOpId.value) {
      const op = stack.opById(selectedGenerativeMaskOpId.value) as any
      return generativeOpHasEditableMask(op)
        ? opMaskComponents(op).map(component => component.id)
        : []
    }
    const region = retouchRegionLocation(selectedRetouchRegionId.value)?.region
    return region
      ? regionMaskComponents(region as RetouchRegion).map(component => component.id)
      : []
  },
  componentIds => {
    const id = selectedMaskComponentId.value
    if (id && !componentIds.includes(id)) {
      selectedMaskComponentId.value = null
      void refreshRetouchFeedback()
    }
    const hovered = hoveredMaskComponentId.value
    if (hovered && hoveredRetouchRegionId.value === selectedRetouchRegionId.value
      && !componentIds.includes(hovered)) {
      hoveredMaskComponentId.value = null
      void refreshRetouchFeedback()
    }
  },
)

/**
 * While bound, the ants track the recipe: component toggles, deletions,
 * gradient drags, captures, undo — whatever changes the session target's
 * mask re-projects into the selection. The signature only moves on real
 * recipe changes, so ordinary renders never reload the ants.
 */
watch(
  () => {
    if (!maskSessionBound.value) return null
    if (selectedGenerativeMaskOpId.value) {
      const op = stack.opById(selectedGenerativeMaskOpId.value) as any
      return op
        ? JSON.stringify([op.id, op.mask_components ?? op.mask_ref ?? null])
        : null
    }
    const region = retouchRegionLocation(selectedRetouchRegionId.value)?.region as
      RetouchRegion | undefined
    return region
      ? JSON.stringify([
          region.id,
          region.mask_components ?? [region.mask ?? null, region.mask_ref ?? null],
        ])
      : null
  },
  (signature, previous) => {
    if (!signature || !previous || signature === previous) return
    void bindMaskSessionSelection()
  },
)

/**
 * A generative mask selection is referential too: undo or removal that drops
 * the op (or its editable mask) releases the session in the same tick.
 */
watch(
  () => {
    const id = selectedGenerativeMaskOpId.value
    if (!id) return true
    return generativeOpHasEditableMask(stack.opById(id))
  },
  valid => {
    if (!valid) {
      clearGenerativeMaskSelection()
      selectedMaskComponentId.value = null
      void refreshRetouchFeedback()
    }
  },
)

// -- annotate --------------------------------------------------------------------

/**
 * Annotations accumulate into one Annotate step per session. The shapes are the
 * params, so the step stays vector and re-entering it is lossless.
 */
/**
 * Dragging and on-canvas text entry stay local to the vector overlay. It
 * reports the finished shape list here once at mouseup / text-session end, so
 * the persistent stack, journal and autosave see one edit. One gesture, one
 * undo.
 */
const annotateGesture = ref(0)
const annotateGestureKey = computed(() => `annotate:${annotateGesture.value}`)

let annotationPreviewTimer: ReturnType<typeof setTimeout> | null = null
let annotationPreviewRevision = 0

/** The stage omits live vector overlays, so thumbnail them from the real doc. */
function scheduleAnnotationLivePreview() {
  const revision = ++annotationPreviewRevision
  if (annotationPreviewTimer) clearTimeout(annotationPreviewTimer)
  annotationPreviewTimer = setTimeout(async () => {
    annotationPreviewTimer = null
    const doc = stack.doc.value
    if (!doc) return
    try {
      const rendered = await compositor.render(JSON.parse(JSON.stringify(doc)))
      if (revision === annotationPreviewRevision) {
        publishEditorLivePreview(props.assetId, rendered)
      }
    } catch {
      // The normal render/save path remains authoritative; a live thumbnail is
      // an optimistic convenience and retries on the next edit.
    }
  }, 50)
}

/**
 * Reconcile the canvas's shape list against one step per shape.
 *
 * The canvas owns the list and reports the whole of it; this turns that into
 * creations, updates and removals. New shapes become steps at the top, changed
 * ones update in place under the gesture's coalesce key, and a shape that has
 * gone takes its step with it.
 */
function onAnnotationsChange(shapes: Shape[]) {
  const doc = stack.doc.value
  if (!doc) return
  const head = geometryBelow(doc, doc.edits.length)
  const documentFromHead = invertMatrix(head.matrix)
  if (!documentFromHead) return
  const inDocument = (shape: Shape): Shape => transformShapes(
    [shape],
    documentFromHead,
    head.width,
    head.height,
    doc.canvas.width,
    doc.canvas.height,
  )[0] as Shape

  const seen = new Set(shapes.map(shape => shape.id))
  const shapeToOp = new Map<string, string>()
  for (const op of annotateOps.value) {
    for (const shape of ((op as any).params?.shapes ?? []) as Shape[]) {
      shapeToOp.set(shape.id, op.id)
    }
  }

  const nextById = new Map(doc.edits.map(op => [op.id, op]))
  const additions: any[] = []
  let newestOpId: string | null = null

  for (const shape of shapes) {
    const documentShape = inDocument(shape)
    const opId = shapeToOp.get(shape.id)
    const existing = opId ? nextById.get(opId) as any : null
    if (opId && existing) {
      nextById.set(opId, {
        ...existing,
        label: shapeLabel(shape),
        shapes_in_document: true,
        params: { ...(existing.params || {}), shapes: [documentShape] },
      })
      continue
    }

    newestOpId = newOpId()
    additions.push({
      id: newestOpId,
      class: 'container',
      enabled: true,
      label: shapeLabel(shape),
      exec: { kind: 'annotate' },
      shapes_in_document: true,
      params: { shapes: [documentShape] },
    })
  }

  // Only the enabled ops the canvas was given can be reconciled against what
  // it returned. Hidden annotation rows remain untouched.
  const removed = new Set(
    visibleAnnotateOps.value
      .filter(op => {
        const held = ((op as any).params?.shapes ?? []) as Shape[]
        return !held.every(shape => seen.has(shape.id))
      })
      .map(op => op.id)
  )
  const nextEdits = [
    ...doc.edits.flatMap(op => removed.has(op.id) ? [] : (nextById.get(op.id) ?? [])),
    ...additions,
  ]

  stack.replaceEdits(nextEdits, annotateGestureKey.value)
  scheduleAnnotationLivePreview()
  if (newestOpId) selectedOpId.value = newestOpId
  // The live vector overlay already owns these pixels. Rebuilding the stage
  // here would only replay the stack, resample the palette and repaint the
  // source beneath an overlay that has not changed. When no overlay is active
  // (for example, an inspector edit while another family is open), the
  // composite does need the updated annotation.
  if (!annotationOverlayActive.value) void render()
}

/**
 * The stack takes the keyboard.
 *
 * A list of things you can select is a list you expect to walk with the arrow
 * keys and clear with Delete — and deleting should land you on the next row,
 * not nowhere, so a run of deletions is one gesture repeated rather than a
 * click between each.
 */
function focusRow(opId: string | null) {
  if (!opId) return
  // Keyboard navigation in Edits is just as intentional as clicking a row:
  // the selected step's controls, not the Looks browser, own the surface.
  looksOpen.value = false
  selectedOpId.value = opId
  void nextTick(() => {
    const element = sidebarEl.value?.querySelector<HTMLElement>(`[data-op-id="${opId}"]`)
    element?.focus()
  })
}

async function onStackKeydown(event: KeyboardEvent) {
  const doc = stack.doc.value
  // The inspector is a sibling of the list, and descendants such as candidate
  // and eye buttons own their own keys. Only a directly focused row may invoke
  // navigation, visibility, or destructive list commands.
  const current = directEditRowId(event.target)
  if (!doc || !current) return
  const index = doc.edits.findIndex(op => op.id === current)
  if (index < 0) return
  if (event.isComposing || event.metaKey || event.ctrlKey || event.altKey) return

  const command = editRowKeyboardCommand(event.key)
  if (!command) return
  event.preventDefault()
  event.stopPropagation()

  if (command.type === 'move-row') {
    // The list is drawn top-down with the newest first, opposite document order.
    const next = doc.edits[index + command.indexDelta]
    if (next) focusRow(next.id)
    return
  }

  if (command.type === 'move-candidate') {
    const available = candidateThumbs.value[current] ?? []
    const picked = (doc.edits[index] as any).picked as string | undefined
    const pickedIndex = available.findIndex(candidate => candidate.id === picked)
    const nextIndex = rowCandidateIndex(available.length, pickedIndex, command.candidateDelta)
    const next = available[nextIndex]
    if (next && nextIndex !== pickedIndex) {
      stack.pickCandidate(current, next.id)
      void render()
    }
    return
  }

  if (command.type === 'toggle') {
    if (!event.repeat) await setEnabledWithGeometry(current, !doc.edits[index].enabled)
    return
  }

  if (command.type === 'remove') {
    // Whatever sits where this row was, once it is gone.
    const after = doc.edits[index - 1] ?? doc.edits[index + 1] ?? null
    const nextId = after?.id ?? null
    await removeOpWithGeometry(current)
    if (nextId) focusRow(nextId)
    else selectedOpId.value = null
  }
}

/**
 * Selecting a row selects what the row IS.
 *
 * For an annotation that means the shape, so the canvas puts handles on it and
 * the inspector shows its properties — a row that named a thing but selected
 * nothing was a dead end.
 */
function onRowSelect(op: any) {
  if (maskedAdjustOpId && maskedAdjustOpId !== op.id) {
    releaseBoundSelection()
    disarmMaskedAdjustmentEditing()
  }
  if (maskedGenerativeOpId && maskedGenerativeOpId !== op.id) {
    releaseBoundSelection()
    clearGenerativeMaskSelection()
  }
  looksOpen.value = false
  selectedOpId.value = op.id
  // A parent-row click selects the parent, not whichever child happened to be
  // selected before it. Child clicks stop propagation and take their own path.
  if (selectedRetouchRegionId.value || hoveredRetouchRegionId.value) {
    selectedRetouchRegionId.value = null
    hoveredRetouchRegionId.value = null
    selectedMaskComponentId.value = null
    hoveredMaskComponentId.value = null
    selectedRetouchFeedbackVisible.value = false
    void refreshRetouchFeedback()
  }
  // A scoped Adjust step is one region wearing a row: clicking it should open
  // its controls, not an empty parent surface — and while it is selected, the
  // selection gestures belong to ITS mask.
  if (
    op.exec?.kind === 'retouch-regions'
    && (op.regions ?? []).length === 1
    && isMaskedAdjustmentKind(op.regions[0].kind)
  ) {
    selectedRetouchRegionId.value = op.regions[0].id
    selectedRetouchFeedbackVisible.value = false
    armMaskEditingForSelection(op.regions[0].id)
    if (!maskSessionBound.value) void bindMaskSessionSelection()
    void refreshRetouchFeedback()
  }
  // Selecting a generative row with an editable mask arms ITS mask session:
  // the composed mask binds as the live selection, gestures become
  // components, and Regenerate settles any debt.
  if (generativeOpHasEditableMask(op)) {
    selectedGenerativeMaskOpId.value = op.id
    maskedGenerativeOpId = op.id
    selectedRetouchFeedbackVisible.value = false
    if (!maskSessionBound.value) void bindMaskSessionSelection()
    void refreshRetouchFeedback()
  } else if (maskedGenerativeOpId === op.id) {
    releaseBoundSelection()
    clearGenerativeMaskSelection()
  }
  selectedShapeId.value = op.exec?.kind === 'annotate'
    ? (op.params?.shapes ?? [])[0]?.id ?? null
    : null
  // Selecting a shape puts handles on the canvas; an armed selection tool
  // would sit on top of them with the pointer.
  if (selectedShapeId.value) disarmSelect()
  syncImplicitPaintLayer()
}

/**
 * The canvas follows the host's shape selection too — a row click or a family
 * switch must put handles up, and the canvas keeps its own selection state for
 * gesture-time reasons, so it is pushed rather than passed.
 */
watch([selectedShapeId, annotateRef], ([id]) => {
  annotateRef.value?.setSelected(id)
})

/** Selecting an annotation selects its step, so the stack follows the canvas. */
function onShapeSelected(shapeId: string | null) {
  selectedShapeId.value = shapeId
  const opId = shapeId ? opIdForShape(shapeId) : null
  if (opId) {
    selectedOpId.value = opId
  } else {
    const selectedOp = selectedOpId.value ? stack.opById(selectedOpId.value) as any : null
    if (selectedOp?.exec?.kind === 'annotate') selectedOpId.value = null
  }
}

/**
 * The gesture ended: the next one starts its own undo step, and a tool that
 * just CREATED something hands back to Select.
 *
 * One-shot creation is what removes the create-versus-move ambiguity rather
 * than arbitrating it: with no armed creation tool, a drag on top of a shape
 * can only mean move. Drawing another takes one keystroke, and you almost
 * always want to adjust the thing you just made first.
 */
function onAnnotationCommit(action: string) {
  annotateGesture.value += 1
  if (family.value === 'annotate' && action.startsWith('Draw')) sub.value = null
}

// -- selection handoff ------------------------------------------------------------

/**
 * Arm a selection tool: the overlay takes the pointer, the open family is
 * SUSPENDED — its session, step and controls all survive underneath. Clicking
 * the armed tool again hands the pointer back.
 */
function armSelectTool(id: SelectToolId, force = false) {
  // Crop replaces the display box with its own viewport, so there is nothing
  // to select over; arming from inside it leaves it first.
  if (family.value === 'crop') leaveMode()
  if (!force && armedSelectTool.value === id) {
    disarmSelect()
    return
  }
  armedSelectTool.value = id
  if (id === 'brush') selectCombine.value = 'add'
  lastSelectTool.value = id
  writeToolPrefs({ selectTool: id })
  // Arming Object is the earliest honest signal a segmentation is coming;
  // encode now so the click only pays the decoder.
  if (id === 'object') warmAiSelect()
}

/**
 * Hand the pointer back to whatever family is open. Reaching for any control
 * that implies a canvas gesture — a paint engine, an annotate sub-tool, a
 * family — calls this: a selection tool that stays armed past the user's
 * attention is a broken pointer.
 */
function disarmSelect() {
  armedSelectTool.value = null
}

// The preview only means anything while a selection tool can gesture.
watch(armedSelectTool, armed => {
  if (!armed) heldCombineOverride.value = null
})

/** Island-only settings: tuning the armed tool must never disarm it. */
function onSelectionSet(patch: Record<string, any>) {
  if ('combine' in patch) selectCombine.value = patch.combine
  if ('featherPx' in patch) selectFeather.value = patch.featherPx
  if ('tolerance' in patch) selectTolerance.value = patch.tolerance
  if ('spread' in patch) selectSpread.value = patch.spread
  if ('growPx' in patch) selectGrow.value = patch.growPx
  if ('antialias' in patch) selectAntialias.value = patch.antialias
  if ('selectBrushSize' in patch) selectBrushSize.value = patch.selectBrushSize
  // The gradient sliders edit the ramp on the canvas when there is one, and the
  // default for the next ramp when there is not. Same control, and the mask
  // thumbnail plus the guides make which one is happening obvious.
  if ('gradientSoftness' in patch) {
    selectGradientSoftness.value = patch.gradientSoftness
    retuneActiveGradient(patch.gradientSoftness, 'linear')
  }
  if ('gradientFeather' in patch) {
    selectGradientFeather.value = patch.gradientFeather
    retuneActiveGradient(patch.gradientFeather, 'radial')
  }
}

function retuneActiveGradient(value: number, kind: 'linear' | 'radial') {
  const current = canvasGradient.value
  if (!current || current.kind !== kind) return
  onGradientEdit(withGradientSlider(current, value))
}

function clearSelection() {
  // Through the overlay when it exists (it also cancels an in-flight gesture);
  // straight at the model when crop has the display box (overlay unmounted) —
  // otherwise the ants would come back the moment crop closes.
  if (selectRef.value) selectRef.value.clear()
  else {
    selModel.clearSelection()
    // With no overlay there is no published `change`, but clear is still the
    // explicit end of a Regenerate session.
    selectionRevision += 1
    repaintSession = null
  }
  selection.value = null
  selectionMaster = null
  selectionToDocument = null
  selectionAppliedKey = null
  selectionIsGradient.value = false
  workspaceGradient.value = null
  workspaceGradientKey.value = null
  workspaceSemantic.value = null
  workspaceSemanticKey.value = null
  workspaceMaskRecipe = null
  workspaceMaskRecipeKey = null
  pendingGestureCapture = null
  // Combine modes describe how a gesture meets an existing selection. Once
  // there is no existing selection, the next gesture starts a new one.
  selectCombine.value = combineAfterSelectionChange(
    selectCombine.value, false, armedSelectTool.value,
  )
}

function morphSelection(deltaPx: number) {
  if (!selection.value || !deltaPx) return
  if (selectRef.value) {
    selectRef.value.morph(deltaPx)
    return
  }
  // Crop temporarily unmounts the overlay, but workspace selection state still
  // exists and the island remains usable.
  selModel.morph(deltaPx)
  onSelectionChange(selModel.hasSelection() ? selModel.getSelectionMask() : null)
}

function invertSelection() {
  selectRef.value?.invert()
}

// -- AI select (prompt-to-mask) ---------------------------------------------

const aiSelectBusy = ref(false)
const aiSelectError = ref<string | null>(null)
type AiSelectAction = 'find' | 'subject' | 'background' | 'sky' | 'canvas'
const aiSelectAction = ref<AiSelectAction | null>(null)
const aiSelectProgressVisible = ref(false)
type AiSelectStage = 'starting' | 'downloading_model' | 'loading' | 'processing_image' | 'selecting'
const aiSelectStage = ref<AiSelectStage>('starting')
const AI_SELECT_PROGRESS_DELAY_MS = 400
let aiSelectProgressTimer: ReturnType<typeof setTimeout> | null = null
let aiSelectProgressPollTimer: ReturnType<typeof setInterval> | null = null
/** Segmentation can take seconds; the panel's Cancel (and Esc) abort it. */
let aiSelectAbort: AbortController | null = null

/** Longest side sent to object segmentation. SAM3 works at ~1k. */
const AI_SELECT_MAX_SIDE = 1536
/** Sky semantics run at 384px, but its guided edge pass needs source detail. */
const AI_SKY_SELECT_MAX_SIDE = 4096

/**
 * The last Object click's granularity stack. The tracker returns the clicked
 * object at every granularity (object → part → subpart, area-descending);
 * clicking the SAME spot again steps to the next one, locally, against the
 * selection as it was before the first application — no second request.
 */
let objectPickState: {
  src: HTMLCanvasElement
  x: number
  y: number
  masks: HTMLImageElement[]
  index: number
  mode: SelectionMode
  before: HTMLCanvasElement | null
} | null = null
/** True while an applyMask below is publishing, so onSelectionChange can tell
 *  our own change events from a gesture that invalidates the cycle stack. */
let applyingAiMask = false

/**
 * The composite as segmentation sees it. Warm and select MUST both come
 * through here: the backend's embedding cache is keyed on the sent bytes, so
 * a warm encoded any other way buys nothing.
 */
function aiSelectCanvas(
  src: HTMLCanvasElement,
  maxSide = AI_SELECT_MAX_SIDE,
): HTMLCanvasElement {
  const scale = Math.min(1, maxSide / Math.max(src.width, src.height))
  if (scale >= 1) return src
  const sent = document.createElement('canvas')
  sent.width = Math.round(src.width * scale)
  sent.height = Math.round(src.height * scale)
  sent.getContext('2d')!.drawImage(src, 0, 0, sent.width, sent.height)
  return sent
}

/**
 * Fire-and-forget encoder warm-up, sent when the Object tool arms: model load
 * plus the encoder pass happen while the user aims, so the click itself pays
 * only the decoder. Arming is the earliest signal of intent worth this much
 * compute — composite edits do NOT re-warm.
 */
function warmAiSelect() {
  const src = composite.value
  if (!src) return
  const image_data_url = aiSelectCanvas(src).toDataURL('image/png')
  void axios.post('/api/mask/select/warm', { image_data_url }).catch(() => {})
}

function loadMaskImage(dataUrl: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('mask decode failed'))
    img.src = dataUrl
  })
}

function applyAiMask(mask: CanvasImageSource, mode: SelectionMode) {
  applyingAiMask = true
  try {
    selectRef.value?.applyMask(mask, mode)
  } finally {
    applyingAiMask = false
    // Publish is synchronous, so a landing not consumed by now would only
    // mislabel some LATER gesture as semantic.
    aiGestureLanding = null
  }
}

/** An AI mask comes back at the SENT (possibly downscaled) size; the recipe
 *  keeps coverage in source pixels like every other gesture. */
function coverageAtSourceSize(
  mask: CanvasImageSource,
  src: HTMLCanvasElement,
): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = src.width
  canvas.height = src.height
  canvas.getContext('2d')!.drawImage(mask as any, 0, 0, canvas.width, canvas.height)
  return canvas
}

/**
 * AI select: segment the CURRENT composite (the pixels the selection will sit
 * over) and land the result exactly as a drawn gesture would, through the
 * combine mode. A PROMPT names a concept and selects every instance of it; a
 * POINT (normalized 0-1) selects the object under the click; an INTENT asks
 * BEN2 for the whole subject or its exact background complement, or the
 * dedicated SkyWater pipeline for sky.
 */
type AiSelectRequest = {
  prompt?: string
  point?: { x: number; y: number }
  intent?: 'subject' | 'background' | 'sky'
}

function aiActionFor(request: AiSelectRequest): AiSelectAction {
  if (request.point) return 'canvas'
  if (request.intent === 'subject') return 'subject'
  if (request.intent === 'background') return 'background'
  if (request.intent === 'sky') return 'sky'
  return 'find'
}

function stopAiSelectProgressPolling() {
  if (aiSelectProgressPollTimer) clearInterval(aiSelectProgressPollTimer)
  aiSelectProgressPollTimer = null
}

function startAiSelectProgressPolling(requestId: string, abort: AbortController) {
  stopAiSelectProgressPolling()
  const refresh = async () => {
    if (abort.signal.aborted || aiSelectAbort !== abort) return
    try {
      const { data } = await axios.get(`/api/mask/select/progress/${requestId}`)
      if (!abort.signal.aborted && aiSelectAbort === abort && data?.stage) {
        aiSelectStage.value = data.stage as AiSelectStage
      }
    } catch {
      // Progress is supplementary; the selection request owns real errors.
    }
  }
  void refresh()
  aiSelectProgressPollTimer = setInterval(refresh, 200)
}

async function runAiSelect(
  request: AiSelectRequest,
  mode: SelectionMode = selectCombine.value,
) {
  if (aiSelectBusy.value) return
  // Crop replaces the display box, so there is no overlay to land a mask on.
  if (family.value === 'crop') leaveMode()
  const src = composite.value
  if (!src || !selectRef.value) return
  aiSelectBusy.value = true
  aiSelectAction.value = aiActionFor(request)
  aiSelectProgressVisible.value = false
  aiSelectStage.value = 'starting'
  aiSelectProgressTimer = setTimeout(() => {
    aiSelectProgressVisible.value = true
  }, AI_SELECT_PROGRESS_DELAY_MS)
  aiSelectError.value = null
  const abort = new AbortController()
  aiSelectAbort = abort
  const request_id = globalThis.crypto?.randomUUID?.()
    ?? `select-${Date.now()}-${Math.random().toString(36).slice(2)}`
  startAiSelectProgressPolling(request_id, abort)
  try {
    const sent = aiSelectCanvas(
      src,
      request.intent === 'sky' ? AI_SKY_SELECT_MAX_SIDE : AI_SELECT_MAX_SIDE,
    )
    const image_data_url = sent.toDataURL('image/png')
    const { data } = await axios.post('/api/mask/select', {
      request_id,
      image_data_url,
      ...request,
    }, { signal: abort.signal })
    if (!data.success || !data.detections?.length) {
      aiSelectError.value = data.error
        || (request.prompt ? `No match for “${request.prompt}”` : 'No object at that point')
      return
    }
    const masks = await Promise.all(
      data.detections.map((d: any) => loadMaskImage(d.mask_data_url))
    )
    if (request.point) {
      // One object, several granularities: apply the object-level mask and
      // keep the rest for same-spot cycling.
      objectPickState = {
        src,
        x: request.point.x * src.width,
        y: request.point.y * src.height,
        masks,
        index: 0,
        mode,
        before: selModel.toSnapshot(),
      }
      aiGestureLanding = {
        semantic: null,
        replaces: mode === 'new' || !selModel.hasSelection(),
        coverage: coverageAtSourceSize(masks[0], src),
        mode,
      }
      applyAiMask(masks[0], mode)
      return
    }
    // A named concept is the union of every instance. BEN2 intents return one
    // mask and take the same path.
    const union = document.createElement('canvas')
    union.width = sent.width
    union.height = sent.height
    const unionCtx = union.getContext('2d')!
    for (const mask of masks) unionCtx.drawImage(mask, 0, 0, union.width, union.height)
    // A named selection keeps its name — the landing change handler records
    // it with the gesture's own coverage, so it stays an editable, later
    // recomputable ingredient whatever it gets combined with.
    aiGestureLanding = {
      semantic: request.prompt
        ? { prompt: request.prompt }
        : request.intent
          ? { intent: request.intent }
          : null,
      replaces: mode === 'new' || !selModel.hasSelection(),
      coverage: coverageAtSourceSize(union, src),
      mode,
    }
    applyAiMask(union, mode)
  } catch (e: any) {
    // A cancel is an answer, not a failure: the panel returns to rest with no
    // error to read.
    if (!abort.signal.aborted) aiSelectError.value = e?.message || 'Selection failed'
  } finally {
    if (aiSelectProgressTimer) clearTimeout(aiSelectProgressTimer)
    aiSelectProgressTimer = null
    stopAiSelectProgressPolling()
    aiSelectProgressVisible.value = false
    aiSelectStage.value = 'starting'
    aiSelectAction.value = null
    aiSelectBusy.value = false
    if (aiSelectAbort === abort) aiSelectAbort = null
  }
}

function cancelAiSelect() {
  aiSelectAbort?.abort()
}

/** A same-spot re-click means "not that granularity": within this radius (in
 *  source pixels, scaled for large sources) the click cycles instead of
 *  re-segmenting. */
function objectCycleRadius(src: HTMLCanvasElement): number {
  return Math.max(8, Math.max(src.width, src.height) * 0.01)
}

/** The Object tool's click uses the same explicit combine control as every
 *  other selection tool. Shift remains the geometry constraint for rectangle
 *  and ellipse rather than meaning something different only for Object. */
function onObjectPick(pick: { x: number; y: number; combine?: SelectionMode }) {
  const src = composite.value
  if (!src) return
  const cycle = objectPickState
  if (
    cycle && cycle.src === src && cycle.masks.length > 1
    && Math.hypot(pick.x - cycle.x, pick.y - cycle.y) <= objectCycleRadius(src)
  ) {
    cycle.index = (cycle.index + 1) % cycle.masks.length
    if (cycle.before) selModel.loadFromSnapshot(cycle.before)
    else selModel.clearSelection()
    aiGestureLanding = {
      semantic: null,
      replaces: cycle.mode === 'new' || !selModel.hasSelection(),
      coverage: coverageAtSourceSize(cycle.masks[cycle.index], src),
      mode: cycle.mode,
      // The re-land supersedes the previous granularity's recipe entry.
      cycling: true,
    }
    applyAiMask(cycle.masks[cycle.index], cycle.mode)
    return
  }
  void runAiSelect(
    { point: { x: pick.x / src.width, y: pick.y / src.height } },
    pick.combine ?? selectCombine.value,
  )
}

/**
 * The affine from the crop geometry's frame to the actual composite frame —
 * the part `geometryBelow` cannot see, because Expand grows the frame with
 * pixels rather than with geometry: it pads around unmoved content, so the
 * mapping is a centred translate. A frame change that is not that has no honest
 * mapping, and returns null.
 *
 * There used to be a uniform-scale case here for an upscale checkpoint. The
 * output stage runs at save, on the flattened composite, so no step ever
 * rescales the frame under a live selection any more.
 */
function frameAdjust(
  geomW: number, geomH: number, frameW: number, frameH: number
): number[] | null {
  if (geomW === frameW && geomH === frameH) return [1, 0, 0, 1, 0, 0]
  if (frameW >= geomW && frameH >= geomH) {
    return [1, 0, 0, 1, Math.round((frameW - geomW) / 2), Math.round((frameH - geomH) / 2)]
  }
  return null
}

/** Every gesture end republishes: the mask consumers copy, and the master the
 *  geometry sync re-derives from. */
function onSelectionChange(mask: HTMLCanvasElement | null) {
  selectionRevision += 1
  repaintSession = null
  // Whether a selection existed BEFORE this change — the recipe needs to know
  // if the landing gesture replaced emptiness or combined onto coverage.
  const hadSelection = !!selection.value
  // Any change the Object tool didn't publish itself (a drawn gesture, clear,
  // invert) makes its granularity stack stale — cycling would resurrect the
  // pre-click selection over the user's newer edits.
  if (!applyingAiMask) objectPickState = null
  selection.value = mask
  // The patch flow is select-then-DRAG: the moment the selection lands, the
  // pointer hands back to the paint canvas so the very next gesture drags it.
  if (
    mask && armedSelectTool.value
    && family.value === 'retouch' && sub.value === 'patch'
  ) {
    armedSelectTool.value = null
  }
  // Consume the one-shot gesture identity FIRST, whatever the flattened
  // result was: an intersect or subtract gesture over an empty workspace
  // publishes null, and the gesture must not vanish with it.
  const landedAsGradient = gradientGestureLanding
  gradientGestureLanding = false
  const landedAsAi = aiGestureLanding
  aiGestureLanding = null
  const drawnGesture = pendingGestureCapture
  pendingGestureCapture = null
  const gestureMode = landedAsAi?.mode
    ?? drawnGesture?.combine
    ?? (landedAsGradient ? lastGestureGradientCombine : null)
    ?? selectCombine.value
  const gestureInput: {
    mask?: HTMLCanvasElement
    gradient?: GradientMask
    semantic?: AdjustmentScopeSemantic
    label?: string
    replacesPrevious?: boolean
  } | null = landedAsGradient && lastGestureGradient
    ? { gradient: { ...lastGestureGradient } }
    : landedAsAi?.coverage
      ? {
          mask: landedAsAi.coverage,
          semantic: landedAsAi.semantic ?? undefined,
          label: landedAsAi.semantic ? undefined : GESTURE_TOOL_LABELS.object,
          replacesPrevious: landedAsAi.cycling,
        }
      : drawnGesture
        ? {
            mask: drawnGesture.coverage,
            label: GESTURE_TOOL_LABELS[drawnGesture.tool],
          }
        : null

  // A programmatic re-load of the BOUND selection (the session step's
  // composed mask arriving as ants): bookkeeping only — it must not capture
  // itself back into the mask or pretend to be a recipe.
  if (syncingBoundSelection && mask) {
    selectCombine.value = combineAfterSelectionChange(selectCombine.value, true)
    selectionMaster = selModel.toSnapshot()
    const boundHead = payloadFrame()
    const boundAdjust = boundHead && composite.value
      ? frameAdjust(
          boundHead.width, boundHead.height,
          composite.value.width, composite.value.height,
        )
      : null
    const boundCompositeFromDocument = boundHead && boundAdjust
      ? multiply(boundAdjust as Affine, boundHead.matrix as Affine)
      : null
    selectionToDocument = boundCompositeFromDocument
      ? invertMatrix(boundCompositeFromDocument)
      : null
    selectionAppliedKey = composite.value
      ? appliedKeyFor(boundHead, composite.value.width, composite.value.height)
      : null
    selectionIsGradient.value = false
    workspaceGradient.value = null
    workspaceGradientKey.value = null
    workspaceSemantic.value = null
    workspaceSemanticKey.value = null
    workspaceMaskRecipe = null
    workspaceMaskRecipeKey = null
    return
  }

  const wasBound = maskSessionBound.value

  // Which mask a gesture edits is what the workspace answers. BOUND: the
  // selection IS the session step's mask, so every combining gesture lands as
  // a component (the ants already show the model's own combination; the
  // composed result resyncs after the commit) — and `New` is the walk-away,
  // becoming an ordinary fresh selection. UNBOUND: a live selection takes the
  // gesture; an empty workspace hands combines to the armed step; `New` never
  // captures (base Replace arms explicitly from the inspector).
  const replaceArmed = maskBaseReplaceArmed
  if (gestureInput) maskBaseReplaceArmed = false
  const sessionArmed = !suppressMaskedAdjustmentSync
    && ((maskedAdjustRegionId && maskedAdjustOpId) || !!maskedGenerativeOpId)
  const captures = !!gestureInput && sessionArmed && (
    wasBound
      ? gestureMode !== 'new' || replaceArmed
      : !hadSelection && (gestureMode !== 'new' || replaceArmed)
  )
  if (captures && gestureInput) {
    const capture: MaskComponentCapture = {
      mode: gestureMode,
      gradient: gestureInput.gradient ?? null,
      semantic: gestureInput.semantic ?? null,
      label: !gestureInput.gradient && !gestureInput.semantic
        ? gestureInput.label ?? null
        : null,
    }
    if (maskedGenerativeOpId) {
      queueGenerativeMaskCapture(gestureInput.mask ?? null, capture)
    } else {
      queueMaskComponentCapture(gestureInput.mask ?? null, capture)
    }
    if (wasBound) {
      // Stay bound and keep the tool: the ants already approximate the new
      // composition, the exact resync follows the commit, and the next
      // stroke continues the same mask.
      return
    }
    // Unbound legacy capture: the workspace copy is consumed, and the
    // re-entrant clear resets the bookkeeping this early return skips.
    consumeWorkspaceSelection()
    armedSelectTool.value = null
    return
  }
  if (wasBound && mask) {
    // A gesture the bound mask does not take — `New`. The session ends and
    // this selection is an ordinary fresh one; the step's mask stays as the
    // components say.
    maskSessionBound.value = false
    disarmMaskedAdjustmentEditing()
    clearGenerativeMaskSelection()
    selectedRetouchRegionId.value = null
    selectedMaskComponentId.value = null
    selectedRetouchFeedbackVisible.value = false
    void refreshRetouchFeedback()
  }

  if (!mask) {
    if (wasBound) endBoundMaskSession()
    selectionMaster = null
    selectionToDocument = null
    selectionAppliedKey = null
    workspaceGradient.value = null
    workspaceGradientKey.value = null
    workspaceSemantic.value = null
    workspaceSemanticKey.value = null
    workspaceMaskRecipe = null
    workspaceMaskRecipeKey = null
    selectionIsGradient.value = false
    selectCombine.value = combineAfterSelectionChange(
      selectCombine.value, false, armedSelectTool.value,
    )
    return
  }
  selectCombine.value = combineAfterSelectionChange(selectCombine.value, true)
  selectionMaster = selModel.toSnapshot()
  const head = payloadFrame()
  const adjust = head && composite.value
    ? frameAdjust(head.width, head.height, composite.value.width, composite.value.height)
    : null
  // The current composite is `adjust × head.matrix × document`. Invert it
  // once at authoring time; every later projection starts from this canonical
  // local-selection → document relationship.
  const compositeFromDocument = head && adjust
    ? multiply(adjust as Affine, head.matrix as Affine)
    : null
  selectionToDocument = compositeFromDocument
    ? invertMatrix(compositeFromDocument)
    : null
  selectionAppliedKey = null
  if (composite.value) {
    selectionAppliedKey = appliedKeyFor(head, composite.value.width, composite.value.height)
  }
  // A gradient gesture keeps its parametric identity for Adjust to scope
  // with; any other gesture makes the selection drawn pixels. The key pins
  // the frame the ramp was drawn in — geometry changes underneath invalidate
  // it, and the raster (which sync DOES carry) becomes the honest scope.
  selectionIsGradient.value = landedAsGradient
  if (landedAsGradient) {
    workspaceGradientKey.value = selectionAppliedKey
  } else {
    workspaceGradient.value = null
    workspaceGradientKey.value = null
  }
  // Semantic identity follows the gradient's discipline: it survives only
  // while the selection IS the one recomputable AI gesture. Any drawn
  // gesture, or an AI mask combined onto existing coverage, flattens it.
  if (landedAsAi?.semantic && landedAsAi.replaces) {
    workspaceSemantic.value = { ...landedAsAi.semantic }
    workspaceSemanticKey.value = selectionAppliedKey
  } else {
    workspaceSemantic.value = null
    workspaceSemanticKey.value = null
  }

  // The recipe: this change as ONE gesture with its own coverage and
  // identity. A change nothing captured (invert, morph, a snapshot rewrite)
  // has no gesture to record, and the recipe honestly resigns.
  if (gestureInput) {
    workspaceMaskRecipe = appendWorkspaceMaskGesture(
      workspaceMaskRecipe,
      { combine: gestureMode, hadSelection, ...gestureInput },
      mergeCoverageMax,
    )
    workspaceMaskRecipeKey = workspaceMaskRecipe ? selectionAppliedKey : null
  } else {
    workspaceMaskRecipe = null
    workspaceMaskRecipeKey = null
  }
}

/** Union of two coverage canvases by per-pixel max — the brush's own rule. */
function mergeCoverageMax(
  a: HTMLCanvasElement,
  b: HTMLCanvasElement,
): HTMLCanvasElement {
  const out = document.createElement('canvas')
  out.width = a.width
  out.height = a.height
  const ctx = out.getContext('2d', { willReadFrequently: true })!
  ctx.drawImage(a, 0, 0)
  const merged = ctx.getImageData(0, 0, out.width, out.height)
  const scratch = document.createElement('canvas')
  scratch.width = a.width
  scratch.height = a.height
  const scratchCtx = scratch.getContext('2d', { willReadFrequently: true })!
  scratchCtx.drawImage(b, 0, 0, scratch.width, scratch.height)
  const other = scratchCtx.getImageData(0, 0, scratch.width, scratch.height)
  for (let i = 3; i < merged.data.length; i += 4) {
    if (other.data[i] > merged.data[i]) {
      merged.data[i] = other.data[i]
      merged.data[i - 3] = 255
      merged.data[i - 2] = 255
      merged.data[i - 1] = 255
    }
  }
  ctx.putImageData(merged, 0, 0)
  return out
}

function appliedKeyFor(
  head: { matrix: any } | undefined | null, width: number, height: number
): string {
  return JSON.stringify({ m: head?.matrix ?? null, width, height })
}

/**
 * A live selection pre-fills the next mask. Captured by COPY at the moment it
 * is used, never live-linked — the op ends up referencing only its own payload,
 * while the workspace selection remains available for another operation.
 * Flattened onto black: white-where-selected on opaque black is the shape every
 * mask consumer expects (the model’s own canvas is white on transparent).
 */
function selectionAsMask(): HTMLCanvasElement | null {
  if (!selection.value) return null
  const copy = document.createElement('canvas')
  copy.width = selection.value.width
  copy.height = selection.value.height
  const ctx = copy.getContext('2d')!
  ctx.fillStyle = '#000'
  ctx.fillRect(0, 0, copy.width, copy.height)
  ctx.drawImage(selection.value, 0, 0)
  return copy
}

/**
 * Keep the selection registered to the pixels it was drawn over.
 *
 * The selection lives at the head of the stack, so any change to the geometry
 * below the head moves the image under it: crop edits, toggles, reorders, and
 * Expand, which pads the frame around the pixels already there.
 * Re-derives from the as-created master each time — never from the previous
 * derivative — and runs after every render, which is the one funnel all of
 * those changes already pass through.
 */
function syncSelectionGeometry() {
  if (!selectionMaster || !selectionToDocument || !stack.doc.value || !composite.value) return

  const head = payloadFrame()
  if (!head) return
  const frameW = composite.value.width
  const frameH = composite.value.height

  const key = appliedKeyFor(head, frameW, frameH)
  if (key === selectionAppliedKey) return

  // A raster selection can be carried through a frame change, but the saved
  // gradient coordinates name the old frame. Drop only the parametric claim;
  // the transformed raster remains the honest selection fallback.
  if (workspaceGradientKey.value && workspaceGradientKey.value !== key) {
    selectionIsGradient.value = false
    workspaceGradient.value = null
    workspaceGradientKey.value = null
  }
  // Semantic identity is pinned to the frame the gesture segmented; the
  // transformed raster remains the honest selection after a frame change.
  if (workspaceSemanticKey.value && workspaceSemanticKey.value !== key) {
    workspaceSemantic.value = null
    workspaceSemanticKey.value = null
  }
  // Recipe coverages were captured in the old frame too; the carried raster
  // is the honest selection now.
  if (workspaceMaskRecipeKey && workspaceMaskRecipeKey !== key) {
    workspaceMaskRecipe = null
    workspaceMaskRecipeKey = null
  }

  const adjustNow = frameAdjust(head.width, head.height, frameW, frameH)
  if (!adjustNow) {
    // A frame change with no honest mapping: a wrong selection is worse than
    // none, so it clears — visibly, since the ants vanish with it.
    clearSelection()
    return
  }
  // local selection → permanent document → current geometry → current frame.
  const documentToComposite = multiply(adjustNow as Affine, head.matrix as Affine)
  const matrix = multiply(documentToComposite, selectionToDocument)

  const rewritten = rewritePayload(selectionMaster, matrix, frameW, frameH)
  selModel.initSelection({ width: frameW, height: frameH })
  selModel.loadFromSnapshot(rewritten)
  selection.value = selModel.hasSelection() ? selModel.getSelectionMask() : null
  if (!selection.value) { clearSelection(); return }
  selectionAppliedKey = key
  selectRef.value?.redraw()
}

// -- compare -------------------------------------------------------------------

/**
 * Compare against the base. Toggling into compare swaps the canvas for a
 * before/after wipe (ImageCompareSlider) — the original on the left, the edited
 * composite on the right. Both are encoded at the composite's frame so the
 * divider reveals the same pixel location on either side even after geometry
 * ops (a crop) change the frame.
 */
const comparing = ref(false)
const baseImage = ref<HTMLImageElement | null>(null)
const compareOriginalUrl = ref<string | null>(null)
const compareEditedUrl = ref<string | null>(null)

async function toggleCompare() {
  if (comparing.value) {
    comparing.value = false
    return
  }
  const src = composite.value
  if (!src) return
  const baseMediaId = stack.doc.value?.base.media_id
  if (!baseImage.value && baseMediaId) {
    baseImage.value = await loadImage(getMediaFileUrl(Number(baseMediaId)))
  }
  compareEditedUrl.value = src.toDataURL()
  if (baseImage.value) {
    // Draw the base into the composite's frame, so a cropped edit lines up with
    // its original instead of the two images sitting at different sizes.
    const frame = document.createElement('canvas')
    frame.width = src.width
    frame.height = src.height
    frame.getContext('2d')!.drawImage(baseImage.value, 0, 0, frame.width, frame.height)
    compareOriginalUrl.value = frame.toDataURL()
  } else {
    compareOriginalUrl.value = compareEditedUrl.value
  }
  comparing.value = true
}

// -- output stage ----------------------------------------------------------

/**
 * The upscaler used when the document has not named one. Kept out of the
 * document until the stage is actually turned on: writing a default into
 * document.json on open would mark a freshly-opened image as edited.
 */
const defaultUpscaleToolId = ref<string | null>(null)
const outputPickerOpen = ref(false)

/** Which sidebar panel is showing. Edits owns the stack, Output owns the
 * terminal stage, and Info reuses the library's media-information body. */
const sidebarTab = ref<'edits' | 'output' | 'info'>('edits')

async function loadEditorMediaInfo() {
  const token = ++infoLoadToken
  infoLoading.value = true
  try {
    // This is deliberately the Asset's projected HEAD, not the editor's base
    // payload. An existing editor autosave is a head revision with its own
    // Image Editor lineage step and marker state.
    const item = await getAssetBrowserItem(Number(props.assetId))
    if (token !== infoLoadToken) return
    const mediaId = Number(item.media_id)
    infoItem.value = {
      ...item,
      id: mediaId,
      media_id: mediaId,
    }

    const [projects, boards, faceResult, lineage, chat] = await Promise.all([
      getAssetProjects(Number(props.assetId)).catch(() => []),
      getAssetBoards(Number(props.assetId)).catch(() => []),
      getMediaFaces(mediaId).catch(() => ({ faces: [] })),
      axios.get(`/api/media/${mediaId}/lineage?include_descendants=true`)
        .then(response => response.data)
        .catch(() => ({ derivatives: [], descendants: [] })),
      item.chat_item_id
        ? axios.get(`/api/chats/by-item/${item.chat_item_id}`)
            .then(response => response.data)
            .catch(() => null)
        : Promise.resolve(null),
    ])
    if (token !== infoLoadToken) return

    const descendants = [
      ...(lineage?.derivatives ?? []),
      ...(lineage?.descendants ?? []),
    ]
      .filter(entry => entry?.media?.id)
      .map(entry => ({
        ...entry.media,
        _relationship_type: entry.relationship_type ?? 'derived',
      }))
    const uniqueDescendants = [...new Map(
      descendants.map(descendant => [descendant.id, descendant]),
    ).values()]

    infoProjects.value = projects
    infoBoards.value = boards
    infoFaces.value = faceResult?.faces ?? []
    infoDescendants.value = uniqueDescendants.filter(
      descendant => descendant._relationship_type !== 'inspired',
    )
    infoInspiredDescendants.value = uniqueDescendants.filter(
      descendant => descendant._relationship_type === 'inspired',
    )
    infoChat.value = chat
  } catch (infoError) {
    if (token === infoLoadToken) {
      console.warn('[imageEditor] could not load media info', infoError)
      // The editor document still carries enough authoritative information for
      // the technical facts section, even if the richer media request failed.
      infoItem.value = {
        ...baseInfo.value,
        id: Number(baseInfo.value?.media_id),
        media_id: Number(baseInfo.value?.media_id),
        asset_id: Number(props.assetId),
      }
    }
  } finally {
    if (token === infoLoadToken) infoLoading.value = false
  }
}

watch(sidebarTab, tab => {
  if (tab === 'info') void loadEditorMediaInfo()
})

async function toggleInfoMarker(markerId: number) {
  const active = (infoItem.value?.markers ?? []).some((marker: any) => marker.id === markerId)
  try {
    if (active) await removeAssetMarker(Number(props.assetId), markerId)
    else await addAssetMarker(Number(props.assetId), markerId)
    await loadEditorMediaInfo()
    infoMarkerUpdateTrigger.value += 1
  } catch (markerError) {
    console.error('[imageEditor] could not update marker', markerError)
  }
}

function updateInfoTags(_mediaId: number, tags: any[]) {
  if (infoItem.value) infoItem.value = { ...infoItem.value, tags }
}

function navigateInfoProject(projectId: number) {
  void router.push({ name: 'project-overview', params: { id: projectId } })
}

function navigateInfoBoard(boardId: number) {
  void router.push({ name: 'board-detail', params: { id: boardId } })
}

function navigateInfoMedia(mediaId: number) {
  void openImageEditor(router, mediaId)
}

function navigateInfoLineage() {
  if (infoItem.value?.id) {
    void router.push({ name: 'lineage', params: { mediaId: infoItem.value.id } })
  }
}

function navigateInfoChat(chatId: number) {
  void router.push(`/chat/${chatId}`)
}

const outputStage = computed(() => {
  const stored = outputOf(stack.doc.value?.output)
  return { ...stored, tool_id: stored.tool_id ?? defaultUpscaleToolId.value }
})

/** What a save starts from — the composite's real size, not the base's. */
const outputInput = computed(() => ({
  width: composite.value?.width ?? stack.doc.value?.canvas.width ?? 0,
  height: composite.value?.height ?? stack.doc.value?.canvas.height ?? 0,
}))

function updateOutput(patch: Partial<OutputStage>) {
  // The tool is written down the moment the stage starts mattering, so the
  // saved document says what it will actually run rather than depending on
  // whatever the catalog happens to offer first next time.
  const withTool =
    patch.enabled && !stack.doc.value?.output?.tool_id && defaultUpscaleToolId.value
      ? { ...patch, tool_id: defaultUpscaleToolId.value }
      : patch
  stack.setOutput(withTool)
}

/** Merge into the tool's params; the panel never owns the whole blob. */
function setOutputParams(patch: Record<string, any>) {
  stack.setOutput({ params: { ...outputStage.value.params, ...patch } })
}

// -- version chain and the commit bar ---------------------------------------

/**
 * The journal cursor as of the last commit — what Revert walks back to.
 *
 * Set at open and after every in-place save. Undo already knows how to move the
 * document backwards, so reverting is walking that cursor rather than a second
 * mechanism that could disagree with it.
 */
const savedCursor = ref(0)
const confirmingRevert = ref(false)

const canRevert = computed(() =>
  stack.dirtySinceSave.value && stack.cursor.value > savedCursor.value
)

const revertCount = computed(() => stack.cursor.value - savedCursor.value)

async function revertToSaved() {
  confirmingRevert.value = false
  while (stack.cursor.value > savedCursor.value && stack.canUndo.value) stack.undo()
  const headIsAutosave = !!stack.doc.value?.last_commit?.autosave
  // Back at the committed state by definition.
  stack.markCommitted()
  await afterGeometryChange(stack.doc.value)
  void render()
  // The discarded edits may already BE the committed head — they autosave on
  // leave — so re-commit the reverted state to bring the Asset back with it.
  if (headIsAutosave) void autosaveEdits(true)
}

/** Transient confirmation, so a commit is not a button that just stops spinning. */
const savedNote = ref<string | null>(null)
let savedNoteTimer: ReturnType<typeof setTimeout> | null = null

function noteSaved(message: string) {
  savedNote.value = message
  if (savedNoteTimer) clearTimeout(savedNoteTimer)
  savedNoteTimer = setTimeout(() => { savedNote.value = null }, 2600)
}

/** The split button's menu: Save is the button, the rare fork is behind it. */
const saveMenuOpen = ref(false)
const saveMenuRef = ref<HTMLElement | null>(null)

function onSaveMenuClickOutside(ev: MouseEvent) {
  if (saveMenuRef.value && !saveMenuRef.value.contains(ev.target as Node)) {
    saveMenuOpen.value = false
  }
}

// Soft-dismiss on any click outside the split control. Deferred so the click
// that opened the menu does not immediately close it.
watch(saveMenuOpen, (open) => {
  if (open) {
    setTimeout(() => document.addEventListener('mousedown', onSaveMenuClickOutside), 0)
  } else {
    document.removeEventListener('mousedown', onSaveMenuClickOutside)
  }
})

onBeforeUnmount(() => document.removeEventListener('mousedown', onSaveMenuClickOutside))

// -- save ------------------------------------------------------------------

const saving = ref(false)
const savedRevisionId = ref<number | null>(null)

/**
 * What the save is doing right now, as the label of the button that is doing
 * it — a save with the output stage on runs a model and takes as long as one
 * takes, and a button that only spins reads as stuck. A separate status line
 * put the answer somewhere other than the thing the user is watching.
 */
const savingNote = ref<string | null>(null)

async function save(asNew = false) {
  if (!composite.value || !stack.doc.value) return
  saving.value = true
  error.value = null
  savingNote.value = null
  try {
    await stack.flush()
    // Always flatten the REAL document, never the stage. Saving from inside
    // the annotate family would otherwise write the composite the overlay is
    // drawing over — the one without its annotations.
    const flattened = await applyOutputStage(await compositor.render(stack.doc.value))
    const blob = await canvasToBlob(flattened)
    const form = new FormData()
    form.append('file', blob, 'edited.png')
    form.append('source_media_id', String(stack.doc.value.base.media_id))
    form.append('asset_id', String(stack.doc.value.base.asset_id))
    form.append('base_revision_id', String(stack.doc.value.base.revision_id))
    form.append('working_document_id', String(stack.documentId.value))
    form.append('stack_summary', JSON.stringify(stack.executedStackSummary()))
    if (asNew) {
      form.append('save_as_new', 'true')
      const availableMarkerIds = new Set(availableMarkers.value.map(marker => marker.id))
      const selectedMarkerIds = newAssetMarkerIds.value.filter(
        markerId => availableMarkerIds.has(markerId),
      )
      if (selectedMarkerIds.length) {
        form.append('marker_ids', selectedMarkerIds.join(','))
      }
    }

    const { data } = await axios.post('/api/media/save-edit', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    savedRevisionId.value = data.revision_id
    stack.markCommitted(data.asset_id, data.revision_id)
    if (sidebarTab.value === 'info') void loadEditorMediaInfo()
    savedCursor.value = stack.cursor.value
    // The version commit already succeeded. Persist its working-state boundary
    // separately so a reload cannot turn that state back into "unsaved."
    void stack.flush().catch((persistError) => {
      console.error('[imageStack] could not persist commit boundary', persistError)
    })
    if (asNew) {
      // The editor stays on the original Asset, but the current state is now
      // committed durably to the new one, so it is no longer "unsaved."
      noteSaved('Saved as a new asset')
    } else {
      noteSaved('Saved')
    }
  } catch (err: any) {
    error.value = apiErrorMessage(err, 'Could not save.')
  } finally {
    saving.value = false
    savingNote.value = null
  }
}

/**
 * Leaving is saving: the applied stack is committed as the Asset's current
 * Revision, so the browser, tools, and the agent all see what the editor
 * shows. There is no persistent "unsaved" state for applied edits.
 *
 * Autosaves coalesce server-side — one autosave head per base, replaced on
 * the next commit — and they never run the output stage, which can invoke a
 * paid tool: only an explicit Save may do that.
 */
const autosaving = ref(false)

function hasAppliedEditorState() {
  const doc = stack.doc.value
  return !!doc && (
    doc.edits.length > 0
    || !!doc.output?.enabled
    || !!doc.base.payload_ref
  )
}

/**
 * An autosave is a mutable working layer, not history. If its stack returns to
 * the untouched base and no explicit version exists, remove that layer so the
 * Asset projects the original Media again and loses the Edited marker. The
 * server declines this when a saved version exists; in that case the normal
 * autosave below commits the now-empty stack as the current working state.
 */
let emptyAutosaveDiscardPromise: Promise<boolean> | null = null

async function discardEmptyAutosaveIfPossible(): Promise<boolean> {
  const doc = stack.doc.value
  if (!doc?.last_commit?.autosave || hasAppliedEditorState()) return false
  if (emptyAutosaveDiscardPromise) return emptyAutosaveDiscardPromise
  emptyAutosaveDiscardPromise = (async () => {
    const { data } = await axios.post('/api/media/discard-edit-autosave', {
      asset_id: doc.base.asset_id,
      base_revision_id: doc.base.revision_id,
      working_document_id: stack.documentId.value,
    })
    if (!data.discarded) return false

    savedRevisionId.value = data.revision_id
    stack.markCommitted(data.asset_id, data.revision_id)
    void stack.flush().catch((persistError) => {
      console.error('[imageStack] could not persist cleared autosave boundary', persistError)
    })
    return true
  })()
  try {
    return await emptyAutosaveDiscardPromise
  } finally {
    emptyAutosaveDiscardPromise = null
  }
}

async function autosaveEdits(force = false) {
  if (autosaving.value || saving.value) return
  try {
    await stack.flush()
  } catch {
    return // The recipe itself did not persist; the next leave retries.
  }
  if (!stack.doc.value) return
  try {
    if (await discardEmptyAutosaveIfPossible()) return
  } catch (discardError) {
    // Do not replace a removable autosave with another editor-authored copy of
    // the original just because the cleanup request failed. The next leave
    // retries the smaller, lossless operation.
    console.error('[imageEditor] could not clear empty autosave', discardError)
    return
  }
  if (!composite.value) return
  if (!force && !stack.dirtySinceSave.value) return
  autosaving.value = true
  try {
    const flattened = await compositor.render(stack.doc.value)
    const blob = await canvasToBlob(flattened)
    const form = new FormData()
    form.append('file', blob, 'edited.png')
    form.append('source_media_id', String(stack.doc.value.base.media_id))
    form.append('asset_id', String(stack.doc.value.base.asset_id))
    form.append('base_revision_id', String(stack.doc.value.base.revision_id))
    form.append('working_document_id', String(stack.documentId.value))
    form.append('stack_summary', JSON.stringify(stack.executedStackSummary()))
    form.append('autosave', 'true')
    const { data } = await axios.post('/api/media/save-edit', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    savedRevisionId.value = data.revision_id
    stack.markCommitted(data.asset_id, data.revision_id, true)
    if (sidebarTab.value === 'info') void loadEditorMediaInfo()
    void stack.flush().catch(() => {})
  } catch (err) {
    // Declined (the Asset moved on) or failed: the recipe is persisted and
    // the sidebar indicator stays lit; the next leave tries again.
    console.error('[imageEditor] autosave failed', err)
  } finally {
    autosaving.value = false
  }
}

/**
 * The output stage: scale the flattened composite, then re-render the vector
 * steps on top at the final resolution.
 *
 * Vectors AFTER the scale is the whole reason this lives at save rather than in
 * the stack — text an upscaler enlarged is text at 2× the pixels and none of
 * the sharpness, while text rendered into the scaled frame is simply text at
 * the final size. Raster steps ride the scale, which is what you want from them.
 *
 * Throws rather than degrading: a save that quietly skipped the upscale would
 * write the wrong file into the version chain, and the row said 2×.
 */
async function applyOutputStage(flattened: HTMLCanvasElement): Promise<HTMLCanvasElement> {
  const doc = stack.doc.value!
  const output = outputStage.value
  if (!output.enabled) return flattened

  // The vector steps come off before the scale and go back on after it, so the
  // upscaler never sees them and never has to reproduce them.
  const vectorOps = doc.edits.filter(
    op => op.enabled && op.class === 'container' && (op as any).exec?.kind === 'annotate'
  )
  const withoutVectors = vectorOps.length
    ? await compositor.render({
        ...doc,
        edits: doc.edits.filter(op => !vectorOps.some(v => v.id === op.id)),
      })
    : flattened

  const target = outputDimensions(output, withoutVectors.width, withoutVectors.height)

  let scaled: HTMLCanvasElement
  const tool = tools.value.find(t => t.full_tool_id === output.tool_id)
  if (output.method === 'resample' || !tool) {
    if (output.method === 'photo' && !tool) {
      throw new Error('The upscale tool is no longer in the catalog.')
    }
    savingNote.value = 'Resizing…'
    scaled = resampleLanczos(withoutVectors, target.width, target.height)
  } else {
    savingNote.value = 'Upscaling…'
    // The tool's OWN parameters, by schema property name, straight through the
    // shared payload builder — the same path ToolView takes. Nothing here
    // knows what this particular upscaler calls its factor.
    const result = await candidates.runToolOnce({
      tool,
      inputCanvas: withoutVectors,
      params: output.params,
      finalResolution: finalResolutionFor(
        output, withoutVectors.width, withoutVectors.height
      ),
    })
    // Providers snap to their own grids, so the returned size is the size —
    // the vectors are drawn into whatever actually came back rather than into
    // what was asked for.
    scaled = document.createElement('canvas')
    scaled.width = result.naturalWidth
    scaled.height = result.naturalHeight
    scaled.getContext('2d')!.drawImage(result, 0, 0)
  }

  if (!vectorOps.length) return scaled

  savingNote.value = 'Rendering…'
  const shapes: any[] = []
  const sx = scaled.width / withoutVectors.width
  const sy = scaled.height / withoutVectors.height
  for (const op of vectorOps) {
    shapes.push(...transformShapes((op as any).params?.shapes || [], [sx, 0, 0, sy, 0, 0]))
  }
  return applyAnnotations(scaled, scaled.width, scaled.height, shapes, scaled)
}

const migrationNote = ref<string | null>(null)

/**
 * Resolve a document that still contains whole-image steps.
 *
 * Runs before the first render, because those steps have no executor any more —
 * rendering first would show the image without them and then replace it.
 */
async function flattenIfNeeded() {
  const doc = stack.doc.value
  if (!hasWholeOps(doc)) return

  const result = await flattenWholeOps(doc!, {
    loadPayload: (ref: string, revision = 0) =>
      loadImage(stack.payloadUrl(ref, revision)),
    loadBase: loadStackBase,
    uploadPayload: stack.uploadPayload,
    canvasToBlob,
  })
  if (!result) return

  stack.replaceDocument(result.document, {
    action: 'flatten_whole_ops',
    forward: { flattened: result.flattenedCount },
    inverse: { document: doc },
  })
  await stack.flush()
  compositor.clear()

  const count = result.flattenedCount
  migrationNote.value =
    `Combined ${count} ${count === 1 ? 'step' : 'steps'} into the image. `
    + 'Whole-image edits are now saved as a version instead of a step.'
}

// -- lifecycle -------------------------------------------------------------

function onKeydown(event: KeyboardEvent) {
  const target = event.target as HTMLElement
  updateHeldCombine(event)
  // Canvas text editing has no focusable element to hide behind, so the
  // single-key tool shortcuts would eat the typing: 'e' and 'l' switched to
  // Effects and Adjust mid-word and unmounted the editor being typed into.
  if (annotateRef.value?.isEditingText()) return
  if (event.key === 'Escape') {
    event.preventDefault()
    // Escape resolves canvas content. An armed selection tool and the
    // parameter palette that expresses it are persistent tool state: clearing
    // the pixels must not silently change the selected tool.
    const action = editorEscapeAction({
      hasSelection: !!selection.value,
      hasRetouchFeedback: selectedRetouchFeedbackVisible.value,
      hasArmedSelectionTool: !!armedSelectTool.value,
      hasFamily: !!family.value,
      hasSelectedShape: !!selectedShapeId.value,
    })
    if (action === 'clear-selection') {
      clearSelection()
    } else if (action === 'dismiss-retouch-feedback') {
      // Escape steps OUT of the region: feedback off, selection released,
      // and the mask-editing session with it — the next gesture belongs to
      // the workspace again.
      selectedRetouchFeedbackVisible.value = false
      selectedRetouchRegionId.value = null
      selectedMaskComponentId.value = null
      disarmMaskedAdjustmentEditing()
      clearGenerativeMaskSelection()
      void refreshRetouchFeedback()
    } else if (action === 'leave-family') {
      leaveMode()
    } else if (action === 'clear-shape') {
      selectedShapeId.value = null
      selectedOpId.value = null
    }
    return
  }
  if (target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA') return
  if (event.code === 'Space' && !event.metaKey && !event.ctrlKey && !event.altKey) {
    spacePanHeld.value = true
    event.preventDefault()
    return
  }
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'z') {
    event.preventDefault()
    if (event.shiftKey) stack.redo()
    else stack.undo()
    void render()
  }
  // A selected annotation answers the Delete key wherever focus is (inputs
  // and canvas text editing already returned above); the sidebar's own
  // handler covers rows, so this only fires for canvas-selected shapes.
  if (
    (event.key === 'Delete' || event.key === 'Backspace') &&
    selectedShapeId.value && !sidebarEl.value?.contains(event.target as Node)
  ) {
    event.preventDefault()
    // The canvas owns object selection, including marquee groups. It reports
    // the resulting list through the same reconciliation path as every other
    // annotation gesture, so one keypress removes the whole selection.
    if (annotateRef.value) {
      annotateRef.value.deleteSelected()
    } else {
      const opId = opIdForShape(selectedShapeId.value)
      selectedShapeId.value = null
      if (opId) void removeOpWithGeometry(opId)
    }
    return
  }
  // Toggle the before/after comparison against the base.
  if (event.key === '\\' && !event.repeat) void toggleCompare()
  if (!event.metaKey && !event.ctrlKey) {
    if (event.key === '0') {
      event.preventDefault()
      resetView()
      return
    }
    if (event.key === '=' || event.key === '+') {
      event.preventDefault()
      zoomViewBy(1)
      return
    }
    if (event.key === '-') {
      event.preventDefault()
      zoomViewBy(-1)
      return
    }
    // 's' arms the last-used selection tool; the families keep their keys.
    if (event.key.toLowerCase() === 's') armSelectTool(lastSelectTool.value)
    const shortcut = TOOL_FAMILIES.find(f => f.key === event.key.toLowerCase())
    if (shortcut) selectFamily(shortcut.id)
  }
}

function onKeyup(event: KeyboardEvent) {
  if (event.code === 'Space') spacePanHeld.value = false
  updateHeldCombine(event)
}

/**
 * The island previews what the held modifiers would do to the next gesture.
 * Display only: each gesture samples its own pointer event's modifiers, so
 * this can never disagree with what a press actually does.
 */
function updateHeldCombine(event: KeyboardEvent) {
  heldCombineOverride.value = armedSelectTool.value
    ? combineFromModifiers(event.shiftKey, event.altKey)
    : null
}

function clearViewportGestureState() {
  heldCombineOverride.value = null
  // An abandoned gesture still owns the stage's transform; without the commit
  // the next unrelated render would snap it back to the pre-drag pan.
  const wasPanning = viewPanning.value || middleMousePointerId !== null
  spacePanHeld.value = false
  viewPanning.value = false
  middleMousePointerId = null
  nativeTabletPanActive = false
  if (wasPanning) commitLivePan()
}

function addViewportPanListeners() {
  window.addEventListener('pointerdown', startMiddleMousePan, true)
  window.addEventListener('pointermove', moveMiddleMousePan, true)
  window.addEventListener('pointerup', endMiddleMousePan, true)
  window.addEventListener('pointercancel', endMiddleMousePan, true)
  stopTabletPan ??= subscribeTabletPan(onNativeTabletPan)
}

function removeViewportPanListeners() {
  window.removeEventListener('pointerdown', startMiddleMousePan, true)
  window.removeEventListener('pointermove', moveMiddleMousePan, true)
  window.removeEventListener('pointerup', endMiddleMousePan, true)
  window.removeEventListener('pointercancel', endMiddleMousePan, true)
  stopTabletPan?.()
  stopTabletPan = null
}

/**
 * Leaving a mode ends its session: the next entry starts a new step.
 * The selection is NOT a session — it survives, visibly, ants marching.
 */
function leaveMode() {
  // Leaving is a pick too: Esc'ing out means the next visit should open on the
  // canvas, not back inside the family that was deliberately closed.
  if (family.value) writeToolPrefs({ family: null })
  // Ending the mode ends a scoped step's mask-editing session. The step
  // itself survives like any pristine whole-image step would — the next
  // Adjust doorway click is what replaces an untouched one.
  disarmMaskedAdjustmentEditing()
  family.value = null
  sub.value = null
  // Ending a mode session ends its STEP: the next entry starts a new one.
  cropOpId.value = null
  resetPaintSession()
  resetRetouchSession()
}

let resizeObserver: ResizeObserver | null = null

/** Re-read the runnable catalog after a provider is enabled, disabled or drops. */
async function refreshToolCatalog() {
  try {
    tools.value = (await listAllTools()).filter(isRunnableTool)
  } catch (toolError) {
    console.warn('[imageStack] could not refresh tool catalog', toolError)
  }
}

function attachToolCatalogListener() {
  if (!editorActive.value || toolCatalogListenerAttached) return
  window.addEventListener('tools-changed', refreshToolCatalog)
  toolCatalogListenerAttached = true
}

function detachToolCatalogListener() {
  if (!toolCatalogListenerAttached) return
  window.removeEventListener('tools-changed', refreshToolCatalog)
  toolCatalogListenerAttached = false
}

async function hydrateEditorExtras() {
  void stack.hydrateHistory()
    .then(() => { savedCursor.value = stack.openedCursor.value })
    .catch(() => {
      // The current recipe is already open. History failure disables Undo but
      // must not take the image back down.
    })

  try {
    // Only tools that can actually run. The catalog reports the ones behind a
    // disconnected or disabled provider so screens that EXPLAIN a tool can
    // still name it; a picker is not one of those screens — every row in it is
    // an offer, and offering a tool that cannot run is a dead end the person
    // only discovers by pressing Run.
    const all = (await listAllTools()).filter(isRunnableTool)
    tools.value = all
    // Last session's pick wins, but only while that tool is still installed
    // and still supports the operation the restored family will ask it for.
    const prefs = readToolPrefs()
    const eligibleRepaint = all.filter(t => (t.task_types || []).includes('inpaint-image'))
    const eligibleRemove = removeCapableTools(all)
    const validRepaint = (id: string) =>
      eligibleRepaint.some(t => t.full_tool_id === id)
    const validRemove = (id: string) =>
      eligibleRemove.some(t => t.full_tool_id === id)

    // The former Generate/Inpaint pick remains a migration fallback for
    // Repaint; the retired Expand surface no longer owns a tool preference.
    repaintToolId.value =
      rememberedIfValid(prefs.repaintToolId, validRepaint)
      ?? rememberedIfValid(prefs.inpaintToolId, validRepaint)
      ?? eligibleRepaint[0]?.full_tool_id
      ?? null
    removeToolId.value =
      rememberedIfValid(prefs.removeToolId, validRemove)
      ?? rememberedIfValid(prefs.eraseToolId, validRemove)
      ?? eligibleRemove[0]?.full_tool_id
      ?? null
    const eligibleCutout = all.filter(t =>
      (t.task_types || []).includes('remove-background'))
    cutoutToolId.value =
      rememberedIfValid(
        prefs.cutoutToolId,
        id => eligibleCutout.some(t => t.full_tool_id === id),
      )
      ?? eligibleCutout[0]?.full_tool_id
      ?? null
    const eligibleExpand = all.filter(t =>
      (t.task_types || []).includes('outpaint-image'))
    expandToolId.value =
      rememberedIfValid(
        prefs.expandToolId,
        id => eligibleExpand.some(t => t.full_tool_id === id),
      )
      ?? eligibleExpand[0]?.full_tool_id
      ?? null
    for (const id of [
      repaintToolId.value, removeToolId.value, cutoutToolId.value, expandToolId.value,
    ]) {
      ensureModelToolParams(all.find(tool => tool.full_tool_id === id))
    }
    defaultUpscaleToolId.value =
      all.find(t => (t.task_types || []).includes('upscale-image'))?.full_tool_id ?? null
  } catch (toolError) {
    console.warn('[imageStack] could not load tool catalog', toolError)
  }

  // The catalog changes under a long-lived editor: a provider gets disabled or
  // goes offline in Settings while this tab stays open, and a menu fetched once
  // at open keeps offering its tools. Re-read it on the same signal the rest of
  // the app listens for. Picks are left alone — a person's chosen tool going
  // quiet is reported when they press Run, not by silently swapping models.
  attachToolCatalogListener()

  // Restore workspace preference only after the first usable frame. Some
  // families prepare previews of their own; none may delay showing the image.
  const rememberedFamily = rememberedIfValid(
    readToolPrefs().family ?? undefined,
    id => TOOL_FAMILIES.some(spec => spec.id === id),
  )
  if (rememberedFamily) selectFamily(rememberedFamily as FamilyId)
}

onMounted(async () => {
  void initMarkers()
  try {
    const opened = await stack.open(Number(props.assetId), props.revisionId ? Number(props.revisionId) : undefined)
    // Repair an older sticky autosave as soon as its empty document opens;
    // waiting to leave would keep the Asset badged Edited throughout the
    // session even though the sidebar contains only Original image.
    void discardEmptyAutosaveIfPossible().catch((discardError) => {
      console.warn('[imageEditor] could not clear empty autosave', discardError)
    })
    // A saved Asset head and a working document base are different things.
    // The recipe owns the latter and is authoritative whenever it exists.
    baseInfo.value = stack.doc.value?.base
      ? { ...stack.doc.value.base }
      : opened.base
    // Before the first render: whole-image steps have no executor any more, so
    // rendering first would show the image without them.
    await flattenIfNeeded()

    // A hash-addressed materialized head makes the common cold open a decode,
    // not a replay. A first open or evicted cache falls back to the recipe.
    if (!await restoreCachedHead()) await render()

    // Let Vue create and paint the viewport before starting history, tool
    // discovery, version status, or family-specific preview work.
    loading.value = false
    editorReady = true
    if (editorActive.value) candidates.start()
    await nextTick()
    requestAnimationFrame(() => setTimeout(() => { void hydrateEditorExtras() }, 0))
  } catch (err: any) {
    error.value = apiErrorMessage(err, 'Could not open this image.')
  } finally {
    loading.value = false
  }

})

// The screen is KeepAlive'd per asset, so it stays mounted after you navigate
// away: window-level keys must follow activation, not mount, or the editor's
// shortcuts would keep firing on whatever screen you moved to.
onActivated(() => {
  editorActive.value = true
  // Re-entering a KeepAlive'd editor is a fresh editing session. The previous
  // session may have ended on Info, but the useful landing surface is Edits.
  sidebarTab.value = 'edits'
  if (editorReady) candidates.start()
  attachToolCatalogListener()
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('keyup', onKeyup)
  window.addEventListener('blur', clearViewportGestureState)
  addViewportPanListeners()
  addBrushHudListeners()
})

onDeactivated(() => {
  editorActive.value = false
  candidates.pause()
  detachToolCatalogListener()
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('keyup', onKeyup)
  window.removeEventListener('blur', clearViewportGestureState)
  removeViewportPanListeners()
  removeBrushHudListeners()
  brushHud.value = null
  clearViewportGestureState()
  // Leaving IS saving: the applied stack becomes the Asset's current Revision
  // (and the recipe is persisted regardless, for eviction or reload).
  void autosaveEdits()
})

// The sidebar entry's unsaved-edits indicator.
watch(() => stack.dirtySinceSave.value, dirty => setEditorDirty(props.assetId, dirty), { immediate: true })

// The viewport only exists once loading finishes, so the observer attaches when
// the element appears rather than at mount — otherwise the canvas is sized
// against a viewport of 0x0 and never paints.
watch(viewport, element => {
  resizeObserver?.disconnect()
  if (!element) return
  resizeObserver = new ResizeObserver(entries => {
    const box = entries[0].contentRect
    viewportSize.value = { width: box.width, height: box.height }
    nextTick(clampViewPan)
  })
  resizeObserver.observe(element)
}, { flush: 'post' })

onBeforeUnmount(() => {
  if (savedNoteTimer) clearTimeout(savedNoteTimer)
  if (headCacheTimer) clearTimeout(headCacheTimer)
  if (annotationPreviewTimer) clearTimeout(annotationPreviewTimer)
  abandonScheduledRender()
  if (paintPrefsTimer) persistPaintSettings()
  if (retouchPreviewFrame !== null) cancelAnimationFrame(retouchPreviewFrame)
  cancelLiveAdjustPreview()
  liveAdjustPreview.dispose()
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('keyup', onKeyup)
  window.removeEventListener('blur', clearViewportGestureState)
  removeViewportPanListeners()
  removeBrushHudListeners()
  detachToolCatalogListener()
  setEditorDirty(props.assetId, false)
  clearEditorLivePreview(props.assetId)
  resizeObserver?.disconnect()
  candidates.stop()
  void autosaveEdits()
})

// Mounting or unmounting the annotation overlay hands its pixels between the
// overlay and the composite, so the stage is rebuilt in both directions.
// Keyed on the boolean, not on displayDoc: the filtered document is a fresh
// object on every evaluation, and watching it would re-render on every shape
// edit for a composite that cannot have changed.
watch(annotationOverlayActive, () => { void render() })
// The composite is usually ready BEFORE the canvas exists (rendering happens
// while `loading` still hides it), so repaint on either changing rather than
// only on the composite.
// renderSnapshot paints composite changes itself. This watcher only covers the
// canvas appearing after initial loading and geometry-driven display sizing.
watch([displayCanvas, displayBox], () => nextTick(paint), { flush: 'post' })
watch([displayBox, () => family.value], () => nextTick(clampViewPan), { flush: 'post' })

// -- clipping overlays -------------------------------------------------------

/**
 * Clipping indicators: workspace state toggled from the curve plot's corners,
 * never part of the document. The overlay canvas sits over the composite and
 * marks blown highlights red and crushed shadows blue.
 */
const clipShadows = ref(false)
const clipHighlights = ref(false)
const clipCanvas = ref<HTMLCanvasElement | null>(null)
const showClipOverlay = computed(() => clipShadows.value || clipHighlights.value)

function setClipIndicators(state: { shadows: boolean; highlights: boolean }) {
  clipShadows.value = state.shadows
  clipHighlights.value = state.highlights
}

/** The warning needs display resolution, not the full-resolution frame. */
const CLIP_SCAN_MAX_PIXELS = 1_500_000

function paintClipOverlay() {
  const target = clipCanvas.value
  const source = composite.value
  if (!target || !source || !showClipOverlay.value) return
  const scale = Math.min(
    1,
    Math.sqrt(CLIP_SCAN_MAX_PIXELS / Math.max(1, source.width * source.height)),
  )
  const width = Math.max(1, Math.round(source.width * scale))
  const height = Math.max(1, Math.round(source.height * scale))
  const staging = document.createElement('canvas')
  staging.width = width
  staging.height = height
  const stagingContext = staging.getContext('2d', { willReadFrequently: true })!
  stagingContext.drawImage(source, 0, 0, width, height)
  const frame = stagingContext.getImageData(0, 0, width, height)
  const overlay = stagingContext.createImageData(width, height)
  const pixels = frame.data
  const marks = overlay.data
  for (let index = 0; index < pixels.length; index += 4) {
    if (pixels[index + 3] === 0) continue
    const maxChannel = Math.max(pixels[index], pixels[index + 1], pixels[index + 2])
    const minChannel = Math.min(pixels[index], pixels[index + 1], pixels[index + 2])
    if (clipHighlights.value && maxChannel >= 254) {
      marks[index] = 239
      marks[index + 1] = 68
      marks[index + 2] = 68
      marks[index + 3] = 230
    } else if (clipShadows.value && minChannel <= 1) {
      marks[index] = 96
      marks[index + 1] = 165
      marks[index + 2] = 250
      marks[index + 3] = 230
    }
  }
  target.width = width
  target.height = height
  target.getContext('2d')!.putImageData(overlay, 0, 0)
}

watch(
  [clipShadows, clipHighlights, composite, clipCanvas],
  () => nextTick(paintClipOverlay),
  { flush: 'post' },
)

// -- point-color eyedropper ----------------------------------------------------

/** Which inspector the armed eyedropper writes its pick into. */
const pointPickTarget = ref<'adjust' | 'retouch' | null>(null)
const pointPicking = computed(() => pointPickTarget.value !== null)

/** The chip toggles: armed is a mode you can also leave by pressing it. */
function armPointColorPick() {
  if (pointPicking.value) {
    pointPickTarget.value = null
    return
  }
  if (inspectorKind.value === 'retouch' && selectedRetouchRegion.value) {
    pointPickTarget.value = 'retouch'
  } else if (selectedAdjustOp.value) {
    pointPickTarget.value = 'adjust'
  }
}

/**
 * Landing on Point color with nothing sampled arms the dropper for you.
 *
 * The tool has exactly one thing it can do first, and making the person say so
 * with an extra click taught nothing. Only the empty case auto-arms — coming
 * back to a step that already has its color must not hijack the next canvas
 * click.
 */
function pointStepNeedsPick(): boolean {
  const values = inspectorKind.value === 'retouch'
    ? (selectedRetouchRegion.value?.kind === 'point'
        ? selectedRetouchRegion.value.settings as Record<string, any>
        : null)
    : (adjustInspectorParams.value.section === 'point'
        ? adjustInspectorParams.value
        : null)
  if (!values) return false
  return !values.pointHue && !values.pointSat && !values.pointLum
}

function onPointColorPick(event: PointerEvent) {
  const target = pointPickTarget.value
  const canvas = displayCanvas.value
  if (!target || !canvas?.width || !canvas.height) {
    pointPickTarget.value = null
    return
  }
  const rect = canvas.getBoundingClientRect()
  if (!rect.width || !rect.height) return
  const x = Math.max(0, Math.min(
    canvas.width - 1,
    Math.floor((event.clientX - rect.left) / rect.width * canvas.width),
  ))
  const y = Math.max(0, Math.min(
    canvas.height - 1,
    Math.floor((event.clientY - rect.top) / rect.height * canvas.height),
  ))
  const sample = canvas.getContext('2d')?.getImageData(x, y, 1, 1).data
  if (!sample) return
  const picked = rgbToHslColor(sample[0], sample[1], sample[2])
  const patch = {
    pointHue: Math.round(picked.hue),
    pointSat: Math.round(picked.sat),
    pointLum: Math.round(picked.lum),
  }
  if (target === 'retouch') {
    setRetouchRegionSettings(patch, 'point-pick')
    void commitRetouchSettingsRender()
  } else {
    onAdjustInspectorChange(patch, 'adjust:point-pick')
    void commitAdjustInspectorChange()
  }
  // The dropper STAYS armed: sampling is a hunt, and the second click is
  // usually a correction of the first. Esc, the chip, or leaving the step
  // puts it away.
}

function pointPickKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape') return
  pointPickTarget.value = null
  event.stopPropagation()
  event.preventDefault()
}

watch(pointPicking, active => {
  if (active) window.addEventListener('keydown', pointPickKeydown, true)
  else window.removeEventListener('keydown', pointPickKeydown, true)
})

// Switching steps or panels disarms the dropper — a pick belongs to the
// inspector that asked for it — and landing on a Point color step with no
// color yet arms it, because that is the only move the step has.
watch(
  [inspectorKind, selectedOpId, selectedRetouchRegionId],
  () => {
    pointPickTarget.value = null
    nextTick(() => {
      if (pointPicking.value || !pointStepNeedsPick()) return
      armPointColorPick()
    })
  },
)
</script>

<template>
  <!--
    Layout, top level:

      ┌──────────────────────────────┬────────────┐
      │  toolbars (stacked, shrink)  │            │
      │──────────────────────────────│   Edits    │
      │                              │  sidebar   │
      │   canvas — flex-1, matte     │ (full      │
      │                              │  height)   │
      │──────────────────────────────│            │
      │  document bar (undo/save)    │            │
      └──────────────────────────────┴────────────┘

    The sidebar sits OUTSIDE the toolbars and spans top to bottom, so nothing a
    mode does can disturb it. The toolbars are shrink-0 above a flex-1 canvas,
    so opening one takes matte space from the canvas and closing one gives it
    back — the image itself never gets pushed around.
  -->
  <div class="h-full flex flex-col bg-base">
    <div class="flex-1 flex min-h-0">
      <div class="flex-1 flex flex-col min-w-0 min-h-0">
      <!-- Toolbar 1: the families. A container so the family buttons can drop
           their labels from the ROW's width — the viewport says nothing about
           this column once the resizable sidebar takes its share. Clipped so a
           still-too-long row can never paint under the sidebar. -->
      <div class="@container flex items-center gap-3 px-3 h-11 shrink-0 min-w-0 overflow-hidden border-b border-edge-subtle">
        <h1 class="text-sm font-medium text-content shrink-0">Edit</h1>
        <StatusDot
          v-if="stack.dirtySinceSave.value"
          bucket="warning"
          class="shrink-0"
          title="Unsaved edits"
          aria-label="Unsaved edits"
        />
        <EditorToolbar :active="family" class="ml-2" @select="selectFamily" />
      </div>

      <!-- The canvas region. relative so the sub-toolbar can FLOAT over the
           top of the matte: the viewport keeps its full height whether or not
           a family is open, so the image holds steady and opening a mode
           consumes matte instead of reflowing the picture. -->
      <div class="relative flex-1 min-h-0 flex flex-col">
      <!-- Toolbar 2: the active family's controls, overlaid on the matte. -->
      <div class="absolute top-0 left-0 right-0 z-20">
        <EditorSubbar
          v-if="family"
          :family="family"
          :sub="sub"
          :state="subbarState"
          :tool-label="activeToolLabel"
          :busy="busy"
          :can-run="canRun"
          :run-label="iterationOp ? 'Re-run' : null"
          @sub="selectSub"
          @set="onSubbarSet"
          @commit="onSubbarCommit"
          @run="run"
          @open-tool-picker="onOpenToolPicker"
          @refresh-loras="refreshEditorLoras"
          @upload-loras="uploadEditorLoras"
        />

        <!-- Under the sub-bar and left-aligned to the button that opened it. -->
        <div v-if="toolPickerOpen" class="relative z-menu">
          <div class="absolute top-0" :style="{ left: toolPickerLeft + 'px' }">
            <ToolPicker
              :tools="tools"
              :task-type="activeTaskType"
              :compatible-task-types="activeCompatibleTaskTypes"
              :selected-id="activeToolId"
              @select="chooseTool"
              @close="toolPickerOpen = false"
            />
          </div>
        </div>
      </div>

      <div v-if="loading" class="flex-1 grid place-items-center">
        <Spinner size="md" />
      </div>

      <!-- Canvas. Centred in whatever matte is left. The selection island
           floats over the matte at the bottom: selection is workspace state
           (WHERE) and the top bar is the families (WHAT), and floating chrome
           can never push either one around. -->
      <div
        v-else
        ref="viewport"
        class="relative flex-1 min-h-0 grid place-items-center overflow-hidden bg-matte p-6"
        :class="viewPanning ? 'cursor-grabbing' : (spacePanHeld ? 'cursor-grab' : '')"
        @wheel.prevent="onViewportWheel"
        @pointerdown.capture="startViewPan"
        @pointermove.capture="moveViewPan"
        @pointerup.capture="endViewPan"
        @pointercancel.capture="endViewPan"
        @auxclick.middle.prevent
        @mousedown.self="onViewportMatteMouseDown"
        @click.self="onViewportMatteClick"
      >
        <!-- Crop works on the step's INPUT, not on the composite: the region
             outside the crop is dimmed rather than absent, so it takes the
             whole viewport instead of the cropped display box. -->
        <div
          v-if="family === 'crop'"
          ref="stageTransform"
          class="absolute left-1/2 top-1/2"
          :style="[
            {
              width: viewportSize.width * viewZoom + 'px',
              height: viewportSize.height * viewZoom + 'px',
            },
            viewTransformStyle,
          ]"
        >
          <StackCropCanvas
            :source="cropInput"
            :crop="cropRect"
            :flip-x="!!cropParamsOf().flipX"
            :flip-y="!!cropParamsOf().flipY"
            :rotation="cropParamsOf().rotation ?? 0"
            :rotation90="cropParamsOf().rotation90 ?? 0"
            :view-width="viewportSize.width * viewZoom"
            :view-height="viewportSize.height * viewZoom"
            @change="onCropRectChange"
            @commit="onCropCommit"
          />
        </div>
        <div
          v-else
          ref="stageTransform"
          class="absolute left-1/2 top-1/2"
          :style="[
            { width: zoomedDisplayBox.width + 'px', height: zoomedDisplayBox.height + 'px' },
            viewTransformStyle,
          ]"
        >
          <canvas
            ref="displayCanvas"
            class="rounded-media w-full h-full"
            :class="compositeHasCutout ? 'bg-checker' : ''"
            :style="{ width: zoomedDisplayBox.width + 'px', height: zoomedDisplayBox.height + 'px' }"
          />
          <!-- Clipping overlay: marks blown highlights and crushed shadows
               over the composite. Pointer-transparent — it is a read-out. -->
          <canvas
            v-if="showClipOverlay"
            ref="clipCanvas"
            class="absolute inset-0 w-full h-full pointer-events-none rounded-media"
          />
          <!-- Armed point-color eyedropper: one click samples the composite
               under the cursor into the selected step, Esc disarms. -->
          <div
            v-if="pointPicking"
            class="absolute inset-0 z-20 cursor-crosshair"
            @pointerdown.stop.prevent="onPointColorPick"
          />
          <StackPaintCanvas
            v-if="family === 'retouch'"
            ref="retouchRef"
            :source="retouchInput || composite"
            :selection-mask="selection"
            :display-width="zoomedDisplayBox.width"
            :display-height="zoomedDisplayBox.height"
            :view-zoom="viewZoom"
            :engine-id="sub || 'heal'"
            :brush="retouchBrush"
            :exposure="retouchExposure"
            :range="retouchRange"
            :strength="retouchStrength"
            :saturate="retouchSaturate"
            :accumulate="false"
            @stroke="onRetouchStroke"
            @patch-applied="clearSelection"
          />
          <StackPaintCanvas
            v-else-if="family === 'paint' && paintLayerReady"
            ref="paintRef"
            :source="composite"
            :initial-layer="paintInitialLayer"
            :selection-mask="selection"
            :display-width="zoomedDisplayBox.width"
            :display-height="zoomedDisplayBox.height"
            :view-zoom="viewZoom"
            :engine-id="paintEngineId"
            :brush="paintBrush"
            :color="paintColorRgb"
            :gradient="paintGradient"
            :gradient-type="paintGradientType"
            :gradient-reverse="paintGradientReverse"
            @stroke="onPaintStroke"
            @patch-applied="clearSelection"
          />
          <!-- Also mounted in the IDLE state (no family, nothing armed), in
               object-select mode: annotations are the grabbable things, and
               clicking one should just select it. -->
          <StackAnnotateCanvas
            v-else-if="family === 'annotate' || objectSelectActive"
            ref="annotateRef"
            :source="composite"
            :shapes="annotateShapes"
            :display-width="zoomedDisplayBox.width"
            :display-height="zoomedDisplayBox.height"
            :render-width="displayBox.width"
            :render-height="displayBox.height"
            :tool="annotateTool"
            :stroke-color="annotatePaint"
            :fill-color="annotateFillColor"
            :stroke-width="annotateStrokeWidth"
            :shape-effect="annotateShapeEffect"
            :opacity="annotateOpacity"
            :text-style="textStyle"
            @change="onAnnotationsChange"
            @commit="onAnnotationCommit"
            @select="onShapeSelected"
          />
          <StackRetouchFeedback
            v-if="(
              (selectedRetouchFeedbackVisible && selectedRetouchMask)
              || (hoveredRetouchRegionId && hoveredRetouchMask)
              || (hoveredRetouchOpId && allRetouchFeedback.length)
            )"
            :all-regions="hoveredRetouchRegionId ? [] : allRetouchFeedback"
            :selected-mask="
              !hoveredRetouchRegionId && !hoveredRetouchOpId && selectedRetouchFeedbackVisible
                ? selectedRetouchMask
                : null
            "
            :hovered-mask="hoveredRetouchMask"
            :source-point="selectedRetouchSource"
            :target-point="selectedRetouchTarget"
            :hovered-source-point="hoveredRetouchSource"
            :hovered-target-point="hoveredRetouchTarget"
            :selected-is-patch="selectedRetouchIsPatch"
            :hovered-is-patch="hoveredRetouchIsPatch"
            :display-width="zoomedDisplayBox.width"
            :display-height="zoomedDisplayBox.height"
            :render-width="displayBox.width"
          />
          <!-- The selection overlay: always mounted, ants above whatever mode
               is open, pointer-transparent until a rail tool is armed. The
               model itself lives in the host, so nothing here owns the state. -->
          <StackSelectCanvas
            ref="selectRef"
            :source="composite"
            :model="selModel"
            :armed="armedSelectTool"
            :busy="aiSelectProgressVisible"
            :visible="editorActive"
            :display-width="zoomedDisplayBox.width"
            :display-height="zoomedDisplayBox.height"
            :render-width="displayBox.width"
            :render-height="displayBox.height"
            :view-zoom="viewZoom"
            :combine="selectCombine"
            :feather-px="selectFeather"
            :tolerance="selectTolerance"
            :wand-spread="selectSpread"
            :wand-grow-px="selectGrow"
            :wand-antialias="selectAntialias"
            :brush-size="selectBrushSize"
            :gradient="canvasGradient"
            :gradient-owns-result="canvasGradientOwnsResult"
            :gradient-previewing="gradientAdjustmentPreview"
            :gradient-softness="selectGradientSoftness"
            :gradient-feather="selectGradientFeather"
            @gesture-capture="pendingGestureCapture = $event"
            @change="onSelectionChange"
            @object-pick="onObjectPick"
            @gradient="onGradientChange"
            @gradient-edit="onGradientEdit"
          />
          <!-- The selected annotation's own verbs, over the shape they act
               on. Inside the display box so it shares the shapes' coordinate
               space, and last so it sits above every overlay. Always mounted:
               it owns its own fade, and a v-if here would unmount it before
               the leave could play. -->
          <AnnotationIsland
            :visible="annotationIslandVisible"
            :shapes="selectedAnnotationShapes"
            :image-size="frameSize"
            :display-width="zoomedDisplayBox.width"
            :display-height="zoomedDisplayBox.height"
            :can-bring-to-front="canBringAnnotationToFront"
            :can-send-to-back="canSendAnnotationToBack"
            class="z-chrome"
            @edit-text="editSelectedText"
            @reset-rotation="onShapeChange({ rotation: 0 })"
            @bring-to-front="moveAnnotation('front')"
            @send-to-back="moveAnnotation('back')"
            @duplicate="duplicateAnnotation"
            @remove="deleteSelectedAnnotation"
          />
          <!-- Before/after wipe against the base. Covers the canvas and its
               overlays while active; Esc or the footer toggle leaves. -->
          <ImageCompareSlider
            v-if="comparing && compareOriginalUrl && compareEditedUrl"
            :left-src="compareOriginalUrl"
            :right-src="compareEditedUrl"
            left-label="Original"
            right-label="Edited"
            class="z-overlay"
            @close="comparing = false"
          />
        </div>

        <SelectIsland
          :armed="armedSelectTool"
          :last-used="lastSelectTool"
          :pointer-active="objectSelectActive"
          :has-selection="!!selection"
          :combine="selectCombine"
          :combine-override="heldCombineOverride"
          :feather-px="selectFeather"
          :tolerance="selectTolerance"
          :spread="selectSpread"
          :grow-px="selectGrow"
          :antialias="selectAntialias"
          :brush-size="selectBrushSize"
          :gradient-softness="canvasGradient?.kind === 'linear'
            ? canvasGradient.softness : selectGradientSoftness"
          :gradient-feather="canvasGradient?.kind === 'radial'
            ? canvasGradient.feather : selectGradientFeather"
          :ai-busy="aiSelectBusy"
          :ai-progress-visible="aiSelectProgressVisible"
          :ai-stage="aiSelectStage"
          :ai-action="aiSelectAction"
          :ai-error="aiSelectError"
          class="absolute bottom-4 left-1/2 -translate-x-1/2 z-chrome"
          @arm="armSelectTool"
          @choose="(id: SelectToolId) => armSelectTool(id, true)"
          @pointer="activatePointer"
          @set="onSelectionSet"
          @invert="invertSelection"
          @clear="clearSelection"
          @morph="morphSelection"
          @gradient-adjusting="gradientAdjustmentPreview = $event"
          @ai-select="runAiSelect"
          @ai-cancel="cancelAiSelect"
        />
      </div>
      </div>
    </div>

      <!-- Edits: outside everything a mode can touch. -->
      <!-- Drag to widen the stack. The panels in here carry real controls, and
           how much room they deserve is the user's call, not a constant. -->
      <div
        class="w-1 shrink-0 cursor-col-resize bg-edge-subtle/40 hover:bg-accent/40 transition-colors"
        @pointerdown="startSidebarResize"
      />
      <aside
        ref="sidebarEl"
        class="shrink-0 border-l border-edge-subtle flex flex-col min-h-0"
        :style="{ width: sidebarWidth + 'px' }"
      >
        <!-- Three panels, not three lists. Edits is the stack, Output is the
             terminal stage, and Info is the shared media-information body. -->
        <div
          class="px-3 h-11 flex items-center gap-1 shrink-0 bg-surface-raised
                 border-b border-edge-strong"
        >
          <template
            v-for="tab in [
              { id: 'edits', label: 'Edits' },
              { id: 'output', label: 'Output' },
              { id: 'info', label: 'Info' },
            ]"
            :key="tab.id"
          >
            <div v-if="tab.id === 'info'" class="flex-1" />
            <button
              type="button"
              class="px-2 py-1 text-xs font-medium uppercase tracking-wide rounded-md
                     transition-colors focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
              :class="sidebarTab === tab.id
                ? 'text-content bg-selection/15'
                : 'text-content-tertiary hover:text-content-secondary'"
              @click="sidebarTab = tab.id as 'edits' | 'output' | 'info'"
            >
              {{ tab.label }}
              <span
                v-if="tab.id === 'output' && outputLabel(outputStage)"
                class="ml-1 text-accent normal-case tracking-normal tabular-nums"
              >{{ outputLabel(outputStage) }}</span>
            </button>
          </template>
          <Spinner v-if="rendering" size="sm" />
        </div>

        <OutputPanel
          v-if="sidebarTab === 'output' && stack.doc.value"
          :output="outputStage"
          :tools="tools"
          :input-width="outputInput.width"
          :input-height="outputInput.height"
          :picker-open="outputPickerOpen"
          @update="updateOutput"
          @set-params="setOutputParams"
          @toggle-picker="outputPickerOpen = !outputPickerOpen"
          @close-picker="outputPickerOpen = false"
        />

        <div
          v-else-if="sidebarTab === 'info'"
          class="flex-1 min-h-0 flex flex-col"
        >
          <div v-if="infoLoading && !infoItem" class="flex-1 grid place-items-center">
            <Spinner size="sm" />
          </div>
          <SlideshowInfoPanel
            v-else
            content-only
            :show-edit-action="false"
            :current-item="infoItem"
            :available-markers="availableMarkers"
            :marker-update-trigger="infoMarkerUpdateTrigger"
            :media-projects="infoProjects"
            :media-boards="infoBoards"
            :faces="infoFaces"
            :descendants="infoDescendants"
            :inspired-descendants="infoInspiredDescendants"
            :chat-info="infoChat"
            :chat-info-loading="infoLoading"
            @download="infoExportOpen = true"
            @share-to-cloud="infoShareOpen = true"
            @toggle-marker="toggleInfoMarker"
            @tags-updated="updateInfoTags"
            @navigate-to-project="navigateInfoProject"
            @navigate-to-board="navigateInfoBoard"
            @navigate-to-source-media="navigateInfoMedia"
            @view-lineage="navigateInfoLineage"
            @jump-to-chat="navigateInfoChat"
          />
        </div>

        <!-- One dragover on the list, resolved with closest(): per-row
             handlers miss the gaps (the list's padding) and leave a stale line
             behind, and dragenter is unreliable in WKWebView. -->
        <div
          v-else-if="sidebarTab === 'edits'"
          class="flex-1 overflow-y-auto custom-scrollbar p-1.5"
          @keydown="onStackKeydown"
          @dragover.prevent="onListDragOver"
          @drop.prevent="onDrop"
          @dragleave="onListDragLeave"
        >
          <!-- Top of the stack reads first, the way the image is built up. -->
          <template v-for="row in visibleRows" :key="row.op.id">
            <!-- Where the dragged row would land. The gap above a row is the
                 doc index one higher, because the list is drawn top-first. -->
            <div v-if="dropGap === row.index + 1" :class="DROP_LINE" />
            <EditRow
              :op="row.op"
              :selected="selectedOpId === row.op.id"
              :staleness="row.staleness"
              :candidate-thumbs="candidateThumbs[row.op.id]"
              :pending-count="pendingByOp[row.op.id]"
              :pending-batches="pendingBatchesByOp[row.op.id]"
              :preview-staleness="previewStalenessOf(row.op.id)"
              :out-of-frame="outOfFrame[row.op.id]"
              :resampling="runningOpIds.has(row.op.id)"
              :draggable="true"
              :dragging="dragOpId === row.op.id"
              :preview="stepPreviews[row.op.id]"
              :selected-region-id="selectedRetouchRegionId"
              :selected-mask-component-id="selectedMaskComponentId"
              :recomputing-mask-component-id="recomputingMaskComponentId"
              :generative-mask-selected="selectedGenerativeMaskOpId === row.op.id"
              :coverage-debt="maskDebtByOp[row.op.id] ?? 0"
              :coverage-debt-threshold="MASK_DEBT_ADVISORY_THRESHOLD"
              @select="onRowSelect(row.op)"
              @toggle="setEnabledWithGeometry(row.op.id, $event)"
              @pick="stack.pickCandidate(row.op.id, $event); render()"
              @remove="removeOpWithGeometry(row.op.id)"
              @resample="resample(row.op.id)"
              @toggle-region="(regionId, enabled) => setRetouchRegionEnabled(row.op.id, regionId, enabled)"
              @remove-region="removeRetouchRegion(row.op.id, $event)"
              @select-region="selectRetouchRegion(row.op.id, $event)"
              @hover-region="hoverRetouchRegion($event)"
              @select-mask-component="(targetId, componentId) => selectMaskComponent(row.op.id, targetId, componentId)"
              @hover-mask-component="(targetId, componentId) => hoverMaskComponent(row.op.id, targetId, componentId)"
              @toggle-mask-component="(targetId, componentId, enabled) => setMaskComponentEnabled(row.op.id, targetId, componentId, enabled)"
              @remove-mask-component="(targetId, componentId) => removeMaskComponent(row.op.id, targetId, componentId)"
              @remove-mask="unscopeRegion($event)"
              @hover-retouch="hoverRetouchOp(row.op.id, $event)"
              @intent-hover="intentOpId = $event ? row.op.id : null"
              @drag-start="onDragStart(row.op.id, $event)"
              @drag-end="onDragEnd"
              @reenter="enterContainerOp(row.op)"
            />
            <div
              v-if="dropGap !== null && dropGap === row.index && row.index === lastVisibleIndex"
              :class="DROP_LINE"
            />
          </template>

          <!-- The image every edit above applies to. Last, because the stack
               composites bottom to top. -->
          <BaseRow
            v-if="baseInfo"
            :media-id="Number(baseInfo.media_id)"
            :width="baseInfo.width"
            :height="baseInfo.height"
          />
        </div>

        <!-- Inspector: the selected row's full control surface, under the
             stack. The row keeps only the eye as an immediate affordance. -->
        <!-- Properties gets two thirds of the sidebar by default: these panels
             carry the active controls, while Edits remains available above. -->
        <div
          v-if="inspectorKind !== null"
          class="h-1 shrink-0 cursor-row-resize bg-edge-subtle/40 hover:bg-accent/40 transition-colors"
          @pointerdown="startPropertiesResize"
        />
        <div
          v-if="inspectorKind === 'annotation' && selectedShape"
          class="shrink-0 border-t border-edge-subtle flex flex-col"
          :style="propertiesPanelStyle"
        >
          <div
            class="px-3 h-11 flex items-center shrink-0 bg-surface-raised/60
                   border-b border-edge-strong"
          >
            <h2 class="text-xs font-medium uppercase tracking-wide text-content-secondary">
              Properties
            </h2>
          </div>
          <div class="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
            <AnnotationInspector
              :shape="selectedShape"
              :shapes="selectedAnnotationShapes"
              :palette="imagePalette"
              @change="onSelectedShapesChange"
              @commit="commitSelectedShapesChange"
              @remove="annotateRef?.deleteSelected()"
            />
          </div>
        </div>

        <div
          v-else-if="inspectorKind === 'retouch' && selectedRetouchRegion"
          class="shrink-0 border-t border-edge-subtle flex flex-col"
          :style="propertiesPanelStyle"
        >
          <div
            class="px-3 h-11 flex items-center shrink-0 bg-surface-raised/60
                   border-b border-edge-strong"
          >
            <h2 class="text-xs font-medium uppercase tracking-wide text-content-secondary">
              Properties
            </h2>
          </div>
          <div class="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
            <RetouchInspector
              :region="selectedRetouchRegion"
              :selected-component-id="selectedMaskComponentId"
              :recomputing-component-id="recomputingMaskComponentId"
              :histogram="toneCurveHistogram"
              :picking="pointPicking"
              :clip-shadows="clipShadows"
              :clip-highlights="clipHighlights"
              @settings="setRetouchRegionSettings"
              @settings-commit="commitRetouchSettingsRender"
              @pick="armPointColorPick"
              @clip="setClipIndicators"
              @gradient="onInspectorGradient"
              @gradient-commit="commitInspectorGradient"
              @gradient-adjusting="gradientAdjustmentPreview = $event"
              @edit-mask="armScopedMaskEditing"
              @replace-base="armMaskBaseReplace"
              @recompute-base="componentId => selectedRetouchRegionId
                && selectedOpId
                && recomputeSemanticComponent(selectedOpId, selectedRetouchRegionId, componentId)"
              @unscope="unscopeSelectedRegion"
            />
          </div>
        </div>

        <div
          v-else-if="inspectorKind === 'model' && selectedModelOp"
          class="shrink-0 border-t border-edge-subtle flex flex-col"
          :style="propertiesPanelStyle"
        >
          <div
            class="px-3 h-11 flex items-center shrink-0 bg-surface-raised/60
                   border-b border-edge-strong"
          >
            <h2 class="text-xs font-medium uppercase tracking-wide text-content-secondary">
              Properties
            </h2>
          </div>
          <div class="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
            <ModelEditInspector
              :op="selectedModelOp"
              :tool="selectedModelTool"
              :running="runningOpIds.has(selectedModelOp.id)"
              :is-refreshing-loras="isRefreshingLoras"
              :is-uploading-lora="isUploadingLora"
              :lora-upload-progress="loraUploadProgress"
              :lora-upload-file-name="loraUploadFileName"
              @params="setSelectedModelParams"
              @references="setSelectedModelReferences"
              @blend="setSelectedModelBlend"
              @blend-commit="commitSelectedModelBlend"
              @run="resample(selectedModelOp.id)"
              @refresh-loras="refreshEditorLoras"
              @upload-loras="uploadEditorLoras"
            />
          </div>
        </div>

        <!-- Properties names the panel, so it is a level above the groups
             inside it: fixed, outside the scroll region, styled like the
             Edits header rather than like a section within. -->
        <div
          v-else-if="showsAdjustInspector"
          class="shrink-0 border-t border-edge-subtle flex flex-col"
          :style="propertiesPanelStyle"
        >
          <div
            class="px-3 h-11 flex items-center shrink-0 bg-surface-raised/60
                   border-b border-edge-strong"
          >
            <h2 class="text-xs font-medium uppercase tracking-wide text-content-secondary">
              Properties
            </h2>
          </div>
          <div class="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
          <AdjustInspector
            :params="adjustInspectorParams"
            :histogram="toneCurveHistogram"
            :picking="pointPicking"
            :clip-shadows="clipShadows"
            :clip-highlights="clipHighlights"
            :scope-eligible="!!selectedAdjustScopeKind"
            :has-selection="!!selection"
            @change="onAdjustInspectorChange"
            @commit="commitAdjustInspectorChange"
            @pick="armPointColorPick"
            @clip="setClipIndicators"
            @limit="limitSelectedAdjustToSelection"
          />
          </div>
        </div>

        <p v-if="migrationNote" class="px-3 py-2 text-xs text-content-tertiary border-t border-edge-subtle">
          {{ migrationNote }}
        </p>
        <p v-if="error" class="px-3 py-2 text-xs text-red-400 border-t border-edge-subtle">
          {{ error }}
        </p>
        <p v-else-if="candidates.lastError.value" class="px-3 py-2 text-xs text-red-400 border-t border-edge-subtle">
          {{ candidates.lastError.value }}
        </p>
      </aside>
    </div>

      <!-- The commit bar. Left is session history, middle is what this document
           IS (which version, whether it has uncommitted work), right is what
           you can do to it. One meaning per control: the chip reports, Revert
           discards, Save commits. -->
    <footer class="flex items-center gap-2 px-3 h-11 shrink-0 border-t border-edge-subtle">
      <Tooltip text="Undo">
        <IconButton :disabled="!stack.canUndo.value" @click="stack.undo(); render()">
          <ArrowUturnLeftIcon class="w-4 h-4" />
        </IconButton>
      </Tooltip>
      <Tooltip text="Redo">
        <IconButton :disabled="!stack.canRedo.value" @click="stack.redo(); render()">
          <ArrowUturnRightIcon class="w-4 h-4" />
        </IconButton>
      </Tooltip>

      <span class="h-5 w-px bg-edge-subtle mx-1" />

      <div class="flex items-center gap-1" aria-label="Canvas zoom controls">
        <Tooltip text="Zoom out (−)">
          <IconButton
            aria-label="Zoom out"
            :disabled="viewZoom <= MIN_VIEW_ZOOM"
            @click="zoomViewBy(-1)"
          >
            <MinusIcon class="w-3.5 h-3.5" />
          </IconButton>
        </Tooltip>
        <span
          class="w-11 text-center font-mono text-[11px] tabular-nums text-content-secondary"
          aria-live="polite"
        >
          {{ viewZoomLabel }}
        </span>
        <Tooltip text="Zoom in (+)">
          <IconButton
            aria-label="Zoom in"
            :disabled="viewZoom >= MAX_VIEW_ZOOM"
            @click="zoomViewBy(1)"
          >
            <PlusIcon class="w-3.5 h-3.5" />
          </IconButton>
        </Tooltip>
        <Tooltip text="Fit and recenter (0)">
          <IconButton aria-label="Fit and recenter" @click="resetView">
            <ArrowsPointingInIcon class="w-3.5 h-3.5" />
          </IconButton>
        </Tooltip>
      </div>

      <Transition
        enter-active-class="transition-opacity duration-150"
        leave-active-class="transition-opacity duration-500"
        enter-from-class="opacity-0"
        leave-to-class="opacity-0"
      >
        <p v-if="savedNote" class="text-xs text-accent">{{ savedNote }}</p>
      </Transition>

      <div class="flex-1" />

      <!-- A mode toggle, not an action: lit with the selected-state indigo so
           its on-state reads like the app's other toggles. -->
      <button
        type="button"
        :disabled="!composite"
        :aria-pressed="comparing"
        class="inline-flex items-center justify-center rounded-md px-2.5 py-1.5 text-xs font-medium
               transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2
               ring-accent/60 ring-offset-1 ring-offset-surface disabled:opacity-50 disabled:cursor-not-allowed"
        :class="comparing
          ? 'bg-selection/15 text-selection'
          : 'bg-surface-raised hover:bg-surface-hover text-content'"
        @click="toggleCompare()"
      >
        Compare
      </button>

      <!-- Revert is about THIS session's uncommitted work, which is why it is
           disabled the moment there is none. Restoring an older version of the
           asset is a different verb and does not live here. -->
      <Tooltip :text="canRevert ? 'Discard edits made since the last save' : 'Nothing to revert'">
        <Button
          variant="secondary" size="sm"
          :disabled="!canRevert || saving"
          @click="confirmingRevert = true"
        >
          Revert
        </Button>
      </Tooltip>

      <!-- Save itself always commits a version. The menu exposes both save
           destinations at equal weight; only the new-Asset section carries
           the marker strip because those markers belong to the fork. -->
      <div ref="saveMenuRef" class="relative flex items-stretch">
        <Button
          size="sm"
          class="rounded-r-none"
          :loading="saving"
          :disabled="saving || !composite"
          @click="save(false)"
        >
          <i v-if="savingNote">{{ savingNote }}</i>
          <template v-else>Save</template>
        </Button>
        <button
          type="button"
          class="px-1.5 rounded-r-md bg-accent hover:bg-accent/90 text-white
                 border-l border-white/20 transition-colors disabled:opacity-50
                 focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
          :disabled="saving || !composite"
          aria-label="More save options"
          @click="saveMenuOpen = !saveMenuOpen"
        >
          <ChevronUpIcon class="w-3.5 h-3.5" />
        </button>

        <!-- Opens upward: the bar is the last row of the window. -->
        <div
          v-if="saveMenuOpen"
          class="absolute bottom-full right-0 mb-1 w-72 p-1.5 z-menu
                 rounded-lg border border-edge-subtle bg-surface-overlay shadow-xl"
        >
          <Button
            variant="ghost"
            size="sm"
            class="w-full !justify-start"
            :disabled="saving"
            @click="saveMenuOpen = false; save(false)"
          >
            Save a new version of this asset
          </Button>
          <div class="mt-1 pt-1 border-t border-edge-subtle">
            <div v-if="availableMarkers.length" class="px-0.5 pb-1">
              <AutoMarkPicker
                :markers="availableMarkers"
                v-model="newAssetMarkerIds"
              />
            </div>
            <Button
              variant="ghost"
              size="sm"
              class="w-full !justify-start"
              :disabled="saving"
              @click="saveMenuOpen = false; save(true)"
            >
              Save as new asset
            </Button>
          </div>
        </div>
      </div>
    </footer>

    <!-- Pen quick brush picker: the SAME picker the toolbar chip opens,
         popped beside the cursor by a stylus side button. -->
    <CursorPopover
      v-if="brushHud && brushHudTarget"
      :x="brushHud.x"
      :y="brushHud.y"
      @close="brushHud = null"
    >
      <BrushPicker
        v-if="brushHudTarget === 'paint'"
        v-model="paintBrush"
        :is-eraser="paintEngineId === 'erase'"
        :stroke-color="paintColorRgb"
      />
      <BrushPicker
        v-else
        v-model="retouchBrush"
        :stroke-color="paintColorRgb"
      />
    </CursorPopover>

    <ConfirmDialog
      :show="confirmingRevert"
      title="Revert to the last saved version?"
      :message="`${revertCount} ${revertCount === 1 ? 'edit' : 'edits'} made since the last save will be undone. The saved version is not affected.`"
      confirm-label="Revert"
      danger
      @confirm="revertToSaved"
      @cancel="confirmingRevert = false"
    />

    <ExportModal
      :show="infoExportOpen"
      :media-ids="infoItem?.id ? [infoItem.id] : []"
      :media-items="infoItem ? [infoItem] : []"
      @close="infoExportOpen = false"
    />
    <ShareDialog
      v-model="infoShareOpen"
      :media-item="infoItem"
    />
    <MediaContextMenu />
  </div>
</template>
