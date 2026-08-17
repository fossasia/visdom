/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

const { test, expect } = require('@playwright/test');
const {
  allScreenshots,
  allCompareviews,
  screenshotOptions,
  compareScreenshotOptions,
} = require('../support/screenshots.config');
const {
  prepareDemoForScreenshot,
  prepareCompareView,
  prepareLineSmoothing,
  preparePropertyChange,
} = require('../support/screenshots');

const screenshotTimeout = 120000;

test.use({
  viewport: { width: 1000, height: 660 },
});

test.describe.configure({ mode: 'serial' });

test.beforeEach(async ({ page }) => {
  await page.goto('/');
});

async function compareScreenshot(page, name, options = {}) {
  const content = page.locator('.content').first();
  await expect(content).toHaveScreenshot([`${name}.png`], {
    animations: 'allow',
    threshold: 0,
    timeout: 20000,
    ...options,
  });
}

test.describe('Compare with previous plot screenshots', () => {
  for (const run of allScreenshots) {
    test(`Compare screenshot of ${run}`, async ({ page }) => {
      test.setTimeout(screenshotTimeout);

      await prepareDemoForScreenshot(page, run);
      await compareScreenshot(page, run, screenshotOptions[run]);
    });
  }
});

test.describe('Compare with compare-view screenshots', () => {
  for (const run of allCompareviews) {
    test(`Compare screenshot for ${run}`, async ({ page }) => {
      test.setTimeout(screenshotTimeout);

      await prepareCompareView(page, run);
      await compareScreenshot(
        page,
        `compare_${run}`,
        compareScreenshotOptions[run]
      );
    });
  }
});

test.describe('Compare screenshots for PlotPane functions', () => {
  test('Compare screenshot for Line Smoothing', async ({ page }) => {
    test.setTimeout(screenshotTimeout);

    await prepareLineSmoothing(page);
    await compareScreenshot(page, 'line_smoothing', { maxDiffPixels: 200 });
  });

  test('Compare screenshot for Property Change', async ({ page }) => {
    test.setTimeout(screenshotTimeout);

    await preparePropertyChange(page);
    await compareScreenshot(page, 'change-properties');
  });
});
