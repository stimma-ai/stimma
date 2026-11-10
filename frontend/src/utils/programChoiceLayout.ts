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

export interface ProgramSection { id: string; label: string; choices: ProgramChoice[] }

/** Shared controls lead; dependent controls inherit their subject's section. */
export function programSections(choices: ProgramChoice[], groups: ProgramGroup[]): ProgramSection[] {
  const byId = new Map(choices.map(c => [c.id, c]))
  function owner(c: ProgramChoice, seen = new Set<string>()): { group: string; index?: number } | null {
    if (seen.has(c.id)) return null
    seen.add(c.id)
    if (c.group) return { group: c.group, index: c.index }
    const parent = byId.get(c.follows || c.parent || '')
    return parent ? owner(parent, seen) : null
  }
  const shared: ProgramSection = { id: 'shared', label: '', choices: [] }
  const subjects = new Map<string, ProgramSection & { group: string; index: number }>()
  for (const c of choices) {
    const subject = owner(c)
    if (!subject) { shared.choices.push(c); continue }
    const index = subject.index ?? 1
    const id = `${subject.group}:${index}`
    let section = subjects.get(id)
    if (!section) {
      const group = groups.find(g => g.id === subject.group)
      section = { id, label: `${programLabel(subjectLabel(group?.label || subject.group))} ${index}`, choices: [], group: subject.group, index }
      subjects.set(id, section)
    }
    section.choices.push(c)
  }
  const groupOrder = [...new Set([...groups.map(g => g.id), ...[...subjects.values()].map(s => s.group)])]
  const ordered = [...subjects.values()].sort((a, b) => groupOrder.indexOf(a.group) - groupOrder.indexOf(b.group) || a.index - b.index)
  return [...(shared.choices.length ? [shared] : []), ...ordered]
}
