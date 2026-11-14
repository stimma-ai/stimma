// Tool View's prompt feature (PROMPT_BRAND) has each image's choices checked to fit
// together by the chat model, on the server, as the image is drawn.

/** Generation details: one quiet line when this image's choices weren't checked. */
export function unjudgedNote(run: any, brand: string): string | null {
  const why = run?.fix?.skipped
  if (!why) return null
  return `Choices weren’t checked to fit together: ${brand} wasn’t ready.`
}
