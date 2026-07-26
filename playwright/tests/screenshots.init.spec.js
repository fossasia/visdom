/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

const path = require('path');
const { test } = require('@playwright/test');
const { screenshotContent } = require('../support/helpers');
const {
  allScreenshots,
  allCompareviews,
} = require('../support/screenshots.config');
const {
  prepareDemoForScreenshot,
  prepareCompareView,
  prepareLineSmoothing,
  preparePropertyChange,
} = require('../support/screenshots');

const baselineDir = path.join(
  __dirname,
  '..',
  'screenshots_init',
  'screenshots.init.spec.js'
);
const screenshotTimeout = 120000;

test.use({
  viewport: { width: 1000, height: 660 },
});

test.describe.configure({ mode: 'serial' });

test.beforeEach(async ({ page }) => {
  await page.goto('/');
});

async function saveBaseline(page, name) {
  await screenshotContent(page, path.join(baselineDir, `${name}.png`));
}

test.describe('Take plot screenshots', () => {
  for (const run of allScreenshots) {
    test(`Screenshot for ${run}`, async ({ page }) => {
      test.setTimeout(screenshotTimeout);

      await prepareDemoForScreenshot(page, run);
      await saveBaseline(page, run);
    });
  }
});

test.describe('Take compare-view screenshots', () => {
  for (const run of allCompareviews) {
    test(`Screenshot for ${run}`, async ({ page }) => {
      test.setTimeout(screenshotTimeout);

      await prepareCompareView(page, run);
      await saveBaseline(page, `compare_${run}`);
    });
  }
});

test.describe('Take screenshot for PlotPane functions', () => {
  test('Screenshot for Line Smoothing', async ({ page }) => {
    test.setTimeout(screenshotTimeout);

    await prepareLineSmoothing(page);
    await saveBaseline(page, 'line_smoothing');
  });

  test('Screenshot for Property Change (using Line Plot)', async ({ page }) => {
    test.setTimeout(screenshotTimeout);

    await preparePropertyChange(page);
    await saveBaseline(page, 'change-properties');
  });
});
