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

const TREE_PROPS = {
  treeLine: true,
  treeDefaultExpandAll: true,
  dropdownMatchSelectWidth: false,
};

export const ColumnSelect = ({
  value,
  placeholder,
  treeData,
  onChange,
  label,
}) => (
  <TreeSelect
    {...TREE_PROPS}
    className="hparams-treeselect hparams-select-narrow"
    value={value || undefined}
    placeholder={placeholder}
    allowClear
    treeData={treeData}
    onChange={(next) => onChange(next || null)}
    aria-label={label}
  />
);

export const ColumnMultiSelect = ({
  value,
  placeholder,
  treeData,
  maxCount,
  onChange,
  label,
}) => (
  <TreeSelect
    {...TREE_PROPS}
    className="hparams-treeselect hparams-select-wide"
    value={value}
    placeholder={placeholder}
    treeCheckable
    multiple
    showCheckedStrategy="SHOW_CHILD"
    maxTagCount={3}
    treeData={treeData}
    onChange={(next) =>
      onChange(Array.isArray(next) ? next.slice(0, maxCount) : [])
    }
    aria-label={label}
  />
);

export default ColumnSelect;
