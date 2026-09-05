import { mkdir } from 'node:fs/promises';
import { expect, test } from '@playwright/test';
import { auditHitTargets, auditHorizontalOverflow, expectNoOverflow, settleAnyViewport } from '../helpers/viewport';

/**
 * Phone lane: every hub and detail route at 390×844 with touch emulation.
 *
 * Two hard rules from DESIGN.md §1.11: no horizontal overflow, no visible
 * interactive element under 44×44 px. Routes listed in KNOWN_BAD only warn —
 * that is the ratchet: each mobile PR removes the routes it fixes, and a route
 * can never go back on the list without a diff that says so.
 *
 * A screenshot per route lands in acceptance/phone-shots/ so a reviewer can
 * see the phone without owning one.
 */

const ROUTES = [
  '/home',
  '/browse',
  '/workspace',
  '/search?q=test',
  '/boards',
  '/chats',
  '/flows',
  '/projects',
  '/tools',
  '/stimpacks',
  '/trash',
  '/upload',
];

// Ratchet. Everything starts here; the chrome PR and each hub PR delete rows.
const KNOWN_BAD: Record<string, { overflow?: boolean; hitTargets?: boolean }> = {
  // Overflow is clean on every hub since the compact chrome landed, except
  // the Boards landing's fixed-width search field. Hit targets are the
  // per-hub PRs' job; each one deletes its row here.
  '/home': { hitTargets: true },
  '/browse': { hitTargets: true },
  '/search?q=test': { hitTargets: true },
  '/boards': { overflow: true, hitTargets: true },
  '/chats': { hitTargets: true },
  '/flows': { hitTargets: true },
  '/projects': { hitTargets: true },
  '/tools': { hitTargets: true },
  '/trash': { hitTargets: true },
  '/upload': { hitTargets: true },
};

test.describe('phone lane: route audit', () => {
  test.beforeAll(async () => {
    await mkdir('acceptance/phone-shots', { recursive: true });
  });

  for (const route of ROUTES) {
    test(`${route} fits a phone`, async ({ page }) => {
      await page.goto(route);
      await settleAnyViewport(page);
      await expect(page.locator('html')).toHaveAttribute('data-viewport', 'compact');
      await expect(page.locator('html')).toHaveAttribute('data-pointer', 'coarse');

      const slug = route.replace(/^\//, '').replace(/[^a-z0-9]+/gi, '-') || 'root';
      await page.screenshot({ path: `acceptance/phone-shots/${slug}.png`, fullPage: false });

      const known = KNOWN_BAD[route] ?? {};
      const overflow = await auditHorizontalOverflow(page);
      if (known.overflow) {
        if (overflow.docWidth > overflow.viewportWidth + 1 || overflow.offenders.length) {
          console.warn(`[phone] ${route} overflows (known): ${overflow.docWidth}px, ${overflow.offenders.join(', ')}`);
        } else {
          console.warn(`[phone] ${route} no longer overflows — remove it from KNOWN_BAD.overflow`);
        }
      } else {
        expectNoOverflow(overflow, route);
      }

      const hits = await auditHitTargets(page);
      if (known.hitTargets) {
        if (hits.small.length) {
          console.warn(`[phone] ${route} has ${hits.small.length}/${hits.total} sub-44px targets (known): ${hits.small.slice(0, 6).map((s) => `${s.el} ${s.w}×${s.h}`).join(', ')}`);
        } else {
          console.warn(`[phone] ${route} hit targets are clean — remove it from KNOWN_BAD.hitTargets`);
        }
      } else {
        expect(hits.small, `${route}: interactive elements under 44px: ${hits.small.map((s) => `${s.el} ${s.w}×${s.h}`).join(', ')}`).toHaveLength(0);
      }
    });
  }
});
