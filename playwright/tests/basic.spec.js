/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

const { test, expect } = require('@playwright/test');

test.describe('Test Setup', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('successfully loads', async ({ page }) => {
    await expect(page).toHaveTitle(/Visdom/i);
  });

  test('server is online', async ({ page }) => {
    await expect(page.locator('text=online').first()).toBeVisible();
  });

  test('manual server reconnect', async ({ page }) => {
    await expect(page.locator('text=online').first()).toBeVisible();
    const onlineIndicator = page.locator('text=online').first();
    const offlineIndicator = page.locator('text=offline').first();

    await onlineIndicator.click();
    await expect(offlineIndicator).toBeVisible();

    await offlineIndicator.click();
    await expect(onlineIndicator).toBeVisible();

    await onlineIndicator.click();
    await expect(offlineIndicator).toBeVisible();

    await offlineIndicator.click();
    await expect(onlineIndicator).toBeVisible();

    await onlineIndicator.click();
    await expect(offlineIndicator).toBeVisible();

    await offlineIndicator.click();
    await expect(onlineIndicator).toBeVisible();
  });

  test('tree selection opens & shows main', async ({ page }) => {
    await page.locator('.rc-tree-select').click();
    const tree = page.locator('.rc-tree-select-tree');
    await expect(tree.locator('text=main').first()).toBeVisible();
  });

  test('env selection works', async ({ page }) => {
    const mainTitle = page.locator('.rc-tree-select [title="main"]').first();
    await expect(mainTitle).toBeVisible();

    const mainSelection = page
      .locator('.rc-tree-select')
      .getByText('main')
      .first();
    await mainSelection.hover();
    await page.waitForTimeout(100);

    const removeBtn = page
      .locator('.rc-tree-select .rc-tree-select-selection-item-remove')
      .first();
    await removeBtn.click({ force: true });
    await expect(mainTitle).not.toBeVisible();

    await page.locator('.rc-tree-select').click();
    const tree = page.locator('.rc-tree-select-tree');
    await tree.locator('text=main').first().click();
    await expect(mainTitle).toBeVisible();

    const clearBtn = page.locator('.rc-tree-select-clear').first();
    await clearBtn.click({ force: true });
    await expect(mainTitle).not.toBeVisible();
  });
});
