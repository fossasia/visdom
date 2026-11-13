/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
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

    for (const Context of [
      window.WebGLRenderingContext,
      window.WebGL2RenderingContext,
    ]) {
      if (!Context) continue;
      const prototype = Context.prototype;
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
  const packet = {
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
  };
  const response = await request.post('/events', { data: packet });
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

    const otherPane = await request.post('/events', {
      data: {
        eid: env,
        win: 'other-pane',
        opts: { title: 'Other pane' },
        data: [{ type: 'text', content: 'Focus switching target' }],
      },
    });
    expect(otherPane.ok()).toBe(true);
    const otherTitle = page.getByText('Other pane', { exact: true });
    const embeddingTitle = page.getByText('Embedding hover disposal', {
      exact: true,
    });
    await expect(otherTitle).toBeVisible();

    for (let cycle = 0; cycle < 6; cycle++) {
      await embeddingTitle.dispatchEvent('click');
      const bounds = await canvas.boundingBox();
      await page.mouse.move(
        bounds.x + bounds.width / 2 - 1000 * scale,
        bounds.y + bounds.height / 2
      );
      await expect
        .poll(() => page.evaluate(() => window.embeddingResources.buffers))
        .toBe(baseline.buffers + 2);
      // Switch focus without a mouseleave clearing the highlight first.
      await otherTitle.dispatchEvent('click');
      await expect
        .poll(() => page.evaluate(() => window.embeddingResources.buffers))
        .toBe(baseline.buffers);
    }

    for (const count of [3, 4, 2]) {
      const previousCanvas = await canvas.elementHandle();
      packet.data[0].content.data = Array.from({ length: count }, (_, idx) => ({
        position: [idx / count - 0.5, 0],
        group: idx % 2,
        name: `Entity ${idx}`,
        label: idx,
        idx,
      }));
      const updated = await request.post('/events', { data: packet });
      expect(updated.ok()).toBe(true);
      await expect
        .poll(() => previousCanvas.evaluate((element) => element.isConnected))
        .toBe(false);
      await expect(canvas).toHaveCount(1);
      await expect
        .poll(() =>
          previousCanvas.evaluate((element) => {
            const gl =
              element.getContext('webgl2') || element.getContext('webgl');
            return gl.isContextLost();
          })
        )
        .toBe(true);
      await expect
        .poll(() => page.evaluate(() => window.embeddingResources.buffers))
        .toBe(baseline.buffers);
      await previousCanvas.dispose();
    }

    await page
      .locator('.window')
      .filter({ has: embeddingTitle })
      .locator('button[title="close"]')
      .click();
    await expect(canvas).toHaveCount(0);
    await expect
      .poll(() => page.evaluate(() => window.embeddingResources.buffers))
      .toBe(0);
  } finally {
    await request.post('/delete_env', { data: { eid: env } });
  }
});
