import { POLLING_INTERVAL } from '../settings.js';

/**
 * Dispatch an array of raw server messages through a handler.
 *
 * Each message is wrapped in { data: msg } to match the WebSocket
 * MessageEvent interface, since handleMessage in ApiProvider.js
 * reads evt.data to parse incoming commands. This wrapper is
 * required because polling responses return raw JSON strings,
 * unlike WebSocket which provides MessageEvent objects natively.
 *
 * The handler parses evt.data itself, so we do not pre-parse here.
 * A try/catch guards the dispatch instead, so a single malformed
 * message is skipped with a warning rather than aborting the poll.
 */
function dispatchMessages(messages, handler) {
  if (!Array.isArray(messages)) {
    return;
  }
  messages.forEach((msg) => {
    if (msg == null) {
      return;
    }
    if (typeof msg === 'string') {
      msg = msg
        .replace(/\bNaN\b/g, 'null')
        .replace(/-Infinity\b/g, 'null')
        .replace(/\bInfinity\b/g, 'null');
    }
    try {
      handler({ data: msg });
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn('Skipping invalid message:', e.message);
    }
  });
}

function postData(url = ``, data = {}) {
  return fetch(url, {
    method: 'POST',
    mode: 'cors',
    cache: 'no-cache',
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
    },
    redirect: 'follow',
    referrer: 'no-referrer',
    body: JSON.stringify(data),
  });
}

class Poller {
  closed = false;

  constructor(correctPathname, _handleMessage, onConnect, onDisconnect) {
    this.onConnect = onConnect;
    this.onDisconnect = onDisconnect;
    const url = window.location;
    this.target =
      url.protocol + '//' + url.host + correctPathname() + 'socket_wrap';
    this.onmessage = _handleMessage;

    fetch(this.target)
      .then((res) => {
        if (!res.ok) {
          throw new Error('HTTP ' + res.status);
        }
        return res.json();
      })
      .then((data) => {
        if (!data || !data.sid) {
          throw new Error('missing sid in socket_wrap response');
        }
        this.finishSetup(data.sid);
      })
      .catch((err) => {
        // eslint-disable-next-line no-console
        console.error('[Visdom API] Poller setup failed:', err);
        this.close();
      });
  }

  finishSetup = (sid) => {
    if (this.closed) {
      return; // disconnected while setup was in flight
    }
    this.sid = sid;
    this.poller_id = window.setInterval(() => this.poll(), POLLING_INTERVAL);
    this.onConnect(true);
  };

  close = () => {
    if (this.closed) {
      return;
    }
    this.closed = true;
    window.clearInterval(this.poller_id);
    this.onDisconnect();
  };
  send = (msg) => {
    if (this.closed) return;
    // Post a messge containing the desired command
    postData(this.target, { message_type: 'send', sid: this.sid, message: msg })
      .then((res) => res.json())
      .then(
        (result) => {
          if (!result.success) {
            this.close();
          } else {
            this.poll(); // Get a response right now if there is one
          }
        },
        () => {
          this.close();
        }
      );
  };

  poll = () => {
    if (this.closed) return;
    postData(this.target, { message_type: 'query', sid: this.sid })
      .then((res) => res.json())
      .then(
        (result) => {
          if (this.closed) return;
          if (!result.success) {
            this.close();
          } else {
            dispatchMessages(result.messages, this.onmessage);
          }
        },
        () => {
          this.close();
        }
      );
  };
}

export default Poller;
