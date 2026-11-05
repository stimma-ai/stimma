// The two saved views every profile starts with are stored under title-case
// names. Labels are sentence case, so those two stored names show that way;
// any other name (including one a person typed) is shown as stored.
const BUILT_IN_DISPLAY: Record<string, string> = {
  'My Library': 'My library',
  'Expiring Soon': 'Expiring soon',
}

export function displaySavedViewName(name: string | null | undefined): string {
  if (!name) return ''
  return BUILT_IN_DISPLAY[name] ?? name
}
