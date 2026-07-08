import React, { useState } from 'react';
import ReactModal from 'react-modal';
import { MODAL_STYLE } from './settings';

function DashboardTabs({ show, onHide }) {
  const [activeTab, setActiveTab] = useState('workspaces');

  const tabs = [
    { id: 'workspaces', label: 'Workspaces' },
    { id: 'members', label: 'Members' },
    { id: 'shared_links', label: 'Shared Links' },
    { id: 'billing', label: 'Billing' },
  ];

  return (
    <ReactModal
      isOpen={show}
      onRequestClose={onHide}
      contentLabel="Workspace Management Dashboard"
      ariaHideApp={false}
      style={MODAL_STYLE}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span className="visdom-title">Workspace Management Dashboard</span>
        <button className="btn btn-default btn-sm" onClick={onHide}>Close</button>
      </div>
      <br />
      <ul className="nav nav-tabs" style={{ marginBottom: '15px', borderBottom: '1px solid #ddd' }}>
        {tabs.map((tab) => (
          <li key={tab.id} className={activeTab === tab.id ? 'active' : ''} style={{ display: 'inline-block', marginRight: '5px' }}>
            <a 
              href="#" 
              onClick={(e) => { e.preventDefault(); setActiveTab(tab.id); }}
              style={{ padding: '10px 15px', textDecoration: 'none', color: activeTab === tab.id ? '#333' : '#777', borderBottom: activeTab === tab.id ? '2px solid #333' : 'none' }}
            >
              {tab.label}
            </a>
          </li>
        ))}
      </ul>
      <div className="tab-content" style={{ marginTop: '10px' }}>
        {activeTab === 'workspaces' && (
          <div>
            <h4>Workspaces</h4>
            <p>Manage your team workspaces here.</p>
            <ul>
              <li>Default Workspace</li>
              <li>Team A</li>
            </ul>
          </div>
        )}
        {activeTab === 'members' && (
          <div>
            <h4>Members</h4>
            <p>Manage workspace members and roles.</p>
          </div>
        )}
        {activeTab === 'shared_links' && (
          <div>
            <h4>Shared Links</h4>
            <p>Manage public read-only guest links.</p>
          </div>
        )}
        {activeTab === 'billing' && (
          <div>
            <h4>Billing</h4>
            <p>Manage subscription and billing information.</p>
          </div>
        )}
      </div>
    </ReactModal>
  );
}

export default DashboardTabs;
