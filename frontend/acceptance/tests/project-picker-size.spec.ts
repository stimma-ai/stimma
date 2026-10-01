import { expect, test } from '../helpers/testbed';
import { waitForShell } from '../helpers/app';

for (const count of [0, 1, 5, 50]) {
  test(`picker stays simple with ${count} projects and searches only a long list`, async ({ page }) => {
    await page.route('**/api/projects', route => route.fulfill({ json: Array.from({ length: count }, (_, i) => ({ id: i + 1, name: `Project ${i + 1}` })) }));
    await page.goto('/browse?library=1');
    await waitForShell(page);
    // The sidebar lists five recent projects; the rest sit behind All projects.
    const section = page.locator('.navigation-sidebar').getByRole('region', { name: 'Projects' });
    await expect(section.getByRole('button', { name: /^Project \d+$/ })).toHaveCount(Math.min(count, 5));
    await expect(section.getByRole('button', { name: /^All projects/ })).toHaveCount(count > 5 ? 1 : 0);
    await page.goto('/browse?library=1&projects=1');
    const picker = page.getByRole('dialog', { name: 'Choose a project' });
    // A pure project picker: no everything row, no section header.
    await expect(picker.getByRole('button', { name: 'Everything', exact: true })).toHaveCount(0);
    await expect(picker.getByRole('button', { name: 'New project', exact: true })).toBeVisible();
    if (count <= 5) {
      await expect(picker.getByRole('textbox')).toHaveCount(0);
      await expect(picker.getByText('Projects', { exact: true })).toHaveCount(0);
      await expect(picker.getByRole('button', { name: /^Project \d+$/ })).toHaveCount(count);
      if (!count) await expect(picker.getByText('No projects yet')).toBeVisible();
      if (count) {
        const last = picker.getByRole('button', { name: `Project ${count}`, exact: true });
        await expect(last).toBeVisible();
        const box = await last.boundingBox();
        const menuBox = await picker.boundingBox();
        expect(box!.y + box!.height).toBeLessThanOrEqual(menuBox!.y + menuBox!.height);
      }
    } else {
      await expect(picker.getByRole('button', { name: /^Project \d+$/ })).toHaveCount(50);
      await picker.getByRole('textbox', { name: 'Find a project' }).fill('Project 50');
      await expect(picker.getByRole('button', { name: /^Project \d+$/ })).toHaveCount(1);
      await expect(picker.getByRole('button', { name: 'Project 50', exact: true })).toBeVisible();
    }
    await page.keyboard.press('Escape');
    await expect(picker).toBeHidden();
  });
}
