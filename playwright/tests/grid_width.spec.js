/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

const { spawnSync } = require('child_process');
const { test, expect } = require('@playwright/test');
const { getPythonExecutable } = require('../support/helpers');

// three 470px panes fit in one row at 1536px, but only two at 1280px
const script = `
import sys, numpy as np, visdom
viz = visdom.Visdom(port=8098, env=sys.argv[1], raise_exceptions=True)
for i in range(3):
    viz.line(Y=np.arange(5), opts=dict(width=470, height=372, title=str(i)))
`;

test('initial layout uses the measured grid width', async ({ page }) => {
  const env = `gridwidth_${Math.floor(Math.random() * 1e6)}`;
  const result = spawnSync(getPythonExecutable(), ['-c', script, env], {
    encoding: 'utf-8',
  });
  expect(result.status, result.stderr).toBe(0);

  await page.setViewportSize({ width: 1536, height: 900 });
  await page.goto(`/env/${env}`);

  const panes = page.locator('.layout .react-grid-item');
  await expect(panes).toHaveCount(3);
  // let the grid settle (initial width measurement + relayout)
  await page.waitForTimeout(1000);

  const rowCount = () =>
    panes.evaluateAll(
      (els) =>
        new Set(els.map((el) => Math.round(el.getBoundingClientRect().top)))
          .size
    );
  expect(await rowCount()).toBe(1);

  // shrinking the window must repack against the new width
  await page.setViewportSize({ width: 1280, height: 900 });
  await expect.poll(rowCount).toBe(2);
});
