import { computed } from 'vue'

/** Only the queue's requirements; the application retains its complete document type. */
interface RenderableDocument {
  edits: { id: string; enabled: boolean }[]
}
interface Readable<T> { readonly value: T }
interface Writable<T> { value: T }

export interface RenderScheduler {
  requestFrame(callback: () => void): number
  cancelFrame(handle: number): void
  setTimer(callback: () => void, delay: number): ReturnType<typeof setTimeout>
  clearTimer(handle: ReturnType<typeof setTimeout>): void
}

export interface EditorRendererOptions<D extends RenderableDocument, C> {
  document: Readable<D | null>
  baseReady(): boolean
  annotationOverlayActive: Readable<boolean>
  visibleAnnotateOps: Readable<readonly { id: string }[]>
  family(): string | null
  cropOpId(): string | null
  setCropInput(canvas: C | null): void
  compositor: {
    render(document: D): Promise<C>
    renderUpTo(document: D, index: number): Promise<C>
    readonly failedOpIds: ReadonlySet<string>
    readonly maskDebt: ReadonlyMap<string, number>
  }
  composite: Writable<C | null>
  stepPreviews: Writable<Record<string, string>>
  rendering: Writable<boolean>
  maskDebtByOp: Writable<Record<string, number>>
  publishLivePreview(canvas: C): void
  scheduleHeadCache(document: D, canvas: C): void
  syncSelectionGeometry(): void
  paint(): void
  samplePalette(): void
  looksOpen(): boolean
  renderLookThumbs(): Promise<void>
  reportError(message: string): void
  scheduler?: RenderScheduler
}

export type RenderOptions = {
  /**
   * Debounce destructive bursts while the rows update optimistically. Normal
   * renders use the next animation frame.
   */
  settleMs?: number
}

export const RENDER_BURST_SETTLE_MS = 140

/** Serialize replay and publish only results from the latest requested document. */
export function createEditorRenderer<D extends RenderableDocument, C>(options: EditorRendererOptions<D, C>) {
  const compositor = options.compositor
  const scheduler: RenderScheduler = options.scheduler ?? {
    requestFrame: callback => requestAnimationFrame(callback),
    cancelFrame: handle => cancelAnimationFrame(handle),
    setTimer: (callback, delay) => setTimeout(callback, delay),
    clearTimer: handle => clearTimeout(handle),
  }
  /** Set only while rendering the full document — see onStepPreview. */
  let emitPreviews = true
  /** One reactive update per replay, not one per recomputed stack stage. */
  let bufferedStepPreviews: Record<string, string> | null = null

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
      scheduler.cancelFrame(renderFrame)
      renderFrame = null
    }
    if (renderTimer) {
      scheduler.clearTimer(renderTimer)
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
      if (renderTimer) scheduler.clearTimer(renderTimer)
      renderTimer = scheduler.setTimer(() => {
        renderTimer = null
        void drainRenderQueue()
      }, settleMs)
      return
    }

    if (renderTimer) {
      scheduler.clearTimer(renderTimer)
      renderTimer = null
    }
    if (renderFrame !== null) return
    renderFrame = scheduler.requestFrame(() => {
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
    const doc = options.document.value
    if (!doc || !options.annotationOverlayActive.value) return doc
    const drawnByOverlay = new Set(options.visibleAnnotateOps.value.map(op => op.id))
    if (!drawnByOverlay.size) return doc
    return { ...doc, edits: doc.edits.filter(op => !drawnByOverlay.has(op.id)) }
  })

  /** Drop previews for steps that no longer exist, so removals don't accumulate. */
  function prunePreviews() {
    const live = new Set((options.document.value?.edits || []).map(op => op.id))
    const kept: Record<string, string> = {}
    for (const [opId, preview] of Object.entries(options.stepPreviews.value)) {
      if (live.has(opId)) kept[opId] = preview
    }
    options.stepPreviews.value = kept
  }

  async function renderSnapshot(requestRevision: number) {
    // Mutations can request a render before open() has assigned the base. The
    // later open path requests again once both halves are ready.
    if (!options.document.value || !options.baseReady()) return
    const liveDoc = displayDoc.value!
    const whole = liveDoc === options.document.value
    // The compositor awaits payloads. Snapshot the plain composition so a mutation
    // arriving during that await cannot change the array underneath its loop.
    const doc = JSON.parse(JSON.stringify(liveDoc)) as D
    const cropSession = options.family() === 'crop'
    const cropId = options.cropOpId()
    // Crop owns the uncropped input, including annotations below its step.
    // Use the authoritative document even when another overlay trims displayDoc.
    const cropDoc = cropSession
      ? (whole ? doc : JSON.parse(JSON.stringify(options.document.value)) as D)
      : null
    bufferedStepPreviews = whole ? {} : null
    try {
      emitPreviews = whole
      // Keep this replay in the same queue as the head. Independent entry-time
      // renders left Crop stale on sidebar edits and could finish out of order.
      const cropSource = cropDoc ? await renderCropInput(cropDoc, cropId) : null
      if (requestRevision !== renderRequestRevision) return
      const rendered = await compositor.render(doc)
      if (requestRevision !== renderRequestRevision) return
      if (cropSession && options.family() === 'crop' && cropId === options.cropOpId()) {
        options.setCropInput(cropSource)
      }
      options.composite.value = rendered
      if (whole) options.publishLivePreview(rendered)
      if (whole && bufferedStepPreviews) {
        options.stepPreviews.value = { ...options.stepPreviews.value, ...bufferedStepPreviews }
      }
      if (whole) prunePreviews()
      if (
        whole
        && doc.edits.some(op => op.enabled)
        && !compositor.failedOpIds.size
      ) {
        options.scheduleHeadCache(doc, rendered)
      }
      // Coverage debt is measured while the compositor recomputes generative
      // ops; publish the fresh readings for the rows' amber advisories.
      options.maskDebtByOp.value = Object.fromEntries(compositor.maskDebt)
      // The selection lives at the head, so whatever this render did to the
      // geometry under it (crop edits, toggles, an expand's new frame) is
      // carried into it here — the one funnel every such change passes through.
      options.syncSelectionGeometry()
      options.paint()
      options.samplePalette()
      if (options.family() === 'levels' && options.looksOpen()) void options.renderLookThumbs()
    } catch (err) {
      options.reportError((err as { message?: string } | null)?.message || 'Could not render the composite.')
    } finally {
      bufferedStepPreviews = null
      emitPreviews = true
    }
  }

  async function drainRenderQueue() {
    if (renderRunning) return
    clearRenderSchedule()
    renderRunning = true
    options.rendering.value = true
    try {
      while (renderRequested) {
        renderRequested = false
        const requestRevision = renderRequestRevision
        await renderSnapshot(requestRevision)
      }
    } finally {
      renderRunning = false
      options.rendering.value = false
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

  async function renderCropInput(doc: D, opId: string | null) {
    const index = opId
      ? doc.edits.findIndex(op => op.id === opId)
      : doc.edits.length
    return compositor.renderUpTo(doc, index < 0 ? doc.edits.length : index)
  }

  function onStepPreview(opId: string, preview: string) {
    // Overlay-only renders do not describe the authoritative stack's steps.
    if (!emitPreviews) return
    if (bufferedStepPreviews) {
      bufferedStepPreviews[opId] = preview
      return
    }
    options.stepPreviews.value = { ...options.stepPreviews.value, [opId]: preview }
  }
  return { render, displayDoc, abandonScheduledRender, onStepPreview }
}
