import { expect, test } from '../helpers/testbed';
import { createChat, waitForShell } from '../helpers/app';

// Space-to-dictate regression (Electron lane only: dictation needs the desktop
// shell; the browser lane's bridge reports voice as unsupported so the hold is
// a designed no-op there).
//
// The Tier B shell runs with STIMMA_PRIVACY_LOCKDOWN=1, so the model-download
// attempt the hold triggers fails fast in the native helper without touching
// the network — the observable outcome of a successful hold in a modelless
// sandbox is the composable leaving 'idle' (downloading spinner, then the
// lockdown error state).
const electronLane = process.env.STIMMA_ACCEPTANCE_SHELL === 'electron';

test.describe('voice input acceptance', () => {
  test.skip(!electronLane, 'space-to-dictate requires the desktop shell');

  test('holding space in the chat composer starts dictation', async ({ page }) => {
    await page.goto('/browse');
    await waitForShell(page);

    const chat = await createChat(page, 'Voice Hold Chat');
    await page.goto(`/chat/${chat.id}`);

    const input = page.getByRole('textbox', { name: 'Type a message...' });
    await expect(input).toBeVisible({ timeout: 30000 });
    await input.click();

    // Mic button rendered (voice supported through the bridge).
    const micButton = page.locator('button[title*="Hold to talk"]').first();
    await expect(micButton).toBeVisible({ timeout: 10000 });

    // Instrument: count Space keydowns reaching the document so a failure
    // distinguishes "events not delivered" from "hold logic broken".
    await page.evaluate(() => {
      const w = window as any;
      w.__spaceKeydowns = 0;
      document.addEventListener(
        'keydown',
        (e) => {
          if ((e as KeyboardEvent).code === 'Space') w.__spaceKeydowns++;
        },
        true,
      );
    });

    // Hold Space well past the 250ms tap-vs-hold threshold.
    await page.keyboard.down('Space');
    await page.waitForTimeout(600);

    const spaceSeen = await page.evaluate(() => (window as any).__spaceKeydowns as number);
    expect(spaceSeen, 'Space keydown must reach the page').toBeGreaterThan(0);

    // A successful hold leaves idle: spinner (downloading) appears, and with
    // the helper in lockdown the attempt settles into an error title on the
    // button. Either observable proves start() ran from the hold.
    await expect
      .poll(
        async () =>
          page.evaluate(() => {
            const spinner = document.querySelector('button .animate-spin');
            const buttons = Array.from(document.querySelectorAll('button[title]'));
            // The idle title starts with "Hold to talk"; any other title on
            // the mic (downloading %, transcribing, recording, error text)
            // means start() ran.
            const micChanged = buttons.some((b) => {
              const t = b.getAttribute('title') || '';
              return /Downloading voice model|Transcribing|Recording|Lockdown|error/i.test(t);
            });
            return Boolean(spinner) || micChanged;
          }),
        { timeout: 10000, message: 'hold must trigger start() (spinner or error state)' },
      )
      .toBe(true);

    await page.keyboard.up('Space');
  });

  test('physical-style hold with macOS auto-repeat also starts dictation', async ({ page }) => {
    await page.goto('/browse');
    await waitForShell(page);

    const chat = await createChat(page, 'Voice Hold Repeat Chat');
    await page.goto(`/chat/${chat.id}`);

    const input = page.getByRole('textbox', { name: 'Type a message...' });
    await expect(input).toBeVisible({ timeout: 30000 });
    await input.click();

    // Drive raw CDP key events with autoRepeat, exactly like holding the
    // physical spacebar on macOS (initial keydown, then repeats every ~35ms).
    const session = await page.context().newCDPSession(page);
    const key = {
      key: ' ',
      code: 'Space',
      windowsVirtualKeyCode: 32,
      nativeVirtualKeyCode: 49,
    };
    await session.send('Input.dispatchKeyEvent', { type: 'keyDown', text: ' ', ...key });
    const repeatTimer = setInterval(() => {
      void session
        .send('Input.dispatchKeyEvent', { type: 'keyDown', text: ' ', autoRepeat: true, ...key })
        .catch(() => {});
    }, 35);

    try {
      await expect
        .poll(
          async () =>
            page.evaluate(() => {
              const spinner = document.querySelector('button .animate-spin');
              const buttons = Array.from(document.querySelectorAll('button[title]'));
              const micChanged = buttons.some((b) => {
                const t = b.getAttribute('title') || '';
                return /Downloading voice model|Transcribing|Recording|Lockdown|error/i.test(t);
              });
              return Boolean(spinner) || micChanged;
            }),
          { timeout: 10000, message: 'auto-repeat hold must trigger start()' },
        )
        .toBe(true);
    } finally {
      clearInterval(repeatTimer);
      await session.send('Input.dispatchKeyEvent', { type: 'keyUp', ...key }).catch(() => {});
    }
  });
});
