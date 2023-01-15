/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */
import React from 'react';

function ViewControls(props) {
  const {
    connected,
    envIDs,
    activeLayout,
    layoutList,
    readonly,
    onViewManageButton,
    onRepackButton,
    onViewChange,
  } = props;

  // rendering
  // ---------
  let view_options = Array.from(layoutList.keys()).map((view) => {
    // add checkmark before currently used layout
    let check_space = '';
    if (view == activeLayout) {
      check_space = <span>&nbsp;&#10003;</span>;
    }

    return (
      <li key={view}>
        <a href={'#' + view} onClick={() => onViewChange(view)}>
          {view}
          {check_space}
        </a>
      </li>
    );
  });
  return (
    <span>
      <span>View&nbsp;</span>
      <div className="btn-group navbar-btn" role="group" aria-label="View:">
        <div className="btn-group" role="group">
          <button
            className="btn btn-default dropdown-toggle"
            type="button"
            id="viewDropdown"
            data-toggle="dropdown"
            aria-haspopup="true"
            aria-expanded="true"
            disabled={!(connected && envIDs.length > 0)}
          >
            {envIDs.length > 0 == null ? 'compare' : activeLayout}
            &nbsp;
            <span className="caret" />
          </button>
          <ul className="dropdown-menu" aria-labelledby="viewDropdown">
            {view_options}
          </ul>
        </div>
        <button
          data-toggle="tooltip"
          title="Repack"
          data-placement="bottom"
          className="btn btn-default"
          onClick={onRepackButton}
        >
          <span className="glyphicon glyphicon-th" />
        </button>
        <button
          data-toggle="tooltip"
          title="Manage Views"
          data-placement="bottom"
          className="btn btn-default"
          disabled={!(connected && envIDs.length > 0 && !readonly)}
          onClick={onViewManageButton}
        >
          <span className="glyphicon glyphicon-folder-open" />
        </button>
      </div>
    </span>
  );
}

export default ViewControls;
