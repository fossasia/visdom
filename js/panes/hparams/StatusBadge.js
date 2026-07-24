/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React from 'react';

const StatusBadge = ({ status }) =>
  status ? (
    <span className={'hparams-run-status hparams-status-' + status}>
      {status}
    </span>
  ) : null;

export default StatusBadge;
