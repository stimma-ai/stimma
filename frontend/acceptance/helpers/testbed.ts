/**
 * Shell-selectable test entry for acceptance specs.
 *
 * Browser lane (default): plain @playwright/test — Chromium against the dev
 * server, exactly as before.
 * Electron lane (STIMMA_ACCEPTANCE_SHELL=electron): the same specs run inside
 * the real Electron shell via the fixtures in electron-app.ts.
 */

import { readFileSync } from 'node:fs';
import { test as browserTest, expect } from '@playwright/test';
import { test as electronTest } from './electron-app';

const shellTest =
  process.env.STIMMA_ACCEPTANCE_SHELL === 'electron'
    ? (electronTest as unknown as typeof browserTest)
    : browserTest;

function acceptanceProfile(): string {
  const state = JSON.parse(readFileSync('acceptance/.auth/storage-state.json', 'utf8'));
  for (const origin of state.origins ?? []) {
    const entry = origin.localStorage?.find((item: { name: string }) => item.name === 'profileId');
    if (entry) return entry.value;
  }
  throw new Error('No profile in the acceptance storage state');
}

// Tabs and tool state live on the backend, which every test shares. Each test
// starts with an empty workspace, as it used to by getting a fresh browser.
export const test = shellTest.extend<{ emptyWorkspace: void }>({
  emptyWorkspace: [async ({ request, baseURL }, use) => {
    const headers = { 'X-Profile-ID': acceptanceProfile() };
    const { docs } = await (await request.get(`${baseURL}/api/workspace`, { headers })).json();
    const ops = docs.map((doc: { namespace: string; key: string }) => ({
      namespace: doc.namespace,
      key: doc.key,
      deleted: true,
    }));
    if (ops.length) await request.post(`${baseURL}/api/workspace/docs`, { headers, data: { ops } });
    await request.put(`${baseURL}/api/preferences/experimental_flows`, { headers, data: { enabled: false } });
    await use();
  }, { auto: true }],
});

export { expect };
