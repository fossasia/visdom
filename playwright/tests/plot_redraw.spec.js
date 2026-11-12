/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

const { test, expect } = require('@playwright/test');
const { runDemo, waitForPlotRender } = require('../support/helpers');

const plotSelector = '.layout .window .plotly-graph-div';

async function countPlotCalls(page) {
  await page.evaluate(() => {
    window.__plotCalls = { react: 0, resize: 0 };
    const react = Plotly.react;
    Plotly.react = function (...args) {
      window.__plotCalls.react += 1;
      return react.apply(this, args);
    };
    const resize = Plotly.Plots.resize;
    Plotly.Plots.resize = function (...args) {
      window.__plotCalls.resize += 1;
      return resize.apply(this, args);
    };
  });
}

const readPlotCalls = (page) => page.evaluate(() => window.__plotCalls);

async function openSmoothing(page, value) {
  await page.locator('.layout .window button[title="smooth lines"]').click();
  const slider = page.locator('.widget input[type="range"]');
  await expect(slider).toBeVisible();
  if (value !== undefined) await slider.fill(value);
  await page.waitForTimeout(800);
}

const openProperty = async (page, key) => {
  await page
    .locator('.layout .window button[title="properties"]')
    .first()
    .click();
  const row = page
    .locator('td.table-properties-name')
    .filter({ hasText: key })
    .first()
    .locator('xpath=..');
  return row.locator('td.table-properties-value input').first();
};

test.describe('plot redraws', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await runDemo(page, 'plot_line_basic');
    await waitForPlotRender(page);
  });

  test('a redraw does not also resize the plot', async ({ page }) => {
    await openSmoothing(page, '20');
    await countPlotCalls(page);

    await page.locator('.widget input[type="range"]').fill('40');
    await page.waitForTimeout(800);

    const calls = await readPlotCalls(page);
    expect(calls.react).toBeGreaterThan(0);
    expect(calls.resize).toBe(0);
  });

  test('resizing the pane still resizes the plot', async ({ page }) => {
    await countPlotCalls(page);

    await page.setViewportSize({ width: 820, height: 620 });
    await page.waitForTimeout(800);

    const calls = await readPlotCalls(page);
    expect(calls.resize).toBeGreaterThan(0);
  });

  test('typing a note does not redraw the plot', async ({ page }) => {
    await page.locator(plotSelector).first().hover();
    await page
      .locator('.modebar-btn[data-title="annotate points"]')
      .click({ force: true });

    await page.evaluate((selector) => {
      const graph = document.querySelector(selector);
      const trace = graph._fullData[0];
      graph.emit('plotly_click', {
        points: [{ x: trace.x[0], y: trace.y[0], fullData: trace }],
        event: { clientX: 120, clientY: 120 },
      });
    }, plotSelector);

    const note = page.locator('.annotate-editor input');
    await expect(note).toBeVisible();
    await page.waitForTimeout(800);
    await countPlotCalls(page);

    await note.pressSequentially('converged', { delay: 20 });
    await page.waitForTimeout(800);

    await expect(note).toHaveValue('converged');
    const calls = await readPlotCalls(page);
    expect(calls.react).toBe(0);
  });

  test('editing a property redraws the plot', async ({ page }) => {
    await countPlotCalls(page);

    const value = await openProperty(page, 'type');
    await value.fill('bar');
    await value.press('Enter');
    await page.waitForTimeout(800);

    const calls = await readPlotCalls(page);
    expect(calls.react).toBeGreaterThan(0);
    await expect
      .poll(() =>
        page.evaluate(
          (selector) => document.querySelector(selector)._fullData[0].type,
          plotSelector
        )
      )
      .toBe('bar');
  });

  test('a numeric property stays a number', async ({ page }) => {
    const value = await openProperty(page, 'marker.line.width');
    await value.fill('5');
    await value.press('Enter');
    await page.waitForTimeout(800);

    const width = await page.evaluate(
      (selector) => document.querySelector(selector).data[0].marker.line.width,
      plotSelector
    );
    expect(width).toBe(5);
  });

  test('a rejected numeric property edit restores the editor', async ({
    page,
  }) => {
    const value = await openProperty(page, 'marker.line.width');
    await value.fill('5');
    await value.press('Enter');
    await page.waitForTimeout(800);

    await value.fill('');
    await value.press('Enter');
    await page.waitForTimeout(800);

    await expect(value).toHaveValue('5');
    const width = await page.evaluate(
      (selector) => document.querySelector(selector).data[0].marker.line.width,
      plotSelector
    );
    expect(width).toBe(5);
  });

  test('a resize while the plot redraws still ends at the pane size', async ({
    page,
  }) => {
    await page
      .locator('.layout .window button[title="smooth lines"]')
      .first()
      .click();
    await page.setViewportSize({ width: 780, height: 600 });
    await page.waitForTimeout(1500);

    const sizes = await page.evaluate((selector) => {
      const graph = document.querySelector(selector);
      return { drawn: graph._fullLayout.width, pane: graph.clientWidth };
    }, plotSelector);
    expect(Math.abs(sizes.drawn - sizes.pane)).toBeLessThanOrEqual(2);
  });

  test('the smoothed overlay reuses the plotted x data', async ({ page }) => {
    const before = await page.evaluate(
      (selector) => document.querySelector(selector).data[0].y.slice(),
      plotSelector
    );

    await openSmoothing(page, '40');

    const shared = await page.evaluate((selector) => {
      const traces = document.querySelector(selector).data;
      for (let i = 0; i < traces.length; i++) {
        for (let j = i + 1; j < traces.length; j++) {
          if (traces[i].x && traces[i].x === traces[j].x) {
            return {
              sharesX: true,
              ownY: traces[i].y !== traces[j].y,
              sourceY: traces[i].y.slice(),
            };
          }
        }
      }
      return { sharesX: false };
    }, plotSelector);

    expect(shared.sharesX).toBe(true);
    expect(shared.ownY).toBe(true);
    expect(shared.sourceY).toEqual(before);
  });
});
