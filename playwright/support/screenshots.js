/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

const { expect } = require('@playwright/test');
const {
  runDemo,
  openEnv,
  waitForPlotRender,
  waitForMathJax,
} = require('./helpers');

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

async function prepareCompareView(page, run) {
  const envs = [];

  for (let i = 0; i < 3; i++) {
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

async function prepareLineSmoothing(page) {
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
}

async function changeProperty(page, key, value) {
  const nameCell = page
    .locator('td.table-properties-name')
    .filter({ hasText: key })
    .first();
  const row = nameCell.locator('xpath=..');
  await row.locator('td.table-properties-value input').first().fill(value);
}

async function preparePropertyChange(page) {
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
}

module.exports = {
  prepareDemoForScreenshot,
  prepareCompareView,
  prepareLineSmoothing,
  preparePropertyChange,
};
