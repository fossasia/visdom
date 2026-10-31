/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

const { test, expect } = require('@playwright/test');

for (const directed of [true, false]) {
  test(`network links and labels (directed=${directed})`, async ({
    page,
    request,
  }) => {
    const env = `network_${directed}_${Date.now()}`;
    const edges = directed
      ? [
          { source: 0, target: 1, label: 'forward' },
          { source: 1, target: 0, label: 'back' },
          { source: 1, target: 2, label: 'single' },
        ]
      : [{ source: 0, target: 1, label: 'single' }];
    const response = await request.post('/events', {
      data: {
        eid: env,
        win: 'network',
        data: [
          {
            type: 'network',
            content: {
              nodes: [0, 1, 2].map((name) => ({ name, label: String(name) })),
              edges,
            },
          },
        ],
        opts: { directed, showEdgeLabels: true, showVertexLabels: true },
      },
    });
    expect(response.ok()).toBe(true);
    await page.goto(`/env/${env}`);
    const links = page.locator('.Network_Div .link');
    await expect(links).toHaveCount(edges.length);
    await expect(page.locator('.Network_Div .edgelabel')).toHaveText(
      edges.map((edge) => edge.label)
    );
    await expect
      .poll(() =>
        links.evaluateAll((paths) =>
          paths.every((path) => {
            const data = path.getAttribute('d');
            return data && !/NaN|undefined/.test(data);
          })
        )
      )
      .toBe(true);
    const paths = await links.evaluateAll((elements) =>
      elements.map((element) => element.getAttribute('d'))
    );
    expect(paths[0].includes('Q')).toBe(directed);
    if (directed) {
      expect(paths[1]).toContain('Q');
      expect(paths[2]).toContain('L');
      await expect
        .poll(() =>
          page.locator('.Network_Div .edgelabel').evaluateAll((elements) => {
            const a = elements[0].getBoundingClientRect();
            const b = elements[1].getBoundingClientRect();
            return Math.hypot(
              a.x + a.width / 2 - b.x - b.width / 2,
              a.y + a.height / 2 - b.y - b.height / 2
            );
          })
        )
        .toBeGreaterThan(15);
      await expect
        .poll(() =>
          page.locator('.Network_Div .edgepath').evaluateAll((elements) => {
            const a = elements[0].getPointAtLength(
              elements[0].getTotalLength() / 2
            );
            const b = elements[1].getPointAtLength(
              elements[1].getTotalLength() / 2
            );
            return Math.hypot(a.x - b.x, a.y - b.y);
          })
        )
        .toBeGreaterThan(20);
    } else {
      expect(paths[0]).toContain('L');
    }
  });
}
