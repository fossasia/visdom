/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useEffect, useRef, useState } from 'react';

import { LATEX_STYLES } from './LatexExport';

const STYLE_LABELS = {
  ieee: 'IEEE',
  springer: 'Springer',
  generic: 'Generic',
};

function LatexExportPane({ onExport, hidden }) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;

    const handleOutsideClick = (ev) => {
      if (containerRef.current && !containerRef.current.contains(ev.target)) {
        setOpen(false);
      }
    };
    const handleKeyDown = (ev) => {
      if (ev.key === 'Escape') setOpen(false);
    };

    document.addEventListener('mousedown', handleOutsideClick);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleOutsideClick);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open]);

  if (hidden || !onExport) return null;

  const handleSelect = (style) => {
    setOpen(false);
    onExport(style);
  };

  return (
    <div className="export-dropdown" ref={containerRef}>
      <button
        title="export latex"
        onClick={() => setOpen((prev) => !prev)}
        className={open ? 'active' : ''}
      >
        {' '}
        TeX{' '}
      </button>
      {open && (
        <ul className="export-dropdown-menu">
          {LATEX_STYLES.map((style) => (
            <li className="export-dropdown-item" key={style}>
              <button
                className="export-dropdown-button"
                onClick={() => handleSelect(style)}
              >
                {STYLE_LABELS[style] || style}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default LatexExportPane;
