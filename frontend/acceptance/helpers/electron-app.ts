/**
 * Tier B fixtures: run the acceptance specs inside the real Electron shell.
 *
 * Each test gets a freshly launched shell (real main process, preload bridge,
 * window lifecycle) pointed at the same acceptance backend/frontend servers
 * the browser lane uses. A per-test temp data dir gives every launch a clean
 * Chromium profile; the browser lane's storage-state (seeded by the shared
 * global-setup) is replayed into localStorage before the app boots its UI.
 */

import { test as base, expect, type Page } from '@playwright/test';
import { _electron, type ElectronApplication } from 'playwright';
import { createRequire } from 'node:module';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const moduleDir = path.dirname(fileURLToPath(import.meta.url));

const frontendPort = process.env.STIMMA_FRONTEND_PORT || '19292';
const backendPort = process.env.STIMMA_BACKEND_PORT || '19291';
const baseURL = `http://127.0.0.1:${frontendPort}`;

const repoRoot = path.resolve(moduleDir, '..', '..', '..');
const electronRoot = path.join(repoRoot, 'electron');
const electronRequire = createRequire(path.join(electronRoot, 'package.json'));
const electronBinary: string = electronRequire('electron');

interface StorageStateOrigin {
  origin: string;
  localStorage: { name: string; value: string }[];
}

function storageSeed(): { name: string; value: string }[] {
  try {
    const state = JSON.parse(
      readFileSync(path.join(moduleDir, '..', 'acceptance', '.auth', 'storage-state.json'), 'utf8'),
    ) as { origins?: StorageStateOrigin[] };
    // The browser lane runs on localhost, the shell on 127.0.0.1 — same
    // server; replay every origin's entries.
    return (state.origins ?? []).flatMap((o) => o.localStorage ?? []);
  } catch {
    return [];
  }
}

export const test = base.extend<{
  electronApp: ElectronApplication;
  page: Page;
}>({
  electronApp: async ({}, use) => {
    const sandboxDir = mkdtempSync(path.join(tmpdir(), 'stimma-tierb-'));
    const env: Record<string, string> = { ...process.env } as Record<string, string>;
    delete env.ELECTRON_RUN_AS_NODE;
    const app = await _electron.launch({
      executablePath: electronBinary,
      args: [electronRoot],
      env: {
        ...env,
        STIMMA_DEV: '1',
        STIMMA_SANDBOX: 'tier-b',
        STIMMA_DATA_DIR: path.join(sandboxDir, 'data'),
        STIMMA_CACHE_DIR: path.join(sandboxDir, 'cache'),
        STIMMA_BACKEND_PORT: backendPort,
        STIMMA_FRONTEND_PORT: frontendPort,
      },
    });
    await use(app);
    await app.close();
    rmSync(sandboxDir, { recursive: true, force: true });
  },

  page: async ({ electronApp }, use) => {
    const page = await electronApp.firstWindow();
    await page.waitForLoadState('domcontentloaded');

    // Replay the browser lane's seeded storage, then reboot the UI so the
    // app starts from the same baseline the Chromium project uses.
    const seed = storageSeed();
    if (seed.length > 0) {
      await page.evaluate((entries) => {
        for (const { name, value } of entries) localStorage.setItem(name, value);
      }, seed);
    }

    // Electron pages have no context baseURL; make relative goto work like
    // the browser project.
    const originalGoto = page.goto.bind(page);
    page.goto = ((url: string, options?: Parameters<Page['goto']>[1]) => {
      const resolved = /^[a-z]+:/i.test(url) ? url : new URL(url, baseURL).toString();
      return originalGoto(resolved, options);
    }) as Page['goto'];

    await page.goto('/browse');
    await use(page);
  },
});

export { expect };
