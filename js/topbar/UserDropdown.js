/**
 * UserDropdown component for Visdom topbar
 * Matches existing UI style
 */

import React, { useState, useRef, useEffect } from 'react';

function UserDropdown() {
  const [open, setOpen] = useState(false);
  const dropdownRef = useRef(null);

  const toggleDropdown = () => {
    setOpen(!open);
  };

  useEffect(() => {
    function handleClickOutside(event) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target)
      ) {
        setOpen(false);
      }
    }

    document.addEventListener('mousedown', handleClickOutside);

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  return (
    <div
      ref={dropdownRef}
      style={{
        position: 'relative',
        display: 'inline-block',
        marginLeft: '10px',
      }}
    >
      <button
        onClick={toggleDropdown}
        className="btn btn-default"
        style={{
          height: '34px',
          minWidth: '90px',
        }}
      >
        User ▼
      </button>

      {open && (
        <div
          style={{
            position: 'absolute',
            right: 0,
            top: '38px',
            backgroundColor: '#fff',
            border: '1px solid #ccc',
            borderRadius: '4px',
            boxShadow: '0 2px 6px rgba(0,0,0,0.15)',
            zIndex: 1000,
            minWidth: '140px',
          }}
        >
          <div
            style={itemStyle}
            onClick={() => alert('Profile clicked')}
          >
            Profile
          </div>

          <div
            style={itemStyle}
            onClick={() => alert('Settings clicked')}
          >
            Settings
          </div>

          <div
            style={itemStyle}
            onClick={() => alert('Logout clicked')}
          >
            Logout
          </div>
        </div>
      )}
    </div>
  );
}

const itemStyle = {
  padding: '10px',
  cursor: 'pointer',
  borderBottom: '1px solid #eee',
};

export default UserDropdown;