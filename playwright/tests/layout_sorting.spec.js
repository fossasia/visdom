/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

const { test, expect } = require('@playwright/test');

async function paneOrder(page) {
  return page.locator('.layout .react-grid-item').evaluateAll((elements) =>
    elements
      .map((element) => {
        const position = new DOMMatrix(getComputedStyle(element).transform);
        return {
          id: element.querySelector('.content').textContent,
          x: position.m41,
          y: position.m42,
        };
      })
      .sort((a, b) => a.y - b.y || a.x - b.x)
      .map((pane) => pane.id)
  );
}

test('relayout preserves pane order without comparator scans', async ({
  page,
  request,
}) => {
  await page.addInitScript(() => {
    const sort = Array.prototype.sort;
    const indexOf = Array.prototype.indexOf;
    let sorting = 0;
    window.layoutComparisonScans = 0;
    Array.prototype.sort = function (...args) {
      sorting++;
      try {
        return sort.apply(this, args);
      } finally {
        sorting--;
      }
    };
    Array.prototype.indexOf = function (value, ...args) {
      if (sorting && value?.i?.startsWith('rank-pane-')) {
        window.layoutComparisonScans++;
      }
      return indexOf.call(this, value, ...args);
    };
  });

  const eid = `layout-sorting-${Date.now()}`;
  const ids = Array.from({ length: 8 }, (_, index) => `rank-pane-${index}`);
  try {
    for (const [index, id] of ids.entries()) {
      const response = await request.post('/events', {
        data: {
          eid,
          win: id,
          opts: {
            title: `${index % 2 ? 'keep' : 'other'} ${index}`,
            width: 240,
            height: 120,
          },
          data: [{ type: 'text', content: id }],
        },
      });
      expect(response.ok()).toBe(true);
    }
    await page.goto(`/env/${eid}`);
    await expect(page.locator('.layout .window')).toHaveCount(ids.length);
    await page.getByTitle('Repack', { exact: true }).click();
    await expect.poll(() => paneOrder(page)).toEqual(ids);

    const filter = page.locator('[data-cy="filter"]');
    const filtered = ids.filter((_, index) => index % 2);
    const unfiltered = ids.filter((_, index) => !(index % 2));
    const grouped = [...filtered, ...unfiltered];
    await page.evaluate(() => {
      window.layoutComparisonScans = 0;
    });
    await filter.fill('keep');
    await expect.poll(() => paneOrder(page)).toEqual(grouped);
    await expect(page.locator('.layout .hidden-window')).toHaveCount(4);
    await filter.fill('');
    await expect.poll(() => paneOrder(page)).toEqual(grouped);
    expect(await page.evaluate(() => window.layoutComparisonScans)).toBe(0);

    await filter.fill('other');
    await expect
      .poll(() => paneOrder(page))
      .toEqual([...unfiltered, ...filtered]);
    await filter.fill('');
    await expect
      .poll(() => paneOrder(page))
      .toEqual([...unfiltered, ...filtered]);
    await page.getByTitle('Repack', { exact: true }).click();
    await expect
      .poll(() => paneOrder(page))
      .toEqual([...unfiltered, ...filtered]);
    expect(await page.evaluate(() => window.layoutComparisonScans)).toBe(0);
  } finally {
    await request.post('/delete_env', { data: { eid } });
  }
});
