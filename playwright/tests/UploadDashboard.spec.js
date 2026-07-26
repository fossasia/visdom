/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

const { test, expect } = require('@playwright/test');

test.describe('Visdom - Upload Dashboard JSON Feature', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.visdom-title')).toBeVisible({ timeout: 15000 });
  });

  test('should display Upload JSON button', async ({ page }) => {
    await expect(
      page.locator('button[aria-label="Upload JSON file"]')
    ).toBeVisible();
  });

  test('should reject non-JSON files', async ({ page }) => {
    await page.setInputFiles('input[type="file"]', {
      name: 'test.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('This is not json'),
    });

    const toast = page.locator('.visdom-toast-message');
    await expect(toast).toBeVisible();
    await expect(toast).toContainText(/json/i);
  });
});
