/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useState } from 'react';

import EnvControls from '../topbar/EnvControls';
import ViewControls from '../topbar/ViewControls';

function Sidebar(props) {
  const {
    // env props
    envIDs,
    envList,
    onEnvClear,
    onEnvManageButton,
    onEnvSelect,
    // view props
    activeLayout,
    layoutList,
    onRepackButton,
    onViewChange,
    onViewManageButton,
  } = props;

  const [collapsed, setCollapsed] = useState(
    localStorage.getItem('sidebarCollapsed') === 'true'
  );

  const toggleCollapsed = () => {
    const next = !collapsed;
    setCollapsed(next);
    localStorage.setItem('sidebarCollapsed', String(next));
  };

  return (
    <div className={`visdom-sidebar${collapsed ? ' collapsed' : ''}`}>
      <div className="sidebar-inner">
        <div className="sidebar-header">
          <span className="sidebar-brand">&#9776;</span>
          <span className="sidebar-brand-text">Workspaces</span>
        </div>

        <div className="sidebar-section">
          <div className="sidebar-section-title">Environment</div>
          <div className="sidebar-control">
            <EnvControls
              envIDs={envIDs}
              envList={envList}
              envSelectorStyle={{ width: '100%' }}
              onEnvClear={onEnvClear}
              onEnvManageButton={onEnvManageButton}
              onEnvSelect={onEnvSelect}
            />
          </div>
        </div>

        <div className="sidebar-section">
          <div className="sidebar-section-title">View</div>
          <div className="sidebar-control">
            <ViewControls
              activeLayout={activeLayout}
              envIDs={envIDs}
              layoutList={layoutList}
              onRepackButton={onRepackButton}
              onViewChange={onViewChange}
              onViewManageButton={onViewManageButton}
            />
          </div>
        </div>
      </div>

      <button
        className="sidebar-toggle"
        onClick={toggleCollapsed}
        title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        {collapsed ? '\u203A' : '\u2039'}
      </button>
    </div>
  );
}

export default Sidebar;
