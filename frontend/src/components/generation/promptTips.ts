/**
 * The prompt tips, in one place: Tool View's panel (slots first) and the syntax help of every
 * other prompt editor (the marks it reads), in the user's words. Each kind of mark wears its
 * color in the editor (useCodeMirrorPrompt's theme).
 */
import { PROMPT_BRAND } from './promptBrand'

export const fluentIntro = 'Each image gets something new in the parts you mark. The rest stays as you wrote it.'
export type Tone = 'slot' | 'list' | 'name' | 'comment' | 'exact'
export const TONES: Record<Tone, string> = {
  slot: 'text-selection bg-selection/[0.12] ring-1 ring-inset ring-selection/25',
  list: 'text-green-600 bg-green-500/10',
  name: 'text-amber-600 bg-amber-500/10',
  comment: 'text-gray-500 italic bg-zinc-500/10',
  exact: 'text-blue-500 bg-blue-500/10',
}
export type Tip = { title: string; line?: { tone: Tone; parts: { text: string; tone?: Tone }[] }; code?: { text: string; tone: Tone }; text: string[]; steps?: string[] }
export const fluentTips: Tip[] = [
  { title: 'Vary any part',
    line: { tone: 'slot', parts: [{ text: 'dorm room with a ' }, { text: '<young man>', tone: 'slot' }, { text: ', lit by ' }, { text: '<light>', tone: 'slot' }] },
    text: ['Words in angle brackets change with every image. Any words can be a slot.'],
    steps: ['Select words and choose Vary this', 'Select words and press <', 'Click an underlined word, then Vary this', 'Click a + idea under your prompt, like + light'] },
  { title: 'Choose what it can be',
    text: ['Click a slot, or its pill under the prompt, to pick one option or several.',
      'As written keeps your own words. Leave out drops it from the images. The × on a pill puts it back.',
      '<friend> and <friend> are two different people.'] },
  { title: 'Keep from this',
    text: ['Like an image? Choose Keep from this under it, and tick what the next images should keep.'] },
  { title: 'Detail level',
    text: [`In the ${PROMPT_BRAND} menu: Yours adds nothing to your words, Medium adds a little, High a lot.`] },
  { title: 'Lists', code: { text: '{red|blue|green}', tone: 'list' },
    text: ['Each image uses one of the options, and nothing else.'] },
  { title: 'Saved wildcards and segments', code: { text: '{{hairstyle}}', tone: 'name' },
    text: ['Uses the one you saved with that name in Settings. A name that isn’t saved turns red.'] },
  { title: 'Comment lines', code: { text: '# she is a regular here', tone: 'comment' },
    text: [`Tells ${PROMPT_BRAND} more about what you want. Never sent to the image.`] },
  { title: 'Exact text', code: { text: '[ohwx woman]', tone: 'exact' },
    text: ['Sent exactly as typed. Use it for trigger words, or words that should appear in the picture.'] },
]
// Outside Tool View the editor reads the same marks but slots: the same tips, with comment
// lines read by the chat model that improves the prompt.
export const classicTips: Tip[] = fluentTips.slice(-4).map(t => t.code?.tone === 'comment'
  ? { ...t, text: ['Notes for the chat model that improves your prompt. Never sent to the image.'] }
  : t)
