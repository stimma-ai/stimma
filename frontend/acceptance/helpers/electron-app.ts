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

// Resolved lazily: the browser lane imports this module transitively (via
// helpers/testbed) in environments where electron/node_modules doesn't exist
// (CI quality gate). Only the electron lane may touch the electron package.
let electronBinary: string | null = null;
function resolveElectronBinary(): string {
  if (!electronBinary) {
    const electronRequire = createRequire(path.join(electronRoot, 'package.json'));
    electronBinary = electronRequire('electron') as string;
  }
  return electronBinary;
}

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
      executablePath: resolveElectronBinary(),
      args: [electronRoot],
      env: {
        ...env,
        // Voice model downloads must fail fast (no network) so voice specs
        // can assert the attempt without fetching a 650MB model.
        STIMMA_PRIVACY_LOCKDOWN: '1',
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

    // The shell kicks off its own loadURL(devUrl) when it creates the window
    // (electron/src/windows.ts) and does not await it. firstWindow() plus
    // domcontentloaded can resolve before that navigation lands, so the seed
    // below would write to the wrong origin and the goto would race the
    // shell's own load -- Playwright then aborts the goto with "interrupted
    // by another navigation". Let the shell reach its start URL first.
    await page.waitForURL((url) => url.href.startsWith(baseURL), {
      waitUntil: 'domcontentloaded',
    });

    // Replay the browser lane's seeded storage, then reboot the UI so the
    // app starts from the same baseline the Chromium project uses.
    const seed = storageSeed();
    if (seed.length > 0) {
      await page.evaluate((entries) => {
        for (const { name, value } of entries) localStorage.setItem(name, value);
      }, seed);
    }

    // Electron pages have no context baseURL; make relative goto and
    // request.fetch work like the browser project.
    const originalGoto = page.goto.bind(page);
    page.goto = ((url: string, options?: Parameters<Page['goto']>[1]) => {
      const resolved = /^[a-z]+:/i.test(url) ? url : new URL(url, baseURL).toString();
      return originalGoto(resolved, options);
    }) as Page['goto'];

    const request = page.request;
    const originalFetch = request.fetch.bind(request);
    request.fetch = ((urlOrRequest: unknown, options?: unknown) => {
      if (typeof urlOrRequest === 'string' && !/^[a-z]+:/i.test(urlOrRequest)) {
        return originalFetch(new URL(urlOrRequest, baseURL).toString(), options as never);
      }
      return originalFetch(urlOrRequest as never, options as never);
    }) as typeof request.fetch;

    await page.goto('/browse');
    await use(page);
  },
});

export { expect };
