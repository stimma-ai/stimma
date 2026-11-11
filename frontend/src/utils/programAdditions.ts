/**
 * The user's own options for a vocabulary list, kept for later prompts (the server's
 * prompt_programs/additions.py). Pure, so it tests without a DOM.
 *
 * An option typed into the card of a choice bound to a list is kept for that list; every
 * later choice bound to it offers it again, and the pools response names those as `mine`.
 * Deleting one of the user's own options forgets it everywhere. A choice whose options were
 * written for one prompt has no list: its additions stay with that prompt.
 */

/** The list a choice's additions are kept under, or null for a choice with no list. */
export function additionList(choice: { cls?: string }, vocab?: { cls?: string } | null): string | null {
  return vocab?.cls || choice.cls || null
}

/** Whether an option is the user's own: added in this card, or kept for the choice's list. */
export function isOwnOption(option: string, edit?: { add?: string[] } | null, vocab?: { mine?: string[] } | null): boolean {
  return !!edit?.add?.includes(option) || !!vocab?.mine?.includes(option)
}
