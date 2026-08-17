/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import { Download, FolderOpen, LayoutGrid, Undo2, Upload } from 'lucide-react';
import React, { useContext, useEffect, useRef, useState } from 'react';

import ApiContext from '../api/ApiContext';
import { showToast } from '../toasts/toastEvents';

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

  const [isViewMenuOpen, setViewMenuOpen] = useState(false);
  const viewDropdownRef = useRef(null);

  useEffect(() => {
    if (!isViewMenuOpen) return undefined;

    const handleOutsideClick = (event) => {
      if (
        viewDropdownRef.current &&
        !viewDropdownRef.current.contains(event.target)
      ) {
        setViewMenuOpen(false);
      }
    };
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        setViewMenuOpen(false);
      }
    };

    document.addEventListener('mousedown', handleOutsideClick);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleOutsideClick);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isViewMenuOpen]);

  useEffect(() => {
    if (!(connected && envIDs.length > 0)) {
      setViewMenuOpen(false);
    }
  }, [connected, envIDs.length]);

  const handleUploadDashboard = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    if (!file.name.toLowerCase().endsWith('.json')) {
      showToast('Please upload a valid .json file.', 'error', {
        duration: 4000,
      });
      e.target.value = '';
      return;
    }

    if (file.size > 100 * 1024 * 1024) {
      // 100 MB limit
      showToast('Maximum 100 MB File allowed.', 'warning', {
        duration: 4000,
      });
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
        showToast(
          `Dashboard successfully loaded as "${result.eid}"`,
          'success',
          { duration: 4000 }
        );
        if (props.onEnvSelect) {
          props.onEnvSelect([result.eid]);
        }
      } else {
        showToast('Error: ' + (result.error || 'Upload failed'), 'error', {
          duration: 4000,
        });
      }
    } catch (err) {
      console.error('Upload error:', err);
      if (!navigator.onLine) {
        showToast('Network error: no internet connection detected.', 'error', {
          duration: 4000,
        });
      } else if (err.message.includes('Failed to fetch')) {
        showToast(
          'Cannot connect to the Visdom server.\nPlease check that the server is running.',
          'error',
          {
            duration: 4000,
          }
        );
      } else {
        showToast(`Upload failed:\n${err.message}`, 'error', {
          duration: 4000,
        });
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
        <a
          href={'#' + view}
          onClick={() => {
            onViewChange(view);
            setViewMenuOpen(false);
          }}
        >
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
        <div className="btn-group" role="group" ref={viewDropdownRef}>
          <button
            className="btn btn-default btn-sm dropdown-toggle"
            type="button"
            id="viewDropdown"
            aria-haspopup="true"
            aria-expanded={isViewMenuOpen}
            disabled={!(connected && envIDs.length > 0)}
            onClick={() => setViewMenuOpen((open) => !open)}
          >
            {envIDs.length > 1 ? 'compare' : activeLayout}
            &nbsp;
            <span className="caret" />
          </button>
          <ul
            className={'dropdown-menu' + (isViewMenuOpen ? ' show' : '')}
            aria-labelledby="viewDropdown"
          >
            {view_options}
          </ul>
        </div>
        <button
          title="Repack"
          className="btn btn-default btn-sm"
          onClick={onRepackButton}
        >
          <LayoutGrid size={14} />
        </button>
        <button
          title="Manage Views"
          className="btn btn-default btn-sm"
          disabled={!(connected && envIDs.length > 0 && !readonly)}
          onClick={onViewManageButton}
        >
          <FolderOpen size={14} />
        </button>
        <button
          title="Undo Close"
          className="btn btn-default btn-sm"
          disabled={!(connected && envIDs.length === 1 && !readonly && canUndo)}
          onClick={onUndoButton}
        >
          <Undo2 size={14} />
        </button>
        <button
          title="Upload Dashboard JSON"
          className="btn btn-default btn-sm"
          onClick={() => fileInputRef.current && fileInputRef.current.click()}
          disabled={!(connected && !readonly)}
          aria-label="Upload JSON file"
        >
          <Upload size={14} />
        </button>

        <input
          type="file"
          ref={fileInputRef}
          style={{ display: 'none' }}
          accept=".json"
          onChange={handleUploadDashboard}
        />
        <button
          title="Export as HTML"
          className="btn btn-default btn-sm"
          disabled={!(connected && envIDs.length > 0)}
          onClick={onExportHtml}
          aria-label="Export as HTML"
        >
          <Download size={14} />
        </button>
      </div>
    </span>
  );
}

export default ViewControls;
