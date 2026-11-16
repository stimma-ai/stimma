import { createApp, h, ref } from 'vue'
import '../../src/style.css'
import AIPromptEditor from '../../src/components/generation/AIPromptEditor.vue'
import { setWildcards } from '../../src/composables/useWildcards'

// Tool View's prompt box in Fluent, cut down to the editor: the real AIPromptEditor with a
// stand-in prompt control in its mode slot. The page answers Suggest. What the
// editor sends up lands in window.opened (open-slot), window.modes (slot-mode) and window.text().
const prompt = ref((window as any).START ?? '')
const promptOptions = ref<any>({ autoImprove: { enabled: true, instructions: '' }, varyPrompt: { enabled: false, instructions: '' } })
const opened: any[] = ((window as any).opened = [])
const modes: any[] = ((window as any).modes = [])
setWildcards([{ name: 'hairstyle', values: ['bob', 'pixie'] } as any])

;(window as any).text = () => prompt.value
;(window as any).setText = (t: string) => { prompt.value = t }
;(window as any).setWay = (w: 'fluent' | 'direct' | 'raw') => {
  promptOptions.value = { ...promptOptions.value, raw: w === 'raw' || undefined, direct: w === 'direct' || undefined }
}

// The host shows the editor's suggestions on their own line (Tool View's slot list).
const editorRef = ref<any>(null)
const adds = () => {
  const s = editorRef.value?.suggestions
  if (!s || !(s.vary.length + s.looks.length + s.adds.length)) return null
  return h('div', { 'data-slot-adds': '' }, [
    ...s.vary.map((p: any) => h('button', { type: 'button', 'data-slot-vary': p.text, onClick: () => editorRef.value.varyPhrase(p) }, p.label)),
    ...s.looks.map((w: any) => h('button', { type: 'button', 'data-slot-look-chip': w.label, onClick: () => editorRef.value.addWords(w.text) }, w.label)),
    ...s.adds.map((w: any) => h('button', { type: 'button', 'data-slot-add': w.label, onClick: () => editorRef.value.addWords(w.text) }, w.label)),
  ])
}

createApp({
  render: () => h('div', { class: 'p-6 w-[480px]' }, [
    h(AIPromptEditor, {
      ref: editorRef,
      modelValue: prompt.value,
      'onUpdate:modelValue': (v: string) => { prompt.value = v },
      promptOptions: promptOptions.value,
      'onUpdate:promptOptions': (v: any) => { promptOptions.value = v },
      programs: !promptOptions.value.raw && !promptOptions.value.direct && !!prompt.value.trim(),
      promptControl: true,
      externalChat: true,
      rows: 5,
      suggestContext: { project_id: 7 },
      'onSlot-mode': (e: { n: number; mode: string }) => { modes.push([e.n, e.mode]) },
      'onOpen-slot': (e: { n: number; words: string; rect: DOMRect }) => {
        opened.push({ n: e.n, words: e.words, rect: { x: e.rect.x, y: e.rect.y, width: e.rect.width, height: e.rect.height } })
      },
    }, { mode: () => h('span', { 'data-mode': '', class: 'text-ctl text-content' }, 'Fluent') }),
    adds(),
  ]),
}).mount('#app')
