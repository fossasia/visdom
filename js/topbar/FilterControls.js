/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import { Eraser } from 'lucide-react';
import React from 'react';

function FilterControls(props) {
  const { filter, onFilterChange, onFilterClear } = props;

  return (
    <div className="input-group navbar-btn">
      <input
        type="text"
        className="form-control"
        data-cy="filter"
        placeholder="Filter text"
        onChange={onFilterChange}
        value={filter}
      />
      <span className="input-group-btn">
        <button
          title="Clear filter"
          type="button"
          className="btn btn-default"
          onClick={onFilterClear}
        >
          <Eraser size={14} />
        </button>
      </span>
    </div>
  );
}

export default FilterControls;
