import { ref } from 'vue'
import axios from 'axios'

/**
 * Prompt-editor mini-agent loop driver.
 *
 * The backend (`POST /api/prompt/agent/step`) is stateless: it decides the next
 * assistant message + tool calls. This composable owns the running conversation
 * and executes tool calls against the frontend via the injected `runTool` — the
 * agent operates the screen with parity to the user.
 *
 * One call to `send()` = one "run": snapshot once for undo, then loop
 * step → execute tools → step until the model returns a text reply with no more
 * tool calls (or we hit the iteration cap).
 */

export interface AgentToolCall {
  id: string
  name: string
  arguments: string // raw JSON string
}

export interface AgentMessage {
  role: 'user' | 'assistant' | 'tool'
  content?: string | null
  tool_calls?: { id: string; type: 'function'; function: { name: string; arguments: string } }[]
  tool_call_id?: string
  /** Display-only reasoning trace; stripped before sending back to the model. */
  thinking?: string | null
}

export interface MiniAgentContext {
  /** Compact, live snapshot of the editor screen. Refreshed every step. */
  getStateContext: () => Record<string, any>
  /** Execute one tool against the frontend; return a short result string. */
  runTool: (name: string, args: any) => Promise<string> | string
  /** Called once at the start of each run (e.g. reset per-run snapshot state). */
  onRunStart?: () => void
  /** Called before each tool executes — lets the host snapshot lazily so that
   *  non-mutating tools (undo/redo/search) don't trigger an undo entry. */
  onBeforeTool?: (name: string) => void
  /** Per-request thinking override (the lightbulb). Defaults to on if absent. */
  getThinking?: () => boolean
}

const MAX_ITERATIONS = 8
const CLEAR_COMMANDS = new Set(['/clear', '/reset'])

function newSessionId(): string {
  const rand = (globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2))
  return `prompt-editor-${rand}`
}

export function usePromptMiniAgent(ctx: MiniAgentContext) {
  const messages = ref<AgentMessage[]>([])
  const running = ref(false)
  const error = ref<string | null>(null)
  const lastReply = ref<string>('')
  // Stable id for the whole conversation (caching + trace grouping); a new
  // conversation (/clear) gets a fresh id.
  const sessionId = ref<string>(newSessionId())

  // Messages typed while a run is in flight queue here and fire in order, so the
  // user can rapid-fire type/enter/type/enter and everything settles out.
  const pending: string[] = []
  let draining = false

  function clearHistory(): void {
    pending.length = 0
    messages.value = []
    error.value = null
    lastReply.value = ''
    sessionId.value = newSessionId()
  }

  async function send(text: string): Promise<void> {
    const trimmed = text.trim()
    if (!trimmed) return

    // Easter-egg slash command: start fresh (also clears any queued messages).
    if (CLEAR_COMMANDS.has(trimmed.toLowerCase())) {
      clearHistory()
      lastReply.value = '🧹 Fresh start — conversation cleared.'
      return
    }

    pending.push(trimmed)
    if (draining) return // a drain loop is already running; it'll pick this up

    draining = true
    running.value = true
    try {
      while (pending.length) {
        await runOne(pending.shift() as string)
      }
    } finally {
      running.value = false
      draining = false
    }
  }

  async function runOne(text: string): Promise<void> {
    error.value = null

    // Reset per-run state (the host snapshots lazily via onBeforeTool).
    ctx.onRunStart?.()

    // Capture the screen state ONCE per turn. If we re-read it on every loop
    // step, the model would see its own just-applied edits as the current state
    // and report them as "already set". Tools still operate on live state.
    const stateForTurn = ctx.getStateContext()

    messages.value.push({ role: 'user', content: text })

    try {
      for (let iter = 0; iter < MAX_ITERATIONS; iter++) {
        // Send only the wire fields — never the display-only thinking trace.
        const wireHistory = messages.value.map((m) => ({
          role: m.role,
          content: m.content,
          ...(m.tool_calls ? { tool_calls: m.tool_calls } : {}),
          ...(m.tool_call_id ? { tool_call_id: m.tool_call_id } : {}),
        }))
        const resp = await axios.post('/api/prompt/agent/step', {
          conversation_history: wireHistory,
          state_context: stateForTurn,
          thinking: ctx.getThinking ? ctx.getThinking() : true,
          session_id: sessionId.value,
        })
        const data = resp.data as { message: string; tool_calls: AgentToolCall[]; thinking?: string | null }
        const toolCalls = data.tool_calls || []

        messages.value.push({
          role: 'assistant',
          content: data.message || null,
          thinking: data.thinking || null,
          tool_calls: toolCalls.length
            ? toolCalls.map((tc) => ({
                id: tc.id,
                type: 'function' as const,
                function: { name: tc.name, arguments: tc.arguments },
              }))
            : undefined,
        })

        if (toolCalls.length === 0) {
          lastReply.value = data.message || ''
          return
        }

        for (const tc of toolCalls) {
          let result: string
          try {
            let args: any = {}
            if (tc.arguments) {
              try {
                args = JSON.parse(tc.arguments)
              } catch {
                args = {}
              }
            }
            ctx.onBeforeTool?.(tc.name)
            result = await ctx.runTool(tc.name, args)
          } catch (e: any) {
            result = `Error: ${e?.message || String(e)}`
          }
          messages.value.push({ role: 'tool', tool_call_id: tc.id, content: result ?? 'ok' })
        }
      }
      lastReply.value = 'Stopped after too many steps. Try a more specific instruction.'
    } catch (e: any) {
      error.value =
        e?.response?.data?.detail?.message ||
        e?.response?.data?.detail ||
        e?.message ||
        'Agent request failed'
    }
  }

  return { messages, running, error, lastReply, send, clearHistory }
}
