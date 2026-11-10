import type { ProgramChoice, ProgramGroup } from '../composables/usePromptProgram'

/** Display labels use US English, including programs prepared by older models. */
export function programLabel(label: string): string {
  return label.replace(/\bcolours?\b/gi, word => {
    const color = word.toLowerCase() === 'colours' ? 'colors' : 'color'
    return word[0] === word[0].toUpperCase() ? color[0].toUpperCase() + color.slice(1) : color
  })
}

function subjectLabel(label: string): string {
  const irregular: Record<string, string> = { people: 'Person', children: 'Child', men: 'Man', women: 'Woman' }
  return irregular[label.toLowerCase()] || label.replace(/ies$/i, 'y').replace(/(friends|girls|boys|persons|subjects|characters|dogs|cats)$/i, word => word.slice(0, -1))
}

export interface ProgramSection {
  id: string
  label: string
  choices: ProgramChoice[]
  /** scene: details of the whole image (no header); shared: one value for every subject; subject: one subject's own. */
  kind?: 'scene' | 'shared' | 'subject'
}

/** Whose detail an id names, the way the backend reads it (runtime.subject_of): for programs
 * prepared before choices carried their subject. friends[2].age, woman1.hair, mother.outfit. */
export function subjectOfId(id: string): { group: string; index?: number } | null {
  if (id.startsWith('param.') || (id.endsWith('.colours') && id.split('.').length === 2)) return null
  const m = /^([A-Za-z_][A-Za-z0-9_]*?)(?:_?(\d+))?(?:\[(\d+)\])?\.[A-Za-z_]/.exec(id)
  if (!m) return null
  const [, name, num, index] = m
  if (num && index) return { group: name + num, index: Number(index) }
  const n = index || num
  return n ? { group: name, index: Number(n) } : { group: name }
}

/**
 * The choices row's sections: the scene's details first (no header), then details every
 * subject shares ("Shared"), then one section per subject ("Friend 1", "Mother"), in the
 * order the program declares its groups and then meets its subjects, numbered ones by number.
 * Dependent controls (a look's colours) inherit their subject's section. With fewer than two
 * subjects there are no headers: everything is one plain section.
 */
export function programSections(choices: ProgramChoice[], groups: ProgramGroup[]): ProgramSection[] {
  const byId = new Map(choices.map(c => [c.id, c]))
  const structured = choices.some(c => c.group || c.shared)  // prepared with subjects on its choices
  function owner(c: ProgramChoice, seen = new Set<string>()): { group: string; index?: number } | null {
    if (seen.has(c.id)) return null
    seen.add(c.id)
    if (c.group) return { group: c.group, index: c.index }
    const parent = byId.get(c.follows || c.parent || '')
    if (parent) return owner(parent, seen)
    return structured || c.kind === 'param' ? null : subjectOfId(c.id)
  }
  function isShared(c: ProgramChoice, seen = new Set<string>()): boolean {
    if (c.shared) return true
    if (seen.has(c.id)) return false
    seen.add(c.id)
    const parent = byId.get(c.follows || c.parent || '')
    return !!parent && isShared(parent, seen)
  }
  const scene: ProgramSection = { id: 'scene', label: '', choices: [], kind: 'scene' }
  const shared: ProgramSection = { id: 'shared', label: 'Shared', choices: [], kind: 'shared' }
  const subjects = new Map<string, ProgramSection & { group: string; index?: number }>()
  for (const c of choices) {
    const subject = owner(c)
    if (!subject) { (isShared(c) ? shared : scene).choices.push(c); continue }
    const id = subject.index == null ? subject.group : `${subject.group}:${subject.index}`
    let section = subjects.get(id)
    if (!section) {
      const group = groups.find(g => g.id === subject.group)
      const name = group?.label || subject.group.replace(/_/g, ' ').replace(/^./, x => x.toUpperCase())
      const label = subject.index == null ? programLabel(name) : `${programLabel(subjectLabel(name))} ${subject.index}`
      section = { id, label, choices: [], kind: 'subject', group: subject.group, index: subject.index }
      subjects.set(id, section)
    }
    section.choices.push(c)
  }
  if (subjects.size < 2) {  // one subject: no pointless header
    return choices.length ? [{ id: 'scene', label: '', choices: [...choices], kind: 'scene' }] : []
  }
  const groupOrder = [...new Set([...groups.map(g => g.id), ...[...subjects.values()].map(s => s.group)])]
  const ordered = [...subjects.values()].sort((a, b) => groupOrder.indexOf(a.group) - groupOrder.indexOf(b.group) || (a.index ?? 0) - (b.index ?? 0))
  return [scene, shared, ...ordered].filter(s => s.choices.length)
}
