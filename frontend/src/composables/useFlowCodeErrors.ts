import { computed, type ComputedRef, type Ref } from 'vue'
import type { FlowEquation } from './useFlowsApi'

export type CodeErrorSource = 'build' | 'dry-run' | 'runtime'

export interface CodeError {
  source: CodeErrorSource
  category: string
  line: number | null
  message: string
  // One-line summary used in the panel rows (last non-blank traceback line,
  // module prefix stripped from the exception class name).
  summary: string
  equationKey?: string
  equationDisplayName?: string | null
  // Stable key for v-for / dedupe
  id: string
}

interface ProgramLoadError {
  category: string
  message: string
  suggestion?: string | null
  program_traceback?: string | null
  issues?: Array<{
    equation_key: string
    equation_type: string
    status: string
    message: string
    category: string
    phase_path: string[]
  }> | null
}

// Match any path ending in `program.py` followed by `line N`. Covers both
// traceback frames (`File ".../program.py", line 18, in foo`) and SyntaxError
// strings (`invalid syntax (program.py, line 3)`). The innermost user frame
// is the LAST match, so we keep the last hit and ignore framework frames
// (loader.py / primitives.py / etc.) entirely. No generic fallback — picking
// up `line N` from a framework frame is exactly the bug we're avoiding.
const PROGRAM_LINE_RE = /(?:^|[\s"'(/\\])program\.py["'`)]?,\s*line\s+(\d+)/gi

function extractLine(text: string | null | undefined): number | null {
  if (!text) return null
  let last: number | null = null
  for (const m of text.matchAll(PROGRAM_LINE_RE)) {
    const n = Number(m[1])
    if (Number.isFinite(n) && n > 0) last = n
  }
  return last
}

// Take the last non-blank line of a Python traceback or error message and
// strip the module-path prefix from the exception class name so the panel
// shows `DSLMisuseError: ...` rather than `flow_dsl.errors.DSLMisuseError: ...`.
function summarize(message: string | null | undefined): string {
  if (!message) return ''
  const lines = message.split('\n').map((l) => l.trim()).filter(Boolean)
  if (lines.length === 0) return ''
  const last = lines[lines.length - 1]
  return last.replace(
    /^([a-z_][\w.]*\.)([A-Z][A-Za-z0-9_]*(?:Error|Exception|Warning)):/,
    '$2:',
  )
}

export function useFlowCodeErrors(
  programLoadError: Ref<ProgramLoadError | null>,
  equations: Ref<FlowEquation[]>,
): ComputedRef<CodeError[]> {
  return computed<CodeError[]>(() => {
    const errs: CodeError[] = []
    const lookupName = (key: string): string | null | undefined => {
      const eq = equations.value.find((e) => e.equation_key === key)
      return eq?.display_name ?? null
    }

    const ple = programLoadError.value
    if (ple) {
      const issues = ple.issues ?? null
      if (issues && issues.length > 0) {
        // Dry-run produced per-equation issues. Emit one entry each.
        for (const issue of issues) {
          errs.push({
            source: 'dry-run',
            category: issue.category || ple.category,
            line: extractLine(issue.message),
            message: issue.message,
            summary: summarize(issue.message),
            equationKey: issue.equation_key,
            equationDisplayName: lookupName(issue.equation_key),
            id: `dry:${issue.equation_key}`,
          })
        }
      } else {
        // Single build-time error (program failed to import/parse).
        const line =
          extractLine(ple.program_traceback) ?? extractLine(ple.message)
        const fullMessage = ple.program_traceback?.trim() || ple.message
        errs.push({
          source: 'build',
          category: ple.category,
          line,
          message: fullMessage,
          summary: summarize(fullMessage),
          id: 'build:program',
        })
      }
    }

    const dryRunKeys = new Set(
      ple?.issues?.map((i) => i.equation_key) ?? [],
    )
    for (const eq of equations.value) {
      if (eq.status !== 'failed') continue
      if (!eq.error) continue
      if (dryRunKeys.has(eq.equation_key)) continue
      errs.push({
        source: 'runtime',
        category: 'runtime_error',
        line: extractLine(eq.error),
        message: eq.error,
        summary: summarize(eq.error),
        equationKey: eq.equation_key,
        equationDisplayName: eq.display_name ?? null,
        id: `runtime:${eq.equation_key}`,
      })
    }

    errs.sort((a, b) => {
      if (a.line == null && b.line == null) return 0
      if (a.line == null) return -1
      if (b.line == null) return 1
      return a.line - b.line
    })
    return errs
  })
}
