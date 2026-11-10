import { test } from '@playwright/test'
import { settle, shoot } from '../helpers'

/**
 * Library and collections shots.
 * Inventory: Getting Started #2 context, Layouts #1 context, Organizing #3.
 */

test('library grid (all assets)', async ({ page }) => {
  await page.goto('/browse')
  await settle(page)
  await shoot(page, 'library/all-assets')
})

test('collections landing', async ({ page }) => {
  await page.goto('/collections')
  await settle(page)
  await shoot(page, 'library/collections-landing')
})

test('collection detail', async ({ page }) => {
  await page.goto('/collections')
  await settle(page)
  await page.getByText('Brand Refresh').first().click()
  await settle(page)
  await shoot(page, 'library/collection-detail')
})

test('lineage view', async ({ page }) => {
  // Media 23 is the kontext-edit restyle of media 1 (seed.py), so it has a chain.
  await page.goto('/lineage/23')
  await settle(page)
  await shoot(page, 'lineage/lineage-view-demo')
})
