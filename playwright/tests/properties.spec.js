/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 */

const { test, expect } = require('@playwright/test');

const { runDemo } = require('../support/helpers');

test.describe('Properties Pane', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('check download button', async ({ page }) => {
    await runDemo(page, 'properties_basic');

    const downloadPromise = page.waitForEvent('download');

    await page
      .locator('.layout .react-grid-item')
      .first()
      .locator('button[title="save"]')
      .click();

    const download = await downloadPromise;

    expect(download.suggestedFilename()).toBe(
      'visdom_properties.json'
    );
  });

  test('properties_callbacks', async ({ page }) => {
    await runDemo(page, 'properties_callbacks', { asyncrun: true });

    await page
      .locator('input[value="initial"]')
      .first()
      .fill('changed');

    await page.keyboard.press('Enter');

    await expect(
      page.locator('.layout .react-grid-item .content-text').first()
    ).toContainText('Updated: Text input => changed');

    await expect(
      page.locator('input[value="changed_updated"]')
    ).toBeVisible();


    await page
      .locator('input[value="12"]')
      .first()
      .fill('42');

    await page.keyboard.press('Enter');

    await expect(
      page.locator('.layout .react-grid-item .content-text').first()
    ).toContainText('Updated: Number input => 42');

    await expect(
      page.locator('input[value="420"]')
    ).toBeVisible();


    await page.getByText('Start').click();

    await expect(
      page.locator('.layout .react-grid-item .content-text').first()
    ).toContainText('Updated: Button => clicked');


    const checkbox = page.locator('input[type="checkbox"]').first();

    await expect(checkbox).toBeChecked();
    await checkbox.click();

    await expect(
      page.locator('.layout .react-grid-item .content-text').first()
    ).toContainText('Updated: Checkbox => False');

    await expect(checkbox).not.toBeChecked();


    const select = page.locator('select').first();

    await expect(select).toHaveValue('1');

    await select.selectOption('Red');

    await expect(
      page.locator('.layout .react-grid-item .content-text').first()
    ).toContainText('Updated: Select => 0');

    await expect(select).toHaveValue('0');

    await select.selectOption('Blue');

    await expect(
      page.locator('.layout .react-grid-item .content-text').first()
    ).toContainText('Updated: Select => 2');

    await expect(select).toHaveValue('2');
  });
});