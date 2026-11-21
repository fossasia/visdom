/* SPDX-License-Identifier: Apache-2.0 */

const { devices, test, expect } = require('@playwright/test');

test.use({ ...devices['Desktop Firefox'], browserName: 'firefox' });

test('Firefox fits complete LaTeX labels inside the plot legend', async ({
  page,
  request,
}) => {
  const eid = `latex-legend-${Date.now()}`;
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
    const legend = page.locator('.js-plotly-plot .legend');
    const glyphs = legend.locator('.legendtext-math-group > svg > g');
    await expect(glyphs).toHaveCount(labels.length);
    await expect
      .poll(() =>
        glyphs.evaluateAll((groups) =>
          groups.every((group) => {
            const bounds = group.getBoundingClientRect();
            const frame = group
              .closest('.legend')
              .querySelector('.bg')
              .getBoundingClientRect();
            return bounds.width > 0 && bounds.right <= frame.right + 1;
          })
        )
      )
      .toBe(true);
  } finally {
    await request.post('/delete_env', { data: { eid } });
  }
});
