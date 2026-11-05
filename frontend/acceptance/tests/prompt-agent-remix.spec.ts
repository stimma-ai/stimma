import { expect, test } from '../helpers/testbed';
import { openPromptToolById, promptInput, toolRunButton, waitForGeneratedMedia, TEST_T2I_TOOL_ID } from '../helpers/app';

const ORIGINAL = 'a fox in a snowy forest at dawn';

test.describe('tool agent after a remix', () => {
  test('Use Exact Prompt leaves the agent nothing but the text on screen', async ({ page }) => {
    const requests: any[] = [];
    let reply: (body: any) => any = () => ({ message: 'done', tool_calls: [] });
    await page.route('**/api/prompt/agent/step', async (route) => {
      const body = route.request().postDataJSON();
      requests.push(body);
      await route.fulfill({ json: reply(body) });
    });
    const agentInput = page.locator('#agent-dock textarea, #agent-dock-result textarea').last();
    const ask = async (text: string, steps: number) => {
      const before = requests.length;
      await agentInput.fill(text);
      await agentInput.press('Enter');
      await expect.poll(() => requests.length).toBe(before + steps);
    };
    const callOnce = (name: string, args: (body: any) => object) => {
      reply = (body) => {
        reply = () => ({ message: 'done', tool_calls: [] });
        return { message: '', tool_calls: [{ id: `call-${requests.length}`, name, arguments: JSON.stringify(args(body)) }] };
      };
    };

    await openPromptToolById(page, TEST_T2I_TOOL_ID);
    const enhance = page.getByRole('button', { name: /^Enhance(?: Prompt)?$/ }).first();
    if (!await enhance.evaluate((el) => el.getAttribute('aria-pressed') === 'true')) {
      await enhance.click();
    }

    // The agent writes the short prompt, so its conversation spells it out.
    await promptInput(page).fill('a fox');
    await expect(promptInput(page)).toHaveText('a fox');
    callOnce('set_prompt', () => ({ text: ORIGINAL }));
    await ask('write the prompt', 2);
    await expect(promptInput(page)).toHaveText(ORIGINAL);

    await toolRunButton(page).click();
    await waitForGeneratedMedia(page, {});
    await page.locator('button[title^="Remix: load this image"]').first().click({ force: true });
    await page.getByRole('button', { name: 'Use Exact Prompt' }).click();
    await expect(promptInput(page)).not.toHaveText(ORIGINAL);
    const rendered = await promptInput(page).innerText();

    // The agent's edit lands on what's on screen, and what it was sent can't
    // bring the short prompt back.
    const firstRequest = requests.length;
    callOnce('edit_prompt', (body) => ({ old_string: body.state_context.prompt.slice(0, 10), new_string: 'EDITED' }));
    await ask('change the fox to a lynx', 2);

    const sent = JSON.stringify(requests.slice(firstRequest));
    expect(sent).not.toContain(ORIGINAL);
    expect(requests[firstRequest].state_context.prompt).toBe(rendered);
    expect(requests[firstRequest].state_context.prompt_options.auto_improve).toBe(false);
    await expect(promptInput(page)).toHaveText(`EDITED${rendered.slice(10)}`);
  });

  test('a remix during an agent run drops what the run was about to do', async ({ page }) => {
    let answer: (() => void) | undefined;
    let requests = 0;
    await page.route('**/api/prompt/agent/step', async (route) => {
      requests += 1;
      await new Promise<void>((resolve) => { answer = resolve; });
      await route.fulfill({
        json: { message: '', tool_calls: [{ id: 'stale', name: 'set_prompt', arguments: JSON.stringify({ text: 'stale edit' }) }] },
      });
    });

    await openPromptToolById(page, TEST_T2I_TOOL_ID);
    const enhance = page.getByRole('button', { name: /^Enhance(?: Prompt)?$/ }).first();
    if (!await enhance.evaluate((el) => el.getAttribute('aria-pressed') === 'true')) {
      await enhance.click();
    }
    await promptInput(page).fill(ORIGINAL);
    await expect(promptInput(page)).toHaveText(ORIGINAL);
    await toolRunButton(page).click();
    await waitForGeneratedMedia(page, {});
    await page.locator('button[title^="Remix: load this image"]').first().click({ force: true });
    await expect(page.getByRole('button', { name: 'Use Exact Prompt' })).toBeVisible();

    const agentInput = page.locator('#agent-dock textarea, #agent-dock-result textarea').last();
    await agentInput.fill('change the fox to a lynx');
    await agentInput.press('Enter');
    await expect.poll(() => requests).toBe(1);

    await page.getByRole('button', { name: 'Use Exact Prompt' }).click();
    await expect(promptInput(page)).not.toHaveText(ORIGINAL);
    const rendered = await promptInput(page).innerText();
    const settled = page.waitForResponse('**/api/prompt/agent/step');
    answer!();
    await settled;
    await page.waitForTimeout(500);

    await expect(promptInput(page)).toHaveText(rendered);
    expect(requests).toBe(1);
  });
});
