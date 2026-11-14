import { computed, createApp, defineComponent, h, provide, ref } from 'vue'
import axios from 'axios'
import '../../src/style.css'
import AIPromptEditor from '../../src/components/generation/AIPromptEditor.vue'
import FluentControl from '../../src/components/generation/FluentControl.vue'
import FluentSlotList from '../../src/components/generation/FluentSlotList.vue'
import { usePromptProgram, type EnhanceLevel } from '../../src/composables/usePromptProgram'
import { shapePromptOptions } from '../../src/utils/fluentSubmit'
import { setDevMode } from '../../src/appConfig'
import JobTile from '../../src/components/generation/JobTile.vue'
import { RESULT_KEEP } from '../../src/composables/resultKeep'
import { mediaMenuActions, useMediaMenuAction } from '../../src/composables/useMediaContextMenu'

// Tool View's prompt card in Fluent, wired as ToolView.vue wires it: the real editor with
// the real Fluent menu in its mode slot, its marks and the lines under the text, the slot's
// picker and hover card, the prompt program composable, and a Generate button that shapes the submit's promptOptions
// the way ToolView's submit does (utils/fluentSubmit.ts). As in ToolView, the prompt is read
// when the user pauses in the box or leaves it, not while they type. The page's routes answer the
// backend's endpoints in their real shapes; what Generate sent lands in window.sent.

const prompt = ref((window as any).START ?? '')
const promptOptions = ref<any>({ autoImprove: { enabled: true, instructions: '', level: 'fill' }, varyPrompt: { enabled: false, instructions: '' } })
const sent: any[] = ((window as any).sent = [])
;(window as any).text = () => prompt.value
;(window as any).options = () => promptOptions.value
if ((window as any).DEV) setDevMode(true)

// Two results in Tool View's strip: one made from slots, one not. Tool View offers Keep from
// this on the first, on its tile and in the menu of any of its images.
const kept: any[] = ((window as any).kept = [])
const results = [
  { id: 1, status: 'completed', result_media_id: 5, parameters: JSON.stringify({ prompt: 'a', prompt_program: { key: 'k', draws: [] } }) },
  { id: 2, status: 'completed', result_media_id: 6, parameters: JSON.stringify({ prompt: 'b' }) },
]
const fromSlots = (job: any) => !!JSON.parse(job.parameters || '{}').prompt_program
;(window as any).menuActions = (mediaId: number) => mediaMenuActions(mediaId).map(a => a.label)
;(window as any).runMenuAction = (mediaId: number) => mediaMenuActions(mediaId)[0]?.run(new DOMRect(0, 0, 1, 1))

const App = defineComponent({
  setup() {
    provide(RESULT_KEEP, { can: fromSlots, open: job => { kept.push(['tile', (job as any).id]) } })
    useMediaMenuAction((mediaId) => {
      const job = results.find(j => j.result_media_id === mediaId)
      return job && fromSlots(job) ? { label: 'Keep from this', run: () => { kept.push(['menu', job.id]) } } : null
    })
    const raw = computed(() => !!promptOptions.value.raw)
    const direct = computed(() => !!promptOptions.value.direct)
    const editorEl = () => document.querySelector('[data-prompt-editor]')
    const inEditor = () => !!editorEl()?.contains(document.activeElement)
    const program = usePromptProgram({
      toolId: ref('local/krea-2'),
      prompt,
      enabled: computed(() => !raw.value && !direct.value),
      projectId: ref(7),
      promptOptions,
      setPromptOptions: (next: any) => { promptOptions.value = next },
      prepareWhenFound: () => !inEditor(),
      inPrompt: inEditor,
    })
    // ToolView's handlePromptFocusOut and preparePromptNow (the typing pause is the composable's).
    const prepareNow = () => program.doneTyping()
    function onFocusout(e: FocusEvent) {
      if (editorEl()?.contains(e.relatedTarget as Node | null)) return
      program.doneTyping()
    }
    const enhance = computed<EnhanceLevel>(() => {
      const ai = promptOptions.value.autoImprove
      return !ai?.enabled ? 'off' : ai.level === 'fill' ? 'fill' : 'expand'
    })
    function setDetailLevel(level: EnhanceLevel) {
      promptOptions.value = { ...promptOptions.value, autoImprove: { ...promptOptions.value.autoImprove, enabled: level !== 'off', ...(level !== 'off' ? { level } : {}) } }
    }
    async function generate() {
      await program.ensureReady()
      const shaped = shapePromptOptions(promptOptions.value, {
        fluentOn: true, llmUnconfigured: false, toolHasPrompt: true, unsupported: program.unsupported.value,
        enhance: { model: 'krea-2', mode: 'prose' }, program: program.payload(),
      })
      const { data } = await axios.post('/api/generate', { tool_id: 'local/krea-2', parameters: { prompt: prompt.value }, promptOptions: shaped })
      sent.push(data)
    }
    // Generate with the cursor still in the prompt (a shortcut), so leaving it reads nothing.
    ;(window as any).generate = generate
    const editorRef = ref<any>(null)
    return () => h('div', { class: 'p-4 w-full max-w-[520px] flex flex-col gap-3' }, [
      h(AIPromptEditor, {
        ref: editorRef,
        'data-prompt-editor': '',
        onFocusout,
        onSave: prepareNow,
        modelValue: prompt.value,
        'onUpdate:modelValue': (v: string) => { prompt.value = v },
        promptOptions: promptOptions.value,
        'onUpdate:promptOptions': (v: any) => { promptOptions.value = v },
        programs: program.status.value !== 'off',
        suggestContext: { project_id: 7 },
        promptControl: true,
        externalChat: true,
        rows: 5,
        slotMarks: program.marks.value,
        'onOpen-slot': (e: { n: number; words: string; rect: DOMRect }) => { if (program.status.value !== 'off') program.openEditorSlot(e) },
        'onOpen-list': (e: { n: number; rect: DOMRect }) => { if (program.status.value !== 'off') program.openEditorList(e) },
        'onLeft-slot': () => program.leftSlot(),
      }, {
        mode: ({ openHelp }: any) => h(FluentControl, {
          program, raw: raw.value, direct: direct.value, enhance: enhance.value, llmUnconfigured: false, modelName: 'Krea 2',
          translate: promptOptions.value.translate, lastPrompt: sent.length ? 'A dorm room with a 24-year-old man' : null,
          onMode: setDetailLevel,
          onWay: (w: string) => { promptOptions.value = { ...promptOptions.value, raw: w === 'raw' || undefined, direct: w === 'direct' || undefined } },
          onHelp: (anchor: DOMRect | null) => openHelp(anchor),
        }),
      }),
      h(FluentSlotList, {
        program,
        adds: editorRef.value?.slotAdds || [],
        adding: editorRef.value?.adding ?? null,
        onAdd: (name: string) => editorRef.value?.addSlot(name),
      }),
      h('button', { type: 'button', 'data-generate': '', class: 'self-end px-3 py-1.5 rounded-md bg-accent text-white text-xs', onClick: generate }, 'Generate'),
      h('div', { class: 'grid grid-cols-2 gap-2 w-[440px]', 'data-results': '' }, results.map(job => h(JobTile, { key: job.id, job }))),
    ])
  },
})
createApp(App).mount('#app')
