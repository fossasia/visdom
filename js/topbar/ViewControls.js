/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */
import React, { useContext, useRef } from 'react';

import ApiContext from '../api/ApiContext';

function ViewControls(props) {
  const { connected, sessionInfo } = useContext(ApiContext);
  const readonly = sessionInfo.readonly;
  const {
    envIDs,
    activeLayout,
    layoutList,
    onViewManageButton,
    onRepackButton,
    onViewChange,
    onUndoButton,
    canUndo,
    onExportHtml,
  } = props;

  const fileInputRef = useRef(null);

  const handleUploadDashboard = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    if (!file.name.toLowerCase().endsWith('.json')) {
      alert('Please upload a valid .json file.');
      e.target.value = '';
      return;
    }

    if (file.size > 100 * 1024 * 1024) {
      // 100 MB limit
      alert('Maximum 100 MB File allowed.');
      e.target.value = '';
      return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
      const base = window.location.origin + (window.base_url || '');
      const res = await fetch(`${base}/upload_env`, {
        method: 'POST',
        body: formData,
      });

      const result = await res.json();

      if (result.success) {
        alert(`Dashboard successfully loaded as "${result.eid}"`);
        if (props.onEnvSelect) {
          props.onEnvSelect([result.eid]);
        }
      } else {
        alert('Error: ' + (result.error || 'Upload failed'));
      }
    } catch (err) {
      console.error('Upload error:', err);
      if (!navigator.onLine) {
        alert('Network error: no internet connection detected.');
      } else if (err.message.includes('Failed to fetch')) {
        alert('Cannot connect to the Visdom server.\nPlease check that the server is running.');
      } else {
        alert(`Upload failed:\n${err.message}`);
      }
    }

    e.target.value = '';
  };

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
            className="btn btn-default btn-sm dropdown-toggle"
            type="button"
            id="viewDropdown"
            data-toggle="dropdown"
            aria-haspopup="true"
            aria-expanded="true"
            disabled={!(connected && envIDs.length > 0)}
          >
            {envIDs.length > 1 ? 'compare' : activeLayout}
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
          className="btn btn-default btn-sm"
          onClick={onRepackButton}
        >
          <span className="glyphicon glyphicon-th" />
        </button>
        <button
          data-toggle="tooltip"
          title="Manage Views"
          data-placement="bottom"
          className="btn btn-default btn-sm"
          disabled={!(connected && envIDs.length > 0 && !readonly)}
          onClick={onViewManageButton}
        >
          <span className="glyphicon glyphicon-folder-open" />
        </button>
        <button
          data-toggle="tooltip"
          title="Undo Close"
          data-placement="bottom"
          className="btn btn-default btn-sm"
          disabled={!(connected && envIDs.length === 1 && !readonly && canUndo)}
          onClick={onUndoButton}
        >
          <span
            className="glyphicon glyphicon-share-alt"
            style={{ transform: 'scaleX(-1)' }}
          />
        </button>
        <button
          data-toggle="tooltip"
          title="Upload Dashboard JSON"
          data-placement="bottom"
          className="btn btn-default btn-sm"
          onClick={() => fileInputRef.current && fileInputRef.current.click()}
          disabled={!(connected && !readonly)}
          aria-label="Upload JSON file"
        >
          <span className="glyphicon glyphicon-upload" />
        </button>

        <input
          type="file"
          ref={fileInputRef}
          style={{ display: 'none' }}
          accept=".json"
          onChange={handleUploadDashboard}
        />
        <button
          data-toggle="tooltip"
          title="Export as HTML"
          data-placement="bottom"
          className="btn btn-default btn-sm"
          disabled={!(connected && envIDs.length > 0)}
          onClick={onExportHtml}
          aria-label="Export as HTML"
        >
          <span className="glyphicon glyphicon-download" />
        </button>
      </div>
    </span>
  );
}

export default ViewControls;
