/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

const { spawn, spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const { expect } = require('@playwright/test');

function getPythonExecutable() {
  const isWin = process.platform === 'win32';
  const pyRelativePath = isWin ? ['Scripts', 'python.exe'] : ['bin', 'python'];
  const fallback = isWin ? 'python' : 'python3';

  if (process.env.VIRTUAL_ENV) {
    return path.join(process.env.VIRTUAL_ENV, ...pyRelativePath);
  }
  const rootDir = path.join(__dirname, '..', '..');
  const localVenv = path.join(rootDir, '.venv', ...pyRelativePath);
  if (fs.existsSync(localVenv)) {
    return localVenv;
  }
  const localVenvAlt = path.join(rootDir, 'venv', ...pyRelativePath);
  if (fs.existsSync(localVenvAlt)) {
    return localVenvAlt;
  }
  return fallback;
}

async function runDemo(page, name, opts = {}) {
  const saveto = opts.env || `${name}_${Math.floor(Math.random() * 1e6)}`;

  const spawnArgs = [
    'example/demo.py',
    '-testing',
    '-port',
    '8098',
    '-run',
    name,
    '-env',
    saveto,
  ];
  if (opts.seed !== undefined) {
    spawnArgs.push('-seed', String(opts.seed));
  }
  if (opts.args && opts.args.length > 0) {
    spawnArgs.push('-args', ...opts.args.map(String));
  }

  const pythonBin = getPythonExecutable();

  if (opts.asyncrun) {
    const child = spawn(pythonBin, spawnArgs, {
      stdio: 'ignore',
      detached: true,
    });
    child.unref();
  } else {
    const result = spawnSync(pythonBin, spawnArgs, {
      stdio: 'pipe',
      encoding: 'utf-8',
    });
    if (result.status !== 0) {
      throw new Error(
        `Failed to run demo '${name}'. Exit code: ${result.status}.\nStderr: ${result.stderr}\nStdout: ${result.stdout}`
      );
    }
  }

  if (opts.open === undefined || opts.open) {
    await closeEnvs(page);
    await openEnv(page, saveto);
  }

  return saveto;
}

async function closeEnvs(page) {
  const clearButton = page.locator('.navbar-form .rc-tree-select-clear');

  try {
    await clearButton.first().waitFor({ state: 'attached', timeout: 10000 });
  } catch (error) {
    if ((await clearButton.count()) === 0) {
      return;
    }
    throw error;
  }

  const count = await clearButton.count();
  for (let i = 0; i < count; i++) {
    await clearButton.nth(i).click({ force: true });
  }
}

async function expandAllEnvGroups(page) {
  const closedGroups = page.locator(
    '.rc-tree-select-tree-switcher_close:visible'
  );
  let count = await closedGroups.count();
  let attempts = 0;
  while (count > 0 && attempts < 50) {
    const countBeforeClick = count;
    await closedGroups.first().click({ force: true });
    await expect
      .poll(() => closedGroups.count(), { timeout: 150 })
      .not.toBe(countBeforeClick)
      .catch(() => {});
    count = await closedGroups.count();
    attempts++;
  }
}

async function closeEnvDropdown(page) {
  const dropdown = page.locator(
    '.rc-tree-select-dropdown:not(.rc-tree-select-dropdown-hidden)'
  );
  if (await dropdown.isVisible()) {
    await page
      .locator('.navbar-form .rc-tree-select')
      .first()
      .click({ position: { x: 5, y: 10 }, force: true });
    try {
      await dropdown.waitFor({ state: 'hidden', timeout: 1000 });
    } catch (e) {
      await page.keyboard.press('Escape');
      await dropdown
        .waitFor({ state: 'hidden', timeout: 2000 })
        .catch(() => {});
    }
  }
}

async function openEnv(page, name) {
  const dropdown = page.locator(
    '.rc-tree-select-dropdown:not(.rc-tree-select-dropdown-hidden)'
  );
  if (!(await dropdown.isVisible())) {
    await page
      .locator('.navbar-form .rc-tree-select')
      .first()
      .click({ position: { x: 5, y: 10 }, force: true });
    try {
      await dropdown.waitFor({ state: 'visible', timeout: 1000 });
    } catch (e) {
      await page
        .locator('.navbar-form .rc-tree-select')
        .first()
        .click({ position: { x: 5, y: 10 }, force: true });
      await dropdown.waitFor({ state: 'visible', timeout: 5000 });
    }
  }

  const idx = name.indexOf('_');
  const expectedText = idx > 0 ? name.substring(0, idx) : name;

  const tree = page.locator('.rc-tree-select-tree');
  await tree
    .getByText(expectedText, { exact: true })
    .first()
    .waitFor({ state: 'visible', timeout: 10000 });

  await expandAllEnvGroups(page);

  await tree
    .getByText(name, { exact: true })
    .first()
    .waitFor({ state: 'visible', timeout: 10000 });

  await tree.getByText(name, { exact: true }).first().click({ force: true });
  await closeEnvDropdown(page);
}

async function installPlotRenderObserver(page) {
  await page.addInitScript(() => {
    const hookDiv = (div) => {
      if (typeof div.on !== 'function') return; // Plotly hasn't initialized this div yet

      const bump = () => {
        const n = parseInt(
          div.getAttribute('data-plotly-render-count') || '0',
          10
        );
        div.setAttribute('data-plotly-render-count', String(n + 1));
      };

      if (div.__plotlyListener && typeof div.removeListener === 'function') {
        div.removeListener('plotly_afterplot', div.__plotlyListener);
      }
      div.__plotlyListener = bump;
      div.on('plotly_afterplot', div.__plotlyListener);
    };

    const scan = () => {
      document.querySelectorAll('.js-plotly-plot').forEach(hookDiv);
    };

    const observer = new MutationObserver(scan);
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
    });

    const retryLoop = () => {
      scan();
      requestAnimationFrame(retryLoop);
    };
    retryLoop();
  });
}

async function waitForPlotRender(page) {
  const content = page.locator('.content').first();
  await content.waitFor({ state: 'visible', timeout: 20000 });

  const plotDiv = content.locator('.js-plotly-plot').first();
  if ((await plotDiv.count()) === 0) {
    return;
  }

  const before = parseInt(
    (await plotDiv.getAttribute('data-plotly-render-count')) || '0',
    10
  );

  await expect
    .poll(
      async () =>
        parseInt(
          (await plotDiv.getAttribute('data-plotly-render-count')) || '0',
          10
        ),
      { timeout: 20000 }
    )
    .toBeGreaterThan(before);
}

async function waitForMathJax(page) {
  await page.waitForTimeout(2000);
  await page.evaluate(async () => {
    if (window.MathJax && window.MathJax.Hub) {
      await new Promise((resolve) => {
        window.MathJax.Hub.Queue(() => resolve());
      });
    }

    if (document.fonts && document.fonts.ready) {
      await document.fonts.ready;
    }
  });
  await page.waitForTimeout(2000);
}

async function screenshotContent(page, screenshotPath) {
  fs.mkdirSync(path.dirname(screenshotPath), { recursive: true });

  const content = page.locator('.content').first();
  await content.waitFor({ state: 'visible', timeout: 20000 });
  await content.screenshot({ path: screenshotPath });
}

module.exports = {
  runDemo,
  closeEnvs,
  expandAllEnvGroups,
  closeEnvDropdown,
  openEnv,
  installPlotRenderObserver,
  waitForPlotRender,
  waitForMathJax,
  screenshotContent,
};
