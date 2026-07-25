/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useEffect, useRef, useState } from 'react';

const DPI_OPTIONS = [200, 300, 600];
const RASTER_FORMATS = ['png', 'jpg'];

function ExportPane({ onExport, allowedFormats = ['png', 'jpg', 'svg'] }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [activeSubmenu, setActiveSubmenu] = useState(null);
  const containerRef = useRef();
  const rasterFormats = RASTER_FORMATS.filter((f) =>
    allowedFormats.includes(f)
  );
  const svgAllowed = allowedFormats.includes('svg');

  useEffect(() => {
    if (!menuOpen) return;

    const handleClickOutside = (ev) => {
      if (containerRef.current && !containerRef.current.contains(ev.target)) {
        closeAll();
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [menuOpen]);

  const closeAll = () => {
    setMenuOpen(false);
    setActiveSubmenu(null);
  };

  const toggleMenu = () => {
    setMenuOpen((prev) => !prev);
    setActiveSubmenu(null);
  };

  const handleFormatClick = (format) => {
    if (format === 'svg') {
      onExport('svg');
      closeAll();
      return;
    }
    setActiveSubmenu(format);
  };

  const handleDpiClick = (ev, format, dpi) => {
    ev.stopPropagation();
    onExport(format, dpi);
    closeAll();
  };

  return (
    <div className="export-dropdown" ref={containerRef}>
      <button
        title="export"
        onClick={toggleMenu}
        className={menuOpen ? 'pull-right active' : 'pull-right'}
      >
        &#8681;
      </button>
      {menuOpen && (
        <ul className="export-dropdown-menu" role="menu">
          {rasterFormats.map((format) => (
            <li
              key={format}
              className="export-dropdown-item has-submenu"
              role="menuitem"
              onMouseEnter={() => setActiveSubmenu(format)}
              onClick={() => handleFormatClick(format)}
            >
              {format.toUpperCase()}
              <span className="export-dropdown-caret">&#9656;</span>
              {activeSubmenu === format && (
                <ul className="export-dropdown-submenu" role="menu">
                  {DPI_OPTIONS.map((dpi) => (
                    <li
                      key={dpi}
                      className="export-dropdown-item"
                      role="menuitem"
                      onClick={(ev) => handleDpiClick(ev, format, dpi)}
                    >
                      {dpi} DPI
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
          {svgAllowed && (
            <li
              className="export-dropdown-item"
              role="menuitem"
              onClick={() => handleFormatClick('svg')}
            >
              SVG
            </li>
          )}
        </ul>
      )}
    </div>
  );
}

export default ExportPane;
