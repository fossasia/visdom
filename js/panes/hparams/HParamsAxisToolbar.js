/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import TreeSelect from 'rc-tree-select';
import React from 'react';

/*
 * The axis picker and colour picker both plot views carry. Only the wording
 * differs between them: a scatter matrix talks about dimensions and falls back
 * to no colour, parallel coordinates talks about axes and falls back to run
 * order. `note` is the trailing status each view fills for itself.
 */
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
      <TreeSelect
        className="hparams-treeselect hparams-select-wide"
        value={dims}
        placeholder="pick axes"
        treeCheckable
        multiple
        showCheckedStrategy="SHOW_CHILD"
        treeLine
        treeDefaultExpandAll
        maxTagCount={3}
        dropdownMatchSelectWidth={false}
        treeData={treeData}
        onChange={(value) =>
          onDims(Array.isArray(value) ? value.slice(0, maxDims) : [])
        }
        aria-label={axesName + ' ' + axesLabel}
      />
    </span>
    <span className="hparams-colorby">
      color by:
      <TreeSelect
        className="hparams-treeselect hparams-select-narrow"
        value={colorBy || undefined}
        placeholder={colorFallback}
        allowClear
        treeLine
        treeDefaultExpandAll
        dropdownMatchSelectWidth={false}
        treeData={treeData}
        onChange={(value) => onColorBy(value || null)}
        aria-label={'Color ' + axesName + ' by'}
      />
    </span>
    {note ? <span className="hparams-plot-note">{note}</span> : null}
  </div>
);

export default HParamsAxisToolbar;
