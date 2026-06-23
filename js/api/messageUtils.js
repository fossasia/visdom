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
    if (msg == null) {
      return;
    }
    if (typeof msg === 'string') {
      msg = msg.replace(/\bNaN\b/g, 'null')
        .replace(/\bInfinity\b/g, 'null')
        .replace(/-Infinity\b/g, 'null');
    }
    try {
      JSON.parse(typeof msg === 'string' ? msg : JSON.stringify(msg));
    } catch (e) {
      console.warn('Skipping invalid message:', e.message);
      return;
    }
    handler({ data: msg });
  });
}
