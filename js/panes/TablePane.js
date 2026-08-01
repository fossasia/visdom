/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

import React, { useContext, useEffect, useRef, useState } from 'react';

import ApiContext from '../api/ApiContext';
import Pane from './Pane';
import PropertyItem from './PropertyItem';

const DEFAULT_COL_WIDTH = 120;
const DEFAULT_ROW_HEIGHT = 28;
const MIN_COL_WIDTH = 40;
const MIN_ROW_HEIGHT = 18;

function TablePane(props) {
  const { sendTableEdit } = useContext(ApiContext);
  const { envID, id, content } = props;
  const { headers, rows } = content;
  const editable = props.editable !== false;

  const [colWidths, setColWidths] = useState(() =>
    headers.map(() => DEFAULT_COL_WIDTH)
  );
  const [rowHeights, setRowHeights] = useState(() =>
    rows.map(() => DEFAULT_ROW_HEIGHT)
  );
  const dragState = useRef(null);

  useEffect(() => {
    setColWidths((w) => headers.map((_, i) => w[i] ?? DEFAULT_COL_WIDTH));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [headers.length]);

  useEffect(() => {
    setRowHeights((h) => rows.map((_, i) => h[i] ?? DEFAULT_ROW_HEIGHT));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows.length]);

  // private events
  // --------------

  const editCell = (r, c, value) =>
    sendTableEdit(envID, id, 'edit_cell', { row: r, col: c, value });
  const addRow = () =>
    sendTableEdit(envID, id, 'add_row', { values: headers.map(() => '') });
  const deleteRow = (r) => sendTableEdit(envID, id, 'delete_row', { row: r });
  const addCol = () =>
    sendTableEdit(envID, id, 'add_col', {
      name: `Column ${headers.length + 1}`,
    });
  const deleteCol = (c) => sendTableEdit(envID, id, 'delete_col', { col: c });

  const startResize = (kind, idx, ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    const startPos = kind === 'col' ? ev.clientX : ev.clientY;
    const startSize =
      kind === 'col'
        ? (colWidths[idx] ?? DEFAULT_COL_WIDTH)
        : (rowHeights[idx] ?? DEFAULT_ROW_HEIGHT);
    const minSize = kind === 'col' ? MIN_COL_WIDTH : MIN_ROW_HEIGHT;
    dragState.current = { kind, idx, startPos, startSize };

    const onMove = (moveEv) => {
      const pos = kind === 'col' ? moveEv.clientX : moveEv.clientY;
      const delta = pos - dragState.current.startPos;
      const newSize = Math.max(minSize, dragState.current.startSize + delta);
      if (kind === 'col') {
        setColWidths((w) => {
          const next = [...w];
          next[idx] = newSize;
          return next;
        });
      } else {
        setRowHeights((h) => {
          const next = [...h];
          next[idx] = newSize;
          return next;
        });
      }
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      dragState.current = null;
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  };

  const handleDownload = () => {
    const escapeCsv = (v) => `"${String(v).replace(/"/g, '""')}"`;
    const csv = [headers, ...rows]
      .map((r) => r.map(escapeCsv).join(','))
      .join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.download = 'visdom_table.csv';
    link.href = url;
    link.click();
    setTimeout(() => window.URL.revokeObjectURL(url), 1000);
  };

  // rendering
  // ---------

  return (
    <Pane {...props} handleDownload={handleDownload}>
      <div className="content-table">
        <table className="table-native" style={{ tableLayout: 'fixed' }}>
          <colgroup>
            <col style={{ width: 28 }} />
            {colWidths.map((w, i) => (
              <col key={i} style={{ width: w }} />
            ))}
            {editable && <col style={{ width: 24 }} />}
          </colgroup>
          <thead>
            <tr>
              <th className="table-gutter" />
              {headers.map((h, c) => (
                <th key={c} className="table-header-cell">
                  {editable && (
                    <span
                      className="table-delete-col"
                      role="button"
                      tabIndex={0}
                      title="Delete column"
                      onClick={() => deleteCol(c)}
                    >
                      ×
                    </span>
                  )}
                  <span className="table-header-text">{h}</span>
                  {editable && (
                    <div
                      className="col-resize-handle"
                      onMouseDown={(ev) => startResize('col', c, ev)}
                    />
                  )}
                </th>
              ))}
              {editable && (
                <th
                  className="table-add-col"
                  role="button"
                  tabIndex={0}
                  title="Add column"
                  onClick={addCol}
                >
                  +
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, r) => (
              <tr key={r} style={{ height: rowHeights[r] }}>
                <td className="table-gutter">
                  {editable && (
                    <span
                      className="table-delete-row"
                      role="button"
                      tabIndex={0}
                      title="Delete row"
                      onClick={() => deleteRow(r)}
                    >
                      ×
                    </span>
                  )}
                  {editable && (
                    <div
                      className="row-resize-handle"
                      onMouseDown={(ev) => startResize('row', r, ev)}
                    />
                  )}
                </td>
                {row.map((cell, c) =>
                  editable ? (
                    <td key={c} className="table-cell">
                      <PropertyItem
                        type="text"
                        value={cell}
                        propId={c}
                        updateValue={(_, value) => editCell(r, c, value)}
                        blurStopPropagation={true}
                      />
                    </td>
                  ) : (
                    <td key={c} className="table-cell table-cell-readonly">
                      {cell}
                    </td>
                  )
                )}
                {editable && <td />}
              </tr>
            ))}
            {editable && (
              <tr>
                <td
                  colSpan={headers.length + 2}
                  className="table-add-row"
                  role="button"
                  tabIndex={0}
                  onClick={addRow}
                >
                  + Add row
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </Pane>
  );
}

export default TablePane;
