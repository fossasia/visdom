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

test.describe('Misc Tests', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('plot_special_graph', async ({ page }) => {
    await runDemo(page, 'plot_special_graph');

    await expect(page.locator('svg line')).toHaveCount(6);
    await expect(page.locator('svg path')).toHaveCount(6);
    await expect(page.locator('svg text')).toHaveCount(12);
    await expect(page.locator('svg g')).toHaveCount(6);
  });
});
