import React, { useState, useEffect } from 'react';

function WorkspaceSwitcher({ onWorkspaceSelect }) {
  const [workspaces, setWorkspaces] = useState([]);
  const [activeWorkspace, setActiveWorkspace] = useState(null);

  useEffect(() => {
    fetch('/api/v1/workspaces')
      .then((res) => res.json())
      .then((data) => {
        setWorkspaces(data);
        if (data.length > 0) {
          setActiveWorkspace(data[0].id);
        }
      })
      .catch((err) => console.error('Failed to load workspaces', err));
  }, []);

  const handleChange = (e) => {
    const val = e.target.value;
    setActiveWorkspace(val);
    if (onWorkspaceSelect) {
      onWorkspaceSelect(val);
    }
  };

  return (
    <span className="workspace-switcher">
      <select 
        value={activeWorkspace || ''} 
        onChange={handleChange}
        className="form-control"
        style={{ display: 'inline-block', width: 'auto', marginRight: '10px' }}
      >
        {workspaces.map((ws) => (
          <option key={ws.id} value={ws.id}>
            {ws.name}
          </option>
        ))}
      </select>
    </span>
  );
}

export default WorkspaceSwitcher;
