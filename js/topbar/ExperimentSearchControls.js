/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React from 'react';

function ExperimentSearchControls(props) {
  const { query, onQueryChange, onSearchSubmit, onSearchClear } = props;

  return (
    <form className="input-group navbar-btn" onSubmit={onSearchSubmit}>
      <input
        type="text"
        className="form-control"
        placeholder="Search experiments (query)"
        onChange={onQueryChange}
        value={query}
      />
      <span className="input-group-btn">
        <button
          data-toggle="tooltip"
          title="Search experiments"
          data-placement="bottom"
          type="submit"
          className="btn btn-default"
        >
          <span className="glyphicon glyphicon-search" />
        </button>
        <button
          data-toggle="tooltip"
          title="Clear experiment search"
          data-placement="bottom"
          type="button"
          className="btn btn-default"
          onClick={onSearchClear}
        >
          <span className="glyphicon glyphicon-remove-circle" />
        </button>
      </span>
    </form>
  );
}

export default ExperimentSearchControls;
