import { test } from '@playwright/test';

/** Tool IDs registered by TestToolProvider */
export const TEST_TOOL_ID = 'test:text-to-image:test-model';
export const TEST_EDIT_TOOL_ID = 'test:image-to-image:test-edit';
export const TEST_UPSCALE_TOOL_ID = 'test:upscale-image:test-upscale';
export const TEST_I2V_TOOL_ID = 'test:image-to-video:test-i2v';
export const TEST_INPAINT_TOOL_ID = 'test:inpaint-image:test-inpaint';
export const TEST_ALT_TOOL_ID = 'test:text-to-image:test-model-alt';

/** URL path for the test text-to-image tool */
export const TEST_TOOL_PATH = `/tools/${TEST_TOOL_ID}`;
export const TEST_ALT_TOOL_PATH = `/tools/${TEST_ALT_TOOL_ID}`;

/**
 * Create a test.describe block that skips if STIMMA_TEST_PROVIDER env var is not set.
 * When running via `stimma test frontend`, this env var is always set.
 */
export function describeWithTestProvider(title: string, fn: () => void) {
  test.describe(title, () => {
    test.skip(
      !process.env.STIMMA_TEST_PROVIDER,
      'Test provider not available (run via: stimma test frontend)',
    );
    fn();
  });
}
