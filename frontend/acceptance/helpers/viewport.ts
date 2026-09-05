/**
 * Small-screen audit helpers shared by the phone lane and the desktop
 * chrome-geometry guard. Pure page evaluation; no app knowledge beyond
 * the data-viewport attribute useViewport.ts mirrors onto <html>.
 */
import { expect, type Page } from '@playwright/test';

/**
 * Settle a fresh page load without assuming the desktop shell exists: the
 * compact chrome has no "All Assets" sidebar link, so the desktop helper's
 * shell probe would never resolve. Handles onboarding's Get started and the
 * readiness panel, then waits for the app to render.
 */
export async function settleAnyViewport(page: Page) {
  const getStarted = page.getByRole('button', { name: 'Get started' }).first();
  const dismiss = page.getByTestId('readiness-dismiss');
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    if (await getStarted.isVisible({ timeout: 250 }).catch(() => false)) {
      // Onboarding animates its CTA in; a strict click can chase a moving
      // target for the whole test timeout. Best effort, then loop.
      await getStarted.click({ timeout: 3000, force: true }).catch(() => {});
      await page.waitForTimeout(500);
      continue;
    }
    if (await dismiss.isVisible({ timeout: 250 }).catch(() => false)) {
      await dismiss.click({ timeout: 3000, force: true }).catch(() => {});
      await page.waitForTimeout(300);
      continue;
    }
    const ready = await page.evaluate(() => {
      if (document.querySelector('.startup-screen')) return false;
      const app = document.getElementById('app');
      return !!app && app.children.length > 0 && !!document.documentElement.getAttribute('data-viewport');
    }).catch(() => false);
    if (ready) break;
    await page.waitForTimeout(250);
  }
  await waitForAppReady(page);
}

/** Wait until the startup screen is gone and the router has rendered something. */
export async function waitForAppReady(page: Page) {
  await page.waitForFunction(() => {
    if (document.querySelector('.startup-screen')) return false;
    const app = document.getElementById('app');
    return !!app && app.children.length > 0 && !!document.documentElement.getAttribute('data-viewport');
  }, null, { timeout: 30000 });
  // Connection/lock screens render inside #app too; give data a beat to land.
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
}

export interface OverflowReport { docWidth: number; viewportWidth: number; offenders: string[] }

/** Horizontal overflow: the document, or any element, wider than the viewport. */
export async function auditHorizontalOverflow(page: Page): Promise<OverflowReport> {
  return page.evaluate(() => {
    const vw = window.innerWidth;
    const docWidth = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth);
    const offenders: string[] = [];
    const all = document.body.querySelectorAll<HTMLElement>('*');
    for (const el of all) {
      const r = el.getBoundingClientRect();
      if (r.width === 0) continue;
      // Ignore things that are meant to scroll horizontally inside a clipped parent.
      const style = getComputedStyle(el);
      if (style.position === 'fixed' && r.right <= vw + 1) continue;
      if (r.right > vw + 1 && r.left < vw) {
        // Anything inside a horizontally clipped or scrolling ancestor is
        // that ancestor's business (a scrolling strip is not overflow).
        let clipped = false;
        for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
          if (['hidden', 'auto', 'scroll', 'clip'].includes(getComputedStyle(p).overflowX)) { clipped = true; break; }
        }
        if (clipped) continue;
        offenders.push(describe(el));
        if (offenders.length >= 8) break;
      }
    }
    function describe(el: HTMLElement) {
      const cls = (el.getAttribute('class') || '').split(/\s+/).slice(0, 4).join('.');
      return `${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${cls ? '.' + cls : ''}`;
    }
    return { docWidth, viewportWidth: vw, offenders };
  });
}

export interface HitTargetReport { total: number; small: Array<{ el: string; w: number; h: number }> }

/** Visible interactive elements smaller than 44×44 CSS px (DESIGN.md §1.11 touch targets). */
export async function auditHitTargets(page: Page, min = 44, root = 'body'): Promise<HitTargetReport> {
  return page.evaluate(([MIN, ROOT]) => {
    const sel = 'button, a[href], [role="button"], [role="menuitem"], [role="tab"], input:not([type="hidden"]), select, textarea, summary';
    // When a modal layer is open, only what is on top counts: everything
    // under the backdrop is inert.
    const scope = document.querySelector(ROOT as string) ?? document.body;
    const els = Array.from(scope.querySelectorAll<HTMLElement>(sel));
    const small: Array<{ el: string; w: number; h: number }> = [];
    let total = 0;
    for (const el of els) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      if (r.bottom < 0 || r.top > window.innerHeight) continue;
      // Off-screen horizontally (the closed drawer) or inert: not reachable.
      if (r.right <= 0 || r.left >= window.innerWidth) continue;
      if (el.closest('[inert], [aria-hidden="true"]')) continue;
      const style = getComputedStyle(el);
      if (style.visibility === 'hidden' || style.pointerEvents === 'none' || style.opacity === '0') continue;
      total++;
      if (r.width < MIN || r.height < MIN) {
        const cls = (el.getAttribute('class') || '').split(/\s+/).slice(0, 3).join('.');
        const label = (el.getAttribute('aria-label') || el.getAttribute('title') || el.textContent || '').trim().slice(0, 24);
        small.push({ el: `${el.tagName.toLowerCase()}${cls ? '.' + cls : ''}${label ? `("${label}")` : ''}`, w: Math.round(r.width), h: Math.round(r.height) });
      }
    }
    return { total, small };
  }, [min, root] as [number, string]);
}

export interface ChromeGeometry { sidebar: number[] | null; topbar: number[] | null; content: number[] | null; viewport: number[] }

/** Where the desktop chrome sits. Any mobile PR that moves these has changed desktop. */
export async function readChromeGeometry(page: Page): Promise<ChromeGeometry> {
  return page.evaluate(() => {
    const rect = (el: Element | null) => {
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)];
    };
    return {
      sidebar: rect(document.querySelector('.navigation-sidebar')),
      topbar: rect(document.querySelector('.top-bar')),
      content: rect(document.querySelector('.top-bar')?.parentElement?.lastElementChild ?? null),
      viewport: [window.innerWidth, window.innerHeight],
    };
  });
}

export function expectNoOverflow(report: OverflowReport, route: string) {
  expect(report.docWidth, `${route}: document wider than viewport (${report.docWidth} > ${report.viewportWidth}); offenders: ${report.offenders.join(', ')}`)
    .toBeLessThanOrEqual(report.viewportWidth + 1);
  expect(report.offenders, `${route}: elements overflow the viewport: ${report.offenders.join(', ')}`).toHaveLength(0);
}
