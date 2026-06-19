/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

class EventSystem {
  constructor() {
    this.queue = {};
  }

  publish(event, data) {
    let queue = this.queue[event];

    if (typeof queue === 'undefined') {
      return false;
    }

    queue.forEach((cb) => {
      try {
        cb(data);
      } catch (e) {
        // eslint-disable-next-line no-console
        console.error('EventSystem: subscriber error', e);
      }
    });

    return true;
  }

  subscribe(event, callback) {
    if (typeof this.queue[event] === 'undefined') {
      this.queue[event] = [];
    }

    this.queue[event].push(callback);
  }

  //  the callback parameter is optional. Without it the whole event will be
  // removed, instead of just one subscription. Fine for simple implementation
  unsubscribe(event, callback) {
    let queue = this.queue;

    if (typeof queue[event] !== 'undefined') {
      if (typeof callback === 'undefined') {
        delete queue[event];
      } else {
        this.queue[event] = queue[event].filter(function (sub) {
          return sub !== callback;
        });
      }
    }
  }
}

export default new EventSystem();
