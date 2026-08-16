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

    const chart = page.locator('.content').first();

    await expect(chart.locator('svg line')).toHaveCount(6);
    await expect(chart.locator('svg path')).toHaveCount(6);
    await expect(chart.locator('svg text')).toHaveCount(12);
    await expect(chart.locator('svg g')).toHaveCount(6);
  });
});
