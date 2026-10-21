/**
 * SPDX-License-Identifier: Apache-2.0
 * https://www.apache.org/licenses/LICENSE-2.0
 */

const { test, expect } = require('@playwright/test');
const { Buffer } = require('buffer');

test('embedding hovers release GPU buffers and retain the shared texture', async ({
  page,
  request,
}) => {
  await page.addInitScript(() => {
    const buffers = new Set();
    const textures = new Set();
    const resources = { buffers: 0, textures: 0, createdBuffers: 0 };
    window.embeddingResources = resources;

    const prototype = WebGL2RenderingContext.prototype;
    for (const [type, live] of [
      ['Buffer', buffers],
      ['Texture', textures],
    ]) {
      const create = prototype[`create${type}`];
      const dispose = prototype[`delete${type}`];
      const key = type === 'Buffer' ? 'buffers' : 'textures';
      prototype[`create${type}`] = function (...args) {
        const resource = create.apply(this, args);
        if (resource) live.add(resource);
        resources[key] = live.size;
        if (type === 'Buffer') resources.createdBuffers++;
        return resource;
      };
      prototype[`delete${type}`] = function (resource) {
        dispose.call(this, resource);
        live.delete(resource);
        resources[key] = live.size;
      };
    }
  });

  // Keep this resource lifecycle test independent of the sprite's CDN.
  await page.route('**/circle-sprite.png', (route) =>
    route.fulfill({
      contentType: 'image/png',
      body: Buffer.from(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=',
        'base64'
      ),
    })
  );

  const env = `hover-disposal-${Date.now()}`;
  const response = await request.post('/events', {
    data: {
      eid: env,
      win: 'embedding-hover',
      opts: { title: 'Embedding hover disposal' },
      data: [
        {
          type: 'embeddings',
          content: {
            data: [-0.5, 0.5].map((x, idx) => ({
              position: [x, 0],
              group: idx,
              name: `Entity ${idx}`,
              label: idx,
              idx,
            })),
          },
        },
      ],
    },
  });
  expect(response.ok()).toBe(true);

  try {
    await page.goto(`/env/${env}`, { waitUntil: 'domcontentloaded' });
    const canvas = page.locator('.content canvas');
    await expect(canvas).toBeVisible();
    await page.getByText('Embedding hover disposal', { exact: true }).click();
    await page.mouse.move(0, 0);
    await expect
      .poll(() => page.evaluate(() => window.embeddingResources.buffers))
      .toBeGreaterThan(0);
    const baseline = await page.evaluate(() => ({
      ...window.embeddingResources,
    }));
    const box = await canvas.boundingBox();
    const scale = box.height / (2 * Math.tan((20 * Math.PI) / 180) * 7000);

    for (let cycle = 0; cycle < 12; cycle++) {
      for (let idx = 0; idx < 2; idx++) {
        const created = await page.evaluate(
          () => window.embeddingResources.createdBuffers
        );
        await page.mouse.move(
          box.x + box.width / 2 + (idx === 0 ? -1000 : 1000) * scale,
          box.y + box.height / 2
        );
        await expect(
          page.getByText(`Entity ${idx}`, { exact: true })
        ).toBeVisible();
        await expect
          .poll(() =>
            page.evaluate(() => window.embeddingResources.createdBuffers)
          )
          .toBeGreaterThan(created);
        await expect
          .poll(() => page.evaluate(() => window.embeddingResources.buffers))
          .toBe(baseline.buffers + 2);
      }

      await page.mouse.move(0, 0);
      await expect
        .poll(() => page.evaluate(() => window.embeddingResources.buffers))
        .toBe(baseline.buffers);
      expect(
        await page.evaluate(() => window.embeddingResources.textures)
      ).toBe(baseline.textures);
    }
  } finally {
    await request.post('/delete_env', { data: { eid: env } });
  }
});
