import { expect, test } from '../helpers/testbed';
import { copyFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { apiJSON, goToBrowse, listMedia, waitFor, waitForShell } from '../helpers/app';

const fixturePath = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../public/logo.png',
);

test.describe('Source folder import acceptance', () => {
  test('nested Source media appears live without navigation or reload', async ({ page }, testInfo) => {
    await page.goto('/browse');
    await waitForShell(page);
    await goToBrowse(page);

    const sourceRoot = testInfo.outputPath(`source-${Date.now()}`);
    const nestedDirectory = path.join(sourceRoot, 'nested', 'two-levels-deep');
    const importedPath = path.join(nestedDirectory, `source-${Date.now()}.png`);
    await mkdir(nestedDirectory, { recursive: true });
    await copyFile(fixturePath, importedPath);

    const settings = await apiJSON<{
      folders: Array<{
        path: string;
        refresh_interval_seconds?: number;
        markers?: string[];
      }>;
    }>(page, '/api/settings');

    await apiJSON(page, '/api/settings/folders', {
      method: 'PATCH',
      data: {
        folders: [
          ...settings.folders.map(({ path: folderPath, refresh_interval_seconds, markers }) => ({
            path: folderPath,
            refresh_interval_seconds: refresh_interval_seconds ?? 300,
            markers: markers ?? [],
          })),
          {
            path: sourceRoot,
            refresh_interval_seconds: 300,
            markers: [],
          },
        ],
      },
    } as any);

    await waitFor(async () => {
      const media = await listMedia(page, { page: 1, page_size: 200, is_generated: false });
      return media.find((item) => item.file_path === importedPath) || null;
    }, 30000);

    // Grid identities are Asset IDs, which only happen to equal Media IDs in
    // an otherwise-empty database. Resolve the canonical identity so this
    // acceptance remains valid after the preceding lifecycle tests have made
    // IDs diverge.
    const importedAssetResult = await waitFor(async () => {
      const response = await apiJSON<{
        total: number;
        items: Array<{ id: number; file_path?: string }>;
      }>(page, '/api/assets/browse?sort_by=created_desc&page=1&page_size=200&state=active');
      const asset = response.items.find((item) => item.file_path === importedPath);
      return asset ? { asset, total: response.total } : null;
    }, 30000);

    // This is the product contract: the browser was already open before the
    // Source was configured, and its count/cache update without navigation or
    // reload. copyFile preserves the fixture's old filesystem date, so under
    // Newest First the imported Asset belongs at the bottom of a populated
    // acceptance library rather than at the visible top.
    await expect(page.getByText(`${importedAssetResult.total} items`, { exact: true })).toBeVisible({
      timeout: 30000,
    });
    await page.locator('.media-grid-container').evaluate((element) => {
      element.scrollTop = element.scrollHeight;
      element.dispatchEvent(new Event('scroll'));
    });
    await expect(page.getByTestId(`media-grid-item-${importedAssetResult.asset.id}`)).toBeVisible({
      timeout: 10000,
    });
  });
});
