/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React from 'react';

const HParamsMessage = ({ wrapClass, tone, children }) => {
  const message = (
    <div className={'hparams-message hparams-' + (tone || 'empty')}>
      {children}
    </div>
  );
  return wrapClass ? <div className={wrapClass}>{message}</div> : message;
};

export default HParamsMessage;
