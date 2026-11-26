/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

const { test, expect } = require('@playwright/test');

function isSocketPath(url, suffix) {
  return new URL(url).pathname.endsWith(suffix);
}

function isPollingQuery(request) {
  if (
    request.method() !== 'POST' ||
    !isSocketPath(request.url(), '/socket_wrap')
  ) {
    return false;
  }

  try {
    return request.postDataJSON().message_type === 'query';
  } catch (_error) {
    return false;
  }
}

test('uses the configured frontend transport', async ({ page }, testInfo) => {
  const expectedTransport = testInfo.config.metadata.transport;
  const socketWrapRequests = [];
  const webSocketURLs = [];

  page.on('request', (request) => {
    if (isSocketPath(request.url(), '/socket_wrap')) {
      socketWrapRequests.push(request);
    }
  });
  page.on('websocket', (webSocket) => {
    webSocketURLs.push(webSocket.url());
  });

  await page.goto('/');
  await expect(page.getByText('online').first()).toBeVisible();

  const usePolling = await page.evaluate(() => window.USE_POLLING);
  expect(usePolling).toBe(expectedTransport === 'polling');

  if (expectedTransport === 'polling') {
    await expect
      .poll(() =>
        socketWrapRequests.some((request) => request.method() === 'GET')
      )
      .toBe(true);
    await expect.poll(() => socketWrapRequests.some(isPollingQuery)).toBe(true);
    expect(webSocketURLs.some((url) => isSocketPath(url, '/socket'))).toBe(
      false
    );
  } else {
    await expect
      .poll(() => webSocketURLs.some((url) => isSocketPath(url, '/socket')))
      .toBe(true);
    expect(socketWrapRequests).toHaveLength(0);
  }
});

test('preserves literal NaN and Infinity text and window IDs', async ({
  page,
  request,
}) => {
  const eid = `transport-strings-${Date.now()}`;
  const win = 'Infinity';
  const content = String.raw`Loss is NaN; Infinity and -Infinity are labels.
{"NaN":"Infinity","-Infinity":null} and escaped \"NaN\" stay unchanged.`;
  const packet = {
    eid,
    win,
    opts: { title: 'NaN and Infinity' },
    data: [{ type: 'text', content }],
  };
  const response = await request.post('/events', { data: packet });
  expect(response.ok()).toBe(true);

  try {
    await page.goto(`/env/${eid}`);
    const pane = page.locator('.layout .window');
    await expect(pane).toHaveCount(1);
    await expect(pane.locator('.bar')).toContainText(packet.opts.title);
    await expect(pane.locator('.content')).toHaveText(content);

    const appendedContent = ` Appended: ${content}`;
    const updated = await request.post('/update', {
      data: { eid, win, data: [{ type: 'text', content: appendedContent }] },
    });
    expect(updated.ok()).toBe(true);
    await expect(pane.locator('.content')).toHaveText(
      content + appendedContent
    );

    await pane.locator('button[title="close"]').click();
    await expect(pane).toHaveCount(0);
    await expect
      .poll(async () => {
        const exists = await request.post('/win_exists', {
          data: { eid, win },
        });
        expect(exists.ok()).toBe(true);
        return exists.text();
      })
      .toBe('false');
  } finally {
    await request.post('/delete_env', { data: { eid } });
  }
});
