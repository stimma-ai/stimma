/**
 * Shell-selectable test entry for acceptance specs.
 *
 * Browser lane (default): plain @playwright/test — Chromium against the dev
 * server, exactly as before.
 * Electron lane (STIMMA_ACCEPTANCE_SHELL=electron): the same specs run inside
 * the real Electron shell via the fixtures in electron-app.ts.
 */

import { test as browserTest, expect } from '@playwright/test';
import { test as electronTest } from './electron-app';

export const test =
  process.env.STIMMA_ACCEPTANCE_SHELL === 'electron'
    ? (electronTest as unknown as typeof browserTest)
    : browserTest;

export { expect };
