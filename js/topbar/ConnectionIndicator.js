/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */
import React from 'react';
const classNames = require('classnames');

function ConnectionIndicator(props) {
  const { connected, readonly, onClick } = props;

  // rendering
  // ---------
  return (
    <button
      className={classNames({
        btn: true,
        'btn-warning': connected && readonly,
        'btn-success': connected && !readonly,
        'btn-danger': !connected,
      })}
      onClick={onClick}
    >
      {connected ? (readonly ? 'readonly' : 'online') : 'offline'}
    </button>
  );
}

export default ConnectionIndicator;
