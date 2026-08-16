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

const winSelector = '.layout .react-grid-item';
const windowSelector = '.layout .window';
const resizedSize = { height: 410, width: 307 };

const paneCases = [
  {
    type: 'TextPane',
    demo: 'text_basic',
    targetX: 263,
    size: { height: 290, width: 244 },
  },
  {
    type: 'ImagePane',
    demo: 'image_basic',
    targetX: 276,
    size: { height: 545, width: 256 },
    resetSize: { height: 545, width: 256 },
  },
  { type: 'Line Plot', demo: 'plot_line_basic' },
  { type: 'Bar Plot', demo: 'plot_bar_basic' },
  { type: 'Scatter Plot', demo: 'plot_scatter_basic' },
  { type: 'Surface Plot', demo: 'plot_surface_basic' },
  { type: 'ROC Curve', demo: 'plot_roc_curve' },
  { type: 'PR Curve', demo: 'plot_pr_curve' },
  { type: 'Box Plot', demo: 'plot_special_boxplot' },
  { type: 'Quiver Plot', demo: 'plot_special_quiver' },
  { type: 'Violin Plot', demo: 'plot_violin_basic' },
  {
    type: 'Graph Plot',
    demo: 'plot_special_graph',
    targetX: 520,
    size: { height: 515, width: 500 },
    resetSize: { height: 515, width: 500 },
  },
  { type: 'Sankey Plot', demo: 'plot_special_sankey' },
  { type: 'Learning Curve', demo: 'plot_line_learning_curve' },
  {
    type: 'Matplotlib Plot',
    demo: 'misc_plot_matplot',
    targetX: 10,
    size: { height: 500, width: 622 },
    resetSize: { height: 500, width: 622 },
  },
  { type: 'Latex Plot', demo: 'misc_plot_latex' },
  {
    type: 'Video Pane',
    demo: 'misc_video_tensor',
    targetX: 263,
    size: { height: 290, width: 244 },
    resetSize: { height: 290, width: 244 },
  },
  {
    type: 'Properties Pane',
    demo: 'properties_basic',
    targetX: 263,
    size: { height: 290, width: 244 },
  },
  {
    type: 'HTML Table',
    demo: 'html_table',
    targetX: 263,
    size: { height: 290, width: 244 },
  },
  {
    type: 'Table',
    demo: 'table',
    targetX: 391,
    size: { height: 290, width: 370 },
  },
  { type: 'Confusion Matrix', demo: 'plot_confusion_matrix_basic' },
].map((paneCase) => {
  const size = paneCase.size || { height: 350, width: 370 };
  return {
    targetX: 390,
    resetSize: size,
    ...paneCase,
    size,
  };
});

function firstPane(page) {
  return page.locator(winSelector).first();
}

async function dragMouse(page, locator, deltaX, deltaY = 0) {
  const box = await locator.boundingBox();
  if (!box) {
    throw new Error('Unable to find element box for drag target.');
  }

  const startX = box.x + box.width / 2;
  const startY = box.y + box.height / 2;
  await page.mouse.move(startX, startY);
  await page.mouse.down();
  await page.mouse.move(startX + deltaX, startY + deltaY, { steps: 16 });
  await page.mouse.up();
}

async function resizePane(page, pane, deltaX, deltaY) {
  const handle = pane.locator('.react-resizable-handle').first();
  const box = await handle.boundingBox();
  if (!box) {
    throw new Error('Unable to find pane resize handle.');
  }

  const startX = box.x + box.width / 2;
  const startY = box.y + box.height / 2;
  await page.mouse.move(startX, startY);
  await page.mouse.down();
  await page.mouse.move(startX + deltaX, startY + deltaY, { steps: 8 });
  await page.mouse.up();
}

async function getPaneTranslate(pane) {
  return pane.evaluate((element) => {
    const transform = window.getComputedStyle(element).transform;
    if (!transform || transform === 'none') {
      return { x: 0, y: 0 };
    }

    const matrix = transform.match(/^matrix\((.+)\)$/);
    if (matrix) {
      const values = matrix[1].split(',').map(Number);
      return { x: values[4], y: values[5] };
    }

    const matrix3d = transform.match(/^matrix3d\((.+)\)$/);
    if (matrix3d) {
      const values = matrix3d[1].split(',').map(Number);
      return { x: values[12], y: values[13] };
    }

    throw new Error(`Unexpected transform value: ${transform}`);
  });
}

async function expectPaneTranslate(pane, expectedX, expectedY) {
  await expect
    .poll(async () => {
      const { x, y } = await getPaneTranslate(pane);
      return Math.abs(x - expectedX) + Math.abs(y - expectedY);
    })
    .toBeLessThanOrEqual(1);
}

async function expectPaneSize(pane, size, tolerance = 2) {
  await expect
    .poll(async () => {
      const currentSize = await pane.evaluate((element) => {
        const style = window.getComputedStyle(element);
        return {
          height: parseFloat(style.height),
          width: parseFloat(style.width),
        };
      });
      return (
        Math.abs(currentSize.height - size.height) +
        Math.abs(currentSize.width - size.width)
      );
    })
    .toBeLessThanOrEqual(tolerance);
}

test.describe('Test Pane Actions', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  for (const paneCase of paneCases) {
    test(`Pane actions on ${paneCase.type}`, async ({ page }) => {
      test.setTimeout(90000);

      await test.step(`Open Single ${paneCase.type}`, async () => {
        await runDemo(page, paneCase.demo);
        await expect(page.locator(windowSelector)).toHaveCount(1);
      });

      await test.step('Open Some More Panes', async () => {
        const env = `${paneCase.demo}_${Math.floor(Math.random() * 1e6)}`;
        await runDemo(page, paneCase.demo, { env: env, open: false });
        await runDemo(page, paneCase.demo, { env: env, open: false });
        await runDemo(page, paneCase.demo, { env: env, open: false });
        await runDemo(page, paneCase.demo, { env: env });
        await expect(page.locator(windowSelector)).toHaveCount(4);
      });

      await test.step('Drag & Drop Pane to 2nd Position', async () => {
        const pane = firstPane(page);
        await expectPaneTranslate(pane, 10, 10);
        await dragMouse(page, pane.locator('.bar').first(), 600);
        await page.locator('[title="Repack"]').click();
        await expectPaneTranslate(pane, paneCase.targetX, 10);
      });

      await test.step('Check Pane Size', async () => {
        const tolerance = paneCase.demo === 'misc_plot_latex' ? 12 : 2;
        await expectPaneSize(firstPane(page), paneCase.size, tolerance);
      });

      await test.step('Resize Pane', async () => {
        const pane = firstPane(page);
        await resizePane(
          page,
          pane,
          resizedSize.width - paneCase.size.width,
          resizedSize.height - paneCase.size.height
        );

        const tolerance = paneCase.demo === 'misc_plot_latex' ? 12 : 2;
        await expectPaneSize(pane, resizedSize, tolerance);
      });

      await test.step('Resize Pane Reset', async () => {
        const pane = firstPane(page);
        await pane.locator('.react-resizable-handle').first().dblclick();

        const tolerance = paneCase.demo === 'misc_plot_latex' ? 12 : 2;
        await expectPaneSize(pane, paneCase.resetSize, tolerance);
      });

      await test.step('Close Pane', async () => {
        await firstPane(page).locator('button[title="close"]').click();
        await expect(page.locator(winSelector)).toHaveCount(3);
      });
    });
  }
});

test.describe('Test Pane Filter', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('filters panes by plain text and regex', async ({ page }) => {
    const env = `pane_basic_${Math.floor(Math.random() * 1e6)}`;
    const filter = page.locator('[data-cy="filter"]');
    const visibleWindows = page.locator(`${windowSelector}:visible`);

    await runDemo(page, 'text_basic', {
      env: env,
      open: false,
      args: ['"pane1 tag1"'],
    });
    await runDemo(page, 'text_basic', {
      env: env,
      open: false,
      args: ['"pane2 tag1 tag2"'],
    });
    await runDemo(page, 'text_basic', {
      env: env,
      open: false,
      args: ['"pane3 tag2"'],
    });
    await runDemo(page, 'text_basic', {
      env: env,
      args: ['"pane4 tag2"'],
    });
    await expect(page.locator(windowSelector)).toHaveCount(4);

    await filter.fill('tag1', { force: true });
    await expect(visibleWindows).toHaveCount(2);

    await filter.fill('tag2', { force: true });
    await expect(visibleWindows).toHaveCount(3);

    await filter.fill('pane3', { force: true });
    await expect(visibleWindows).toHaveCount(1);

    await filter.fill('pane3|pane2', { force: true });
    await expect(visibleWindows).toHaveCount(2);
  });
});
