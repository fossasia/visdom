/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

const { spawn, spawnSync } = require('child_process');
const { test, expect } = require('@playwright/test');
const { getPythonExecutable } = require('../support/helpers');

const createScript = `
import sys, numpy as np, visdom
env = sys.argv[1]
viz = visdom.Visdom(port=8098, env=env, raise_exceptions=True)
for i in range(3):
    viz.line(
        X=np.arange(20, dtype=float),
        Y=np.arange(20, dtype=float) + i,
        win='pane%d' % i,
        opts=dict(title='batching %d' % i, width=360, height=280),
    )
viz.save([env])
`;

const appendScript = `
import sys, time, numpy as np, visdom
env, win = sys.argv[1], sys.argv[2]
count, gap = int(sys.argv[3]), float(sys.argv[4])
viz = visdom.Visdom(port=8098, env=env, raise_exceptions=True)
for i in range(count):
    viz.line(
        X=np.array([20.0 + i]),
        Y=np.array([20.0 + i]),
        win=win,
        update='append',
    )
    time.sleep(gap)
`;

const resizeScript = `
import sys, numpy as np, visdom
env, win, height = sys.argv[1], sys.argv[2], int(sys.argv[3])
viz = visdom.Visdom(port=8098, env=env, raise_exceptions=True)
viz.line(
    X=np.arange(20, dtype=float),
    Y=np.arange(20, dtype=float),
    win=win,
    opts=dict(title='batching 0', width=360, height=height),
)
`;

const gridItem = '.layout .react-grid-item';

function newEnv() {
  return `batching_${Math.floor(Math.random() * 1e6)}`;
}

function runPython(script, args) {
  const result = spawnSync(getPythonExecutable(), ['-c', script, ...args], {
    encoding: 'utf-8',
  });
  expect(result.status, result.stderr).toBe(0);
}

function streamPython(script, args) {
  const child = spawn(getPythonExecutable(), ['-c', script, ...args], {
    stdio: 'ignore',
    detached: true,
  });
  child.unref();
  return child;
}

async function openThreePanes(page, env) {
  runPython(createScript, [env]);
  await page.setViewportSize({ width: 1536, height: 900 });
  await page.goto(`/env/${env}`);
  await expect(page.locator(gridItem)).toHaveCount(3);
  await page.waitForTimeout(1500);
}

async function countLayoutWrites(page, env) {
  await page.evaluate((prefix) => {
    window.__layoutWrites = 0;
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (String(key).startsWith(prefix)) window.__layoutWrites += 1;
      return original.call(this, key, value);
    };
  }, `${env}_`);
}

test('appending to one pane does not rewrite every pane layout', async ({
  page,
}) => {
  const env = newEnv();
  await openThreePanes(page, env);
  await countLayoutWrites(page, env);

  runPython(appendScript, [env, 'pane0', '6', '0.15']);
  await page.waitForTimeout(1200);

  expect(await page.evaluate(() => window.__layoutWrites)).toBe(0);
  await expect(page.locator(gridItem)).toHaveCount(3);
});

test('an update that changes a pane height still rewrites the layout', async ({
  page,
}) => {
  const env = newEnv();
  await openThreePanes(page, env);
  const before = await page
    .locator(gridItem)
    .first()
    .evaluate((el) => el.getBoundingClientRect().height);

  await countLayoutWrites(page, env);
  runPython(resizeScript, [env, 'pane0', '520']);

  await expect
    .poll(() => page.evaluate(() => window.__layoutWrites))
    .toBeGreaterThan(0);
  await expect
    .poll(() =>
      page
        .locator(gridItem)
        .first()
        .evaluate((el) => el.getBoundingClientRect().height)
    )
    .toBeGreaterThan(before);
});

test('the title filter still hides panes after an update', async ({ page }) => {
  const env = newEnv();
  await openThreePanes(page, env);

  runPython(appendScript, [env, 'pane0', '3', '0.15']);
  await page.waitForTimeout(600);

  await page.locator('[data-cy=filter]').fill('batching 1');
  await expect
    .poll(() => page.locator('.layout .hidden-window').count())
    .toBe(2);

  await page.locator('[data-cy=filter]').fill('');
  await expect
    .poll(() => page.locator('.layout .hidden-window').count())
    .toBe(0);
});

test('focus still follows a click after an update', async ({ page }) => {
  const env = newEnv();
  await openThreePanes(page, env);

  runPython(appendScript, [env, 'pane0', '3', '0.15']);
  await page.waitForTimeout(600);

  const second = page
    .locator('.layout .window')
    .filter({ hasText: 'batching 1' });
  await second.locator('.bar > div.pull-right').click();
  await expect(second).toHaveClass(/focus/);
  await expect
    .poll(() => page.locator('.layout .window.focus').count())
    .toBe(1);

  const third = page
    .locator('.layout .window')
    .filter({ hasText: 'batching 2' });
  await third.locator('.bar > div.pull-right').click();
  await expect(third).toHaveClass(/focus/);
  await expect
    .poll(() => page.locator('.layout .window.focus').count())
    .toBe(1);
  await expect(page.locator(gridItem)).toHaveCount(3);
});

test('a pane closed while updates stream stays closed', async ({ page }) => {
  const env = newEnv();
  await openThreePanes(page, env);

  streamPython(appendScript, [env, 'pane0', '80', '0.025']);
  await page.waitForTimeout(400);

  await page
    .locator(gridItem)
    .nth(2)
    .locator('.pane-close')
    .click({ force: true });

  await expect(page.locator(gridItem)).toHaveCount(2);
  await page.waitForTimeout(1600);
  await expect(page.locator(gridItem)).toHaveCount(2);
});
