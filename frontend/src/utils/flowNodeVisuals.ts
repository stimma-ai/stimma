import { getTaskTypeIconSvg } from './taskTypeIcons'

/**
 * Flow-graph node type visuals — the quiet-card treatment's replacement for
 * the retired ALL-CAPS type chips (INPUT / CODE / TOOL…). Each equation type
 * gets a friendly outline glyph rendered in a soft-tinted rounded tile, plus
 * a sentence-case word used as the subtitle fallback when a node has no
 * better secondary line.
 *
 * Icons are inner-SVG fragments for a `viewBox="0 0 24 24"` wrapper with
 * `fill="none" stroke="currentColor" stroke-width="1.75"` (§1.10). Tool
 * nodes prefer the task-type glyph (image/video/audio…) from taskTypeIcons
 * so the tile says what the step *makes*.
 */

export interface FlowNodeVisual {
  /** Inner-SVG fragment for the icon tile. */
  icon: string
  /** Tailwind classes for the tile: soft type tint + strong type color. */
  tileClass: string
  /** Sentence-case type word ("Input", "Code") for subtitle fallbacks. */
  label: string
}

const ICONS = {
  // Arrow entering a bracket — something coming into the flow.
  input:
    '<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/><path d="M4 12h10"/><path d="m10 8 4 4-4 4"/>',
  // Finish flag — the flow's result.
  output:
    '<path d="M5 21V4"/><path d="M5 4h12l-2.5 3.5L17 11H5"/>',
  code:
    '<path d="m8 8-4 4 4 4"/><path d="m16 8 4 4-4 4"/>',
  // Two sparkles — the model doing something clever.
  llm:
    '<path d="M12 4l1.7 4.3L18 10l-4.3 1.7L12 16l-1.7-4.3L6 10l4.3-1.7z"/><path d="M18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>',
  // Raised hand — your turn.
  hitl:
    '<path d="M18 11V6a2 2 0 0 0-4 0v5"/><path d="M14 10V4a2 2 0 0 0-4 0v2"/><path d="M10 10.5V6a2 2 0 0 0-4 0v8"/><path d="m7 15-1.76-1.76a2 2 0 0 0-2.83 2.82l3.6 3.6A8 8 0 0 0 22 14V7a2 2 0 0 0-4 0"/>',
  info:
    '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5"/><path d="M12 8h.01"/>',
  // Repeat arrows — loops and other control steps.
  control:
    '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
  // Layers — collecting things into a set/grid/document.
  create:
    '<path d="M12 3 3 8l9 5 9-5-9-5z"/><path d="m3 13 9 5 9-5"/>',
  search:
    '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-3.8-3.8"/>',
  fetch:
    '<path d="M12 4v10m0 0-3.5-3.5M12 14l3.5-3.5"/><path d="M4 17v1a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-1"/>',
} as const

export function flowNodeVisual(
  equationType: string,
  opts?: { taskType?: string | null },
): FlowNodeVisual {
  switch (equationType) {
    case 'tool_call':
      return {
        icon: getTaskTypeIconSvg(opts?.taskType || ''),
        tileClass: 'bg-flow-tool-tint text-flow-tool-strong',
        label: 'Tool',
      }
    case 'llm_call':
    case 'llm_batch':
    case 'llm_slot':
      return { icon: ICONS.llm, tileClass: 'bg-flow-llm-tint text-flow-llm-strong', label: 'LLM' }
    case 'code':
      return { icon: ICONS.code, tileClass: 'bg-flow-code-tint text-flow-code-strong', label: 'Code' }
    case 'hitl':
      return { icon: ICONS.hitl, tileClass: 'bg-flow-hitl-tint text-flow-hitl-strong', label: 'Human step' }
    case 'info':
      return { icon: ICONS.info, tileClass: 'bg-flow-info-tint text-flow-info-strong', label: 'Note' }
    case 'flow_input':
      return { icon: ICONS.input, tileClass: 'bg-flow-input-tint text-flow-input-strong', label: 'Input' }
    case 'flow_output':
      return { icon: ICONS.output, tileClass: 'bg-flow-output-tint text-flow-output-strong', label: 'Output' }
    case 'control':
      return { icon: ICONS.control, tileClass: 'bg-flow-control-tint text-flow-control-strong', label: 'Loop' }
    case 'create_set':
    case 'create_grid':
    case 'create_document':
      return { icon: ICONS.create, tileClass: 'bg-flow-create-tint text-flow-create-strong', label: 'Collect' }
    case 'web_search':
      return { icon: ICONS.search, tileClass: 'bg-flow-tool-tint text-flow-tool-strong', label: 'Search' }
    case 'fetch_media':
      return { icon: ICONS.fetch, tileClass: 'bg-flow-tool-tint text-flow-tool-strong', label: 'Fetch' }
    default:
      return { icon: ICONS.code, tileClass: 'bg-overlay-subtle text-content-muted', label: 'Step' }
  }
}
