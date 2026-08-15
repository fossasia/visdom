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

test.describe('Parallel Coordinates Pane', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('parallel_coordinates_basic', async ({ page }) => {
    await runDemo(page, 'plot_special_parallel_coordinates');

    await expect(page.locator('.layout .window')).toHaveCount(1);
    await expect(page.locator('.content')).toContainText(
      'Experiment Comparison'
    );
  });

  test('parallel_coordinates_close', async ({ page }) => {
    await runDemo(page, 'plot_special_parallel_coordinates');

    await page
      .locator('.layout .react-grid-item')
      .first()
      .locator('button[title="close"]')
      .click();

    await expect(page.locator('.layout .window')).toHaveCount(0);
  });
});
