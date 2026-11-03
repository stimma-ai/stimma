import { expect, type Browser, type Page } from '@playwright/test';
import { apiJSON } from './app';

export type WorkspaceSnapshot = {
  docs: { namespace: string; key: string; value: any; rev: number }[];
  closed_tabs: any[];
  migration: { claimed: boolean };
};

/** A second client of the same backend: a desktop window next to the phone. */
export async function openDesktopClient(browser: Browser): Promise<Page> {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    isMobile: false,
    hasTouch: false,
    deviceScaleFactor: 1,
  });
  return context.newPage();
}

export function readWorkspace(page: Page): Promise<WorkspaceSnapshot> {
  return apiJSON<WorkspaceSnapshot>(page, '/api/workspace');
}

export async function workspaceTabs(page: Page): Promise<any[]> {
  const { docs } = await readWorkspace(page);
  return docs.filter(doc => doc.namespace === 'tab').map(doc => doc.value);
}

/** The tool tab a tool route landed on, read from the URL the guard settled. */
export async function toolInstanceOf(page: Page): Promise<string> {
  await expect(page).toHaveURL(/instance=/);
  return new URL(page.url()).searchParams.get('instance')!;
}

export function promptEditor(page: Page) {
  return page.locator('.cm-content[contenteditable="true"]').first();
}

/**
 * Counts this client's writes to the workspace. The most likely way this system
 * breaks is two clients answering each other forever, so a client only watching
 * must stay silent.
 */
export function countWrites(page: Page): { readonly count: number; reset(): void } {
  let count = 0;
  page.on('request', request => {
    if (request.method() !== 'GET' && request.url().includes('/api/workspace/')) count += 1;
  });
  return {
    get count() { return count; },
    reset() { count = 0; },
  };
}

/** Long enough for a change to arrive, settle, and for any echo to be sent. */
export const SETTLE_MS = 2500;
