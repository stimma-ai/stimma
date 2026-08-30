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

  test('remoted-keyboard hold (press+release pairs) starts dictation', async ({ page }) => {
    // Deskflow-style KVMs deliver a held key as rapid full press+release
    // pairs (~25ms apart) instead of down…repeat…up; the chain-grace logic
    // must treat an unbroken chain as one hold.
    await page.goto('/browse');
    await waitForShell(page);

    const chat = await createChat(page, 'Voice Hold KVM Chat');
    await page.goto(`/chat/${chat.id}`);

    const input = page.getByRole('textbox', { name: 'Type a message...' });
    await expect(input).toBeVisible({ timeout: 30000 });
    await input.click();

    const session = await page.context().newCDPSession(page);
    const key = {
      key: ' ',
      code: 'Space',
      windowsVirtualKeyCode: 32,
      nativeVirtualKeyCode: 49,
    };
    const pairTimer = setInterval(() => {
      void (async () => {
        await session.send('Input.dispatchKeyEvent', { type: 'keyDown', text: ' ', ...key });
        await session.send('Input.dispatchKeyEvent', { type: 'keyUp', ...key });
      })().catch(() => {});
    }, 25);

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
          { timeout: 10000, message: 'press+release chain must trigger start()' },
        )
        .toBe(true);
    } finally {
      clearInterval(pairTimer);
    }
  });

  test('a single space tap does not start dictation', async ({ page }) => {
    await page.goto('/browse');
    await waitForShell(page);

    const chat = await createChat(page, 'Voice Tap Chat');
    await page.goto(`/chat/${chat.id}`);

    const input = page.getByRole('textbox', { name: 'Type a message...' });
    await expect(input).toBeVisible({ timeout: 30000 });
    await input.click();

    await page.keyboard.press('Space');
    await page.waitForTimeout(700);

    const changed = await page.evaluate(() => {
      const spinner = document.querySelector('button .animate-spin');
      const buttons = Array.from(document.querySelectorAll('button[title]'));
      return (
        Boolean(spinner) ||
        buttons.some((b) =>
          /Downloading voice model|Transcribing|Recording|Lockdown|error/i.test(
            b.getAttribute('title') || '',
          ),
        )
      );
    });
    expect(changed, 'a tap must stay a tap').toBe(false);
    await expect(input).toHaveValue(' ');
  });
});
