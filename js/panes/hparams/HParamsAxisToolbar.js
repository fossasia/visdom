/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React from 'react';

import { ColumnMultiSelect, ColumnSelect } from './hparamsUtils';

const HParamsAxisToolbar = ({
  axesLabel,
  axesName,
  colorFallback,
  treeData,
  dims,
  onDims,
  colorBy,
  onColorBy,
  maxDims,
  note,
}) => (
  <div className="hparams-toolbar">
    <span className="hparams-sortby">
      {axesLabel}:
      <ColumnMultiSelect
        value={dims}
        placeholder="pick axes"
        treeData={treeData}
        maxCount={maxDims}
        onChange={onDims}
        label={axesName + ' ' + axesLabel}
      />
    </span>
    <span className="hparams-colorby">
      color by:
      <ColumnSelect
        value={colorBy}
        placeholder={colorFallback}
        treeData={treeData}
        onChange={onColorBy}
        label={'Color ' + axesName + ' by'}
      />
    </span>
    {note ? <span className="hparams-plot-note">{note}</span> : null}
  </div>
);

export default HParamsAxisToolbar;
