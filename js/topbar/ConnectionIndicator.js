/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */
import React, { useContext } from 'react';
const classNames = require('classnames');
import ApiContext from '../api/ApiContext';

function ConnectionIndicator(props) {
  const { connected, sessionInfo } = useContext(ApiContext);
  const readonly = sessionInfo.readonly;
  const { onClick } = props;

  const label = connected ? (readonly ? 'readonly' : 'online') : 'offline';
  const title = connected
    ? readonly
      ? 'Read-only connection'
      : 'Connected'
    : 'Disconnected -- click to reconnect';

  // rendering
  // ---------
  return (
    <button
      className={classNames('btn', 'btn-sm', 'topbar-conn', {
        'topbar-conn-warn': connected && readonly,
        'topbar-conn-ok': connected && !readonly,
        'topbar-conn-off': !connected,
      })}
      title={title}
      onClick={onClick}
    >
      <span className="topbar-conn-dot" />
      {label}
    </button>
  );
}

export default ConnectionIndicator;
