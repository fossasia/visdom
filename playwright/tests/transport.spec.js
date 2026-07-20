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
