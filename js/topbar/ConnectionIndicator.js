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
  const readonly = sessionInfo ? sessionInfo.readonly : false;
  const { onClick } = props;

  // Tri-state evaluation:
  // connected === null  -> initial connection in progress
  // connected === true  -> online or readonly
  // connected === false -> offline / disconnected
  const isConnecting = connected === null;
  const isOnline = connected === true;

  let label = 'offline';
  let title = 'Disconnected -- click to reconnect';

  if (isConnecting) {
    label = 'connecting';
    title = 'Connecting to server...';
  } else if (isOnline) {
    label = readonly ? 'readonly' : 'online';
    title = readonly ? 'Read-only connection' : 'Connected';
  }

  return (
    <button
      className={classNames('btn', 'btn-sm', 'topbar-conn', {
        'topbar-conn-warn': isOnline && readonly,
        'topbar-conn-ok': isOnline && !readonly,
        'topbar-conn-connecting': isConnecting,
        'topbar-conn-off': !isOnline && !isConnecting,
      })}
      title={title}
      onClick={isConnecting ? undefined : onClick}
      disabled={isConnecting}
    >
      <span className="topbar-conn-dot" />
      {label}
    </button>
  );
}

export default ConnectionIndicator;