/**
 * Dispatch an array of raw server messages through a handler,
 * wrapping each in the { data: msg } format expected by
 * handleMessage in ApiProvider.js (matching the WebSocket
 * MessageEvent interface).
 */
export function dispatchMessages(messages, handler) {
  messages.forEach((msg) => {
    handler({ data: msg });
  });
}
