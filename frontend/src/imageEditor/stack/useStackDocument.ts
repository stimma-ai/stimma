/**
 * The stack document: state, journal-cursor undo, and server persistence.
 *
 * Undo is a cursor into a journal of recent edits, not a stack of snapshots.
 * Every document edit (add, remove, reorder, toggle, param change, pick change)
 * is one journal entry carrying both directions. Undoing walks the cursor back
 * and applies inverses; it never truncates the log and never deletes a received
 * payload — undoing a pick just un-picks, and the candidates remain.
 *
 * Redo is linear: a new edit after undo starts a new run. The entries it
 * abandons remain in persisted history until they age out of the bounded
 * survival window. Payload retention is independent and remains pack-ratty.
 */

import { ref, computed, shallowRef } from 'vue'
import axios from 'axios'
import { getCurrentProfileId } from '../../composables/useProfile'
import { getCachedPin } from '../../composables/usePinLock'
import { getApiBase } from '../../apiConfig'
import { newOpId } from './opId'
import type {
  JournalEntry,
  ModelReferenceImage,
  Op,
  OutputStage,
  StackDocument,
} from './types'
import { DEFAULT_OUTPUT, DOCUMENT_FORMAT, DOCUMENT_VERSION } from './types'
import { migrateShapePaints } from './migrateShapePaints'
import {
  normalizeDocumentTerminology,
  normalizeJournalTerminology,
} from './documentTerminology'
import {
  captureCommittedState,
  ensureCommittedState,
  hasUncommittedChanges,
} from './commitState'
import { applyJournalForward, applyJournalInverse } from './journalReplay'
import { stackPayloadUrl } from './stackPayloadUrl'

// Re-exported so callers keep one import for the document surface.
export { newOpId }

const API_BASE = '/api'

/** Debounce for document.json writes. Slider drags must not thrash the disk. */
const PERSIST_DEBOUNCE_MS = 400


export interface StackEditOptions {
  /** Coalesce with the previous entry when it shares this key (slider drags). */
  coalesceKey?: string
}

export function useStackDocument() {
  const documentId = ref<number | null>(null)
  // Another client saved this document after this one read it. Nothing more is
  // written from here until it loads the latest.
  const savedElsewhere = ref(false)
  let generation = 0
  let flushInProgress: Promise<void> | null = null
  const doc = ref<StackDocument | null>(null)
  const journal = shallowRef<JournalEntry[]>([])
  /** Entries at index >= cursor are undone. */
  const cursor = ref(0)
  /** History is secondary state: document.json is enough to show the editor. */
  const historyLoading = ref(false)
  const historyLoaded = ref(false)
  /** Cursor position represented by persisted history when this session opened. */
  const openedCursor = ref(0)
  const saving = ref(false)
  const loadError = ref<string | null>(null)
  /** Set on every document edit, cleared only by committing the current state. */
  const dirtySinceSave = ref(false)

  let nextSeq = -1
  let historyPromise: Promise<void> | null = null
  let persistTimer: ReturnType<typeof setTimeout> | null = null
  let pendingJournal: JournalEntry[] = []

  const ops = computed<Op[]>(() => doc.value?.edits || [])
  const canUndo = computed(() => historyLoaded.value && cursor.value > 0)
  const canRedo = computed(() => historyLoaded.value && cursor.value < journal.value.length)

  function opById(id: string): Op | undefined {
    return doc.value?.edits.find(o => o.id === id)
  }

  // -- persistence ---------------------------------------------------------

  /**
   * Normalize retired vocabulary and data shapes at the persistence boundary.
   * The rest of the editor then sees current Paint labels and annotation
   * paints, while legacy executor identity remains available for stable hashes.
   */
  function migrateDocument(document: any) {
    normalizeDocumentTerminology(document)
    for (const op of document?.edits ?? []) {
      if (op?.exec?.kind === 'annotate' && op.params?.shapes) {
        op.params.shapes = migrateShapePaints(op.params.shapes)
      }
    }
    return document
  }

  async function open(assetId: number, revisionId?: number) {
    loadError.value = null
    historyPromise = null
    historyLoading.value = false
    historyLoaded.value = false
    openedCursor.value = 0
    journal.value = []
    cursor.value = 0
    nextSeq = -1
    pendingJournal = []
    const { data } = await axios.post(`${API_BASE}/image-stack/open`, {
      asset_id: assetId,
      revision_id: revisionId ?? null,
    })
    documentId.value = data.document_id
    generation = data.generation ?? 0
    savedElsewhere.value = false

    if (data.document) {
      doc.value = migrateDocument(data.document)
    } else {
      doc.value = {
        format: DOCUMENT_FORMAT,
        version: DOCUMENT_VERSION,
        base: {
          asset_id: data.base.asset_id,
          revision_id: data.base.revision_id,
          media_id: data.base.media_id,
          file_hash: data.base.file_hash,
          width: data.base.width,
          height: data.base.height,
        },
        canvas: { width: data.base.width, height: data.base.height },
        edits: [],
        output: { ...DEFAULT_OUTPUT },
      }
    }

    ensureCommittedState(doc.value)
    dirtySinceSave.value = hasUncommittedChanges(doc.value)

    return {
      documentId: data.document_id,
      base: data.base,
      headRevisionId: data.head_revision_id,
    }
  }

  /**
   * Load Undo/Redo after the authoritative current document is already usable.
   *
   * Edits made during the short hydration window keep temporary negative
   * sequence numbers. They are renumbered after the persisted maximum before
   * any flush can append them, so opening pixels never has to wait for history
   * and history never risks colliding sequence ids.
   */
  function hydrateHistory(): Promise<void> {
    if (historyPromise) return historyPromise
    const id = documentId.value
    if (!id) return Promise.resolve()

    historyLoading.value = true
    historyPromise = (async () => {
      try {
        const journalResponse = await axios.get(`${API_BASE}/image-stack/${id}/journal`)
        const persistedAll = normalizeJournalTerminology(journalResponse.data.entries || [])
        // A checkpoint is the boundary before the undoable suffix, not an edit
        // the Undo button should step onto.
        const persisted = persistedAll.filter((entry: JournalEntry) => entry.action !== 'checkpoint')
        const maxPersistedSeq = persistedAll.reduce(
          (max: number, entry: JournalEntry) => Math.max(max, entry.seq || 0),
          0,
        )

        const local = journal.value
        const localCursor = cursor.value
        let seq = maxPersistedSeq + 1
        for (const entry of local) entry.seq = seq++

        journal.value = [...persisted, ...local]
        openedCursor.value = persisted.length
        cursor.value = persisted.length + localCursor
        nextSeq = seq
        historyLoaded.value = true
      } catch (error) {
        loadError.value = 'Could not load undo history.'
        historyPromise = null
        throw error
      } finally {
        historyLoading.value = false
      }
    })()
    return historyPromise
  }

  function allocateSeq(): number {
    return historyLoaded.value ? nextSeq++ : nextSeq--
  }

  function schedulePersist() {
    if (persistTimer) clearTimeout(persistTimer)
    persistTimer = setTimeout(() => { void flush() }, PERSIST_DEBOUNCE_MS)
  }

  function refreshUncommittedChanges() {
    if (!doc.value) {
      dirtySinceSave.value = false
      return
    }
    const dirty = hasUncommittedChanges(doc.value)
    doc.value.has_uncommitted_changes = dirty
    dirtySinceSave.value = dirty
  }

  /**
   * Record the durable boundary between working persistence and an Asset
   * commit. Saving document.json or reloading the browser never calls this.
   */
  function markCommitted(assetId?: number, revisionId?: number, autosave = false) {
    if (!doc.value) return
    if (assetId !== undefined && revisionId !== undefined) {
      doc.value.last_commit = {
        asset_id: assetId,
        revision_id: revisionId,
        ...(autosave ? { autosave: true } : {}),
      }
    }
    captureCommittedState(doc.value)
    dirtySinceSave.value = false
    schedulePersist()
  }

  /** Write document.json and drain queued journal entries. */
  async function flush() {
    // One at a time: each save names the generation the previous one produced.
    while (flushInProgress) await flushInProgress.catch(() => {})
    flushInProgress = writeDocument()
    try {
      await flushInProgress
    } finally {
      flushInProgress = null
    }
  }

  async function writeDocument() {
    if (persistTimer) { clearTimeout(persistTimer); persistTimer = null }
    if (!documentId.value || !doc.value || savedElsewhere.value) return
    // History assigns the persisted sequence boundary. A fast edit made before
    // hydration may mutate immediately, but it cannot be written before its
    // temporary sequence id has been made durable and collision-free.
    await hydrateHistory()
    const id = documentId.value
    const entries = pendingJournal
    pendingJournal = []
    saving.value = true
    try {
      if (entries.length) {
        await axios.post(`${API_BASE}/image-stack/${id}/journal`, { entries, expected_generation: generation })
      }
      const { data } = await axios.put(`${API_BASE}/image-stack/${id}/document`, {
        document: JSON.parse(JSON.stringify(doc.value)),
        expected_generation: generation,
      })
      generation = data.generation
    } catch (err: any) {
      if (err?.response?.status === 409) {
        savedElsewhere.value = true
        return
      }
      // Re-queue so the next flush retries rather than dropping history.
      pendingJournal = [...entries, ...pendingJournal]
      console.error('[imageStack] persist failed', err)
      throw err
    } finally {
      saving.value = false
    }
  }

  // -- edits ---------------------------------------------------------------

  /**
   * Record one document edit. `apply` mutates the document; `inverse` describes
   * how to undo it. Both are plain data so the journal stays replayable.
   */
  function record(
    action: string,
    forward: any,
    inverse: any,
    apply: () => void,
    options: StackEditOptions = {}
  ) {
    apply()

    // Anything undone is abandoned by this new edit. It stops being reachable
    // by redo; its persisted audit entry remains until the bounded history
    // window ages it out.
    if (cursor.value < journal.value.length) {
      journal.value = journal.value.slice(0, cursor.value)
    }

    const previous = journal.value[journal.value.length - 1]
    if (
      options.coalesceKey &&
      previous &&
      previous.action === action &&
      (previous as any)._coalesceKey === options.coalesceKey
    ) {
      // A slider drag is one undo step: keep the original inverse (the value
      // before the drag started) and move the forward value along.
      previous.forward = forward
      pendingJournal = pendingJournal.filter(e => e.seq !== previous.seq)
      pendingJournal.push(previous)
    } else {
      const entry: JournalEntry & { _coalesceKey?: string } = {
        seq: allocateSeq(),
        action,
        forward,
        inverse,
      }
      if (options.coalesceKey) entry._coalesceKey = options.coalesceKey
      journal.value = [...journal.value, entry]
      pendingJournal.push(entry)
    }

    cursor.value = journal.value.length
    refreshUncommittedChanges()
    schedulePersist()
  }

  function addOp(op: Op, index?: number) {
    const at = index ?? (doc.value?.edits.length || 0)
    record(
      'add_op',
      { op, index: at },
      { op_id: op.id },
      () => { doc.value!.edits.splice(at, 0, op) }
    )
  }

  function removeOp(opId: string) {
    const index = doc.value!.edits.findIndex(o => o.id === opId)
    if (index < 0) return
    const op = doc.value!.edits[index]
    record(
      'remove_op',
      { op_id: opId },
      // The whole op rides in the inverse: its payload files stay on disk, so
      // restoring it is a document-only operation.
      { op, index },
      () => { doc.value!.edits.splice(index, 1) }
    )
  }

  function moveOp(opId: string, toIndex: number) {
    const from = doc.value!.edits.findIndex(o => o.id === opId)
    if (from < 0 || from === toIndex) return
    record(
      'move_op',
      { op_id: opId, from, to: toIndex },
      { op_id: opId, from: toIndex, to: from },
      () => {
        const [op] = doc.value!.edits.splice(from, 1)
        doc.value!.edits.splice(toIndex, 0, op)
      }
    )
  }

  /** Reorder several rows as one undoable gesture. */
  function reorderOps(order: string[]) {
    const d = doc.value
    if (!d) return
    const before = d.edits.map(op => op.id)
    const known = new Set(before)
    const requested = order.filter(id => known.has(id))
    const requestedSet = new Set(requested)
    const after = [...requested, ...before.filter(id => !requestedSet.has(id))]
    if (before.length !== after.length || before.every((id, index) => id === after[index])) return

    record(
      'reorder_ops',
      { order: after },
      { order: before },
      () => {
        const byId = new Map(d.edits.map(op => [op.id, op]))
        d.edits = after.flatMap(id => byId.get(id) ?? [])
      }
    )
  }

  /**
   * Replace the edit list as one undoable transaction.
   *
   * Some canvas gestures reconcile several independently addressable rows at
   * once (for example, moving or deleting a marquee selection). Recording one
   * setParams/removeOp call per row makes one physical gesture take several
   * Undo presses. The complete before/after lists are small plain document
   * data, so journal the reconciliation at the same boundary the user felt.
   */
  function replaceEdits(edits: Op[], coalesceKey?: string) {
    const d = doc.value
    if (!d) return
    const before = JSON.parse(JSON.stringify(d.edits)) as Op[]
    const after = JSON.parse(JSON.stringify(edits)) as Op[]
    if (JSON.stringify(before) === JSON.stringify(after)) return
    record(
      'replace_edits',
      { edits: after },
      { edits: before },
      () => { d.edits = after },
      { coalesceKey },
    )
  }

  function setEnabled(opId: string, enabled: boolean) {
    const op = opById(opId)
    if (!op || op.enabled === enabled) return
    const was = op.enabled
    record(
      'toggle_op',
      { op_id: opId, enabled },
      { op_id: opId, enabled: was },
      () => { op.enabled = enabled }
    )
  }

  function setParams(opId: string, params: Record<string, any>, coalesceKey?: string) {
    const op = opById(opId) as any
    if (!op) return
    const was = JSON.parse(JSON.stringify(op.params || {}))
    record(
      'set_params',
      { op_id: opId, params },
      { op_id: opId, params: was },
      () => { op.params = { ...(op.params || {}), ...params } },
      { coalesceKey }
    )
  }

  function setReferenceImages(opId: string, images: ModelReferenceImage[]) {
    const op = opById(opId) as any
    if (!op || op.class !== 'patch') return
    const was = JSON.parse(JSON.stringify(op.reference_images || []))
    const next = JSON.parse(JSON.stringify(images))
    if (JSON.stringify(was) === JSON.stringify(next)) return
    record(
      'set_reference_images',
      { op_id: opId, images: next },
      { op_id: opId, images: was },
      () => { op.reference_images = next },
    )
  }

  /**
   * Replace the child list of the one hierarchical container.
   *
   * A Retouch gesture is one region and one undo step. The whole small list is
   * journaled so add, remove, and visibility changes replay without inventing
   * a second nested journal protocol.
   */
  function setRegions(opId: string, regions: any[], coalesceKey?: string) {
    const op = opById(opId) as any
    if (!op || op.exec?.kind !== 'retouch-regions') return
    const was = JSON.parse(JSON.stringify(op.regions || []))
    const next = JSON.parse(JSON.stringify(regions))
    if (JSON.stringify(was) === JSON.stringify(next)) return
    record(
      'set_regions',
      { op_id: opId, regions: next },
      { op_id: opId, regions: was },
      () => { op.regions = next },
      { coalesceKey },
    )
  }

  function setLabel(opId: string, label: string) {
    const op = opById(opId)
    if (!op || op.label === label) return
    const was = op.label
    record(
      'set_label',
      { op_id: opId, label },
      { op_id: opId, label: was },
      () => { op.label = label }
    )
  }

  /**
   * Rename a step from something the app worked out on its own — the
   * quick-task model naming a Remove or Repaint after its region.
   *
   * Not journaled, for the same reason candidates are not: the user did not do
   * it, and undo reaching a name would spend the person's one undo on the
   * label instead of on the edit they just made.
   */
  function annotateLabel(opId: string, label: string) {
    const op = opById(opId)
    if (!op || !label || op.label === label) return
    op.label = label
    schedulePersist()
  }

  function pickCandidate(opId: string, candidateId: string | null) {
    const op = opById(opId) as any
    if (!op || op.picked === candidateId) return
    const was = op.picked ?? null
    record(
      'pick_candidate',
      { op_id: opId, candidate_id: candidateId },
      { op_id: opId, candidate_id: was },
      () => { op.picked = candidateId }
    )
  }

  /**
   * Mark an op's payload as having changed under the same ref.
   *
   * Composites are keyed by content hash, and a payload rewritten in place
   * leaves that hash untouched — a stroke added to an existing Paint layer
   * would otherwise be invisible. Not journaled: the stroke session itself is
   * the undoable unit, not each dab.
   */
  function touchOp(opId: string) {
    const op = opById(opId) as any
    if (!op) return
    op._revision = (op._revision || 0) + 1
    refreshUncommittedChanges()
    schedulePersist()
  }

  /**
   * Attach staged candidates as they arrive. Not an undoable document edit:
   * a job completing is not something the user did, and undoing it would
   * throw away work that was paid for.
   */
  function attachCandidates(opId: string, candidates: any[]) {
    const op = opById(opId) as any
    if (!op) return
    const known = new Set((op.candidates || []).map((c: any) => c.id))
    op.candidates = [...(op.candidates || []), ...candidates.filter(c => !known.has(c.id))]
    schedulePersist()
  }

  /**
   * The output stage. Journaled like any other document edit — it changes what
   * a save writes, so undo has to reach it.
   */
  function setOutput(patch: Partial<OutputStage>) {
    const d = doc.value
    if (!d) return
    const was = { ...DEFAULT_OUTPUT, ...(d.output || {}) }
    const next = { ...was, ...patch }
    if (JSON.stringify(was) === JSON.stringify(next)) return
    record(
      'set_output',
      { output: next },
      { output: was },
      () => { d.output = next }
    )
  }

  /**
   * Swap the whole document for another one, journaling the swap.
   *
   * For conversions, not for editing: a migration changes the base, the canvas
   * and the edit list at once, and expressing that as a run of ordinary edits
   * would put a dozen meaningless entries in undo. The inverse carries the
   * entire previous document, so one undo puts it back.
   */
  function replaceDocument(
    next: StackDocument,
    entry: { action: string; forward: any; inverse: any }
  ) {
    record(
      entry.action,
      entry.forward,
      entry.inverse,
      () => { doc.value = next }
    )
  }

  function setBlend(opId: string, blend: Partial<{ feather_px: number; opacity: number }>, coalesceKey?: string) {
    const op = opById(opId) as any
    if (!op) return
    const was = { ...(op.blend || { feather_px: 6, opacity: 1 }) }
    record(
      'set_blend',
      { op_id: opId, blend },
      { op_id: opId, blend: was },
      () => { op.blend = { ...was, ...blend } },
      { coalesceKey }
    )
  }

  // -- undo / redo ---------------------------------------------------------

  function applyInverse(entry: JournalEntry) {
    doc.value = applyJournalInverse(doc.value!, entry)
  }

  function applyForward(entry: JournalEntry) {
    applyJournalForward(doc.value!, entry)
  }

  function undo() {
    if (!canUndo.value || !doc.value) return
    const entry = journal.value[cursor.value - 1]
    applyInverse(entry)
    cursor.value -= 1
    // The undo is itself journaled: the log is a record of what happened, and
    // a truncating undo would make prior states unrecoverable.
    pendingJournal.push({ seq: allocateSeq(), action: 'undo', forward: { undid: entry.seq } })
    refreshUncommittedChanges()
    schedulePersist()
  }

  function redo() {
    if (!canRedo.value || !doc.value) return
    const entry = journal.value[cursor.value]
    applyForward(entry)
    cursor.value += 1
    pendingJournal.push({ seq: allocateSeq(), action: 'redo', forward: { redid: entry.seq } })
    refreshUncommittedChanges()
    schedulePersist()
  }

  // -- payloads ------------------------------------------------------------

  /**
   * Payloads are fetched by <img>, which cannot send the X-Profile-* headers
   * the profile middleware requires — so the profile and cached PIN ride the
   * query string, matching reference-file and other direct image URLs.
   */
  function payloadUrl(ref: string, revision?: number | string): string {
    const profileId = getCurrentProfileId()
    return stackPayloadUrl(
      getApiBase(),
      documentId.value!,
      ref,
      profileId,
      revision,
      getCachedPin(profileId),
    )
  }

  async function uploadPayload(name: string, blob: Blob, subdir = 'payloads'): Promise<string> {
    const form = new FormData()
    form.append('file', blob, name)
    form.append('name', name)
    form.append('subdir', subdir)
    const { data } = await axios.post(
      `${API_BASE}/image-stack/${documentId.value}/payloads`,
      form,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    )
    return data.ref
  }

  /**
   * The ops that were enabled at save time, stripped of volatile ids — the
   * chains "record only what ran" discipline, for the committed Media's
   * generation_metadata.
   */
  function executedStackSummary() {
    const steps = ops.value.filter(op => op.enabled).map((op: any) => ({
      class: op.class,
      label: op.label,
      exec: op.exec,
      // The editor verb, which the provider task type does not carry: an
      // erase, a repaint and a cutout can all be fulfilled by one task.
      operation: op.operation ?? undefined,
      params: op.params ?? (op.exec?.kind === 'retouch-regions'
        ? {
            regions: (op.regions ?? []).filter((region: any) => region.enabled).map((region: any) => ({
              kind: region.kind,
              label: region.label ?? undefined,
              settings: region.settings,
            })),
          }
        : null),
      reference_images: op.reference_images ?? undefined,
      // Provenance of the pixels that actually landed, not every candidate.
      job_id: (op.candidates || []).find((c: any) => c.id === op.picked)?.job_id ?? null,
    }))

    // The output stage ran on these pixels, so it is part of what produced
    // them — recorded as the last step it effectively is, and only when it
    // actually did something.
    const output = doc.value?.output
    if (output?.enabled) {
      steps.push({
        class: 'output',
        label: 'Output',
        exec: output.method === 'photo' && output.tool_id
          ? { kind: 'tool', tool_id: output.tool_id, task_type: 'upscale-image' }
          : { kind: 'resample' },
        // The tool's own parameters, as submitted — the same record every
        // other step keeps.
        params: { method: output.method, ...output.params },
        job_id: null,
      } as any)
    }
    return steps
  }

  return {
    savedElsewhere,
    documentId,
    doc,
    ops,
    journal,
    cursor,
    historyLoading,
    historyLoaded,
    openedCursor,
    saving,
    loadError,
    dirtySinceSave,
    canUndo,
    canRedo,
    open,
    hydrateHistory,
    flush,
    markCommitted,
    opById,
    addOp,
    removeOp,
    moveOp,
    reorderOps,
    replaceEdits,
    setEnabled,
    setParams,
    setReferenceImages,
    setRegions,
    setLabel,
    annotateLabel,
    setBlend,
    setOutput,
    replaceDocument,
    touchOp,
    pickCandidate,
    attachCandidates,
    undo,
    redo,
    payloadUrl,
    uploadPayload,
    executedStackSummary,
  }
}
