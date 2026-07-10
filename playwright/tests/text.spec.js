/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

const { test, expect } = require('@playwright/test');
const { runDemo } = require('../support/helpers');

test.describe('Text Pane', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('text_basic', async ({ page }) => {
    await runDemo(page, 'text_basic');
    const pane = page.locator('.layout .react-grid-item').first();
    await expect(pane).toContainText('Hello World!');
  });

  test('text_update', async ({ page }) => {
    await runDemo(page, 'text_update');
    const pane = page.locator('.layout .react-grid-item').first();
    await expect(pane).toContainText('Hello World! More text should be here');
    await expect(pane).toContainText('And here it is');
  });

  test('check download button', async ({ page }) => {
    await runDemo(page, 'text_update');
    const pane = page.locator('.layout .react-grid-item').first();
    const saveBtn = pane.locator('button[title="save"]').first();

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      saveBtn.click(),
    ]);

    expect(download.suggestedFilename()).toBe('visdom_text.txt');
  });

  test('text_callbacks', async ({ page }) => {
    await runDemo(page, 'text_callbacks', { asyncrun: true });

    const content = page.locator('.window .content').first();
    await content.waitFor({ state: 'visible' });

    const bar = page.locator('.bar').first();
    await bar.click();

    const layoutWrapper = page.locator('.no-focus');

    const text = 'checking callback :(';
    for (let char of text) {
      await layoutWrapper.focus();
      await page.keyboard.type(char);
      await page.waitForTimeout(50);
    }

    await layoutWrapper.focus();
    await page.keyboard.press('Backspace');
    await page.waitForTimeout(50);

    await layoutWrapper.focus();
    await page.keyboard.type(')');

    await expect(content).toContainText('checking callback :)');
  });

  test('text_close', async ({ page }) => {
    await runDemo(page, 'text_close');
    await expect(page.locator('.layout .window')).toHaveCount(0);
  });
});
