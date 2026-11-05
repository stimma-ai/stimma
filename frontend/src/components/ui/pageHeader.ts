// Class strings for the page header, shared by PageHeader.vue and the one
// header that has to be a teleport target (the tool view's slot). There is one
// desktop header: one height (--header-h), one title style, one fill, one left
// edge (--page-margin). `tier` is still accepted so existing callers compile,
// but both values draw the same header.
export type PageHeaderTier = 'standard' | 'compact'

export function pageHeaderClass(_tier: PageHeaderTier = 'standard', rule = true): string {
  return [
    'flex flex-none items-center gap-3 bg-base px-page h-header',
    rule ? 'border-b border-edge-subtle' : '',
  ].filter(Boolean).join(' ')
}

export function pageHeaderTitleClass(_tier: PageHeaderTier = 'standard'): string {
  return 'min-w-0 truncate font-brand text-lg font-semibold leading-tight text-content'
}
