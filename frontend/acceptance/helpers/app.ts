import { expect, type Page } from '@playwright/test';

export const TEST_T2I_TOOL_ID = 'test:text-to-image:test-model';
export const TEST_T2I_TOOL_URL = `/tools/${TEST_T2I_TOOL_ID}`;

export async function waitForShell(page: Page) {
  await continueWithoutAccountIfNeeded(page);
  await expect(page.getByText('All Assets', { exact: true }).first()).toBeVisible({ timeout: 30000 });
  await expect(page.getByText('Tools', { exact: true }).first()).toBeVisible();
}

export async function openTool(page: Page, projectId?: number) {
  const suffix = projectId ? `?project_id=${projectId}` : '';
  await page.goto(`${TEST_T2I_TOOL_URL}${suffix}`);
  await promptInput(page).waitFor({ state: 'visible', timeout: 30000 });
  await expect(page.getByRole('button', { name: /^Run/ })).toBeEnabled({ timeout: 10000 });
}

export async function submitGeneration(page: Page, prompt: string) {
  await promptInput(page).fill(prompt);
  await page.getByRole('button', { name: /^Run/ }).click();
}

export async function waitForQueueImage(page: Page) {
  await page.locator('.bg-surface-overlay').filter({ hasText: 'Queue' }).locator('img').first()
    .waitFor({ state: 'visible', timeout: 30000 });
}

export async function apiJSON<T>(page: Page, path: string, init: RequestInit = {}): Promise<T> {
  const profileId = await page.evaluate(() => localStorage.getItem('profileId'));
  const response = await page.request.fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(profileId ? { 'X-Profile-ID': profileId } : {}),
      ...(init.headers || {}),
    },
  });
  if (!response.ok()) {
    throw new Error(`${init.method || 'GET'} ${path} failed with ${response.status()}: ${await response.text()}`);
  }
  return response.json() as Promise<T>;
}

export async function createProject(page: Page, name: string): Promise<{ id: number; name: string }> {
  return apiJSON(page, '/api/projects', {
    method: 'POST',
    data: { name },
  } as any);
}

export async function waitForGeneratedMedia(page: Page, projectId?: number): Promise<{ id: number }[]> {
  const query = new URLSearchParams({
    page: '1',
    page_size: '20',
    tool_id: TEST_T2I_TOOL_ID,
    sort_by: 'created_desc',
  });
  if (projectId != null) query.set('project_id', String(projectId));

  return waitFor(async () => {
    const media = await apiJSON<{ items: { id: number }[] }>(page, `/api/media?${query.toString()}`);
    return media.items.length > 0 ? media.items : null;
  }, 30000);
}

async function waitFor<T>(check: () => Promise<T | null>, timeoutMs: number): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  let lastError: unknown = null;
  while (Date.now() < deadline) {
    try {
      const value = await check();
      if (value) return value;
    } catch (err) {
      lastError = err;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw lastError instanceof Error ? lastError : new Error('Timed out waiting for condition');
}

function promptInput(page: Page) {
  return page.getByRole('textbox').first();
}

async function continueWithoutAccountIfNeeded(page: Page) {
  const skip = page.getByRole('button', { name: 'Continue without an account' });
  if (!(await skip.isVisible({ timeout: 1000 }).catch(() => false))) return;

  await skip.click();
  await page.getByRole('button', { name: 'Continue without account' }).click();
  await page.waitForURL((url) => !url.pathname.includes('/onboarding'), { timeout: 10000 });
  await page.goto('/browse');
}
