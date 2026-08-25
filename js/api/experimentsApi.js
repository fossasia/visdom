/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import serverPath from './serverPath';

export function fetchExperimentComparison(envIds, signal) {
  const ids = (envIds || []).filter((id) => typeof id === 'string');
  if (ids.length === 0) {
    return Promise.reject(new Error('No runs to load.'));
  }
  return window
    .fetch(serverPath() + 'experiments/compare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ env_ids: ids }),
      signal,
    })
    .catch((err) => {
      if (err && err.name === 'AbortError') throw err;
      throw new Error('Could not reach the server.');
    })
    .then((res) => {
      if (!res.ok) {
        const reason = res.statusText || 'request failed';
        throw new Error('Could not load metric history (' + reason + ').');
      }
      return res.json();
    });
}

export default fetchExperimentComparison;
