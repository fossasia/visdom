/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

const path = require('path');
const { test, expect } = require('@playwright/test');
const {
  runDemo,
  openEnv,
  waitForPlotRender,
  waitForMathJax,
  screenshotContent,
} = require('../support/helpers');
const {
  allScreenshots,
  allCompareviews,
} = require('../support/screenshots.config');

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

async function prepareDemoForScreenshot(page, run) {
  await runDemo(page, run);

  // ImagePane needs an additional rerender to adjust to the pane size.
  if (run.startsWith('image_')) {
    await page.waitForTimeout(600);
  }

  if (run.startsWith('misc_plot_latex')) {
    await waitForMathJax(page);
  }

  await waitForPlotRender(page);
}

async function openCompareView(page, envs) {
  await page.goto(`/compare/${envs.join('+')}`);
  await page.locator('text=online').first().waitFor({ state: 'visible' });
}

async function setRangeValue(locator, value) {
  await locator.evaluate((range, nextValue) => {
    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      'value'
    ).set;

    nativeInputValueSetter.call(range, String(nextValue));
    range.dispatchEvent(new Event('input', { bubbles: true }));
    range.dispatchEvent(new Event('change', { bubbles: true }));
  }, value);
}

async function changeProperty(page, key, value) {
  const nameCell = page
    .locator('td.table-properties-name')
    .filter({ hasText: key })
    .first();
  const row = nameCell.locator('xpath=..');
  await row.locator('td.table-properties-value input').first().fill(value);
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

      const numRuns = 3;
      const envs = [];

      for (let i = 0; i < numRuns; i++) {
        const env = `${run}_${i}_long_env_name_for_testing`;
        await runDemo(page, run, {
          env,
          open: false,
          seed: 42 + i,
          args: [run],
        });
        envs.push(env);
      }

      await openCompareView(page, envs);
      await waitForPlotRender(page);
      await saveBaseline(page, `compare_${run}`);
    });
  }
});

test.describe('Take screenshot for PlotPane functions', () => {
  test('Screenshot for Line Smoothing', async ({ page }) => {
    test.setTimeout(screenshotTimeout);

    const run = 'line_smoothing';
    const env1 = `${run}_1_long_env_name_for_testing`;
    const env2 = `${run}_2_long_env_name_for_testing`;

    await runDemo(page, 'plot_line_basic', {
      env: env1,
      args: ["'Line smoothing'", 100],
      open: false,
    });
    await runDemo(page, 'plot_line_basic', {
      env: env2,
      args: ["'Line smoothing'", 100],
      seed: 43,
    });
    await openEnv(page, env1);

    await page.locator('button[title="smooth lines"]').first().click();
    await setRangeValue(page.locator('input[type="range"]').first(), 100);
    await waitForPlotRender(page);
    await saveBaseline(page, run);
  });

  test('Screenshot for Property Change (using Line Plot)', async ({ page }) => {
    test.setTimeout(screenshotTimeout);

    await runDemo(page, 'plot_line_basic');
    await expect(page.locator('.layout .window')).toHaveCount(1);
    await page.locator('button[title="properties"]').first().click();

    await changeProperty(page, 'name', 'a line');
    await changeProperty(page, 'type', 'bar');
    await changeProperty(page, 'opacity', '0.75');
    await changeProperty(page, 'marker.line.width', '5');
    await changeProperty(page, 'marker.line.color', '#0FF');

    await changeProperty(page, 'margin.l', '10');
    await changeProperty(page, 'margin.r', '10');
    await changeProperty(page, 'margin.b', '10');
    await changeProperty(page, 'margin.t', '10');
    await changeProperty(page, 'xaxis.type', 'log');

    await page.locator('button[title="properties"]').first().click();
    await waitForPlotRender(page);
    await saveBaseline(page, 'change-properties');
  });
});
