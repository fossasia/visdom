/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

const { test, expect } = require('@playwright/test');
const {
  runDemo,
  closeEnvs,
  openEnv,
  expandAllEnvGroups,
  closeEnvDropdown,
} = require('../support/helpers');

const envmodal = 'div[aria-label="Environment Management Modal"] ';
const envbutton = 'button[data-original-title="Manage Environments"] ';
const viewmodal = 'div[aria-label="Layout Views Management Modal"] ';
const viewbutton = 'button[data-original-title="Manage Views"] ';
const viewselect = 'div[aria-label="View:"] ';

async function dragMouse(page, locator, clientX, clientY) {
  const box = await locator.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(clientX, clientY);
  await page.mouse.up();
}

function paneByTitle(page, title) {
  return page.locator('.react-grid-item').filter({
    has: page.locator('.bar .pull-right', { hasText: title }),
  });
}

test.describe.serial('Test Env Modal', () => {
  const env = 'text_fork_' + Math.floor(Math.random() * 1e6);

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('Env Modal opens & closes', async ({ page }) => {
    await expect(page.locator(envmodal)).toHaveCount(0);
    await page.locator(envbutton).click();
    await expect(page.locator(envmodal)).toBeVisible();
    await page.locator(envmodal).press('Escape');
    await expect(page.locator(envmodal)).toHaveCount(0);
  });

  test('Env Modal forks envs', async ({ page }) => {
    // initialize any env
    await runDemo(page, 'text_fork_part1', { env: env });
    await expect(
      page.locator('.layout .react-grid-item').first()
    ).toContainText('This text will change. Fork to the rescue!');

    // fork the env at this point
    await page.locator(envbutton).click();
    const forkInput = page.locator(envmodal + 'input[type="text"]');
    const currentEnvName = await forkInput.inputValue();
    await forkInput.fill(currentEnvName + '_fork');
    await page.locator('button', { hasText: 'fork' }).click();
    await page.locator(envmodal).press('Escape');

    // apply a change to the same env
    await runDemo(page, 'text_fork_part2', { env: env });
    await expect(
      page.locator('.layout .react-grid-item').first()
    ).toContainText('Changed text.');

    // create a second fork for batch delete testing
    await page.locator(envbutton).click();
    await page.locator(envmodal + 'input[type="text"]').fill(env + '_fork2');
    await page.locator('button', { hasText: 'fork' }).click();
    await page.locator(envmodal).press('Escape');

    // check if fork is still the old one
    await closeEnvs(page);
    await openEnv(page, env + '_fork');
    await expect(
      page.locator('.layout .react-grid-item').first()
    ).toContainText('This text will change. Fork to the rescue!');

    // check again original just to be sure
    await closeEnvs(page);
    await openEnv(page, env);
    await expect(
      page.locator('.layout .react-grid-item').first()
    ).toContainText('Changed text.');
  });

  test('Remove Env', async ({ page }) => {
    // batch delete both forks at once
    await page.locator(envbutton).click();
    await page
      .locator(envmodal + `input[type="checkbox"][value="${env}_fork"]`)
      .check();
    await page
      .locator(envmodal + `input[type="checkbox"][value="${env}_fork2"]`)
      .check();
    await page.locator('button', { hasText: 'Delete Selected' }).click();
    await expect(page.locator(envmodal)).toHaveCount(0);

    // wait for polling cycle to deliver env_update (polling interval is 500ms)
    await page.waitForTimeout(1500);

    // check that both forks do not exist anymore, but original env still exists
    await page.locator('.rc-tree-select').click();
    await expandAllEnvGroups(page);
    const tree = page.locator('.rc-tree-select-tree');
    await expect(tree.locator(`span[title="${env}"]`)).toBeVisible();
    await expect(tree.locator(`span[title="${env}_fork"]`)).toHaveCount(0);
    await expect(tree.locator(`span[title="${env}_fork2"]`)).toHaveCount(0);
    await closeEnvDropdown(page);
  });
});

test.describe.serial('Test View Modal', () => {
  let env;

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('View Modal opens & closes', async ({ page }) => {
    await expect(page.locator(viewmodal)).toHaveCount(0);
    await expect(page.locator(viewbutton)).toBeEnabled();
    await page.locator(viewbutton).click();
    await expect(page.locator(viewmodal)).toBeVisible();
    await page.locator(viewmodal).press('Escape');
    await expect(page.locator(viewmodal)).toHaveCount(0);
  });

  test('View Modal save view', async ({ page }) => {
    env = 'view_modal_' + Math.floor(Math.random() * 1e6);

    // initialize any env
    await runDemo(page, 'text_basic', { env: env, args: ['"Text Pane"'] });
    await page.waitForTimeout(500);
    await runDemo(page, 'image_basic', { env: env, open: false });
    await page.waitForTimeout(500);
    await runDemo(page, 'plot_line_basic', {
      env: env,
      open: false,
      args: ['"Line Plot"'],
    });
    await page.waitForTimeout(500);
    await runDemo(page, 'plot_bar_basic', {
      env: env,
      open: false,
      args: ['"Bar Plot"'],
    });
    await page.waitForTimeout(500);

    // save the view at this point
    await page.locator(viewbutton).click();
    await page.locator(viewmodal + 'input').fill('first');
    await page.locator('button', { hasText: 'fork' }).click();
    await page.locator(viewmodal).press('Escape');

    // apply a change to the same view
    await dragMouse(
      page,
      paneByTitle(page, 'Text Pane').locator('.bar'),
      1000,
      300
    );
    await page.waitForTimeout(300);

    // save the view at this point
    await page.locator(viewbutton).click();
    await page.locator(viewmodal + 'input').fill('second');
    await page.locator('button', { hasText: 'fork' }).click();
    await page.locator(viewmodal).press('Escape');

    // check first view positions
    await page.locator(viewselect + 'button#viewDropdown').click();
    await page.locator(viewselect + "a[href='#first']").click();
    await expect(paneByTitle(page, 'Text Pane')).toHaveCSS(
      'transform',
      'matrix(1, 0, 0, 1, 10, 10)'
    );
    await expect(paneByTitle(page, 'Random!')).toHaveCSS(
      'transform',
      'matrix(1, 0, 0, 1, 264, 10)'
    );
    await expect(paneByTitle(page, 'Line Plot')).toHaveCSS(
      'transform',
      'matrix(1, 0, 0, 1, 530, 10)'
    );
    await expect(paneByTitle(page, 'Bar Plot')).toHaveCSS(
      'transform',
      'matrix(1, 0, 0, 1, 10, 565)'
    );

    // check second view positions
    await page.locator(viewselect + 'button#viewDropdown').click();
    await page.locator(viewselect + "a[href='#second']").click();
    await expect(paneByTitle(page, 'Text Pane')).toHaveCSS(
      'transform',
      'matrix(1, 0, 0, 1, 657, 10)'
    );
    await expect(paneByTitle(page, 'Random!')).toHaveCSS(
      'transform',
      'matrix(1, 0, 0, 1, 10, 10)'
    );
    await expect(paneByTitle(page, 'Line Plot')).toHaveCSS(
      'transform',
      'matrix(1, 0, 0, 1, 276, 10)'
    );
    await expect(paneByTitle(page, 'Bar Plot')).toHaveCSS(
      'transform',
      'matrix(1, 0, 0, 1, 10, 565)'
    );

    // check first view positions
    await page.locator(viewselect + 'button#viewDropdown').click();
    await page.locator(viewselect + "a[href='#first']").click();
    await expect(paneByTitle(page, 'Text Pane')).toHaveCSS(
      'transform',
      'matrix(1, 0, 0, 1, 10, 10)'
    );
    await expect(paneByTitle(page, 'Random!')).toHaveCSS(
      'transform',
      'matrix(1, 0, 0, 1, 264, 10)'
    );
    await expect(paneByTitle(page, 'Line Plot')).toHaveCSS(
      'transform',
      'matrix(1, 0, 0, 1, 530, 10)'
    );
    await expect(paneByTitle(page, 'Bar Plot')).toHaveCSS(
      'transform',
      'matrix(1, 0, 0, 1, 10, 565)'
    );
  });

  test('Remove additional View again', async ({ page }) => {
    // the view select modal only lists the currently active env's views,
    // so switch back to the env from the previous test
    await closeEnvs(page);
    await openEnv(page, env);

    // delete view first and second
    await page.locator(viewbutton).click();
    await page.locator(viewmodal + 'select').selectOption('first');
    await page.locator('button', { hasText: 'Delete' }).click();
    await page.waitForTimeout(300);
    await page.locator(viewmodal + 'select').selectOption('second');
    await page.locator('button', { hasText: 'Delete' }).click();
    await page.locator(viewmodal).press('Escape');
    await expect(page.locator(viewmodal)).toHaveCount(0);

    // check that current view cannot be removed
    await page.locator(viewbutton).click();
    await page.locator(viewmodal + 'select').selectOption('current');
    await expect(page.locator('button', { hasText: 'Delete' })).toBeDisabled();
    await page.locator(viewmodal).press('Escape');
  });
});
