/* SPDX-License-Identifier: Apache-2.0 */

const { randomUUID } = require('node:crypto');
const { devices, test, expect } = require('@playwright/test');

test.use({ ...devices['Desktop Firefox'], browserName: 'firefox' });

for (const legendId of ['legend', 'legend2']) {
  test(`Firefox fits complete LaTeX labels inside ${legendId}`, async ({
    page,
    request,
  }) => {
    const eid = `latex-legend-${randomUUID()}`;
    const labels = [
      String.raw`$\alpha_{1c} = 352 \pm 11 \text{ km s}^{-1}$`,
      String.raw`$\beta_{1c} = 25 \pm 11 \text{ km s}^{-1}$`,
    ];
    const response = await request.post('/events', {
      data: {
        eid,
        win: 'plot',
        data: labels.map((name) => ({
          type: 'scatter',
          legend: legendId,
          x: [1, 2],
          y: [1, 4],
          name,
        })),
        layout: { showlegend: true },
      },
    });
    expect(response.ok()).toBe(true);
    try {
      await page.goto(`/env/${eid}`);
      const legend = page.locator(`.js-plotly-plot .${legendId}`);
      const glyphs = legend.locator(`.${legendId}text-math-group > svg > g`);
      await expect(glyphs).toHaveCount(labels.length);
      await expect
        .poll(() =>
          glyphs.evaluateAll(
            (groups, selector) =>
              groups.every((group) => {
                const bounds = group.getBoundingClientRect();
                const frame = group
                  .closest(selector)
                  .querySelector('.bg')
                  .getBoundingClientRect();
                return bounds.width > 0 && bounds.right <= frame.right + 1;
              }),
            `.${legendId}`
          )
        )
        .toBe(true);
    } finally {
      await request.post('/delete_env', { data: { eid } });
    }
  });
}
