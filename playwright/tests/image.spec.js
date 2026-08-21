/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

const { test, expect } = require('@playwright/test');
const { runDemo, openEnv, closeEnvs } = require('../support/helpers');

const WIN_SEL = '.layout .react-grid-item';
const CONTAINER_SEL = `${WIN_SEL} .content > div`;
const IMG_SEL = `${CONTAINER_SEL} img`;

const MOVE_X = 12;
const MOVE_Y = 34;
const IMG_WIDTH = 255;
const IMG_HEIGHT = 510;
const BASE_POS = 10;

/**
 * Dispatches a WheelEvent with ctrlKey held directly on the target element.
 * page.mouse.wheel() does not support modifier keys, so we use evaluate().
 */
async function ctrlWheel(locator, deltaY, clientX, clientY) {
  let cx = clientX;
  let cy = clientY;
  if (cx === undefined || cy === undefined) {
    const box = await locator.boundingBox();
    if (box) {
      if (cx === undefined) cx = box.x + box.width / 2;
      if (cy === undefined) cy = box.y + box.height / 2;
    }
  }
  await locator.evaluate(
    (el, args) => {
      el.dispatchEvent(
        new WheelEvent('wheel', {
          ctrlKey: true,
          deltaY: args.deltaY,
          clientX: args.clientX,
          clientY: args.clientY,
          bubbles: true,
          cancelable: true,
        })
      );
    },
    { deltaY, clientX: cx ?? 0, clientY: cy ?? 0 }
  );
}

/**
 * Drags an element by (dx, dy) pixels using real mouse events.
 * source offset is the starting point within the element's bounding box.
 */
async function dragBy(page, locator, sourceOffset, dx, dy) {
  const box = await locator.boundingBox();
  if (!box)
    throw new Error(
      `dragBy: boundingBox() returned null — element may not be visible`
    );
  const startX = box.x + sourceOffset;
  const startY = box.y + sourceOffset;
  await page.mouse.move(startX, startY);
  await page.mouse.down();
  await page.mouse.move(startX + dx, startY + dy, { steps: 10 });
  await page.mouse.up();
}

/**
 * Returns the computed top/left CSS values of a locator's element.
 */
async function getComputedPosition(locator) {
  return locator.evaluate((el) => {
    const s = getComputedStyle(el);
    return { top: s.top, left: s.left };
  });
}

test.describe('Image Pane', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('online').first()).toBeVisible();
    // Clear any envs left open by previous tests to prevent cross-test bleed
    await closeEnvs(page);
  });

  test('image_basic', async ({ page }) => {
    await runDemo(page, 'image_basic');
    await expect(page.locator(WIN_SEL).first().locator('img')).toHaveCount(1);
  });

  test('Image Move (Drag and Drop)', async ({ page }) => {
    await runDemo(page, 'image_basic');

    const container = page.locator(CONTAINER_SEL).first();
    const img = page.locator(IMG_SEL).first();

    // Verify initial position
    let pos = await getComputedPosition(container);
    expect(pos.top).toBe('0px');
    expect(pos.left).toBe('0px');

    // First drag
    await dragBy(page, img, BASE_POS, MOVE_X, MOVE_Y);

    pos = await getComputedPosition(container);
    expect(pos.top).toBe(`${MOVE_Y}px`);
    expect(pos.left).toBe(`${MOVE_X}px`);
    await expect(img).toHaveAttribute('width', `${IMG_WIDTH}px`);
    await expect(img).toHaveAttribute('height', `${IMG_HEIGHT}px`);

    // Second drag
    await dragBy(page, img, BASE_POS, MOVE_X, MOVE_Y);

    pos = await getComputedPosition(container);
    expect(pos.top).toBe(`${2 * MOVE_Y}px`);
    expect(pos.left).toBe(`${2 * MOVE_X}px`);
    await expect(img).toHaveAttribute('width', `${IMG_WIDTH}px`);
    await expect(img).toHaveAttribute('height', `${IMG_HEIGHT}px`);
  });

  test('Image Reset (Double-Click)', async ({ page }) => {
    await runDemo(page, 'image_basic');

    const container = page.locator(CONTAINER_SEL).first();
    const img = page.locator(IMG_SEL).first();

    // Move image first so reset has something to do
    await dragBy(page, img, BASE_POS, MOVE_X, MOVE_Y);

    // Double-click to reset
    await img.dblclick();

    const pos = await getComputedPosition(container);
    expect(pos.top).toBe('0px');
    expect(pos.left).toBe('0px');
    await expect(img).toHaveAttribute('width', `${IMG_WIDTH}px`);
    await expect(img).toHaveAttribute('height', `${IMG_HEIGHT}px`);
  });

  test('Image Zoom From Image Corner (Ctrl + Wheel)', async ({ page }) => {
    await runDemo(page, 'image_basic');

    const img = page.locator(IMG_SEL).first();
    const container = page.locator(CONTAINER_SEL).first();

    // 5× Ctrl+Wheel from corner (clientX=0, clientY=0)
    for (let i = 0; i < 5; i++) {
      await ctrlWheel(img, 200, 0, 0);
    }

    await expect(img).toHaveAttribute('width', '156px');
    await expect(img).toHaveAttribute('height', '312px');

    const pos = await getComputedPosition(container);
    expect(pos.top).toBe('-32.658px');
    expect(pos.left).toBe('-3.93469px');
  });

  test('Image Zoom From Image Center (Ctrl + Wheel)', async ({ page }) => {
    await runDemo(page, 'image_basic');

    const img = page.locator(IMG_SEL).first();
    const container = page.locator(CONTAINER_SEL).first();

    // Double-click to ensure we start from a reset state
    await img.dblclick();

    // 5× Ctrl+Wheel from center (no explicit clientX/Y — element center used by default)
    for (let i = 0; i < 5; i++) {
      await ctrlWheel(img, 200);
    }

    await expect(img).toHaveAttribute('width', '156px');
    await expect(img).toHaveAttribute('height', '312px');

    const pos = await getComputedPosition(container);
    expect(pos.top).toBe('104.269px');
    expect(pos.left).toBe('49.9706px');
  });

  test('Image Move & Zoom', async ({ page }) => {
    await runDemo(page, 'image_basic');

    const img = page.locator(IMG_SEL).first();
    const container = page.locator(CONTAINER_SEL).first();

    // Reset
    await img.dblclick();

    let pos = await getComputedPosition(container);
    expect(pos.top).toBe('0px');
    expect(pos.left).toBe('0px');

    // Zoom
    for (let i = 0; i < 5; i++) {
      await ctrlWheel(img, 200);
    }

    pos = await getComputedPosition(container);
    expect(pos.top).toBe('104.269px');
    expect(pos.left).toBe('49.9706px');
    await expect(img).toHaveAttribute('width', '156px');
    await expect(img).toHaveAttribute('height', '312px');

    // Then drag
    await dragBy(page, img, BASE_POS, MOVE_X, MOVE_Y);

    pos = await getComputedPosition(container);
    expect(pos.top).toBe('138.269px');
    expect(pos.left).toBe('61.9706px');
    await expect(img).toHaveAttribute('width', '156px');
    await expect(img).toHaveAttribute('height', '312px');
  });

  test('image_basic download', async ({ page }) => {
    await runDemo(page, 'image_basic');

    const pane = page
      .locator(IMG_SEL)
      .first()
      .locator(`xpath=ancestor::*[contains(@class,'react-grid-item')]`)
      .first();

    await pane.locator('button[title="export"]').click();

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      pane
        .locator('.export-dropdown-menu')
        .getByRole('menuitem', { name: 'JPG' })
        .click(),
    ]);

    expect(download.suggestedFilename()).toBe('Random!.jpg');
    const savePath = await download.path();
    expect(savePath).toBeTruthy();
  });

  test('image_save_jpeg', async ({ page }) => {
    await runDemo(page, 'image_save_jpeg');

    const pane = page
      .locator(IMG_SEL)
      .first()
      .locator(`xpath=ancestor::*[contains(@class,'react-grid-item')]`)
      .first();

    await pane.locator('button[title="export"]').click();

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      pane
        .locator('.export-dropdown-menu')
        .getByRole('menuitem', { name: 'JPG' })
        .click(),
    ]);

    expect(download.suggestedFilename()).toBe('Random image as jpg!.jpg');
    const savePath = await download.path();
    expect(savePath).toBeTruthy();
  });

  test('image_history', async ({ page }) => {
    await runDemo(page, 'image_history', { asyncrun: true });

    const img = page.locator(IMG_SEL).first();
    await expect(img).toHaveCount(1);

    const initialSrc = await img.getAttribute('src');

    const slider = page
      .locator(`${WIN_SEL} .widget input[type="range"]`)
      .first();
    await expect(slider).toBeVisible();

    // Use native input value setter — required because React overrides the setter.
    // Trigger the range input through its native setter so React receives the
    // same input and change events as a user interaction.
    await slider.evaluate((range) => {
      const nativeSet = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        'value'
      ).set;
      nativeSet.call(range, 0);
      range.dispatchEvent(new Event('input', { bubbles: true }));
    });

    // Wait for React to re-render with the new image before reading the attribute
    await expect(img).not.toHaveAttribute('src', initialSrc);
    const newSrc = await img.getAttribute('src');
    expect(newSrc).not.toBe(initialSrc);
  });

  test('image_grid', async ({ page }) => {
    await runDemo(page, 'image_grid', { asyncrun: true });
    const img = page.locator(IMG_SEL).first();
    await expect(img).toHaveCount(1);
    await expect(img).toHaveAttribute('width', '543px');
    await expect(img).toHaveAttribute('height', '204px');
  });

  test('image_svg', async ({ page }) => {
    await runDemo(page, 'image_svg', { asyncrun: true });

    const ellipse = page.locator('.window .content').first().locator('ellipse');

    await expect(ellipse).toHaveCount(1);
    await expect(ellipse).toHaveAttribute('cx', '80');
    await expect(ellipse).toHaveAttribute('cy', '80');
    await expect(ellipse).toHaveAttribute('rx', '50');
    await expect(ellipse).toHaveAttribute('ry', '30');
  });

  test('image_callback', async ({ page }) => {
    const click1 = [12, 34];
    const click2 = [45, 67];

    await runDemo(page, 'image_callback', { asyncrun: true });

    // Locate the pane by finding the grid item that contains the image
    const pane = page
      .locator(WIN_SEL)
      .filter({ has: page.locator('img') })
      .first();
    await pane.click();

    const content = pane.locator('div.content');
    await content.click({ position: { x: click1[0], y: click1[1] } });
    await content.click({ position: { x: click2[0], y: click2[1] } });

    const textPane = page.locator(`${WIN_SEL} .content-text`).first();
    await expect(textPane).toContainText('Coords:');
    await expect(textPane).toContainText(`x: ${click1[0]}, y: ${click1[1]};`);
    await expect(textPane).toContainText(`x: ${click2[0]}, y: ${click2[1]};`);
  });

  test('image_callback2', async ({ page }) => {
    await runDemo(page, 'image_callback2', { asyncrun: true });

    const img = page.locator(IMG_SEL).first();
    await expect(img).toBeVisible();

    const initialSrc = await img.getAttribute('src');

    // Click pane to focus it before sending keyboard events
    await page.locator(WIN_SEL).first().click();

    // Press right 3 times then left once
    await page.keyboard.press('ArrowRight');
    await page.waitForTimeout(150);
    await page.keyboard.press('ArrowRight');
    await page.waitForTimeout(150);
    await page.keyboard.press('ArrowRight');
    await page.waitForTimeout(150);
    await page.keyboard.press('ArrowLeft');

    // The src change is driven by a server WebSocket response — wait for it
    await expect(img).not.toHaveAttribute('src', initialSrc, {
      timeout: 10000,
    });
    const newSrc = await img.getAttribute('src');
    expect(newSrc).toMatch(/^data:image\/png;base64,/);
    expect(newSrc).not.toBe(initialSrc);
  });

  test('Image Compare Mode', async ({ page }) => {
    const envA = `compare_image_env_A_${Math.floor(Math.random() * 1e6)}`;
    const envB = `compare_image_env_B_${Math.floor(Math.random() * 1e6)}`;

    await closeEnvs(page);

    await runDemo(page, 'image_basic', { env: envA, open: false, seed: 1 });
    await runDemo(page, 'image_basic', { env: envB, open: false, seed: 2 });

    await openEnv(page, envA);
    await openEnv(page, envB);

    await expect(page.locator(WIN_SEL)).toHaveCount(2);

    const comparePane = page
      .locator(WIN_SEL)
      .filter({ hasText: 'Random!' })
      .first();

    await expect(comparePane.locator('img.content-image')).toHaveCount(2);

    const downloads = [];
    page.on('download', (dl) => downloads.push(dl));

    await comparePane.locator("button[title='save']").click();

    await expect.poll(() => downloads.length, { timeout: 10000 }).toBe(2);

    const filenames = downloads.map((dl) => dl.suggestedFilename()).sort();
    expect(filenames).toContain('Random!_1.jpg');
    expect(filenames).toContain('Random!_2.jpg');
    for (const dl of downloads) {
      expect(await dl.path()).toBeTruthy();
    }
  });

  test('image_compare_basic: captions are visible and do not overlap images', async ({
    page,
  }) => {
    const baseEnv = `image_compare_basic_${Math.floor(Math.random() * 1e6)}`;

    await runDemo(page, 'image_compare_basic', { env: baseEnv, open: false });

    await closeEnvs(page);
    await openEnv(page, baseEnv);
    await openEnv(page, `${baseEnv}_compare`);

    const comparePane = page
      .locator(WIN_SEL)
      .filter({ hasText: 'CompareTest' })
      .first();

    await expect(comparePane.locator('img.content-image')).toHaveCount(2);

    const captions = comparePane.locator('figcaption.widget');
    await expect(captions).toHaveCount(2);
    await expect(captions.nth(0)).toBeVisible();
    await expect(captions.nth(1)).toBeVisible();

    await expect(captions.nth(0)).toContainText('Image A');
    await expect(captions.nth(1)).toContainText('Image B');

    // Each caption must sit above its sibling image — caption.bottom <= image.top + 2px
    const images = comparePane.locator('img.content-image');
    const imgCount = await images.count();
    for (let i = 0; i < imgCount; i++) {
      const img = images.nth(i);
      const cell = img.locator(
        'xpath=ancestor::*[@data-testid="compare-cell"]'
      );
      const capCount = await cell.locator('figcaption.widget').count();
      if (capCount > 0) {
        const caption = cell.locator('figcaption.widget').first();
        const capBox = await caption.boundingBox();
        const imgBox = await img.boundingBox();
        expect(capBox.y + capBox.height).toBeLessThanOrEqual(imgBox.y + 2);
      }
    }
  });

  test('image_compare_basic: single env shows image without compare', async ({
    page,
  }) => {
    const singleEnv = `image_compare_single_${Math.floor(Math.random() * 1e6)}`;

    await runDemo(page, 'image_compare_basic', { env: singleEnv });

    const comparePane = page
      .locator(WIN_SEL)
      .filter({ hasText: 'CompareTest' })
      .first();

    await expect(comparePane.locator('img.content-image')).toHaveCount(1);
  });

  test('image_compare_basic: download produces files for both images', async ({
    page,
  }) => {
    const baseEnv = `image_compare_dl_${Math.floor(Math.random() * 1e6)}`;

    await runDemo(page, 'image_compare_basic', { env: baseEnv, open: false });

    await closeEnvs(page);
    await openEnv(page, baseEnv);
    await openEnv(page, `${baseEnv}_compare`);

    const comparePane = page
      .locator(WIN_SEL)
      .filter({ hasText: 'CompareTest' })
      .first();

    await expect(comparePane.locator('img.content-image')).toHaveCount(2);

    const downloads = [];
    page.on('download', (dl) => downloads.push(dl));

    await comparePane.locator("button[title='save']").click();

    await expect.poll(() => downloads.length, { timeout: 10000 }).toBe(2);

    const filenames = downloads.map((dl) => dl.suggestedFilename()).sort();
    expect(filenames).toEqual(['CompareTest_1.jpg', 'CompareTest_2.jpg']);
  });
});
