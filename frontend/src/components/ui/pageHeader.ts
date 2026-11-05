// Class strings for the page header tiers, shared by PageHeader.vue and the
// one header that has to be a teleport target (the tool view's slot).
export type PageHeaderTier = 'standard' | 'compact'

export function pageHeaderClass(tier: PageHeaderTier, rule = true): string {
  return [
    'flex flex-none items-center gap-3 bg-base px-page',
    tier === 'standard' ? 'h-header' : 'h-header-compact',
    rule ? 'border-b border-edge-subtle' : '',
  ].filter(Boolean).join(' ')
}

export function pageHeaderTitleClass(tier: PageHeaderTier): string {
  return [
    'min-w-0 truncate font-brand font-semibold leading-tight text-content',
    tier === 'standard' ? 'text-xl' : 'text-base',
  ].join(' ')
}
