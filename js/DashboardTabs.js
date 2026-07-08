import React, { useState } from 'react';
import { Modal } from 'react-bootstrap';

function DashboardTabs({ show, onHide }) {
  const [activeTab, setActiveTab] = useState('workspaces');

  const tabs = [
    { id: 'workspaces', label: 'Workspaces' },
    { id: 'members', label: 'Members' },
    { id: 'shared_links', label: 'Shared Links' },
    { id: 'billing', label: 'Billing' },
  ];

  return (
    <Modal show={show} onHide={onHide} bsSize="large">
      <Modal.Header closeButton>
        <Modal.Title>Workspace Management Dashboard</Modal.Title>
      </Modal.Header>
      <Modal.Body>
        <ul className="nav nav-tabs" style={{ marginBottom: '15px' }}>
          {tabs.map((tab) => (
            <li key={tab.id} className={activeTab === tab.id ? 'active' : ''}>
              <a href="#" onClick={(e) => { e.preventDefault(); setActiveTab(tab.id); }}>
                {tab.label}
              </a>
            </li>
          ))}
        </ul>
        <div className="tab-content">
          {activeTab === 'workspaces' && (
            <div>
              <h4>Workspaces</h4>
              <p>Manage your team workspaces here.</p>
              {/* Mock content */}
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
      </Modal.Body>
    </Modal>
  );
}

export default DashboardTabs;
