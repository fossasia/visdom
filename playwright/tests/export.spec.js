/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

const { test, expect } = require('@playwright/test');
const { runDemo, closeEnvs } = require('../support/helpers');

const EXPORT_BUTTON = 'button[aria-label="Export as HTML"]';

async function stubBlobCapture(page) {
  await page.evaluate(() => {
    window.__exportedBlob = null;
    const original = URL.createObjectURL.bind(URL);
    URL.createObjectURL = (blob) => {
      window.__exportedBlob = blob;
      return 'blob:fake-url-for-testing';
    };
    window.__restoreCreateObjectURL = () => {
      URL.createObjectURL = original;
    };
  });
}

async function readCapturedHtml(page) {
  return page.evaluate(async () => {
    if (!window.__exportedBlob) {
      throw new Error('__exportedBlob was not set — export did not fire');
    }
    return window.__exportedBlob.text();
  });
}

test.describe('Test Export Env as HTML', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('online').first()).toBeVisible();
  });

  test('export button is disabled when no env is open', async ({ page }) => {
    await expect(page.locator('.rc-tree-select-clear')).toBeVisible();
    await closeEnvs(page);
    await expect(page.locator(EXPORT_BUTTON)).toBeDisabled();
  });

  test('downloads a valid HTML file when panes are available', async ({
    page,
  }) => {
    const env = `export_test_${Math.floor(Math.random() * 1e6)}`;
    await runDemo(page, 'text_basic', { env });
    await expect(page.locator('.layout .window')).toHaveCount(1);

    await stubBlobCapture(page);
    const exportBtn = page.locator(EXPORT_BUTTON);
    await expect(exportBtn).toBeEnabled();
    await exportBtn.click();

    const html = await readCapturedHtml(page);
    expect(html).toContain('<!DOCTYPE html>');
    expect(html).toContain('id="board"');
    expect(html).toContain('plotly');
    expect(html).toContain('const DATA =');
    expect(html).toContain('const IDS  =');
    expect(html).toContain(env);
  });

  test('exported HTML contains pane data for plot', async ({ page }) => {
    const env = `export_content_${Math.floor(Math.random() * 1e6)}`;
    await runDemo(page, 'plot_line_basic', { env });
    await expect(page.locator('.layout .window')).toHaveCount(1);

    await stubBlobCapture(page);
    await page.locator(EXPORT_BUTTON).click();

    const html = await readCapturedHtml(page);
    expect(html).toContain('"type"');
    expect(html).toContain('"data"');
    expect(html).toContain(env);
  });

  test('shows toast notification when all panes are closed before export', async ({
    page,
  }) => {
    const env = `export_empty_${Math.floor(Math.random() * 1e6)}`;
    await runDemo(page, 'text_basic', { env });
    await expect(page.locator('.layout .window')).toHaveCount(1);

    await page
      .locator('.layout .react-grid-item')
      .first()
      .locator('button[title="close"]')
      .click();
    await expect(page.locator('.layout .react-grid-item')).toHaveCount(0);

    await page.locator(EXPORT_BUTTON).click();

    const toast = page.locator('.visdom-toast');
    await expect(toast).toBeVisible();
    await expect(toast).toContainText('No panes available to export.');
  });
});
