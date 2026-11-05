// A one-line preview of text that may carry Markdown (an assistant's last
// message, a flow's description). Rows show prose, so the syntax is removed
// rather than rendered: emphasis marks, headings, list bullets, quotes, code
// fences and link targets go; the words stay.
export function plainPreview(text: string | null | undefined): string {
  if (!text) return ''
  return text
    // Code fences and inline code keep their content.
    .replace(/```[a-z0-9_-]*\n?/gi, ' ')
    .replace(/`([^`]*)`/g, '$1')
    // Images and links keep their label.
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    // Headings, quotes and bullets at the start of a line or after a sentence.
    .replace(/(^|\n)\s{0,3}(#{1,6}|>)\s+/g, '$1')
    .replace(/(^|\n)\s*[-*+•]\s+/g, '$1')
    .replace(/([:;.!?])\s+[-*+•]\s+/g, '$1 ')
    // Emphasis pairs. Underscores only count at word edges (snake_case stays).
    .replace(/(\*\*|__)(?=\S)(.+?)(?<=\S)\1/g, '$2')
    .replace(/\*(?=\S)([^*\n]+?)(?<=\S)\*/g, '$1')
    .replace(/(^|\s)_(?=\S)([^_\n]+?)(?<=\S)_(?=\s|[.,;:!?]|$)/g, '$1$2')
    .replace(/~~(.+?)~~/g, '$1')
    .replace(/\s+/g, ' ')
    .trim()
}
