/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

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
          data-toggle="tooltip"
          title="Clear filter"
          data-placement="bottom"
          type="button"
          className="btn btn-default"
          onClick={onFilterClear}
        >
          <span className="glyphicon glyphicon-erase" />
        </button>
      </span>
    </div>
  );
}

export default FilterControls;
