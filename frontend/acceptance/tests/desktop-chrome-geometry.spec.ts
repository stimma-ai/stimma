import { readFile, writeFile } from 'node:fs/promises';
import { expect, test } from '../helpers/testbed';
import { waitForShell } from '../helpers/app';
import { readChromeGeometry } from '../helpers/viewport';

/**
 * Desktop regression guard for mobile work: at 1440×900 the sidebar and top
 * bar must sit exactly where they sit today. Any PR that moves them has
 * changed desktop and must say so by regenerating the baseline:
 *
 *   STIMMA_GEOMETRY_UPDATE=1 stimma test acceptance acceptance/tests/desktop-chrome-geometry.spec.ts
 *
 * Geometry, not pixels: screenshots drift with fonts and generated content;
 * rectangles of the chrome do not.
 */
const BASELINE_PATH = 'acceptance/desktop-chrome-geometry.json';

test.describe('desktop chrome geometry', () => {
  test('sidebar and top bar have not moved', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/browse');
    await waitForShell(page);
    await expect(page.locator('html')).toHaveAttribute('data-viewport', 'wide');
    const geo = await readChromeGeometry(page);
    const current = { sidebar: geo.sidebar, topbar: geo.topbar, viewport: geo.viewport };

    if (process.env.STIMMA_GEOMETRY_UPDATE) {
      await writeFile(BASELINE_PATH, JSON.stringify(current, null, 2) + '\n');
      console.log(`[geometry] baseline written: ${JSON.stringify(current)}`);
      return;
    }
    const baseline = JSON.parse(await readFile(BASELINE_PATH, 'utf8'));
    expect(current.sidebar, 'sidebar rect [left, top, width, height]').toEqual(baseline.sidebar);
    expect(current.topbar, 'top bar rect [left, top, width, height]').toEqual(baseline.topbar);
  });
});
