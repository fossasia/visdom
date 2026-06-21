/**
 * Dispatch an array of raw server messages through a handler.
 *
 * Each message is wrapped in { data: msg } to match the WebSocket
 * MessageEvent interface, since handleMessage in ApiProvider.js
 * reads evt.data to parse incoming commands. This wrapper is
 * required because polling responses return raw JSON strings,
 * unlike WebSocket which provides MessageEvent objects natively.
 */
export function dispatchMessages(messages, handler) {
  if (!Array.isArray(messages)) {
    return;
  }
  messages.forEach((msg) => {
    handler({ data: msg });
  });
}
