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
  const closedGroups = page.locator('.rc-tree-select-tree-switcher_close');
  let count = await closedGroups.count();
  let attempts = 0;
  while (count > 0 && attempts < 50) {
    await closedGroups.first().click({ force: true });
    await page.waitForTimeout(150);
    count = await closedGroups.count();
    attempts++;
  }
}

async function closeEnvDropdown(page) {
  await page.keyboard.press('Escape');
}

async function openEnv(page, name) {
  await page.locator('.navbar-form .rc-tree-select').first().click();

  const idx = name.indexOf('_');
  const expectedText = idx > 0 ? name.substring(0, idx) : name;

  const tree = page.locator('.rc-tree-select-tree');
  await tree
    .locator(`text=${expectedText}`)
    .first()
    .waitFor({ state: 'visible', timeout: 10000 });

  await expandAllEnvGroups(page);

  await tree.locator(`text=${name}`).first().click({ force: true });
  await closeEnvDropdown(page);
}

module.exports = {
  runDemo,
  closeEnvs,
  expandAllEnvGroups,
  closeEnvDropdown,
  openEnv,
};
