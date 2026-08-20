/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

const { test, expect } = require('@playwright/test');
const path = require('path');

const FIXTURE = path.join(__dirname, '..', 'fixtures', 'test.json');

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

  test('should upload valid JSON, switch environment, and create uploaded_* env', async ({
    page,
  }) => {
    await page.setInputFiles('input[type="file"]', FIXTURE);

    const toast = page.locator('.visdom-toast-message');
    await expect(toast).toBeVisible({ timeout: 10000 });
    await expect(toast).toContainText(/successfully loaded as/i);

    const selectedEnv = page
      .locator(
        '.rc-tree-select-selection-item, .rc-tree-select [title^="uploaded_"]'
      )
      .first();

    await expect(selectedEnv).toBeVisible({ timeout: 10000 });

    const envName =
      (await selectedEnv.getAttribute('title')) ||
      (await selectedEnv.textContent()) ||
      '';

    expect(envName.trim().startsWith('uploaded_')).toBe(true);

    await expect(toast).toContainText(envName.trim());
  });

  test('should reject invalid Visdom JSON structure', async ({ page }) => {
    await page.setInputFiles('input[type="file"]', {
      name: 'bad.json',
      mimeType: 'application/json',
      buffer: Buffer.from(JSON.stringify({ test: 'bar' })),
    });

    const toast = page.locator('.visdom-toast-message');
    await expect(toast).toBeVisible();
    await expect(toast).toContainText('Error: This is not a valid Visdom JSON');
  });
});
