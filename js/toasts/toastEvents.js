/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import EventSystem from '../EventSystem';

let idCounter = 0;

const DEFAULT_DURATION = 4000;
const DEFAULT_POSITION = 'top-right';
const DEFAULT_SHAPE = 'rect';

/**
 * @param {string} message
 * @param {'info'|'success'|'warning'|'error'} type
 * @param {object} options
 * @param {number} options.duration
 * @param {string} options.position
 * @param {string} options.shape
 * @returns {string}
 */
export const showToast = (message, type = 'info', options = {}) => {
  const {
    duration = DEFAULT_DURATION,
    position = DEFAULT_POSITION,
    shape = DEFAULT_SHAPE,
  } = options;

  const id = `toast-${Date.now()}-${idCounter++}`;
  EventSystem.publish('toast', {
    id,
    message,
    type,
    duration,
    position,
    shape,
  });
  return id;
};

export const dismissToast = (id) => {
  EventSystem.publish('toast-dismiss', { id });
};
