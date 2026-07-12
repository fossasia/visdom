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
  const count = await clearButton.count();
  for (let i = 0; i < count; i++) {
    await clearButton.nth(i).click({ force: true });
  }
}

async function expandAllEnvGroups(page) {
  // Scope to the visible popup container so we only expand switchers that are
  // actually inside the open dropdown, not stale/hidden ones elsewhere in the DOM.
  const popup = page.locator('.rc-tree-select-dropdown:visible');
  const closedGroups = popup.locator('.rc-tree-select-tree-switcher_close');
  let count = await closedGroups.count();
  let attempts = 0;
  while (count > 0 && attempts < 50) {
    await closedGroups.first().click();
    await page.waitForTimeout(150);
    count = await closedGroups.count();
    attempts++;
  }
}

async function closeEnvDropdown(page) {
  // Click the trigger only if the dropdown is still open, to avoid toggling it
  // back open. The trigger has class rc-tree-select-open when the popup is visible.
  const trigger = page.locator('.navbar-form .rc-tree-select').first();
  const isOpen = await trigger.evaluate((el) =>
    el.classList.contains('rc-tree-select-open')
  );
  if (isOpen) {
    await trigger.click();
  }
}

async function openEnv(page, name) {
  // Only open the dropdown if it is not already open. Unconditionally clicking
  // a tree-select that is already open toggles it closed, which then causes
  // the group-wait and item-click below to target a hidden popup.
  const trigger = page.locator('.navbar-form .rc-tree-select').first();
  const isOpen = await trigger.evaluate((el) =>
    el.classList.contains('rc-tree-select-open')
  );
  if (!isOpen) {
    await trigger.click();
  }

  const idx = name.indexOf('_');
  const expectedText = idx > 0 ? name.substring(0, idx) : name;

  // Wait for the popup to be visible and for the group/root node to appear.
  // This targets the popup container directly so we don't match selection tags
  // that contain the same text in the closed trigger area.
  const popup = page.locator('.rc-tree-select-dropdown');
  await popup.waitFor({ state: 'visible', timeout: 10000 });
  await popup
    .locator(`text=${expectedText}`)
    .first()
    .waitFor({ state: 'visible', timeout: 10000 });

  await expandAllEnvGroups(page);

  await popup.locator(`text=${name}`).first().click();
  await closeEnvDropdown(page);
}

module.exports = {
  runDemo,
  closeEnvs,
  expandAllEnvGroups,
  closeEnvDropdown,
  openEnv,
};
