import { ref, type Ref } from 'vue'
import { EditorView } from '@codemirror/view'
import { Compartment } from '@codemirror/state'
import { vim, Vim, getCM } from '@replit/codemirror-vim'

const VIM_MODE_KEY = 'stimma:vim-mode'
const VIM_COMMANDS_KEY = 'stimma:vim-commands'
const vimSaveHandlers = new WeakMap<object, () => void | Promise<void>>()

interface StoredVimCommand {
  raw: string
  dedupKey: string
}

const MAP_MODE: Record<string, string> = {
  map: '', noremap: '',
  nmap: 'n', nnoremap: 'n',
  imap: 'i', inoremap: 'i',
  vmap: 'v', vnoremap: 'v',
  omap: 'o', onoremap: 'o',
}
const UNMAP_MODE: Record<string, string> = {
  unmap: '', nunmap: 'n', iunmap: 'i', vunmap: 'v', ounmap: 'o',
}
const MAPCLEAR_MODE: Record<string, string> = {
  mapclear: '', nmapclear: 'n', imapclear: 'i', vmapclear: 'v', omapclear: 'o',
}

function parseVimCommand(raw: string): StoredVimCommand | null {
  const trimmed = raw.trim()

  // :set commands — persist set/nooption/option=value, skip queries (?)
  const setMatch = trimmed.match(/^set\s+(no)?(\w+?)([!=?]|$)/)
  if (setMatch) {
    if (trimmed.includes('?')) return null
    return { raw: trimmed, dedupKey: `set:${setMatch[2]}` }
  }

  // :map commands
  const mapMatch = trimmed.match(/^(\w+)\s+(\S+)/)
  if (mapMatch && mapMatch[1] in MAP_MODE) {
    const mode = MAP_MODE[mapMatch[1]]
    return { raw: trimmed, dedupKey: `map:${mode}:${mapMatch[2]}` }
  }

  return null
}

export function getStoredVimCommands(): StoredVimCommand[] {
  try {
    return JSON.parse(localStorage.getItem(VIM_COMMANDS_KEY) || '[]')
  } catch {
    return []
  }
}

export function saveVimCommand(raw: string) {
  const trimmed = raw.trim()
  let commands = getStoredVimCommands()

  // Handle unmap: remove matching map entries
  const unmapMatch = trimmed.match(/^(\w+)\s+(\S+)/)
  if (unmapMatch && unmapMatch[1] in UNMAP_MODE) {
    const mode = UNMAP_MODE[unmapMatch[1]]
    const key = `map:${mode}:${unmapMatch[2]}`
    commands = commands.filter(c => c.dedupKey !== key)
    localStorage.setItem(VIM_COMMANDS_KEY, JSON.stringify(commands))
    return
  }

  // Handle mapclear: remove all map entries for that mode
  const clearMatch = trimmed.match(/^(\w+)$/)
  if (clearMatch && clearMatch[1] in MAPCLEAR_MODE) {
    const mode = MAPCLEAR_MODE[clearMatch[1]]
    const prefix = `map:${mode}:`
    commands = commands.filter(c => !c.dedupKey.startsWith(prefix))
    localStorage.setItem(VIM_COMMANDS_KEY, JSON.stringify(commands))
    return
  }

  const parsed = parseVimCommand(trimmed)
  if (!parsed) return

  commands = commands.filter(c => c.dedupKey !== parsed.dedupKey)
  commands.push(parsed)
  localStorage.setItem(VIM_COMMANDS_KEY, JSON.stringify(commands))
}

export function replayVimCommands(view: EditorView) {
  const cm = getCM(view)
  if (!cm) return
  for (const cmd of getStoredVimCommands()) {
    try {
      Vim.handleEx(cm as any, cmd.raw)
    } catch {
      // ignore invalid commands on replay
    }
  }
}

export function registerVimSaveHandler(view: EditorView, handler: () => void | Promise<void>): () => void {
  const cm = getCM(view)
  if (!cm) return () => {}
  vimSaveHandlers.set(cm as object, handler)
  return () => {
    vimSaveHandlers.delete(cm as object)
  }
}

// Register custom ex commands once at module load.
Vim.defineEx('write', 'w', (cm: any) => {
  const handler = vimSaveHandlers.get(cm as object)
  if (!handler) {
    ;(cm as any).openNotification?.('No save handler for this editor') ||
      console.log('No save handler for this editor')
    return
  }
  void handler()
})

Vim.defineEx('vimrc', 'vimrc', (cm: any) => {
  const cmds = getStoredVimCommands()
  if (cmds.length === 0) {
    (cm as any).openNotification?.('No saved vim commands') ||
      console.log('No saved vim commands')
  } else {
    const lines = cmds.map(c => c.raw).join('\n')
    ;(cm as any).openNotification?.(lines) ||
      console.log('Saved vim commands:\n' + lines)
  }
})

Vim.defineEx('clearrc', 'clearrc', (cm: any) => {
  localStorage.removeItem(VIM_COMMANDS_KEY)
  ;(cm as any).openNotification?.('Vim commands cleared') ||
    console.log('Vim commands cleared')
})

// Capture ex commands typed in the `:` panel so we can persist them across reloads.
export function vimPanelKeydownHandler(e: KeyboardEvent) {
  if (e.key !== 'Enter') return
  const target = e.target as HTMLElement
  if (!(target instanceof HTMLInputElement) || !target.closest('.cm-vim-panel')) return
  saveVimCommand(target.value)
}

export interface VimToggle {
  vimEnabled: Ref<boolean>
  vimCompartment: Compartment
  getVimExtension: () => ReturnType<typeof vim> | []
  toggleVim: () => void
  bindView: (view: EditorView) => void
}

// Composable: shared vim toggle state + persistence wiring for any CM6 editor.
// Both the prompt editor and the read-only code viewer use this so the toggle
// preference and saved mappings stay in sync via localStorage.
export function useVimToggle(): VimToggle {
  const vimCompartment = new Compartment()
  const vimEnabled = ref(localStorage.getItem(VIM_MODE_KEY) === 'true')
  let view: EditorView | null = null

  function getVimExtension() {
    return vimEnabled.value ? vim() : []
  }

  function bindView(v: EditorView) {
    view = v
    if (vimEnabled.value) replayVimCommands(v)
  }

  function toggleVim() {
    vimEnabled.value = !vimEnabled.value
    localStorage.setItem(VIM_MODE_KEY, String(vimEnabled.value))
    if (view) {
      view.dispatch({
        effects: vimCompartment.reconfigure(getVimExtension()),
      })
      if (vimEnabled.value) replayVimCommands(view)
    }
  }

  return { vimEnabled, vimCompartment, getVimExtension, toggleVim, bindView }
}
